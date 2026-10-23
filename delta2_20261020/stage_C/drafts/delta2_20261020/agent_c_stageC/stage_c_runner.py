"""Stage C runner. DRAFT CODE: not executed during exclusive Stage A timing.
freeze requires reviewed prices, exact model IDs and pre-discovery ledger context.
run --live is the only command that permits generation. Existing ledger is shared.
"""
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone
import argparse,copy,hashlib,json,sqlite3,sys
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R));EXP='WP4.delta2.C1'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def ledger_state():
 path=R/'logs/api_budget.sqlite3';con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
 try:
  policy=json.loads(con.execute("SELECT value FROM settings WHERE name='policy'").fetchone()[0]);accounted=con.execute('SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM reservations').fetchone()[0];wp4=con.execute("SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM reservations WHERE share='WP4'").fetchone()[0];last=con.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
  return {'policy':policy,'policy_sha256':hashlib.sha256(canonical(policy)).hexdigest(),'accounted_usd':str(Decimal(accounted)/10**9),'WP4_remaining_usd':str(Decimal(policy['limits']['WP4']-wp4)/10**9),'last_event_id':last}
 finally:con.close()
def freeze(a):
 out=a.output.resolve()
 if out.exists():raise RuntimeError('Freeze output already exists; never overwrite')
 candidates=read(a.candidates);ctx=read(a.stage_context);prices=read(a.prices);rates=prices['models'];original=read(R/'prereg/go_sprint_20261019/w3/requests.json');oldmodels=read(R/'prereg/go_sprint_20261019/w3/design.json')['models']
 models=oldmodels+[a.small,a.flagship];assert len(set(models))==4
 for m in models:
  assert m in rates
  for k in ('input_per_million','output_per_million','context_window','max_output_tokens'):assert k in rates[m]
 assert prices.get('sources') and prices.get('retrieved_on'),'Verified official pricing provenance required'
 state=ledger_state();assert state['policy_sha256']==ctx['policy_sha256'];assert state['policy']['cap']==20*10**9
 assert int(ctx['starting_event_id'])<=state['last_event_id'];assert Decimal(ctx['initial_accounted_usd'])<=Decimal(state['accounted_usd'])
 def unit(r):return (r['room'],r['variant'],r['pair_index'],r['target_id'],r['start_agent'])
 template={unit(r):r for r in original if r['baseline']=='B0' and r['model']==oldmodels[0]};keys=list(template);assert len(keys)==45
 by={(unit(r),r['baseline']):r for r in original if r['model']==oldmodels[0]};strong={unit(r):r for r in candidates if r['payload']['model']==oldmodels[0]};assert set(strong)==set(keys)
 ordered=[]
 # Complete original-model B1s cohorts first. New-model arms interleaved by item,
 # so a budget cutoff preserves paired prefixes rather than completing only B0.
 for model in oldmodels:
  for key in keys:ordered.append((model,'B1s',key))
 for model in (a.small,a.flagship):
  for key in keys:
   for arm in ('B0','B1','B1r','B1s'):ordered.append((model,arm,key))
 reqs=[]
 for n,(model,arm,key) in enumerate(ordered):
  source=strong[key] if arm=='B1s' else by[key,arm];payload=copy.deepcopy(source['payload']);payload['model']=model
  payload['max_output_tokens']=(a.new_model_max_output_b1s if arm=='B1s' else a.new_model_max_output_original) if model in (a.small,a.flagship) else (128 if arm=='B1s' else 96)
  assert 1<=payload['max_output_tokens']<=int(rates[model]['max_output_tokens'])
  if model in a.default_temperature_model:payload.pop('temperature',None)
  fallback=copy.deepcopy(payload);fallback.pop('temperature',None)
  base=template[key]
  reqs.append({'item_id':f'c1_{n:04d}','block_key':list(key),'room':base['room'],'variant':base['variant'],'fault_class':base['fault_class'],'target_id':base['target_id'],'start_agent':base['start_agent'],'I1':base['I1'],'agents':base['agents'],'baseline':arm,'model':model,'payload':payload,'fallback_payload':fallback,'input_limit':10000,'payload_sha256':hashlib.sha256(canonical(payload)).hexdigest(),'fallback_payload_sha256':hashlib.sha256(canonical(fallback)).hexdigest()})
 out.mkdir(parents=True);save(out/'requests.json',reqs);save(out/'prices.json',prices);save(out/'stage_context.json',ctx)
 design={'status':'FROZEN','frozen_utc':datetime.now(timezone.utc).isoformat(),'experiment':EXP,'models':models,'new_small_model':a.small,'new_flagship_model':a.flagship,'planned_requests':len(reqs),'distinct_items':45,'scope':'C1 only; C2 separately registered after complete successful C1 and remaining budget; D not substituted','order':{'original_B1s_model_order':oldmodels,'new_model_order':[a.small,a.flagship],'within_new_model':'item-major B0,B1,B1r,B1s'},'new_model_output_caps':{'original_arms':a.new_model_max_output_original,'B1s':a.new_model_max_output_b1s},'partial_rule':'Stop at budget without replacing experiment; every planned unexecuted item NOT_DONE; partial C1 cannot unlock C2','temperature_policy':{'default_models':a.default_temperature_model,'otherwise':0.3,'fallback':'Only cached explicit unsupported temperature parameter HTTP error permits once-only frozen fallback payload; retain both attempts. No fallback for unknown/network outcome.'},'stage_extra_cap_usd':'15','ledger_policy_sha256':ctx['policy_sha256'],'authoritative_ledger':'logs/api_budget.sqlite3','fixed_ledger_cap_usd':'20','share':'WP4','starting_event_id':ctx['starting_event_id'],'initial_accounted_usd':ctx['initial_accounted_usd'],'input_ceiling':10000,'provider_exact_input_count':True,'generation_attempts_per_payload':1,'bootstrap_seed':20261015,'bootstrap_resamples':10000,'requests_sha256':sha(out/'requests.json'),'prices_sha256':sha(out/'prices.json'),'context_sha256':sha(out/'stage_context.json'),'runner_sha256':sha(Path(__file__)),'source_pins':{str(Path(p).resolve().relative_to(R)):sha(p) for p in (a.candidates,a.prices,a.stage_context,R/'prereg/go_sprint_20261019/w3/requests.json')}}
 save(out/'design.json',design);(out/'design.sha256').write_text(sha(out/'design.json')+'\n');print(json.dumps({'frozen':str(out),'requests':len(reqs),'design_sha256':sha(out/'design.json'),'budget':state}))
def loadplan(out):
 d=read(out/'design.json');assert sha(out/'design.json')==(out/'design.sha256').read_text().strip();assert sha(out/'requests.json')==d['requests_sha256'];assert sha(out/'prices.json')==d['prices_sha256'];assert sha(out/'stage_context.json')==d['context_sha256'];assert sha(Path(__file__))==d['runner_sha256'];return d,read(out/'requests.json')
class StageBudget:
 def __init__(self,inner,design):self.inner=inner;self.design=design
 def __getattr__(self,k):return getattr(self.inner,k)
 def reserve(self,share,experiment,upper):
  from repro.budget import BudgetError
  if share!='WP4' or not experiment.startswith('WP4.delta2.'):raise BudgetError('Wrong stage allocation/experiment')
  if self.inner.policy()['sha256']!=self.design['ledger_policy_sha256']:raise BudgetError('Authoritative policy changed')
  spent=Decimal(self.inner.summary()['accounted_usd'])-Decimal(self.design['initial_accounted_usd'])
  if spent+Decimal(upper)/10**9>Decimal(self.design['stage_extra_cap_usd']):raise BudgetError('Stage C incremental cap reached')
  return self.inner.reserve(share,experiment,upper)
def gateway(out,d,live):
 from repro.llm import Gateway
 g=Gateway(R,replay=True,count_input_tokens=True);g.logs=out/'logs';g.cache=g.logs/'llm_cache';g.prices=read(out/'prices.json')['models']
 if live:
  from repro.budget import Budget
  from importlib import import_module;load_env=import_module('repro'+chr(46)+'env').load_env
  load_env(R);inner=Budget(R/'logs/api_budget.sqlite3',max_usd='20');assert inner.policy()['sha256']==d['ledger_policy_sha256'];g.budget=StageBudget(inner,d);g.replay=False
 return g
def cached_error(g,row,payload,item):
 # Exact cache envelope mirrors Gateway.responses after prepare().
 from repro.llm import API_BASE
 envelope={'version':1,'endpoint':API_BASE+'/responses','experiment_id':EXP,'item_id':item,'repetition_id':'0','share':'WP4','payload':g.prepare(payload)};path=g.cache/(hashlib.sha256(canonical(envelope)).hexdigest()+'.json')
 return read(path).get('response',{}).get('error',{}) if path.exists() else {}
def unsupported_temperature(error):
 text=str(error.get('message','')).lower();return error.get('param')=='temperature' and (error.get('code') in ('unsupported_parameter','unsupported_value') or 'not support' in text)
def execute(a):
 from repro.llm import GatewayError,sanitize
 from repro.budget import BudgetError
 from experiments.lib.wp4_common import parsed_output
 from experiments.routing_baselines import classify
 out=a.output.resolve();d,reqs=loadplan(out)
 if not a.live:raise RuntimeError('Use replay command for offline verification; --live required for authorized execution')
 g=gateway(out,d,True);stop=None
 for row in reqs:
  dest=out/'rows'/(row['item_id']+'.json')
  if dest.exists():continue
  state=g.budget.summary();alloc=state['allocations']['WP4']
  if state['halted'] or Decimal(alloc['stop_usd'])<=Decimal(alloc['accounted_usd']):stop='BUDGET_STOP';break
  saved={k:v for k,v in row.items() if k not in ('payload','fallback_payload','agents')};attempts=[];payload=row['payload'];item=row['item_id']
  for fallback in (False,True):
   try:
    response=g.responses(payload,experiment_id=EXP,item_id=item,repetition_id='0',share='WP4',max_input_tokens=10000,max_attempts=1);attempts.append({'item_id':item,'status':'SUCCESS','response':response});parsed=parsed_output(response);attempts[-1]['parsed']=parsed;saved['status']='SUCCESS';saved['effective_payload']='fallback_payload' if fallback else 'payload';saved['effective_item_id']=item
    primary={k:parsed.get(k) for k in ('answering_agent_id','abstain')} if row['baseline']=='B1s' and isinstance(parsed,dict) else parsed
    saved['outcome']=classify(primary,row['I1'],row['agents'],True)
    saved['reason_correct']=(parsed.get('reason')==row['I1'].get('reason')) if row['baseline']=='B1s' and isinstance(parsed,dict) else None
    if row['baseline']=='B1s' and (not isinstance(parsed,dict) or set(parsed)!=set(('answering_agent_id','abstain','reason'))):saved['outcome']='FORMAT_ERROR';saved['reason_correct']=False
    saved['failure_kind']=None
    break
   except (GatewayError,BudgetError) as exc:
    code=getattr(exc,'code','BUDGET_STOP');err=cached_error(g,row,payload,item);attempts.append({'item_id':item,'status':code,'error':err});saved['status']=code;saved['outcome']=None;saved['failure_kind']='pre_generation_refusal' if code in ('BUDGET_STOP','INPUT_TOKEN_LIMIT','MISSING_KEY','REQUEST_ALREADY_CLAIMED','TOKEN_COUNT_ERROR') else 'generation_or_api_error'
    if code=='BUDGET_STOP':stop=code;break
    if not fallback and 'temperature' in payload and unsupported_temperature(err):payload=row['fallback_payload'];item=row['item_id']+'.temperature_default';continue
    break
   except Exception as exc:
    # Preserve any already-paid response in attempts/cache. Technical parsing or
    # classifier failures are not scored as scientific outcomes or retried.
    saved['status']='TECHNICAL_POSTPROCESS_ERROR';saved['outcome']=None;saved['reason_correct']=None;saved['failure_kind']='technical_postprocess_error';saved['technical_exception_type']=type(exc).__name__;saved['technical_exception_message']=str(exc)
    break
  saved['attempts']=attempts;save(dest,sanitize(saved));print(json.dumps({'item_id':row['item_id'],'model':row['model'],'arm':row['baseline'],'status':saved['status'],'outcome':saved['outcome']}),flush=True)
  if stop:break
 rows=[read(p) for p in sorted((out/'rows').glob('*.json'))];complete=len(rows)==len(reqs) and all(r['status']=='SUCCESS' for r in rows)
 save(out/'terminal.json',{'status':'COMPLETE' if complete else 'PARTLY','planned':len(reqs),'retained':len(rows),'successful':sum(r['status']=='SUCCESS' for r in rows),'not_done':len(reqs)-len(rows),'stop_reason':stop,'C2_eligible':complete and Decimal(g.budget.summary()['allocations']['WP4']['stop_usd'])>Decimal(g.budget.summary()['allocations']['WP4']['accounted_usd']),'D_status':'NOT_DONE: not part of C1; no substitution','budget':g.budget.summary(),'incremental_accounted_usd':str(Decimal(g.budget.summary()['accounted_usd'])-Decimal(d['initial_accounted_usd']))});export_events(out,d)
def export_events(out,d):
 con=sqlite3.connect((R/'logs/api_budget.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
 try:
  events=[{'ledger_event_id':i,**json.loads(s)} for i,s in con.execute('SELECT id,record FROM events WHERE id>? ORDER BY id',(int(d['starting_event_id']),))]
 finally:con.close()
 selected=[r for r in events if r.get('experiment_id','').startswith('WP4.delta2.') or (r.get('experiment_id')=='WP0.preflight' and r.get('endpoint')=='/models')]
 path=out/'filtered_stageC_events.jsonl';path.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in selected),encoding='utf-8');save(out/'filtered_export_proof.json',{'starting_event_id':d['starting_event_id'],'selection':'delta2 experiment events plus model-discovery events after pre-discovery starting event ID; only StageC API work allowed concurrently','events_exported':len(selected),'sha256':sha(path),'historical_redirected_raw_log_excluded_from_package':True})
def replay(a):
 import socket
 def deny(*x,**k):raise RuntimeError('Network forbidden in replay')
 socket.create_connection=deny;socket.socket.connect=deny
 out=a.output.resolve();d,reqs=loadplan(out);by={r['item_id']:r for r in reqs};g=gateway(out,d,False);checked=[];failed_checked=[];no_response_cache=[]
 for p in sorted((out/'rows').glob('*.json')):
  saved=read(p);row=by[saved['item_id']]
  for attempt in saved['attempts']:
   payload=row['fallback_payload'] if attempt['item_id'].endswith('.temperature_default') else row['payload']
   if attempt['status']=='SUCCESS':
    response=g.responses(payload,experiment_id=EXP,item_id=attempt['item_id'],repetition_id='0',share='WP4',max_input_tokens=10000,max_attempts=1);assert response==attempt['response'];checked.append(attempt['item_id'])
   else:
    from repro.llm import GatewayError
    try:
     g.responses(payload,experiment_id=EXP,item_id=attempt['item_id'],repetition_id='0',share='WP4',max_input_tokens=10000,max_attempts=1)
     raise AssertionError('Failed retained attempt unexpectedly replays success')
    except GatewayError as exc:
     if exc.code=='REPLAY_MISS':
      assert attempt['status'] in ('BUDGET_STOP','TOKEN_COUNT_ERROR','INPUT_TOKEN_LIMIT','MISSING_KEY','REQUEST_ALREADY_CLAIMED');no_response_cache.append(attempt['item_id'])
     else:
      assert exc.code=='API_ERROR';assert cached_error(g,row,payload,attempt['item_id'])==attempt.get('error',{});failed_checked.append(attempt['item_id'])
 save(out/'replay_proof.json',{'failed_response_caches_verified':failed_checked,'no_response_cache_expected':no_response_cache,'status':'PASS','successful_responses_replayed':len(checked),'item_ids':checked,'network_forbidden':True,'failed_calls_preserved':'rows and filtered event export; not credited as successful replay'})
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('freeze','run','replay'));p.add_argument('--output',type=Path,required=True);p.add_argument('--candidates',type=Path);p.add_argument('--prices',type=Path);p.add_argument('--stage-context',type=Path);p.add_argument('--small');p.add_argument('--flagship');p.add_argument('--default-temperature-model',action='append',default=[]);p.add_argument('--new-model-max-output-original',type=int,default=96);p.add_argument('--new-model-max-output-b1s',type=int,default=128);p.add_argument('--live',action='store_true');a=p.parse_args();{'freeze':freeze,'run':execute,'replay':replay}[a.mode](a)



