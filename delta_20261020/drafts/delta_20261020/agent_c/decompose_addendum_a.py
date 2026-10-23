"""Exploratory retained-data decomposition, extending report_mutation_analysis admission bins to every probe slot."""
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import csv,hashlib,json,socket,sys
R=Path(__file__).resolve().parents[3];D=R/'data/go_sprint';O=R/'deliverables/delta_20261020';S=Path(__file__).relative_to(R).as_posix();sys.path.insert(0,str(R))
from experiments.report_mutation_analysis import key,admitted
START=datetime.now(timezone.utc).isoformat()
def deny(*a,**k):raise RuntimeError('Network forbidden')
socket.create_connection=deny;socket.socket.connect=deny
pins={}; logs=[]
def read(p):
 b=p.read_bytes();pins[p.relative_to(R).as_posix()]=hashlib.sha256(b).hexdigest();return json.loads(b.decode('utf-8-sig'))
def compare(k,old,new):
 x={'key':k,'old':old,'new':new,'script':S,'flag':'NEW_METRIC' if old is None else 'UNCHANGED' if old==new else 'CHANGED'};logs.append(x);print(json.dumps(x))
def csvout(name,rows):
 with (O/'tables'/name).open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
records=defaultdict(list)
for p in sorted((D/'wp6/outcomes').glob('*.jsonl')):
 b=p.read_bytes();pins[p.relative_to(R).as_posix()]=hashlib.sha256(b).hexdigest();records['generated'].extend(json.loads(s) for s in b.decode('utf-8-sig').splitlines() if s.strip())
for p in sorted((D/'sprint/w2/completed').glob('*/*.json')):records['generated'].append(read(p))
for p in sorted((D/'wp6_classroom').glob('snapshot/*/outcomes/*.json')):records['classroom'].append(read(p))
assert {k:len(v) for k,v in records.items()}=={'generated':908,'classroom':153}
oldpath=R/'tables/T5_executed_ablation.csv';pins[oldpath.relative_to(R).as_posix()]=hashlib.sha256(oldpath.read_bytes()).hexdigest()
with oldpath.open(encoding='utf-8',newline='') as f:old={(r['cohort'],r['variant']):r for r in csv.DictReader(f)}
source=R/'experiments/report_mutation_analysis.py';pins[source.relative_to(R).as_posix()]=hashlib.sha256(source.read_bytes()).hexdigest()
variants=('firstmatch','reach_only','no_digest','stale_no_digest','table','runtime')
bins=('oracle_rejection_admitted','decision_or_provider_mismatch','action_binding_mismatch_only','fully_agreed','reason_only_mismatch','action_and_reason_mismatch','unresolved_oracle_or_outcome','setup_refused')
rows=[]; roomrows=[]; result={}
for cohort,rr in sorted(records.items()):
 assert len({r['metadata']['id'] for r in rr})==len(rr)
 acc=defaultdict(Counter); byroom=defaultdict(Counter)
 for r in rr:
  room=r['metadata']['room']
  for p in r['probes']:
   for variant in variants:
    stale=variant=='stale_no_digest';q=p['stale_request'] if stale else p;v=q['no_digest'] if stale else p['variants'][variant];i=q['I1'];i2=q['I2'];c=acc[variant];c['probe_pairs']+=1
    if v.get('status')=='not_run_setup_refused':bucket='setup_refused'
    elif key(i)!=key(i2) or i.get('evaluation_error') or i2.get('evaluation_error') or v.get('evaluation_error') or v.get('decision') not in ('REJECT','ANSWER_LOCAL','ANSWER_AFTER_HANDOFF'):bucket='unresolved_oracle_or_outcome'
    else:
     c['resolved_executed_pairs']+=1
     is_admitted=admitted(v);c['admitted_pairs']+=is_admitted;c['rejected_pairs']+=not is_admitted
     # Same priority as report_mutation_analysis.analyze: oracle rejection,
     # decision/provider, action, fully-agreed admission. Preserve original bins.
     if is_admitted:
      if i.get('decision')=='REJECT':legacy='oracle_rejection_admitted'
      elif (v.get('decision'),v.get('provider'))!=(i.get('decision'),i.get('provider')):legacy='decision_or_provider_mismatch'
      elif v.get('action')!=i.get('action'):legacy='action_binding_mismatch'
      else:legacy='fully_agreed_admission'
      c['legacy_'+legacy]+=1
     if is_admitted and i.get('decision')=='REJECT':bucket='oracle_rejection_admitted'
     elif (v.get('decision'),v.get('provider'))!=(i.get('decision'),i.get('provider')):bucket='decision_or_provider_mismatch'
     elif v.get('action')!=i.get('action'):
      bucket='action_binding_mismatch_only' if v.get('reason')==i.get('reason') else 'action_and_reason_mismatch'
     elif v.get('reason')!=i.get('reason'):bucket='reason_only_mismatch'
     else:bucket='fully_agreed'
     if bucket=='fully_agreed':c['fully_agreed_admitted' if is_admitted else 'fully_agreed_rejected']+=1
     if bucket=='reason_only_mismatch':c['reason_only_admitted' if is_admitted else 'reason_only_rejected']+=1
     c['legacy_aggregate_wrong_admissions']+=int(is_admitted and key(v)!=key(i))
     if bucket=='action_binding_mismatch_only' and v.get('action') is None:c['action_only_unbound_none']+=1
    c[bucket]+=1;byroom[(variant,room)][bucket]+=1;byroom[(variant,room)]['probe_pairs']+=1
 for variant in variants:
  c=acc[variant];assert sum(c[k] for k in bins)==c['probe_pairs'];assert c['legacy_aggregate_wrong_admissions']==int(old[cohort,variant]['wrongly_admitted_probes']);assert c['probe_pairs']==int(old[cohort,variant]['probe_slots']);assert c['setup_refused']==int(old[cohort,variant]['setup_refused_probes'])
  assert c['legacy_oracle_rejection_admitted']==c['oracle_rejection_admitted']
  assert c['legacy_action_binding_mismatch']==c['action_binding_mismatch_only']+c['action_and_reason_mismatch']
  row={'cohort':cohort,'variant':variant,'interpretation':'exploratory post-freeze decomposition; correlated probe pairs','models':len(rr),'source_rooms':len({r['metadata']['room'] for r in rr}),**{k:c[k] for k in ('probe_pairs','resolved_executed_pairs',*bins,'admitted_pairs','rejected_pairs','fully_agreed_admitted','fully_agreed_rejected','reason_only_admitted','reason_only_rejected','action_only_unbound_none','legacy_oracle_rejection_admitted','legacy_decision_or_provider_mismatch','legacy_action_binding_mismatch','legacy_fully_agreed_admission','legacy_aggregate_wrong_admissions')}}
  rows.append(row)
  for k,v in row.items():
   if isinstance(v,int):
    oldkey={'probe_pairs':'probe_slots','resolved_executed_pairs':'executed_probes','setup_refused':'setup_refused_probes','legacy_aggregate_wrong_admissions':'wrongly_admitted_probes'}.get(k)
    compare(cohort+'/'+variant+'/'+k,int(old[cohort,variant][oldkey]) if oldkey else None,v)
  compare(cohort+'/'+variant+'/aggregate_to_oracle_rejected_admissions_not_same_estimand',int(old[cohort,variant]['wrongly_admitted_probes']),c['oracle_rejection_admitted'])
 for (variant,room),c in sorted(byroom.items()):roomrows.append({'cohort':cohort,'variant':variant,'source_room':room,**{k:c[k] for k in ('probe_pairs',*bins)}})
 result[cohort]={r['variant']:{k:v for k,v in r.items() if isinstance(v,int)} for r in rows if r['cohort']==cohort}
csvout('T5c_exploratory_admission_decomposition.csv',rows);csvout('T5c_decomposition_per_room.csv',roomrows)
for row in roomrows:
 for k,v in row.items():
  if isinstance(v,int):compare('per_room/'+row['cohort']+'/'+row['variant']+'/'+row['source_room']+'/'+k,None,v)
meta={'status':'DONE','exploratory':True,'generator':S,'reused_implementation':'experiments/report_mutation_analysis.py:key,admitted; analyze() priority copied unchanged for legacy_* admission-only columns','bins_mutually_exclusive':list(bins),'fully_agreed_definition':'Exact equality of decision,reason,provider,action; includes admitted and rejected outcomes, separately exposed','decision_provider_definition':'After oracle-rejection admissions removed, any decision/provider mismatch; includes rejected outcomes, unlike original admission-only scope','reason_only_definition':'Same decision,provider,action but different reason; separate from fully agreed; admitted/rejected subtotals explicit','warning':'reach_only aggregate includes intentionally unbound action and MUST NOT be quoted as unsafe admissions. Oracle-rejected admissions count actual admission of an oracle-rejected request; no model-quality/deployment claim.','counts':result}
(O/'numbers_addendum_a.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
(O/'review/addendum_a_comparisons.json').write_text(json.dumps(logs,indent=2)+'\n',encoding='utf-8')
for rel,h in pins.items():assert hashlib.sha256((R/rel).read_bytes()).hexdigest()==h
proof={'status':'PASS','started_utc':START,'ended_utc':datetime.now(timezone.utc).isoformat(),'script':S,'input_sha256':pins,'partition_identity':'sum of eight exclusive bins equals all probe pairs per cohort/variant','legacy_aggregate_reproduced':True,'all_original_input_pins_unchanged':True,'network_forbidden':True}
(O/'review/addendum_a_proof.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
notes=['P0 ADDENDUM A DONE. Exploratory post-freeze decomposition; existing aggregates unchanged.','', 'Reuses report_mutation_analysis key/admitted helpers and its admission-only classification priority. T5c adds exhaustive mutually-exclusive bins covering ALL pairs, with setup refusal and unknown explicit; reason-only discrepancies separated. Legacy admission-only four bins retained beside full-pair bins. Fully agreed means all decision/reason/provider/action equal; not merely a matching decision.','', 'IMPORTANT: reach_only intentionally leaves action unbound. Its legacy wrong-admission aggregate MUST NOT be described as unsafe admissions. Action-binding disagreement is distinct from admitting an oracle-rejected request.','']
for cohort in ('generated','classroom'):
 x=result[cohort]['reach_only'];notes.append(f"{cohort}: legacy aggregate {x['legacy_aggregate_wrong_admissions']} = oracle-rejected admitted {x['oracle_rejection_admitted']} + action-binding-only {x['action_binding_mismatch_only']}; decision/provider mismatches {x['decision_or_provider_mismatch']}; fully agreed {x['fully_agreed']}; setup-refused {x['setup_refused']}; unknown {x['unresolved_oracle_or_outcome']}.")
 x=result[cohort]['firstmatch'];notes.append(f"{cohort} firstmatch: {x['reason_only_mismatch']} reason-only mismatches ({x['reason_only_admitted']} admitted, {x['reason_only_rejected']} rejected); not silently placed in fully-agreed bin.")
notes += ['', 'Normal no_digest and stale_no_digest are distinct request conditions. Stale results compare against retained stale I1/I2, never normal oracles. These probes are correlated within mutant/source and do not increase independent room count. No inference or new model calls. Existing T5/T5b, claims, gates, and figures untouched.', 'Old-to-new aggregate-to-oracle-rejection comparison is explicitly a CHANGE OF ESTIMAND, not correction of the raw aggregate. All legacy aggregates reproduced exactly.']
(O/'item_notes_addendum_a.md').write_text('\n'.join(notes)+'\n',encoding='utf-8')
print('ADDENDUM_A_COMPLETE')
