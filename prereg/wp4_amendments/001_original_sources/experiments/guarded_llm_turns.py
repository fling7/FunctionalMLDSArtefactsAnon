"""Real loopback HTTP guarded turns. Experimental client only selects API mode.

No scripted model responses are used by this runner. A forced JSON fallback raises
an in-memory 400 before the constrained attempt, then calls the real gateway from
the native backend fallback branch. All such rows are explicitly labeled.
"""
from __future__ import annotations
import argparse, contextlib, copy, json, re, sys, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from experiments.lib.wp4_common import *
from experiments.routing_baselines import load_corpus,question_for,question_key
from experiments.lib.backend_driver import Driver
from backend.guard_config import GuardConfig
from backend.openai_client import OpenAIHTTPError
import backend.server as native_server

HTTP_TIMEOUT_SECONDS=420

def http_json(base_url,path,payload):
    # Loopback timeout covers five gateway attempts plus their bounded backoff.
    request=urllib.request.Request(base_url.rstrip('/')+path,data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=HTTP_TIMEOUT_SECONDS) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as exc:return exc.code,json.loads(exc.read())

class ExperimentalClient:
    """Injected protocol adapter; generated answers always originate at Gateway."""
    api_key='';timeout_seconds=90
    def __init__(self,gateway):self.gateway=gateway;self.configure({})
    def configure(self,job):self.job=job;self.calls=[];self.forced_schema_bypass=0
    def create_structured_json(self,**kwargs):
        if self.job.get('channel')=='fallback':
            self.forced_schema_bypass+=1
            raise OpenAIHTTPError(400,'Preregistered experimental JSON-mode selection; no constrained API call sent.')
        return self._call(kwargs,structured=True)
    def create_json_object(self,**kwargs):return self._call(kwargs,structured=False)
    def _call(self,kwargs,structured):
        if self.calls:raise OpenAIHTTPError(0,'Preregistered one-generation ceiling per grounded HTTP turn.')
        messages=copy.deepcopy(kwargs['input_messages'])
        messages.append({'role':'developer','content':prompt('answer_style.txt')})
        if not structured:
            messages.append({'role':'developer','content':prompt('fallback.txt').format(agents=json.dumps(self.job['agents'],ensure_ascii=False,separators=(',',':')))})
        payload={'model':self.job['model'],'temperature':self.job['temperature'],'max_output_tokens':128,'input':messages,'text':{'format':{'type':'json_schema','name':kwargs['schema_name'],'strict':True,'schema':kwargs['schema']}} if structured else {'format':{'type':'json_object'}}}
        record=guarded_call(self.gateway,payload,experiment='WP4.http',item=self.job['identity'],repetition=self.job.get('repetition',0),share='WP4',limit=HTTP_INPUT_LIMIT)
        record['channel']='constrained' if structured else 'fallback';record['input_messages']=messages
        record['schema']=kwargs.get('schema');self.calls.append(record)
        if record['status']!='SUCCESS':raise OpenAIHTTPError(0,'Budgeted model call failed.',details={'code':record['status']})
        return record['parsed'],record['response'],output_text(record['response'])

@contextlib.contextmanager
def serving(store):
    instances=[];ready=threading.Event()
    def factory(*args,**kwargs):
        server=ThreadingHTTPServer(*args,**kwargs);instances.append(server);ready.set();return server
    with patch.object(native_server,'ThreadingHTTPServer',factory):
        worker=threading.Thread(target=native_server.start_http_server,args=('127.0.0.1',0,store),daemon=True);worker.start()
        if not ready.wait(10):raise RuntimeError('Native HTTP server did not bind')
        try:yield 'http://127.0.0.1:'+str(instances[0].server_port)
        finally:instances[0].shutdown();worker.join(10)

def valid_model_answer(call):
    p=call.get('parsed')
    return call.get('status')=='SUCCESS' and isinstance(p,dict) and isinstance(p.get('say'),str) and bool(p['say'].strip()) and all(k in p for k in ('handoff_to','handoff_reason','handoff_brief','confidence')) and all(p[k] is None or isinstance(p[k],str) for k in ('handoff_to','handoff_reason','handoff_brief')) and type(p['confidence']) in (int,float)

def textual_monitor(room,target,answer,question):
    names=[(a['id'],a.get('display_name')) for a in room['agent_profiles']]
    redirects=[]
    for aid,name in names:
        for term in (aid,name):
            if term and re.search(r'(?i)(ask|speak|talk|consult|frage|frag|sprich|wende|geh|besuch).{0,80}'+re.escape(term),answer):redirects.append(aid);break
    others=[]
    for obj in room['instance']['objects']:
        if obj.get('entityRole')!='sceneObject' or obj['id']==target['id']:continue
        # Exact source identifiers avoid declaring shared generic type names to be entities.
        if obj.get('sourceId') and re.search(r'(?<!\w)'+re.escape(obj['sourceId'])+r'(?!\w)',answer,re.I):others.append(obj['id'])
    question_mentions=[]
    for obj in room['instance']['objects']:
        if obj.get('entityRole')=='sceneObject' and obj.get('sourceId') and re.search(r'(?<!\w)'+re.escape(obj['sourceId'])+r'(?!\w)',question,re.I):question_mentions.append(obj['id'])
    return {'textual_redirection_agent_ids':sorted(set(redirects)),'other_object_source_id_mentions':sorted(set(others)),'question_object_mentions':question_mentions,'cheap_mismatch_detected':any(x!=target['id'] for x in question_mentions),'judges_available':False,'interpretation':'lexical indicators only; not semantic ground truth'}

def jobs(room,model,questions):
    pairs=room['turn_pairs'];roster=[{'id':a['id'],'display_name':a['display_name'],'expertise':a['expertise']} for a in room['agent_profiles']]
    result=[]
    for slot in range(15):
        channel='constrained' if slot<10 else 'fallback';mode='drop_log' if slot in (11,14) else 'abort';temperature=0 if slot>=12 else .3
        pair=copy.deepcopy(pairs[slot])
        if slot in (10,11):pair=copy.deepcopy(pairs[10])
        if slot>=12:pair=copy.deepcopy(pairs[12])
        kind=('neutral','natural_1','natural_2')[slot%3] if slot<9 else ('mismatch' if slot in (9,12,13,14) else 'neutral')
        qroom=copy.deepcopy(room)
        if kind=='mismatch':
            owner=room['owner_by_object'].get(pair['target']['id'])
            qroom['mismatch_target']=next((t for t in room['question_targets'] if room['owner_by_object'].get(t['id']) and room['owner_by_object'][t['id']]!=owner),None)
        question=question_for(qroom,pair,kind,questions)
        result.append({'identity':room['source_room_id']+'.'+('mini' if model==MODELS[0] else 'full')+'.turn'+str(slot).zfill(2),'source_room_id':room['source_room_id'],'model':model,'slot':slot,'pair':pair,'question_kind':kind,'question':question,'question_target_id':qroom.get('mismatch_target',{}).get('id') if kind=='mismatch' and qroom.get('mismatch_target') else pair['target']['id'],'channel':channel,'proposal_mode':mode,'temperature':temperature,'agents':roster,'repetition':1 if slot==13 else 0})
    return result

def run(corpus,questions_path,out,replay=False,stage="core"):
    verify_freeze();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if not (out/'provenance.json').exists():archive_sources(out)
    if digest(questions_path)!=Path(questions_path).with_suffix('.sha256').read_text().strip():raise RuntimeError('Frozen questions changed')
    questions=read_json(questions_path);rooms=[r for r in load_corpus(corpus) if r['split']=='evaluation'];gateway=Gateway(ROOT,replay=replay,count_input_tokens=True)
    work=[(room,None) for room in rooms] if stage=='core' else [(room,extra) for extra in range(10) for room in rooms]
    for room,extra in work:
        if stage=='supplement':
            existing=[read_json(p) for p in (out/'rows').glob('*.json')]
            if all(sum(r.get('model')==m and bool(r.get('valid_real_generation')) for r in existing)>=300 for m in MODELS):break
        all_jobs=[job for model in MODELS for job in jobs(room,model,questions)]
        if extra is not None:
            all_jobs=[{**next(j for j in all_jobs if j['model']==model),'identity':room['source_room_id']+'.'+('mini' if model==MODELS[0] else 'full')+'.extra'+str(extra).zfill(2),'slot':15+extra,'pair':room['turn_pairs'][extra%len(room['turn_pairs'])],'channel':'constrained','proposal_mode':'abort','temperature':.3,'question_kind':'neutral','question':'What can you tell me about this selected object?','question_target_id':room['turn_pairs'][extra%len(room['turn_pairs'])]['target']['id']} for model in MODELS]
        pending=[j for j in all_jobs if not (out/'rows'/(j['identity']+'.json')).exists()]
        bound=sum(cost_ceiling(j['model'],HTTP_INPUT_LIMIT,128) for j in pending)
        if not replay and remaining(gateway)<bound:
            write_json(out/('stop_'+stage+'.json'),{'source_room_id':room['source_room_id'],'reason':'INSUFFICIENT_FOR_BALANCED_HTTP_ROOM','pending_ceiling_usd':str(bound),'remaining_usd':str(remaining(gateway))});break
        client=ExperimentalClient(gateway);driver=Driver(ROOT/room['project_path'],client=client)
        try:
            with serving(driver.store) as base:
                previous={}
                # Alternate models within slot so a budget/API interruption is visible in paired order.
                for job in sorted(pending,key=lambda j:(j['slot'],stable_key(j['model']))):
                    client.configure(job);driver.store.guard_config=GuardConfig(proposal_mode=job['proposal_mode']);pair=job['pair'];request=None
                    row={k:v for k,v in job.items() if k not in ('agents','pair')};row.update(target_id=pair['target']['id'],start_agent=pair['start_agent'],I1=pair['I1'],I2=pair['I2'],fault_class=pair['class'])
                    prior=previous.get(job['model'])
                    if job['slot']==13 and prior is None:
                        prior_path=out/'rows'/(room['source_room_id']+'.'+('mini' if job['model']==MODELS[0] else 'full')+'.turn12.json')
                        if prior_path.exists():
                            prior=read_json(prior_path)
                            if prior.get('http_status')==400 and prior.get('response',{}).get('code')=='E_HANDOFF_PROPOSAL':
                                rs,rb=http_json(base,'/setup',{'project_id':driver.project.name,'session_id':prior['request']['session_id']})
                                if rs!=200:raise RuntimeError('Cannot reconstruct fresh aborted retry session')
                    if job['slot']==13 and (not prior or prior['http_status']!=400 or prior['response'].get('code')!='E_HANDOFF_PROPOSAL'):
                        # No abort to retry: retain planned attempt as a fresh neutral constrained turn.
                        row['retry_eligibility']='NO_PRECEDING_HANDOFF_ABORT';job={**job,'channel':'constrained','proposal_mode':'abort','temperature':0,'question_kind':'neutral','question':'What can you tell me about this selected object?'};client.configure(job);row.update(channel=job['channel'],proposal_mode=job['proposal_mode'],temperature=0,question_kind='neutral',question=job['question'])
                    elif job['slot']==13:
                        request=copy.deepcopy(prior['request']);row['retry_eligibility']='IDENTICAL_REQUEST_AFTER_ABORT';row['retry_of']=prior['identity']
                    if not job['question']:
                        row.update(http_status=None,status='QUESTION_UNAVAILABLE',real_generation_completed=False,valid_real_generation=False,committed=False);write_json(out/'rows'/(job['identity']+'.json'),row);continue
                    if request is None:
                        session='wp4_'+stable_key(job['identity'])[:24]
                        setup_status,setup=http_json(base,'/setup',{'project_id':driver.project.name,'session_id':session})
                        if setup_status!=200:
                            row.update(http_status=setup_status,status='SETUP_ERROR',response=setup,real_generation_completed=False,valid_real_generation=False,committed=False);write_json(out/'rows'/(job['identity']+'.json'),row);continue
                        driver.setup=setup;request=driver.request(pair['start_agent'],pair['target']);request['user_text']=job['question']
                    snapshot=driver.store.snapshot_session_mutation(request['session_id']);started=time.perf_counter();status,response=http_json(base,'/chat',request);elapsed=time.perf_counter()-started
                    completed=bool(client.calls and client.calls[0].get('status')=='SUCCESS' and client.calls[0].get('response',{}).get('status')=='completed');valid=bool(client.calls and valid_model_answer(client.calls[0]));after=driver.store.snapshot_session_mutation(request['session_id'])
                    parsed=client.calls[0].get('parsed') if client.calls else None;proposal=parsed.get('handoff_to') if isinstance(parsed,dict) else None
                    owner=pair['I1'].get('provider');ownership=ownership_view(room['instance']);declared=next((a['handoff_targets'] for a in ownership['agents'] if a['id']==owner),[])
                    answer=str(parsed.get('say','')) if isinstance(parsed,dict) else ''
                    row.update(http_status=status,response=response,request=request,calls=client.calls,http_latency_seconds=elapsed,admitted_at_precall=bool(client.calls),real_generation_completed=completed,valid_real_generation=valid,committed=status==200,status='SUCCESS' if status==200 and valid else (client.calls[0]['status'] if client.calls and client.calls[0]['status']!='SUCCESS' else ('MODEL_FORMAT_ERROR' if completed and not valid else response.get('code','HTTP_ERROR'))),snapshot_restored_on_error=(snapshot==after) if status!=200 else None,forced_schema_bypass=client.forced_schema_bypass,proposed_target=proposal,proposal_present=bool(proposal),proposal_declared_target=proposal in declared if proposal else None,grounded_schema_allows_handoffs=False,derived_provider=owner,question_object_owner=room['owner_by_object'].get(job.get('question_target_id')),**textual_monitor(room,pair['target'],answer,job['question']))
                    if row.get('retry_of'):
                        row['proposal_repeated_after_abort']=bool(proposal) and proposal==prior.get('proposed_target');row['identical_wire_request']=request==prior['request'];row['identical_model_payload']=bool(client.calls and prior.get('calls') and client.calls[0]['payload_sha256']==prior['calls'][0]['payload_sha256'])
                    write_json(out/'rows'/(job['identity']+'.json'),row);previous[job['model']]=row
                    # Keep abort session only for its immediate temperature-zero retry.
                    if job['slot']!=12:driver.store.sessions.pop(request['session_id'],None)
        finally:
            evidence=out/'evidence'/room['source_room_id']/(stage+'_'+str(extra)+'_'+str(time.time_ns()));evidence.mkdir(parents=True,exist_ok=False)
            for path in driver.project.rglob('*.jsonl'):
                rel=path.relative_to(driver.project);dest=evidence/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
            driver.close()
    write_json(out/('complete_'+stage+'.json'),{'rooms_planned':len(rooms),'rows_on_disk':len(list((out/'rows').glob('*.json'))) if (out/'rows').exists() else 0,'stopped':(out/('stop_'+stage+'.json')).exists()})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--corpus',required=True);p.add_argument('--questions',dest='questions_path',required=True);p.add_argument('--out',required=True);p.add_argument('--replay',action='store_true');p.add_argument('--stage',choices=['core','supplement'],default='core');run(**vars(p.parse_args()))
