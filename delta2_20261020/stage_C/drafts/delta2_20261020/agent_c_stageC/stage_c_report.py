"""Offline C1 descriptive report; no execution on import. Historical arms labelled.
Bootstrap follows DELTA1 agent_b/cluster_statistics.py: equal room draws, pooled
call ratio and mean room rate, NumPy default_rng seed20261015,10000 resamples.
"""
from pathlib import Path
from collections import defaultdict
import argparse,csv,hashlib,json,math,socket
import numpy as np
R=Path(__file__).resolve().parents[3];S=Path(__file__).relative_to(R).as_posix();SEED=20261015;B=10000

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def wilson(x,n):
 if not n:return None
 z=1.959963984540054;p=x/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [max(0,c-h),min(1,c+h)]
def boot(rr,predicate):
 rooms=sorted({r['room'] for r in rr})
 if not rooms:return None,None
 counts=np.array([sum(r['room']==room for r in rr) for room in rooms]);hits=np.array([sum(r['room']==room and predicate(r) for r in rr) for room in rooms]);idx=np.random.default_rng(SEED).integers(0,len(rooms),(B,len(rooms)))
 return np.quantile(hits[idx].sum(axis=1)/counts[idx].sum(axis=1),[.025,.975],method='linear').tolist(),np.quantile((hits/counts)[idx].mean(axis=1),[.025,.975],method='linear').tolist()
def main(a):
 def deny(*x,**kw):raise RuntimeError('Offline report')
 socket.create_connection=deny;socket.socket.connect=deny
 raw=a.raw.resolve();out=a.output.resolve()
 if out.exists():raise RuntimeError('Choose a new report directory')
 out.mkdir(parents=True);pins={};logs=[]
 def load(p):pins[p.relative_to(R).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest();return read(p)
 new=[load(p) for p in sorted((raw/'rows').glob('*.json'))];old=[load(p) for p in sorted((R/'data/go_sprint/sprint/w3/rows').glob('*.json'))]
 planned=load(raw/'requests.json');oldplan=load(R/'prereg/go_sprint_20261019/w3/requests.json');design=load(raw/'design.json');assert len(old)==270
 for r in old:r['evidence_source']='retained_original';r['reason_correct']=None
 for r in new:
  r['evidence_source']='delta2_C1'
  if r.get('technical_exception_type')=='IntegrityError' and r.get('technical_exception_message')=='GO sprint one-hour hard deadline' and not r.get('attempts'):
   r['failure_kind']='pre_generation_refusal';r['derived_failure_code']='AUTHORITATIVE_DEADLINE_REFUSAL'
 rows=old+new;plans=oldplan+planned;tables=[];perroom=[];paired=[]
 def in_group(r,fault):return fault=='ALL' or (fault=='CONTROLS' and r['I1']['decision']!='REJECT') or (fault=='FAULTS' and r['I1']['decision']=='REJECT') or r['fault_class']==fault
 models=['ALL']+sorted({r['model'] for r in plans});faults=['ALL','CONTROLS','FAULTS']+sorted({r['fault_class'] for r in plans})
 for model in models:
  for arm in ('B0','B1','B1r','B1s'):
   for fault in faults:
    pp=[r for r in plans if (model=='ALL' or r['model']==model) and r['baseline']==arm and in_group(r,fault)]
    if not pp:continue
    retained=[r for r in rows if (model=='ALL' or r['model']==model) and r['baseline']==arm and in_group(r,fault)];ok=[r for r in retained if r['status']=='SUCCESS']
    for outcome in ('SILENT_VIOLATION','ABSTAIN_OK','WRONG_PROVIDER','FORMAT_ERROR','CORRECT'):
     x=sum(r['outcome']==outcome for r in ok);call_ci,room_ci=boot(ok,lambda r:r['outcome']==outcome)
     tables.append({'arm':arm,'model':model,'fault_class':fault,'outcome':outcome,'planned_calls':len(pp),'retained_calls':len(retained),'successful_calls':len(ok),'unsuccessful_records':len(retained)-len(ok),'pre_generation_refusals':sum(r.get('failure_kind')=='pre_generation_refusal' for r in retained),'generation_or_api_error_records':sum(r.get('failure_kind')=='generation_or_api_error' for r in retained),'technical_postprocess_error_records':sum(r.get('failure_kind')=='technical_postprocess_error' for r in retained),'not_done':len(pp)-len(retained),'rooms_planned':len({r['room'] for r in pp}),'rooms_successful':len({r['room'] for r in ok}),'count':x,'rate_successful_denominator':x/len(ok) if ok else None,'wilson95':wilson(x,len(ok)),'room_cluster95':call_ci,'equal_room_cluster95':room_ci,'historical_calls':sum(r['evidence_source']=='retained_original' for r in retained),'delta2_calls':sum(r['evidence_source']=='delta2_C1' for r in retained),'scope':'Pooled ALL can mix partial model coverage; use paired/common-item rows for arm comparisons'})
    if arm=='B1s':
     x=sum(r.get('reason_correct') is True for r in ok);ci,eq=boot(ok,lambda r:r.get('reason_correct') is True)
     tables.append({'arm':arm,'model':model,'fault_class':fault,'outcome':'EXACT_ORACLE_REASON','planned_calls':len(pp),'retained_calls':len(retained),'successful_calls':len(ok),'unsuccessful_records':len(retained)-len(ok),'pre_generation_refusals':sum(r.get('failure_kind')=='pre_generation_refusal' for r in retained),'generation_or_api_error_records':sum(r.get('failure_kind')=='generation_or_api_error' for r in retained),'technical_postprocess_error_records':sum(r.get('failure_kind')=='technical_postprocess_error' for r in retained),'not_done':len(pp)-len(retained),'rooms_planned':len({r['room'] for r in pp}),'rooms_successful':len({r['room'] for r in ok}),'count':x,'rate_successful_denominator':x/len(ok) if ok else None,'wilson95':wilson(x,len(ok)),'room_cluster95':ci,'equal_room_cluster95':eq,'historical_calls':0,'delta2_calls':len(retained),'scope':'Secondary reason correctness, not part of original two-field primary classifier'})
 for model in models:
  for fault in ('ALL','FAULTS','CONTROLS','duplicate_asset_owner','remove_all_owners'):
   ss=[r for r in rows if r['status']=='SUCCESS' and (model=='ALL' or r['model']==model) and in_group(r,fault)]
   def key(r):return (r['model'],*r.get('block_key',[r['room'],r['variant'],r.get('pair_index'),r['target_id'],r['start_agent']]))
   by={arm:{key(r):r for r in ss if r['baseline']==arm} for arm in ('B0','B1','B1r','B1s')}
   for other in ('B0','B1','B1r'):
    common=sorted(set(by['B1s'])&set(by[other]));groups=defaultdict(list)
    for k in common:groups[by['B1s'][k]['room']].append(k)
    if not groups:continue
    rooms=sorted(groups);ns=np.array([len(groups[rm]) for rm in rooms]);idx=np.random.default_rng(SEED).integers(0,len(rooms),(B,len(rooms)))
    for outcome in ('SILENT_VIOLATION','ABSTAIN_OK'):
     sums=np.array([sum(int(by['B1s'][k]['outcome']==outcome)-int(by[other][k]['outcome']==outcome) for k in groups[rm]) for rm in rooms]);draw=sums[idx].sum(axis=1)/ns[idx].sum(axis=1)
     paired.append({'model':model,'fault_class':fault,'comparison':'B1s-minus-'+other,'outcome':outcome,'common_item_model_pairs':len(common),'source_rooms':len(rooms),'difference':float(sums.sum()/ns.sum()),'paired_room_cluster95':np.quantile(draw,[.025,.975],method='linear').tolist(),'restriction':'Only identical model/room/variant/pair/target/start items successful in both arms; incomplete coverage not silently pooled'})
     for rm,n,x in zip(rooms,ns,sums):perroom.append({'model':model,'fault_class':fault,'comparison':'B1s-minus-'+other,'outcome':outcome,'room':rm,'common_item_model_pairs':int(n),'signed_event_difference':int(x),'difference':float(x/n)})
 def csvwrite(name,rr):
  if not rr:rr=[{'status':'NOT_DONE','reason':'No matched successful observations'}]
  with (out/name).open('w',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rr for k in r)));w.writeheader();w.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rr)
  for i,r in enumerate(rr):
   for k,v in r.items():
    if isinstance(v,(int,float,list)):
     e={'key':name+'/'+str(i)+'/'+k,'old':None,'new':v,'script':S,'flag':'NEW_ESTIMATE'};logs.append(e);print(json.dumps(e))
 csvwrite('C1_outcomes_wilson_cluster.csv',tables);csvwrite('C1_paired_common_item_differences.csv',paired);csvwrite('C1_paired_per_room.csv',perroom)
 numbers={'status':'COMPLETE' if len(new)==len(planned) and all(r['status']=='SUCCESS' for r in new) else 'PARTLY','C1_new_planned':len(planned),'C1_new_retained':len(new),'C1_new_successful':sum(r['status']=='SUCCESS' for r in new),'C1_new_unsuccessful_records':sum(r['status']!='SUCCESS' for r in new),'C1_pre_generation_refusals':sum(r.get('failure_kind')=='pre_generation_refusal' for r in new),'C1_generation_or_api_error_records':sum(r.get('failure_kind')=='generation_or_api_error' for r in new),'C1_technical_postprocess_error_records':sum(r.get('failure_kind')=='technical_postprocess_error' for r in new),'C1_successful_response_attempts':sum(t['status']=='SUCCESS' for r in new for t in r.get('attempts',[])),'C1_generation_api_error_attempts':sum(t['status'] not in ('SUCCESS','BUDGET_STOP','INPUT_TOKEN_LIMIT','MISSING_KEY','REQUEST_ALREADY_CLAIMED','TOKEN_COUNT_ERROR') for r in new for t in r.get('attempts',[])),'C1_pre_generation_refusal_attempts':sum(t['status'] in ('BUDGET_STOP','INPUT_TOKEN_LIMIT','MISSING_KEY','REQUEST_ALREADY_CLAIMED','TOKEN_COUNT_ERROR') for r in new for t in r.get('attempts',[])),'C1_new_not_done':len(planned)-len(new),'historical_calls':len(old),'bootstrap_seed':SEED,'bootstrap_resamples':B,'unit':'parent source room; injected fault variants share8sources, controls span20','C2':'NOT_DONE unless separately executed aftercompleteC1','D':'NOT_DONE; optional framework not substituted','limitations':'Historical original arms reused explicitly; prospective B1s schema adds reason. Pooled partial model coverage can differ. Failures never scored as successful abstentions.'}
 for name,value in [('numbers_C1.json',numbers),('comparisons_C1.json',logs),('report_proof.json',{'status':'PASS','input_sha256':pins,'network_forbidden':True,'generator':S})]:(out/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())

