"""Stage B preregistration, offline workers, append-only checkpoints and summaries."""
from pathlib import Path
import argparse,collections,csv,hashlib,itertools,json,math,os,subprocess,sys,time
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
RAW=ROOT/'results/raw/delta2/stage_B';OUT=ROOT/'deliverables/delta2_20261020/stage_B'
SCRIPT=Path(__file__).relative_to(ROOT).as_posix();SEED=20261015

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8')as f:json.dump(v,f,indent=2);f.write('\n')
def audit(event,args):
 if event in ('socket.connect','socket.bind','socket.getaddrinfo'):raise RuntimeError('NETWORK_FORBIDDEN_STAGE_B')
def preregister():
 # No mutation or checker runs here. The inherited source registry fixes the population.
 source=ROOT/'deliverables/delta_20261020/tables/T3b_source_lineage.csv'
 lineage=list(csv.DictReader(source.open(encoding='utf-8-sig')))
 groups=collections.defaultdict(list)
 for r in lineage:groups[r['base_source']].append(r)
 assert len(groups)==56
 audits={}
 for p in sorted((ROOT/'data/go_sprint/sprint/w4/models').glob('*.json')):
  r=read(p)
  if 'model'in r:audits[r['model']['model_id']]=(r,p)
 candidates=[]
 for base,rs in sorted(groups.items()):
  # Prefer an unedited source, then lexicographic model ID; never use checker outcomes.
  chosen=min(rs,key=lambda r:(r['raw_source_id']!=base,r['cohort']=='zone_rename',r['model_id']))
  r,p=audits[chosen['model_id']];m=r['model'];project=ROOT/r['metadata']['project_path']
  files={name:sha(project/name)for name in ['roomcontract.v2.instance.json','trace_map.v2.json','project.json','agents.json']}
  origin='extension' if base.startswith('extension_')else'original'
  size='small' if m['objects']<=15 else 'medium' if m['objects']<=25 else'large'
  candidates.append(dict(room=base,model_id=m['model_id'],cohort='native_base',project=project.relative_to(ROOT).as_posix(),objects=m['objects'],agents=m['agents'],stratum=origin+'|'+size,files_sha256=files,selection_record=p.relative_to(ROOT).as_posix(),selection_record_sha256=sha(p)))
 classroom=[v for v in audits.values()if v[0]['model']['cohort']=='classroom'];assert len(classroom)==1
 r,p=classroom[0];project=ROOT/r['metadata']['project_path'];m=r['model']
 c=dict(room='authored_classroom',model_id=m['model_id'],cohort='classroom',project=project.relative_to(ROOT).as_posix(),objects=m['objects'],agents=m['agents'],stratum='classroom',files_sha256={n:sha(project/n)for n in ['roomcontract.v2.instance.json','trace_map.v2.json','project.json','agents.json']},selection_record=p.relative_to(ROOT).as_posix(),selection_record_sha256=sha(p))
 strata=collections.defaultdict(list)
 for r in candidates:strata[r['stratum']].append(r)
 for values in strata.values():values.sort(key=lambda r:hashlib.sha256(f'{SEED}|{r["room"]}'.encode()).hexdigest())
 selected=[]
 while len(selected)<21:
  for name in sorted(strata):
   if strata[name] and len(selected)<21:selected.append(strata[name].pop(0))
 selected.append(c)
 # Cost planning uses retained equivalence benchmark, not fresh mutant outcomes.
 plan=dict(status='PREREGISTERED_NOT_EXECUTED',created_utc=datetime.now(timezone.utc).isoformat(),source_registry_sha256=sha(source),population=candidates+[c],selected=selected,selection='21 native bases by round-robin across source-origin x object-count strata, seeded hash order within strata; plus classroom. Representative is unedited first then lexicographic model ID. No detector outcomes consulted.',reason_for_subset='Full 57x17=969 planned mutant slots with all oracle pairs and compiled I2 could exceed 60 minutes. Retained compiled policy benchmarks report about 140 seconds for 827 calls plus compile time; multiple tens of oracle pairs per mutant imply more than 60 minutes sequential. Select bounded 22-room subset before observing new outcomes.',seed=SEED,bootstrap_resamples=10000,budget_seconds=3600,worker_limit=2,per_mutant_timeout_seconds=150,oracle_policy='I1 and retained compiled I2 on all normal agent/object pairs; Gate0 lookup must agree on four-field verdict. These are pure oracle queries, not backend or model probes.',groundtruth='True iff all I1/I2/Gate0 pair verdicts agree and at least one I1 reason is E_UNOWNED,E_AMBIGUOUS_OWNER,E_NO_DECLARED_ACTION,E_ACTION_AMBIGUOUS. False iff agreement and all reasons in those plus null,E_NO_HANDOFF_PATH and none faulty. Otherwise unknown; never force consistency.',mutations='17 original single operators, original seed derivation, no pairs. no_op/not_applicable/technical failures excluded and reported; refresh_projections preserves documented main-study procedure.',network='forbidden',backend_setup=False,backend_probes=False,new_model_calls=0,cohort_separation='New Stage B only; no pooling with generated908 or classroom153.',statistical_estimands='Mutant TP/FN/FP/TN among determinate ground truth; sensitivity and specificity Wilson95 plus paired resampling of selected rooms (10000,seed20261015), per-room and per-operator. Undefined bootstrap denominators omitted and count retained.',script_sha256=sha(Path(__file__)),supersedes='preregistration_v2.json (same rooms, same mutation seeds; termination and accounting robustness only)',resampling_room_set='All selected rooms including those with zero eligible outcomes; room-specific summaries use that room only.')
 save(RAW/'preregistration_v3.json',plan)
 print(json.dumps({'plan_sha256':sha(RAW/'preregistration_v3.json'),'population':len(plan['population']),'selected':len(selected),'status':plan['status']}))

def worker(jobpath):
 sys.addaudithook(audit)
 from experiments.mutations import Bundle,mutate,refresh_projections,digest,NotApplicable
 from experiments.detection_matrix import validators,request_for
 from tools.routing_verifier import lookup_route
 from verification.impl_a.reference import evaluate
 from verification.impl_b.compiled_policy import compile_model
 job=read(Path(jobpath));room=job['room'];project=ROOT/room['project']
 for name,pin in room['files_sha256'].items():assert sha(project/name)==pin
 bundle=Bundle.load(project);operator=job['operator'];started=time.monotonic()
 seed=int.from_bytes(hashlib.sha256(f'{SEED}|{bundle.instance.get("caseId")}|{operator}'.encode()).digest()[:8],'big')
 result=dict(room=room['room'],cohort=room['cohort'],operator=operator,seed=seed,status='TECHNICAL_FAILURE',groundtruth=None,oracle_queries=0)
 try:
  mutated,change=mutate(bundle,operator,seed);result['change']=change
  if not change['changed']:result['status']='NO_OP'
  else:
   mutated=refresh_projections(mutated)
   checks,table=validators(mutated)
   result['checkers']=checks;result['mutant_sha256']=digest(mutated.instance)
   technical=[k for k,v in checks.items() if v.get('exception') in {'MemoryError','RecursionError','SystemError','ImportError','ModuleNotFoundError','TimeoutError'}]
   if technical:raise RuntimeError('TECHNICAL_CHECKER_FAILURE:'+','.join(technical))
   policy=compile_model(mutated.instance,mutated.trace,allow_fallback=False)
   session={'model_sha256':digest(mutated.instance),'active_agent_mode':'client'}
   agents=sorted({o['sourceAgentId']for o in mutated.instance['objects']if o.get('type')=='Agent'})
   targets=sorted((o for o in mutated.instance['objects']if o.get('entityRole')=='sceneObject'),key=lambda x:x['id'])
   pairs=[];faults={'E_UNOWNED','E_AMBIGUOUS_OWNER','E_NO_DECLARED_ACTION','E_ACTION_AMBIGUOUS'}
   for agent,target in itertools.product(agents,targets):
    request=request_for(agent,target,session['model_sha256'])
    a=evaluate(mutated.instance,mutated.trace,request,session);b=policy.evaluate(request,session);g=lookup_route(table,agent,target['id'])
    pairs.append(dict(agent=agent,target=target['id'],I1=a,I2=b,Gate0=g,agreement=a==b==g))
   result['oracle_pairs']=pairs;result['oracle_queries']=len(pairs)
   expected=all(p['I1'].get('reason')in faults|{None,'E_NO_HANDOFF_PATH'}for p in pairs)
   agreed=all(p['agreement']for p in pairs)
   result['groundtruth']=any(p['I1'].get('reason')in faults for p in pairs)if agreed and expected and pairs else None
   result['status']='EVALUATED';result['groundtruth_exclusion']=None if result['groundtruth']is not None else 'oracle_disagreement_or_out_of_scope'
 except NotApplicable as e:result.update(status='NOT_APPLICABLE',detail=str(e))
 except Exception as e:result.update(status='TECHNICAL_FAILURE',error_type=type(e).__name__,detail=str(e))
 result['elapsed_seconds']=time.monotonic()-started
 save(ROOT/job['output'],result)

def stop_owned_tree(proc):
 # Popen can be a Windows venv launcher with a Python child. Capture only this
 # owned tree, terminate descendants with taskkill, then verify every child died.
 import psutil
 owned=[]
 try:owned=psutil.Process(proc.pid).children(recursive=True)
 except psutil.NoSuchProcess:pass
 if os.name=='nt':
  subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
 else:
  for child in reversed(owned):
   try:child.kill()
   except psutil.NoSuchProcess:pass
  if proc.poll()is None:proc.kill()
 proc.wait(timeout=30)
 _,alive=psutil.wait_procs(owned,timeout=10)
 for child in alive:
  try:child.kill()
  except psutil.NoSuchProcess:pass
 _,alive=psutil.wait_procs(alive,timeout=10)
 if alive:raise RuntimeError('OWNED_WORKER_TREE_STILL_ALIVE')

def execute():
 from experiments.mutations import OPERATORS
 plan=read(RAW/'preregistration_v3.json');assert plan['script_sha256']==sha(Path(__file__))
 start=time.monotonic();deadline=start+plan['budget_seconds'];queue=[]
 for room in plan['selected']:
  for operator in OPERATORS:
   key=room['room']+'__'+operator;output=RAW/'completed'/(key+'.json')
   if output.exists():continue
   job=dict(room=room,operator=operator,output=output.relative_to(ROOT).as_posix())
   jpath=RAW/'jobs'/(key+'.json')
   if jpath.exists():assert read(jpath)==job
   else:save(jpath,job)
   queue.append((key,jpath,output))
 active=[];failures=[]
 while (queue or active)and time.monotonic()<deadline:
  while queue and len(active)<plan['worker_limit']:
   key,jpath,output=queue.pop(0);logpath=RAW/'console'/(key+'.txt');logpath.parent.mkdir(exist_ok=True)
   if logpath.exists():logpath=logpath.with_name(key+'__resume_'+str(time.time_ns())+'.txt')
   log=logpath.open('x',encoding='utf-8')
   proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__)),'worker',str(jpath)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
   active.append((proc,log,key,output,time.monotonic()))
  time.sleep(.25)
  for item in active[:]:
   proc,log,key,output,began=item
   timeout=time.monotonic()-began>plan['per_mutant_timeout_seconds']
   if proc.poll()is None and not timeout:continue
   if timeout:stop_owned_tree(proc)
   log.close();active.remove(item)
   if not output.exists():
    failure=dict(key=key,status='TECHNICAL_TIMEOUT'if timeout else'TECHNICAL_FAILURE',exit_code=proc.returncode)
    failures.append(failure);save(RAW/'failures'/(key+'__'+str(time.time_ns())+'.json'),failure)
 for proc,log,key,output,began in active:stop_owned_tree(proc);log.close();failures.append(dict(key=key,status='BUDGET_STOP_NOT_EVALUATED'))
 save(RAW/('terminal_'+str(time.time_ns())+'.json'),dict(ended_utc=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-start,queued_not_executed=[x[0]for x in queue],failures=failures,api_calls=0))
 summarize()

def summarize():
 import numpy as np
 from experiments.mutations import OPERATORS
 (OUT/'tables').mkdir(parents=True,exist_ok=True)
 (OUT/'review').mkdir(parents=True,exist_ok=True)
 plan=read(RAW/'preregistration_v3.json');records=[read(p)for p in sorted((RAW/'completed').glob('*.json'))]
 observed=list(records)
 indexed={(r['room'],r['operator']):r for r in records}
 for room in plan['selected']:
  for operator in OPERATORS:
   if (room['room'],operator)not in indexed:records.append(dict(room=room['room'],cohort=room['cohort'],operator=operator,status='NOT_RUN',groundtruth=None,oracle_queries=0))
 checker_names=['Va_structural','Vb_native_schema','Vb_native_domain','Vb_trace_schema','Vb_legacy_invariants_view','Vb_handoff_metrics','Vc_instance','Vc_trace','nonoracle_union']
 def rejected(r,k):
  c=r['checkers'];return any(c[x]['status']=='reject'for x in checker_names[:-1])if k=='nonoracle_union'else c[k]['status']=='reject'
 eligible=[r for r in records if r['status']=='EVALUATED'and r['groundtruth']is not None]
 def wilson(a,n):
  if not n:return None
  z=1.959963984540054;p=a/n;den=1+z*z/n;center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den;return[center-half,center+half]
 rows=[]
 selected_rooms=sorted(r['room']for r in plan['selected'])
 scopes=[('pooled',eligible,selected_rooms)]+[(x,[r for r in eligible if r['operator']==x],selected_rooms)for x in OPERATORS]+[(x,[r for r in eligible if r['room']==x],[x])for x in selected_rooms]
 for scope,values,resample_rooms in scopes:
  for checker in checker_names:
   by={room:np.zeros(4,dtype=int)for room in resample_rooms}
   used=[r for r in values if checker=='nonoracle_union' or r['checkers'][checker]['status']in ('pass','reject')]
   for r in used:
    positive=r['groundtruth'];hit=rejected(r,checker);by[r['room']][0 if positive and hit else 1 if positive else 2 if hit else 3]+=1
   sums=sum(by.values(),np.zeros(4,dtype=int));tp,fn,fp,tn=map(int,sums)
   out=dict(scope=scope,checker=checker,mutants=len(used),checker_not_applicable_excluded=len(values)-len(used),resampling_rooms=len(by),rooms_with_eligible_observations=sum(bool(v.sum())for v in by.values()),TP=tp,FN=fn,FP=fp,TN=tn,sensitivity_wilson95=wilson(tp,tp+fn),specificity_wilson95=wilson(tn,tn+fp))
   for label,a,b in [('sensitivity',0,1),('specificity',3,2)]:
    if by:
     matrix=np.array([by[k]for k in sorted(by)]);idx=np.random.default_rng(SEED).integers(0,len(matrix),(10000,len(matrix)));draw=matrix[idx].sum(axis=1);den=draw[:,a]+draw[:,b];valid=den>0;rates=draw[valid,a]/den[valid]
     out[label+'_cluster95']=list(np.quantile(rates,[.025,.975]))if len(rates)else None;out[label+'_valid_resamples']=int(valid.sum())
    else:out[label+'_cluster95']=None;out[label+'_valid_resamples']=0
   rows.append(out)
 if not rows:raise RuntimeError('No eligible outcomes; cannot claim detection performance')
 with (OUT/'tables/T_B1_detection.csv').open('x',newline='',encoding='utf-8')as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 rawrows=[dict(room=r['room'],cohort=r['cohort'],operator=r['operator'],status=r['status'],groundtruth=r.get('groundtruth'),oracle_queries=r.get('oracle_queries',0),**{k:r.get('checkers',{}).get(k,{}).get('status','NOT_RUN')for k in checker_names[:-1]})for r in records]
 with (OUT/'tables/T_B1_room_operator_outcomes.csv').open('x',newline='',encoding='utf-8')as f:
  w=csv.DictWriter(f,fieldnames=list(rawrows[0]));w.writeheader();w.writerows(rawrows)
 nums=dict(stageB_selected_rooms=len(plan['selected']),stageB_observed_rooms=len({r['room']for r in observed}),stageB_outcomes=len(observed),stageB_planned_slots=len(records),stageB_groundtruth_eligible=len(eligible),stageB_status_counts=dict(collections.Counter(r['status']for r in records)),stageB_oracle_queries=sum(r.get('oracle_queries',0)for r in records),stageB_backend_probes=0,stageB_api_calls=0)
 save(OUT/'review/numbers_b1.json',nums)
 log=[dict(key=k,old=None,new=v,script=SCRIPT,flag='NEW_COHORT')for k,v in nums.items()]
 for i,r in enumerate(rows):
  for k,v in r.items():
   if isinstance(v,(int,float,list))or v is None:log.append(dict(key=f'T_B1_detection[{i}].{k}',old=None,new=v,script=SCRIPT,flag='NEW_COHORT'))
 save(OUT/'review/numeric_log_b1.json',log)
 for x in log:print(json.dumps(x))
 save(OUT/'review/proof_b1.json',dict(status='COMPLETE_WITH_EXPLICIT_ELIGIBILITY'if len(observed)==len(plan['selected'])*17 and all(r['status']in ('EVALUATED','NO_OP','NOT_APPLICABLE')for r in observed)else'PARTIAL_TECHNICAL_OR_UNEXECUTED',determinate_groundtruth=len(eligible),unknown_groundtruth=sum(r['status']=='EVALUATED'and r.get('groundtruth')is None for r in observed),script_sha256=sha(Path(__file__)),preregistration_sha256=sha(RAW/'preregistration_v3.json'),outcome_hashes={p.relative_to(ROOT).as_posix():sha(p)for p in sorted((RAW/'completed').glob('*.json'))},new_api_spend_usd=0))
 note='Stage B: new stratified cohort, separate from 908/153. Selection frozen before mutant outcomes. No backend setup, no backend/model probes; pure oracle queries only. I1, compiled I2 and Gate0 must agree for determinate ground truth. Technical errors, unknown truth, no-ops and inapplicable operators remain excluded with explicit counts. Results do not estimate prevalence across all 56 sources. Source-room bootstrap uses all selected rooms, including zero-eligible rooms, with 10000 resamples seed20261015; per-room scopes use their single room. Zero-denominator draws excluded and reported. Checker not-applicable rows excluded from that checker denominator. All planned slots retained, including NOT_RUN. Completion of execution is separate from determinate scientific ground truth. Single-room bootstrap intervals are degenerate and do not establish population certainty.\n'+json.dumps(nums,indent=2)+'\n'
 (OUT/'review/item_notes_b1.md').write_text(note,encoding='utf-8')
if __name__=='__main__':
 mode=sys.argv[1]
 if mode=='preregister':preregister()
 elif mode=='worker':worker(sys.argv[2])
 elif mode=='execute':execute()
 elif mode=='summarize':summarize()
