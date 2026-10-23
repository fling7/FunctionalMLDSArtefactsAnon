"""Offline-only WP4 denominator and retained-log accounting helpers.

No gateway construction, credentials, networking, or model generation.
"""
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path

MODELS=('gpt-4.1-mini-2025-04-14','gpt-4.1-2025-04-14')
SCORED_OUTCOMES=frozenset(('CORRECT','ABSTAIN_OK','WRONG_PROVIDER','SILENT_VIOLATION'))
ENGINEERING='ENGINEERING_SYNTHETIC_FIXTURE_NOT_LLM_EVIDENCE'


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def scored(row): return row.get('status')=='SUCCESS' and row.get('outcome') in SCORED_OUTCOMES

def _key(record):
    return (record.get('experiment_id'),record.get('item_id'),str(record.get('repetition_id','0')))


def retained_accounting(log_path):
    path=Path(log_path) if log_path else None
    records=[]
    if path and path.exists():
        records=[json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        records=[r for r in records if r.get('experiment_id') in ('WP4.routing','WP4.http','WP4.questions')]
    grouped=defaultdict(list)
    for record in records:grouped[_key(record)].append(record)
    items={}
    for key,group in grouped.items():
        starts={int(r['attempt']):r for r in group if r.get('status')=='ATTEMPT_STARTED'}
        terminals={int(r['attempt']) for r in group if r.get('status') in ('SUCCESS','API_ERROR') and 'attempt' in r and not str(r.get('endpoint','')).endswith('/input_tokens')}
        pending=[r for attempt,r in starts.items() if attempt not in terminals]
        settled=sum((Decimal(str(r['cost_usd'])) for r in group if 'cost_usd' in r),Decimal(0))
        reserved=sum((Decimal(str(r['reserved_usd'])) for r in pending),Decimal(0))
        items[key]={'accounted_cost_usd':str(settled+reserved),'settled_cost_usd':str(settled),'unsettled_reserved_usd':str(reserved),
                    'generation_api_attempts':len(starts),'unsettled_attempts':len(pending),'log_records':len(group)}
    totals=[]
    for experiment in ('WP4.routing','WP4.http','WP4.questions'):
        values=[v for k,v in items.items() if k[0]==experiment]
        totals.append({'experiment_id':experiment,'logical_call_keys':len(values),
                       **{name:str(sum((Decimal(v[name]) for v in values),Decimal(0))) if path and path.exists() else None for name in ('accounted_cost_usd','settled_cost_usd','unsettled_reserved_usd')},
                       'generation_api_attempts':sum(v['generation_api_attempts'] for v in values),'unsettled_attempts':sum(v['unsettled_attempts'] for v in values)})
    return items,{'available':bool(path and path.exists()),'sha256':sha(path) if path and path.exists() else None,'experiments':totals,
                  'interpretation':'Retained sanitized log accounting; unmatched ATTEMPT_STARTED records retain their full reservation. Missing log coverage is unknown, never free.'}


def attach_costs(router,http,log_path):
    items,summary=retained_accounting(log_path)
    def call_cost(row,experiment):
        key=(experiment,row.get('item_id'),str(row.get('repetition_id',row.get('repetition',0))))
        if key in items:return items[key]
        if row.get('baseline')=='B2' or row.get('status') in ('QUESTION_UNAVAILABLE','SETUP_ERROR'):
            return {'accounted_cost_usd':'0','generation_api_attempts':0,'unsettled_attempts':0,'log_records':0}
        return {'accounted_cost_usd':None,'generation_api_attempts':None,'unsettled_attempts':None,'log_records':0}
    for row in router:row.update(call_cost(row,'WP4.routing'))
    for row in http:
        values=[call_cost(call,'WP4.http') for call in row.get('calls',[])]
        row['accounted_cost_usd']=None if any(v['accounted_cost_usd'] is None for v in values) else str(sum((Decimal(v['accounted_cost_usd']) for v in values),Decimal(0)))
        row['generation_api_attempts']=None if any(v['generation_api_attempts'] is None for v in values) else sum(v['generation_api_attempts'] for v in values)
        row['unsettled_attempts']=None if any(v['unsettled_attempts'] is None for v in values) else sum(v['unsettled_attempts'] for v in values)
    return summary


def cost_summary(rows,prefix=''):
    known=[r for r in rows if r.get('accounted_cost_usd') is not None]
    subtotal=sum((Decimal(r['accounted_cost_usd']) for r in known),Decimal(0))
    return {prefix+'accounted_cost_usd':str(subtotal) if len(known)==len(rows) else None,
            prefix+'known_accounted_subtotal_usd':str(subtotal),prefix+'rows_with_unknown_cost':len(rows)-len(known)}


def load_manifest(corpus=None,routing=None,http=None,questions=None):
    choices=[]
    if corpus:choices.append(Path(corpus)/'manifest.json')
    for directory in (routing,http,questions):
        if directory:
            directory=Path(directory)
            if directory.is_file():directory=directory.parent
            choices.append(directory/'corpus'/'manifest.json')
    available=[]
    for path in choices:
        if not path.exists():continue
        pin=path.with_suffix('.sha256')
        if not pin.exists() or pin.read_text(encoding='utf-8-sig').split()[0]!=sha(path):raise RuntimeError('Offline corpus manifest is not hash-verified: '+str(path))
        available.append((path,read(path)))
    if not available:return None,None
    if len({sha(p) for p,_ in available})!=1:raise RuntimeError('Offline inputs refer to different corpora')
    return available[0]


def question_summary(path,manifest=None,accounting=None):
    expected={str(r['source_room_id'])+'.'+str(r['target_id']) for r in (manifest or {}).get('question_objects',[])}
    rows={};frozen=False;files=[]
    if path:
        path=Path(path);frozen_path=path if path.is_file() else path/'questions.json'
        if frozen_path.exists():
            pin=frozen_path.with_suffix('.sha256')
            if not pin.exists() or pin.read_text(encoding='utf-8-sig').split()[0]!=sha(frozen_path):raise RuntimeError('Frozen questions changed during offline report replay')
            rows=read(frozen_path);frozen=True;files=[frozen_path,pin]
        elif path.is_dir():
            for file in sorted(path.glob('*.json')):
                row=read(file)
                if 'key' in row:
                    if row['key'] in rows:raise RuntimeError('Duplicate retained question key')
                    rows[row['key']]=row;files.append(file)
    if manifest is not None and set(rows)-expected:raise RuntimeError('Question outcome is outside the frozen corpus targets')
    statuses=Counter(r.get('status','MISSING_STATUS') for r in rows.values())
    valid=[r for r in rows.values() if r.get('status')=='SUCCESS']
    return {'frozen':frozen,'expected_object_rows':len(expected) if manifest is not None else None,'observed_object_rows':len(rows),
            'missing_object_rows':len(expected-set(rows)) if manifest is not None else None,
            'valid_question_pairs':len(valid),'valid_questions':sum(sum(isinstance(r.get('parsed',{}).get(k),str) and bool(r['parsed'][k].strip()) for k in ('question_1','question_2')) for r in valid),
            'error_object_rows':sum(n for status,n in statuses.items() if status!='SUCCESS'),'statuses':dict(sorted(statuses.items())),
            'files_sha256':{p.name:sha(p) for p in files},'interpretation':'One retained outcome per selected object; absent objects are missing, not successful. Two questions are required for a valid pair.'}


def denominators(router,http,manifest):
    evaluations=[r for r in (manifest or {}).get('rooms',[]) if r.get('split')=='evaluation']
    source_ids=[r['source_room_id'] for r in evaluations] if manifest is not None else sorted({r['source_room_id'] for r in router+http if r.get('source_room_id')!='authored_example'})
    coverage=[]
    for sid in source_ids:
        for model in MODELS:
            rr=[r for r in router if r.get('source_room_id')==sid and r.get('model')==model and r.get('question_kind')=='neutral' and r.get('repetition',0)==0]
            cells=set(itertools.product(('B0','B1'),(False,True),(1,2,3)))
            observed={(r.get('baseline'),r.get('abstain_allowed'),r.get('phrasing')) for r in rr}&cells
            valid={(r.get('baseline'),r.get('abstain_allowed'),r.get('phrasing')) for r in rr if scored(r)}&cells
            hh=[r for r in http if r.get('source_room_id')==sid and r.get('model')==model and type(r.get('slot')) is int and 0<=r['slot']<15]
            slots={r['slot'] for r in hh}
            coverage.append({'source_room_id':sid,'model':model,'expected_primary_routing_cells':12,'observed_primary_routing_cells':len(observed),'valid_primary_routing_cells':len(valid),'missing_primary_routing_cells':12-len(observed),
                             'expected_core_http_rows':15,'observed_core_http_slots':len(slots),'missing_core_http_slots':15-len(slots),
                             'core_chat_requests_attempted':sum('http_latency_seconds' in r for r in hh),'core_admitted_at_precall':sum(bool(r.get('admitted_at_precall')) for r in hh),
                             'core_completed_real_responses':sum(bool(r.get('real_generation_completed')) for r in hh),'core_valid_real_generations':sum(bool(r.get('valid_real_generation')) for r in hh),
                             'core_committed_real_generations':sum(bool(r.get('valid_real_generation')) and bool(r.get('committed')) for r in hh)})
    return {'corpus_denominator_available':manifest is not None,'evaluation_source_rooms':len(source_ids),'coverage':coverage,
            'routing_observed_rows':len(router),'routing_model_rows':sum(r.get('baseline') in ('B0','B1') for r in router),
            'routing_valid_scored_rows':sum(scored(r) and r.get('baseline') in ('B0','B1') for r in router),
            'routing_statuses':dict(sorted(Counter(r.get('status','MISSING_STATUS') for r in router).items())),
            'routing_outcomes':dict(sorted(Counter(r.get('outcome','MISSING_OUTCOME') for r in router).items())),
            'http_observed_rows':len(http),'http_chat_requests_attempted':sum('http_latency_seconds' in r for r in http),
            'http_admitted_at_precall':sum(bool(r.get('admitted_at_precall')) for r in http),
            'http_completed_real_responses':sum(bool(r.get('real_generation_completed')) for r in http),
            'http_valid_real_generations':sum(bool(r.get('valid_real_generation')) for r in http),
            'http_committed_real_generations':sum(bool(r.get('valid_real_generation')) and bool(r.get('committed')) for r in http),
            'http_committed_without_valid_generation':sum(bool(r.get('committed')) and not r.get('valid_real_generation') for r in http),
            'http_statuses':dict(sorted(Counter(r.get('status','MISSING_STATUS') for r in http).items())),
            'interpretation':'Coverage uses the frozen corpus, including rooms with no outcomes. Logical rows, actual chat attempts, admitted calls, completed responses, valid generations and commits are distinct. Missing cells are not silently added to rate denominators.'}
