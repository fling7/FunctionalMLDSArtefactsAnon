"""Sequential local timing delta. Run only after all recomputation workers stop."""
import sys,os,json,csv,time,platform,statistics,subprocess,hashlib,socket,copy
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').exists())
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
OUT=ROOT/'deliverables/delta_20261020'; RAW=ROOT/'drafts/delta_20261020/timing_raw'
CELLS=['gate0_table_build','gates_1_to_3','gate4_commit_protocol','no_guard_baseline','snapshot','commit_revalidation_packet','commit_digest_only','commit_routing_slice','evidence_append']
def write(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
def blocked(*a,**k):raise RuntimeError('NETWORK_FORBIDDEN_DELTA')
socket.socket.connect=blocked;socket.create_connection=blocked

def worker(size,deadline):
 from experiments.lib.backend_driver import Driver,ScriptedClient
 from experiments.lib.model_builder import build_room
 from experiments.wp5_extension_natural import runtime_admission
 from backend.roomcontract_v2_runtime import load_project_contract
 from backend.runtime_trace import contract_commit_fingerprint,_append_jsonl_transaction,log_backend_events
 from tools.routing_verifier import verify_routing
 dest=RAW/size;dest.mkdir(parents=True,exist_ok=True)
 project=None
 if size!='classroom':
  old=ROOT/'results/raw/go_sprint_20261019/cost/fixtures'/size/'projects'/('sprint_scale_'+size)
  if old.exists():project=old
  else:
   spec={'case_id':f'delta_scale_{size}','agents':['agent_a','agent_b','agent_c'],'objects':[{'id':f'object_{i:04d}'} for i in range(int(size))]}
   project=build_room(spec,dest/'fixture').project_dir
 source_pins={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file()} if project and size=='300' else {}
 d=Driver(project,client=ScriptedClient(latency=0))
 try:
  report=verify_routing(d.contract['instance'],d.contract['trace'],model_sha256=d.contract['model_sha256'])
  agent,target=next((a,t) for a,v in report['routing_table'].items() for t,r in v.items() if r['decision']=='ANSWER_LOCAL')
  obj=next(t for t in d.targets if t['id']==target); request=d.request(agent,obj);s=d.store;st=d.session
  grounding=s._validate_spatial_context(st,request['spatial_context']);route=s._resolve_spatial_route(st,agent,grounding);provider=s._v2_provider_entity_id(st,agent)
  actions={kind:s._preflight_v2_interaction_action(st=st,session_id=st.session_id,action_kind=kind,interaction_mode='deictic',provider_entity_id=provider,target_id=target) for kind in ['chat','handoff']}
  def baseline():
   with patch.object(s,'_validate_spatial_context',lambda *a,**k:copy.deepcopy(grounding)),patch.object(s,'_resolve_spatial_route',lambda *a,**k:copy.deepcopy(route)),patch.object(s,'_preflight_v2_interaction_action',lambda **k:copy.deepcopy(actions[k['action_kind']])):
    r=d.probe(request);assert r['decision']=='ANSWER_LOCAL';return r
  def admission():
   r=runtime_admission(d,request);assert r['decision']=='ANSWER_LOCAL';return r
  def commit(scope):return contract_commit_fingerprint(load_project_contract(d.project),scope,project_dir=d.project)
  def protocol():
   r=log_backend_events(project_manager=s.project_manager,project_id=d.project.name,entries=[{'action_kind':'chat','event_type':'delta_timing_commit','session_id':st.session_id,'agent_id':agent,'expected_action':actions['chat']['action']}],expected_contract_fingerprint=st.commit_fingerprint,publication_protocol=s.guard_config.publication_protocol,expected_publication_generation=getattr(st,'publication_generation',None),commit_variant=s.guard_config.commit_variant,pinned_contract=getattr(st,'pinned_contract',None))
   assert len(r)==1;return r
  funcs={'no_guard_baseline':baseline,'gates_1_to_3':admission,'snapshot':lambda:s.snapshot_session_mutation(st.session_id),'commit_revalidation_packet':lambda:commit('full'),'commit_digest_only':lambda:commit('digest_only'),'commit_routing_slice':lambda:commit('slice'),'evidence_append':lambda:_append_jsonl_transaction(dest/'evidence.jsonl',[{'event':'scripted'}],dest/'validation.jsonl',[{'valid':True}]),'gate0_table_build':lambda:verify_routing(d.contract['instance'],d.contract['trace'],model_sha256=d.contract['model_sha256']),'gate4_commit_protocol':protocol}
  write(dest/'fixture_metadata.json',{'size':size,'scene_objects':len(d.targets),'native_elements':len(d.contract['instance']['objects']),'reused_existing_scale_fixture':size=='300','publication_protocol':s.guard_config.publication_protocol,'commit_variant':s.guard_config.commit_variant,'network_forbidden':True,'model_latency':'none; baseline uses deterministic in-process stub only'})
  with (dest/'samples.jsonl').open('w',encoding='utf-8') as f:
   for cell in CELLS:
    for ordinal in range(12):
     if time.time()>=deadline:return
     t=time.perf_counter_ns();error=None
     try:funcs[cell]()
     except Exception as e:error=type(e).__name__+': '+str(e)
     ns=time.perf_counter_ns()-t
     f.write(json.dumps({'size':size,'cell':cell,'ordinal':ordinal,'discard':ordinal<2,'elapsed_ns':ns,'error':error})+'\n');f.flush()
     if error:break
 finally:
  d.close()
  assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in source_pins.items())
  write(dest/'retained_fixture_pins.json',source_pins)

def main():
 RAW.mkdir(parents=True,exist_ok=True)
 start=time.time();deadline=start+25*60
 def ps(code):return subprocess.check_output(['powershell.exe','-NoProfile','-Command',code],text=True,errors='replace').strip()
 hardware={'utc_start':datetime.now(timezone.utc).isoformat(),'cpu':ps('(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress)'), 'os':platform.platform(),'python':sys.version,'power_plan':subprocess.check_output(['powercfg','/getactivescheme'],text=True,errors='replace').strip(),'clock':vars(time.get_clock_info('perf_counter')),'clock_api':'time.perf_counter_ns','schedule':'one worker at a time; two discarded warmups then ten measured repetitions per cell','budget_seconds':1500,'scope':'Local wall-clock component timings; no model or HTTP latency. OS services and unrelated desktop applications are not stopped.'}
 write(OUT/'exports/delta_hardware.json',hardware)
 for size in ['classroom','300','1000']:
  remaining=deadline-time.time()
  if remaining<=0:break
  with (RAW/(size+'.log')).open('w',encoding='utf-8') as log:
   proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',size,str(deadline)],stdout=log,stderr=log)
   try:
    code=proc.wait(timeout=remaining)
    if code:write(RAW/(size+'_stop.json'),{'reason':'worker execution error','exit_code':code})
   except subprocess.TimeoutExpired:
    subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    proc.wait(timeout=20)
    write(RAW/(size+'_stop.json'),{'reason':'25 minute deadline; owned worker process tree terminated'});break
 rows=[];raw=[]
 for p in RAW.glob('*/samples.jsonl'):raw.extend(json.loads(x) for x in p.read_text().splitlines() if x)
 old=list(csv.DictReader((ROOT/'exports/cost_scale.csv').open(encoding='utf-8-sig')))
 for size in ['classroom','300','1000']:
  for cell in CELLS:
   selected=[r for r in raw if r['size']==size and r['cell']==cell];vals=[r['elapsed_ns']/1e6 for r in selected if not r['discard'] and r['error'] is None];previous=next((r for r in old if r['size']==size and r['cell']==cell),{})
   q=statistics.quantiles(vals,n=4,method='inclusive') if len(vals)>=2 else [None]*3
   r={'size':size,'cell':cell,'status':'DONE' if len(vals)>=10 else 'NOT DONE','warmups_discarded':sum(x['discard'] for x in selected),'repetitions':len(vals),'median_ms':statistics.median(vals) if len(vals)>=10 else None,'q1_ms':q[0] if len(vals)>=10 else None,'q3_ms':q[2] if len(vals)>=10 else None,'iqr_ms':q[2]-q[0] if len(vals)>=10 else None,'failures':sum(x['error'] is not None for x in selected),'old_p50_ms':previous.get('p50_ms'),'old_status':'INVALID_TIMER' if previous else 'NOT PREVIOUSLY MEASURED','comparison':'NEW_WALL_CLOCK_NOT_COMPARABLE_TO_OLD_CPU_CLOCK','script':'drafts/delta_20261020/timing_delta.py'}
   rows.append(r)
   for key,value in r.items():
    if isinstance(value,(int,float)):
     print(json.dumps({'size':size,'cell':cell,'key':key,'old':previous.get({'warmups_discarded':'discarded','repetitions':'measured','median_ms':'p50_ms'}.get(key,key)),'new':value,'flag':'NEW_OR_CHANGED_METRIC','script':'drafts/delta_20261020/timing_delta.py'}),flush=True)
   print(json.dumps({'old':previous.get('p50_ms'),'new':r['median_ms'],'size':size,'cell':cell,'flag':'CHANGED_METRIC_INVALID_OLD','script':'drafts/delta_20261020/timing_delta.py'}),flush=True)
 for name,data in [('exports/cost_scale.csv',rows),('tables/T8_cost_scale_delta.csv',rows),('tables/T8_cost_scale_legacy_invalid.csv',[dict(r,original_status=r['status'],status='INVALID_TIMER') for r in old])]:
  p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 write(OUT/'review/timing_samples.json',raw)
 write(OUT/'exports/delta_timing_fixtures.json',[json.loads(p.read_text()) for p in RAW.glob('*/fixture_metadata.json')])
 write(OUT/'review/timing_retained_fixture_pins.json',{p.parent.name:json.loads(p.read_text()) for p in RAW.glob('*/retained_fixture_pins.json')})
 write(OUT/'review/timing_worker_stops.json',[json.loads(p.read_text()) for p in RAW.glob('*_stop.json')])
 terminal={'utc_start':hardware['utc_start'],'utc_end':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.time()-start,'cells_done':sum(r['status']=='DONE' for r in rows),'cells_total':len(rows),'original_cells':24,'added_gate4_protocol_cells':3,'legacy_status':'INVALID_TIMER','zero_external_calls':True,'old_done':8,'new_done_original_grid':sum(r['status']=='DONE' and r['cell']!='gate4_commit_protocol' for r in rows),'error_samples':[r for r in raw if r['error']]}
 write(OUT/'review/timing_terminal.json',terminal);print(json.dumps(terminal))
if __name__=='__main__':
 if '--worker' in sys.argv:worker(sys.argv[2],float(sys.argv[3]))
 else:main()
