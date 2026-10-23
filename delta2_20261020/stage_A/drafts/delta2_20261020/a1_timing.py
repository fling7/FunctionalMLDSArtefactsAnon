"""A1: unoptimized production runtime/table admission, paired sequential timings."""
import os,sys,json,csv,time,statistics,subprocess,socket,copy,cProfile,pstats,hashlib,platform
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from dataclasses import replace
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').is_file())
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
RAW=ROOT/'results/raw/delta2/stage_A/a1';OUT=ROOT/'deliverables/delta2_20261020/stage_A'
CELLS=['gate0_table_build','table_persist_json','table_load_warm_os_cache','verified_table_cold_memory_cache','verified_table_warm_memory_cache','gates_1_to_3_table','gates_1_to_3_runtime','no_guard_baseline','gate4_commit_protocol']
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def deny(*a,**k):raise RuntimeError('NETWORK_FORBIDDEN_A1')
socket.socket.connect=deny;socket.create_connection=deny

def worker(size,deadline):
 from experiments.lib.backend_driver import Driver,ScriptedClient
 from experiments.lib.model_builder import build_room
 from experiments.wp5_extension_natural import runtime_admission
 from backend.guard_config import GuardConfig
 from backend.runtime_trace import log_backend_events
 from backend import verified_routing
 from tools.routing_verifier import verify_routing
 dest=RAW/size;dest.mkdir(parents=True,exist_ok=True);preparing=time.time()
 old=None
 if size=='300':old=ROOT/'results/raw/go_sprint_20261019/cost/fixtures/300/projects/sprint_scale_300'
 if size=='1000':old=ROOT/'drafts/delta_20261020/timing_raw/1000/fixture/projects/delta_scale_1000'
 if size=='classroom':project=None
 elif old and (old/'project.json').is_file():project=old
 else:
  spec={'case_id':f'delta2_scale_{size}','agents':['agent_a','agent_b','agent_c'],'objects':[{'id':f'object_{i:04d}'} for i in range(int(size))]}
  project=build_room(spec,dest/'fixture').project_dir
 pins={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file()} if old else {}
 d=Driver(project,client=ScriptedClient(latency=0))
 try:
  report=verify_routing(d.contract['instance'],d.contract['trace'],model_sha256=d.contract['model_sha256'])
  agent,target=next((a,t) for a,v in report['routing_table'].items() for t,r in v.items() if r['decision']=='ANSWER_LOCAL')
  obj=next(t for t in d.targets if t['id']==target);request=d.request(agent,obj);s=d.store;st=d.session
  config=GuardConfig(digest_check=True);s.guard_config=config
  st.routing_table=verified_routing.verified_table(d.contract)
  grounding=s._validate_spatial_context(st,request['spatial_context']);route=s._resolve_spatial_route(st,agent,grounding);provider=s._v2_provider_entity_id(st,agent)
  actions={kind:s._preflight_v2_interaction_action(st=st,session_id=st.session_id,action_kind=kind,interaction_mode='deictic',provider_entity_id=provider,target_id=target) for kind in ['chat','handoff']}
  table_file=dest/'routing_table.json';table_file.write_text(json.dumps(st.routing_table,sort_keys=True,separators=(',',':')),encoding='utf-8')
  save(dest/'ready.json',{'utc':datetime.now(timezone.utc).isoformat(),'preparation_seconds':time.time()-preparing,'size':size,'scene_objects':len(d.targets),'native_elements':len(d.contract['instance']['objects']),'routing_pairs':sum(len(v) for v in st.routing_table.values()),'retained_project_reused':bool(old),'source_pins':pins,'config':vars(config),'query':{'active_agent':agent,'target':target},'backend_disk_table_loading':'not implemented; production verified_table caches in memory. JSON persist/read are explicitly artifact-I/O measurements, not request-path timings.'})
  def admission(mode):
   s.guard_config=replace(config,routing_mode=mode);r=runtime_admission(d,request);assert r['decision']=='ANSWER_LOCAL';return r
  def baseline():
   s.guard_config=config
   with patch.object(s,'_validate_spatial_context',lambda *a,**k:copy.deepcopy(grounding)),patch.object(s,'_resolve_spatial_route',lambda *a,**k:copy.deepcopy(route)),patch.object(s,'_preflight_v2_interaction_action',lambda **k:copy.deepcopy(actions[k['action_kind']])):
    r=d.probe(request);assert r['decision']=='ANSWER_LOCAL';return r
  def persist():
   raw=json.dumps(st.routing_table,sort_keys=True,separators=(',',':')).encode()
   with table_file.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  def load():
   r=json.loads(table_file.read_bytes());assert r==st.routing_table;return r
  def cold_memory():
   verified_routing._CACHE.clear();return verified_routing.verified_table(d.contract)
  def protocol():
   s.guard_config=replace(config,routing_mode='table')
   r=log_backend_events(project_manager=s.project_manager,project_id=d.project.name,entries=[{'action_kind':'chat','event_type':'a1_timing_commit','session_id':st.session_id,'agent_id':agent,'expected_action':actions['chat']['action']}],expected_contract_fingerprint=st.commit_fingerprint,publication_protocol=config.publication_protocol,expected_publication_generation=getattr(st,'publication_generation',None),commit_variant=config.commit_variant,pinned_contract=getattr(st,'pinned_contract',None));assert len(r)==1;return r
  funcs={'gate0_table_build':lambda:verify_routing(d.contract['instance'],d.contract['trace'],model_sha256=d.contract['model_sha256']),'table_persist_json':persist,'table_load_warm_os_cache':load,'verified_table_cold_memory_cache':cold_memory,'verified_table_warm_memory_cache':lambda:verified_routing.verified_table(d.contract),'gates_1_to_3_table':lambda:admission('table'),'gates_1_to_3_runtime':lambda:admission('runtime'),'no_guard_baseline':baseline,'gate4_commit_protocol':protocol}
  with (dest/'samples.jsonl').open('x',encoding='utf-8') as f:
   def measure(cell,i):
    if time.time()>=deadline:raise TimeoutError('A1 deadline')
    before=time.perf_counter_ns();error=None;v=None
    try:v=funcs[cell]()
    except Exception as exc:error=type(exc).__name__
    elapsed=time.perf_counter_ns()-before
    f.write(json.dumps({'size':size,'cell':cell,'ordinal':i,'discard':i<2,'elapsed_ns':elapsed,'error':error})+'\n');f.flush()
    if error:raise RuntimeError(cell+' execution failure '+error)
    return v
   # Paired modes first: same request/session, alternate order to expose order effects.
   for i in range(12):
    modes=['gates_1_to_3_runtime','gates_1_to_3_table'] if i%2==0 else ['gates_1_to_3_table','gates_1_to_3_runtime']
    a=measure(modes[0],i);b=measure(modes[1],i)
    assert tuple(a.get(k) for k in ['decision','reason','provider','action'])==tuple(b.get(k) for k in ['decision','reason','provider','action'])
   for cell in CELLS:
    if cell.startswith('gates_1_to_3'):continue
    for i in range(12):measure(cell,i)
  if size=='300':
   profiler=cProfile.Profile();profiler.enable();admission('runtime');profiler.disable();stats=pstats.Stats(profiler)
   rows=[]
   for (file,line,name),(primitive,total,selftime,cumtime,callers) in sorted(stats.stats.items(),key=lambda kv:kv[1][3],reverse=True)[:15]:
    p=Path(file)
    try:label=p.relative_to(ROOT).as_posix()
    except ValueError:label=p.name
    rows.append({'file':label,'line':line,'function':name,'primitive_calls':primitive,'total_calls':total,'self_seconds':selftime,'cumulative_seconds':cumtime})
   save(dest/'runtime_profile_top15.json',rows)
  assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in pins.items())
  save(dest/'complete.json',{'status':'DONE','utc':datetime.now(timezone.utc).isoformat(),'paired_verdicts_equal':True,'source_pins_unchanged':True})
 finally:d.close()

def main():
 RAW.mkdir(parents=True,exist_ok=True);started=time.time();deadline=started+65*60
 def ps(code):return subprocess.check_output(['powershell.exe','-NoProfile','-Command',code],text=True,errors='replace').strip()
 save(RAW/'hardware.json',{'utc_start':datetime.now(timezone.utc).isoformat(),'cpu':ps('(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress)'),'os':platform.platform(),'python':sys.version,'power_plan':subprocess.check_output(['powercfg','/getactivescheme'],text=True,errors='replace').strip(),'clock':vars(time.get_clock_info('perf_counter')),'other_applications_running':True,'workers':'one at a time, other scientific workers stopped','disk_cache':'OS cache uncontrolled; OS-cold disk-load cell NOT DONE, no cache eviction/system tuning performed','cold_memory':'verified_table cache cleared per measured call; OS file cache untouched','output_scope':'all median/IQR/min/max values in milliseconds, inclusive quartiles'})
 for size in ['classroom','100','300','1000']:
  if time.time()>=deadline:break
  launch=time.time();prep_limit=1200 if size=='1000' else min(1200,deadline-time.time())
  with (RAW/(size+'_worker.log')).open('x',encoding='utf-8') as log:
   proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',size,str(deadline)],stdout=log,stderr=log)
   while proc.poll() is None:
    reason='A1 measurement time budget' if time.time()>=deadline else '1000 preparation exceeded20minutes' if time.time()-launch>=prep_limit and not (RAW/size/'ready.json').exists() else None
    if reason:
     subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);proc.wait(timeout=20);save(RAW/(size+'_stop.json'),{'reason':reason});break
    time.sleep(1)
   if proc.returncode:save(RAW/(size+'_exit.json'),{'exit_code':proc.returncode})
 summarize(started)

def summarize(started):
 samples=[]
 for p in RAW.glob('*/samples.jsonl'):samples.extend(json.loads(s) for s in p.read_text().splitlines() if s)
 old=list(csv.DictReader((ROOT/'deliverables/delta_20261020/exports/cost_scale.csv').open(encoding='utf-8-sig')));rows=[];changes=[]
 for size in ['classroom','100','300','1000']:
  for cell in CELLS+['table_load_os_cold']:
   rr=[r for r in samples if r['size']==size and r['cell']==cell];v=[r['elapsed_ns']/1e6 for r in rr if not r['discard'] and r['error'] is None];done=len(v)>=10;q=statistics.quantiles(v,n=4,method='inclusive') if done else [None]*3
   r={'size':size,'cell':cell,'status':'DONE' if done else 'NOT DONE','warmups_discarded':sum(x['discard'] for x in rr),'repetitions':len(v),'median_ms':statistics.median(v) if done else None,'q1_ms':q[0],'q3_ms':q[2],'iqr_ms':q[2]-q[0] if done else None,'min_ms':min(v) if done else None,'max_ms':max(v) if done else None,'failures':sum(x['error'] is not None for x in rr),'qualification':'OS-cold cache not controlled; not substituted with a warm-cache result' if cell=='table_load_os_cold' else 'artifact JSON I/O, not implemented in backend request path' if cell.startswith('table_') else ''}
   previous=next((x for x in old if x['size']==size and x['cell']==('gates_1_to_3' if cell=='gates_1_to_3_runtime' else cell)),{})
   rows.append(r)
   for key,new in r.items():
    if key in ['warmups_discarded','repetitions','median_ms','q1_ms','q3_ms','iqr_ms','min_ms','max_ms','failures']:
     ov=previous.get(key);ov=float(ov) if ov not in (None,'') else None
     z={'key':f'{size}/{cell}/{key}','old':ov,'new':new,'flag':'CHANGED' if ov is not None and ov!=new else 'UNCHANGED' if ov is not None else 'NEW_OR_UNMEASURED','script':'drafts/delta2_20261020/a1_timing.py'};changes.append(z);print(json.dumps(z),flush=True)
 target=OUT/'tables/A1_table_lookup_timing.csv';target.parent.mkdir(parents=True,exist_ok=True)
 with target.open('x',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 for name,value in [('a1_samples.json',samples),('changes_a1.json',changes),('a1_hardware.json',json.loads((RAW/'hardware.json').read_text())),('a1_preparation.json',{p.parent.name:json.loads(p.read_text()) for p in RAW.glob('*/ready.json')})]:save(OUT/'review'/name,value)
 profile=RAW/'300/runtime_profile_top15.json'
 if profile.exists():
  data=json.loads(profile.read_text());save(OUT/'review/a1_runtime_profile_top15.json',data)
  with (OUT/'tables/A1_runtime_profile_top15.csv').open('x',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 numbers={'elapsed_seconds':time.time()-started,'cells_done':sum(r['status']=='DONE' for r in rows),'cells_total':len(rows),'api_spend_usd':0,'rows':rows,'production_persistent_table_loading':False,'os_cold_load_measured':False,'profile_300_available':profile.exists()}
 save(OUT/'numbers_a1.json',numbers);save(RAW/'terminal.json',{'status':'TERMINAL','utc':datetime.now(timezone.utc).isoformat(),**{k:v for k,v in numbers.items() if k!='rows'}})
 (OUT/'item_notes_a1.md').write_text('A1 measured production table and runtime admission with digest_check=true on the same request/session, alternating paired order, two discarded warmups then ten repetitions. No optimization. Gate4 uses the unchanged packet/full protocol. JSON persist/read measures artifact serialization only: the backend actually caches verified tables in memory and has no disk-table load path. Cold memory means clearing that cache; OS-cold disk loading is NOT DONE because OS cache was not evicted. Other desktop applications and OS services remained running. Completed sizes, min/max/median/IQR and all unfinished cells appear in A1_table_lookup_timing.csv. A retained complete1000-object project is reused from Delta1 preparation; its original timing cells remain untouched.\n',encoding='utf-8')
if __name__=='__main__':
 if '--worker' in sys.argv:
  try:worker(sys.argv[2],float(sys.argv[3]))
  except BaseException as exc:
   save(RAW/(sys.argv[2]+'_error.json'),{'exception':type(exc).__name__,'message':'Worker failed; no outcome invented'});raise SystemExit(1)
 else:main()
