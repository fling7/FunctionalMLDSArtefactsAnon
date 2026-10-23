"""Append-only recovery of the two exact user-stopped WP6 campaigns.

Reuses frozen prepared input bytes, not a new mutation sample. Every completed
observation is copied once; only absent outcomes use the unchanged compiled worker.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SNAPSHOT='results/raw/wp6_user_wrap_shutdown_v1/final_snapshot.json'
SNAPSHOT_SHA='ece0fd997ae18cef6619505e199f5fc95abcd2ec64e61a3a25a4fbba19c22129'
FILES='results/raw/wp6_user_wrap_shutdown_v1/retained_file_manifest.json'
FILES_SHA='2223662e92708288c49c74afa3d6018abd9bfc4b9c0cceebd74f0346cb8faef4'
RUNS=('results/raw/wp6_generated_combined_recovery_v1','results/raw/wp6_original_batch02_combined_v1')
sha=lambda data:hashlib.sha256(data).hexdigest()
def utc():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_bytes())
def write(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
def safe(root,name):
 p=Path(name)
 if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe relative path')
 if any(x.lower()=='config.json' or x.lower().startswith('\x2eenv') or x.lower()=='excluded_client' or x.lower().startswith('fragebogen') for x in p.parts):raise ValueError('Excluded path')
 q=Path(root)/p
 for part in (q,*q.parents):
  if part==Path(root):break
  if part.is_symlink() or (part.exists() and getattr(part.lstat(),'st_file_attributes',0)&0x400):raise ValueError('Linked path')
 if not q.resolve().is_relative_to(Path(root).resolve()):raise ValueError('Path escape')
 return q

def verify_execution():
 from experiments.wp6_hybrid.compatibility import verify_execution_pins_compat,TRANSITION,LOCK10,SHA10
 from experiments.recover_mutation_run import verify_lock
 verify_execution_pins_compat(ROOT/LOCK10,SHA10,transition=TRANSITION)
 base=verify_lock(ROOT/'prereg/WP6_PLAN.sha256.json')
 verify_lock(ROOT/'prereg/wp6_amendments/002_infrastructure_recovery.sha256.json')
 return base,TRANSITION

def plan_jobs(manifest,completed,new_run):
 models=manifest['models'];seen=set();planned=[]
 for row in models:
  sid=row['storage_id']
  if sid in seen:raise ValueError('Duplicate storage identity')
  seen.add(sid)
  if row['status'] in {'changed','incomplete'}:planned.append(row)
 eligible={r['storage_id'] for r in planned}
 if not set(completed)<=eligible:raise ValueError('Completed outcome outside registered matrix')
 jobs=[]
 for row in planned:
  if row['storage_id'] in completed:continue
  jobs.append({'metadata':row,'project':str(new_run/'models'/row['storage_id']/row['room']),
               'output':str(new_run/'outcomes'/(row['storage_id']+'.json'))})
 return planned,jobs

def copy_registered(root,rows,source,destination):
 source=Path(source);destination=Path(destination)
 expected={r['path']:r for r in rows};prefix=source.as_posix()+'/'
 if len(expected)!=len(rows) or any(not n.startswith(prefix) for n in expected):raise ValueError('Duplicate or foreign retained path')
 actual={p.relative_to(root).as_posix() for p in safe(root,source).rglob('*') if p.is_file()}
 if actual!=set(expected):raise ValueError('Retained source file set changed')
 destination.mkdir(parents=True,exist_ok=False)
 copied=[]
 for row in rows:
  p=safe(root,row['path']);data=p.read_bytes()
  if len(data)!=row['bytes'] or sha(data)!=row['sha256']:raise ValueError('Retained bytes changed: '+row['path'])
  rel=Path(row['path']).relative_to(source)
  # Prior recovery provenance is retained as prior provenance, never overwritten.
  if rel.as_posix()=='recovery_manifest.json':rel=Path('prior_recovery_manifest.json')
  target=safe(destination,rel);target.parent.mkdir(parents=True,exist_ok=True)
  with target.open('xb') as f:f.write(data)
  if target.stat().st_size!=len(data):raise ValueError('Short retained copy')
  copied.append({'source':row['path'],'copy':target.relative_to(root).as_posix(),'sha256':row['sha256'],'bytes':row['bytes']})
 return copied

def prepare(output,workers):
 if output.exists():raise FileExistsError(output)
 snapshot_bytes=(ROOT/SNAPSHOT).read_bytes();files_bytes=(ROOT/FILES).read_bytes()
 if sha(snapshot_bytes)!=SNAPSHOT_SHA or sha(files_bytes)!=FILES_SHA:raise ValueError('Stopped provenance changed')
 snapshot=json.loads(snapshot_bytes);filedata=json.loads(files_bytes)
 if tuple(r['run'] for r in snapshot['runs'])!=RUNS or snapshot['retained_file_manifest_sha256']!=FILES_SHA:raise ValueError('Stopped scope changed')
 if any(r['partial_or_invalid_outcomes'] or r['worker_failure_files'] or r['unknown_outcome_paths'] for r in snapshot['runs']):raise ValueError('Explicit adjudication required')
 base,transition=verify_execution()
 output.mkdir(parents=True)
 write(output/'plan.json',{'schema':'wp6-exact-stopped-recovery-v1','utc':utc(),'source_sha256':sha(Path(__file__).read_bytes()),
  'snapshot':{'path':SNAPSHOT,'sha256':SNAPSHOT_SHA},'retained_files':{'path':FILES,'sha256':FILES_SHA},'workers':workers,
  'expected_existing_outcomes':303,'expected_missing_outcomes':605,'report_only_transition':transition,
  'worker':'experiments.detection_matrix_compiled_accelerated.compiled_accelerated_worker',
  'semantics':'Original complete matrix, checkers, independent APIs and backend execution unchanged. New dispatch uses adopted exact report-only dependency transition. Old raw stays untouched; copied observations count once. No persistent/hybrid solver switch.',
  'scope_limits':'This resumes only two interrupted original campaigns; later original batches, all other native variants and natural-diff scope remain mandatory.'})
 from experiments.recover_mutation_run import verify_completed
 from experiments.mutations import Bundle
 all_jobs=[];runs=[]
 for stop in snapshot['runs']:
  source=stop['run'];dest=output/Path(source).name
  rows=[r for r in filedata['files'] if r['path'].startswith(source+'/')]
  copied=copy_registered(ROOT,rows,source,dest)
  manifest=read(dest/'mutation_manifest.json')
  if sha((dest/'mutation_manifest.json').read_bytes())!=stop['mutation_manifest_sha256'] or manifest['freeze']!=base:raise ValueError('Original mutation manifest changed')
  complete={r['storage_id']:r for r in stop['observations']}
  planned,jobs=plan_jobs(manifest,complete,dest)
  actual={p.stem for p in (dest/'outcomes').glob('*.json')}
  if actual!=set(complete) or len(jobs)!=stop['unfinished_without_outcome']:raise ValueError('Completion partition changed')
  by_id={r['storage_id']:r for r in planned}
  for sid,record in complete.items():
   outcome=dest/'outcomes'/(sid+'.json')
   if sha(outcome.read_bytes())!=record['sha256']:raise ValueError('Copied outcome pin changed')
   meta=by_id[sid];bundle=Bundle.load(dest/'models'/sid/meta['room'])
   verify_completed(outcome,meta,bundle,{'identical':True})
  write(dest/'recovery_manifest.json',{'schema':'wp6-stopped-exact-input-recovery-v1','source_run':source,
   'original_manifest_sha256':stop['mutation_manifest_sha256'],'missing_evaluations':len(jobs),
   'reused_completed_outcomes':[{'id':by_id[sid]['id'],'original':r['path'],'copy':str(dest/'outcomes'/(sid+'.json')),'sha256':r['sha256']} for sid,r in complete.items()],
   'model_provenance':'Exact stopped prepared bytes from hashed quiescent inventory; no regeneration or replacement.',
   'copied_files':copied,'interpretation':'Copied observations are the same observations, never additional data.'})
  runs.append({'path':dest.relative_to(ROOT).as_posix(),'copied':len(complete),'pending':len(jobs),'registered':len(planned)})
  all_jobs.extend(jobs)
  print(json.dumps({'event':'prepared_run','run':runs[-1]}),flush=True)
 if sum(r['copied'] for r in runs)!=303 or len(all_jobs)!=605:raise ValueError('Stopped exact totals changed')
 verify_execution()
 write(output/'prepared.json',{'utc':utc(),'runs':runs,'jobs':all_jobs,'workers':workers,'source_sha256':sha(Path(__file__).read_bytes())})
 return all_jobs,runs

def resume_worker(job):
 # Fresh lifecycle belongs to this attempt, outside the unchanged evaluator output.
 from experiments.detection_matrix_compiled_accelerated import compiled_accelerated_worker
 path=Path(job['output']);life=path.parent.parent/'resume_lifecycle'/path.stem
 begin=time.perf_counter();cpu=time.process_time()
 write(life/'started.json',{'utc':utc(),'pid':os.getpid(),'id':job['metadata']['id']})
 try:
  result=compiled_accelerated_worker(job)
  write(life/'finished.json',{'utc':utc(),'pid':os.getpid(),'elapsed_seconds':time.perf_counter()-begin,
   'process_cpu_seconds':time.process_time()-cpu,'outcome_sha256':sha(path.read_bytes()),'result':result})
  return result
 except BaseException as exc:
  write(life/'failed.json',{'utc':utc(),'type':type(exc).__name__,'message':str(exc),'elapsed_seconds':time.perf_counter()-begin})
  raise

def dispatch(jobs,runs,output,workers):
 verify_execution();started=time.perf_counter();remaining=iter(jobs);returned=0;failure=False
 write(output/'dispatch.json',{'utc':utc(),'workers':workers,'pending':len(jobs),'pid':os.getpid(),'source_sha256':sha(Path(__file__).read_bytes())})
 with ProcessPoolExecutor(max_workers=workers) as pool:
  futures={}
  def next_job():
   job=next(remaining,None)
   if job is not None:futures[pool.submit(resume_worker,job)]=job
  for _ in range(workers):next_job()
  while futures:
   done,_=wait(futures,return_when=FIRST_COMPLETED)
   for f in done:
    job=futures.pop(f)
    try:result=f.result()
    except Exception as exc:
     failure=True;write(output/'worker_failures'/Path(job['output']).name,{'metadata':job['metadata'],'type':type(exc).__name__,'message':str(exc)})
     print(json.dumps({'event':'worker_failure','id':job['metadata']['id'],'error':str(exc)}),flush=True)
    else:
     returned+=1;print(json.dumps({'event':'parent_return','returned_new':returned,'pending_total':len(jobs),'elapsed_seconds':time.perf_counter()-started,'result':result}),flush=True)
    if not failure:next_job()
 if failure:
  write(output/'terminal.json',{'status':'WORKER_FAILURE_STOPPED_NEW_SUBMISSIONS','utc':utc(),'returned_new':returned,'pending':len(jobs),'elapsed_seconds':time.perf_counter()-started});return 1
 from experiments.detection_matrix import aggregate
 summaries={r['path']:aggregate(ROOT/r['path']) for r in runs}
 ok=all(s['evaluation_complete'] and not s['worker_failures'] for s in summaries.values())
 write(output/'terminal.json',{'status':'COMPLETE_TWO_RECOVERED_CAMPAIGNS' if ok else 'INCOMPLETE','utc':utc(),'returned_new':returned,'copied_once':303,'elapsed_seconds':time.perf_counter()-started,'run_status':{p:{k:s[k] for k in ['evaluation_complete','models_evaluated','worker_failures']} for p,s in summaries.items()}})
 return 0 if ok else 1

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--workers',type=int,choices=range(1,5),default=4);p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
 output=safe(ROOT,a.output)
 if not output.is_relative_to(ROOT/'results/raw'):raise ValueError('Output must be under results/raw')
 jobs,runs=prepare(output,a.workers)
 return 0 if a.prepare_only else dispatch(jobs,runs,output,a.workers)
if __name__=='__main__':raise SystemExit(main())
