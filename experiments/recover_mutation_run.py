"""Append-only WP6 infrastructure recovery using the frozen evaluator.

Creates a fresh run directory. Original attempts remain byte-for-byte untouched.
Completed outcomes are copied only after metadata, model files and pair coverage
match deterministic regeneration. Missing evaluations use the original worker.
"""
from __future__ import annotations
import argparse, hashlib, itertools, json, platform, shutil, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments import detection_matrix as frozen
from experiments.mutations import Bundle, SEED, digest, mutation_plan, refresh_projections

# These broad-inventory files are not imported by this runner, frozen evaluator,
# mutation generation, static memoization, backend driver or their dependencies.
NON_EVALUATION_FILES = {
 'experiments/analyze_wp4.py', 'experiments/guarded_llm_turns.py',
 'experiments/lib/wp4_common.py', 'experiments/preregister_wp4.py',
 'experiments/report_mutation_analysis.py', 'experiments/routing_baselines.py',
 'experiments/wp4_token_preflight.py',
}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def inventory(directory):
 directory=Path(directory)
 return {p.relative_to(directory).as_posix():sha(p) for p in sorted(directory.rglob('*')) if p.is_file()}

def compare_files(original, regenerated):
 old=inventory(original) if Path(original).exists() else {}
 new=inventory(regenerated)
 return {'original_files':old,'regenerated_files':new,
         'missing':sorted(new.keys()-old.keys()),'extra':sorted(old.keys()-new.keys()),
         'different':sorted(k for k in old.keys() & new.keys() if old[k]!=new[k]),
         'identical':old==new}

def check_dependencies(paths):
 records=[]
 for path in paths:
  data=json.loads(Path(path).read_text(encoding='utf8'))
  mapping=data.get('sha256',{})
  if not mapping: raise ValueError('Dependency inventory has no sha256 mapping: '+str(path))
  for name,expected in mapping.items():
   actual=sha(ROOT/name)
   changed=actual!=expected
   excluded=name in NON_EVALUATION_FILES
   records.append({'inventory':str(path),'path':name,'expected':expected,'actual':actual,
                   'changed':changed,'excluded_non_evaluation_file':excluded})
   if changed and not excluded: raise ValueError('Evaluation dependency changed: '+name)
 return records

def verify_sources(projects, inventories):
 expected=[]
 for path in inventories:
  expected.extend(json.loads(Path(path).read_text(encoding='utf8')).get('selected_projects',[]))
 if not expected:return []  # Classroom provenance is additionally pinned by the full original mutation manifest.
 by_path={str(Path(row['project_path'])):row for row in expected}
 if [str(Path(p)) for p in projects]!=list(by_path):raise ValueError('Recovery source selection differs from original inventory')
 result=[]
 for project in map(Path,projects):
  row=by_path[str(project)]
  payload=(project/'roomcontract.v2.instance.json').read_bytes().replace(b'\r\n',b'\n')
  actual=hashlib.sha256(payload).hexdigest().upper()
  if actual!=row['model_sha256']:raise ValueError('Recovery source native digest changed: '+str(project))
  result.append({'project':str(project),'model_sha256':actual,'source_priority':row['source_priority'],
                 'source_room_id':row['source_room_id'],'source_files':inventory(project)})
 return result

def verify_completed(path, metadata, bundle, comparison):
 if not comparison['identical']: raise ValueError('Completed model bytes do not match regeneration: '+metadata['id'])
 data=json.loads(Path(path).read_text(encoding='utf8'))
 if data.get('metadata')!=metadata: raise ValueError('Completed outcome metadata differs: '+metadata['id'])
 if data.get('model_sha256')!=digest(bundle.instance): raise ValueError('Completed outcome digest differs: '+metadata['id'])
 agents=[o['sourceAgentId'] for o in bundle.instance['objects'] if o.get('type')=='Agent']
 targets=[o['id'] for o in bundle.instance['objects'] if o.get('entityRole')=='sceneObject']
 expected=list(itertools.product(agents,targets))
 actual=[(p['start_agent'],p['target']) for p in data.get('probes',[])]
 if actual!=expected or data.get('probe_count')!=len(expected): raise ValueError('Completed outcome pair coverage differs: '+metadata['id'])
 for row in data['probes']:
  if set(row.get('variants',{}))!=set(frozen.VARIANTS): raise ValueError('Completed outcome variant coverage differs')
  if not all(k in row for k in ('I1','I2','Gate0','stale_request')): raise ValueError('Completed outcome checker coverage differs')
  if set(row['stale_request'])!={'I1','I2','runtime','no_digest'}: raise ValueError('Completed stale-request coverage differs')
 return data

def prepare_recovery(projects, source_run, run_dir, freeze):
 source_run=Path(source_run);run_dir=Path(run_dir)
 if not source_run.is_dir(): raise ValueError('Missing original run directory')
 if (source_run/'summary.json').exists(): raise ValueError('Source run has a final summary; not an interrupted run')
 if list((source_run/'worker_failures').glob('*.json')): raise ValueError('Prior worker failures require explicit adjudication before recovery')
 run_dir.mkdir(parents=True,exist_ok=False)
 (run_dir/'outcomes').mkdir()
 manifests=[];jobs=[];reused=[];audits=[]
 for source in map(Path,projects):
  bundle=Bundle.load(source)
  base_id=bundle.instance.get('caseId',source.name)
  for metadata,mutated in mutation_plan(bundle):
   metadata['room']=base_id
   metadata['id']=base_id+'__'+metadata['id']
   storage_id='m_'+hashlib.sha256(metadata['id'].encode()).hexdigest()[:16]
   metadata['storage_id']=storage_id
   manifests.append(metadata)
   if metadata['status'] not in {'changed','incomplete'}:continue
   try: mutated=refresh_projections(mutated)
   except Exception as exc:
    metadata['projection_error']={'exception':type(exc).__name__,'message':str(exc)}
    mutated.project['roomcontract_model_sha256']=digest(mutated.instance)
    mutated.trace['model_sha256']=digest(mutated.instance)
   project=run_dir/'models'/storage_id/source.name
   frozen.materialize(source,mutated,project)
   comparison=compare_files(source_run/'models'/storage_id/source.name,project)
   old_outcome=source_run/'outcomes'/(storage_id+'.json')
   output=run_dir/'outcomes'/(storage_id+'.json')
   if old_outcome.exists():
    verify_completed(old_outcome,metadata,mutated,comparison)
    with output.open('xb') as stream: stream.write(old_outcome.read_bytes())
    reused.append({'id':metadata['id'],'original':str(old_outcome),'copy':str(output),'sha256':sha(output)})
   else:
    jobs.append({'project':str(project),'output':str(output),'metadata':metadata})
   audits.append({'id':metadata['id'],'storage_id':storage_id,'completed_outcome_reused':old_outcome.exists(),**comparison})
 manifest={'seed':SEED,'models':manifests,'freeze':freeze}
 old_manifest=source_run/'mutation_manifest.json'
 if old_manifest.exists() and json.loads(old_manifest.read_text(encoding='utf8'))!=manifest:
  raise ValueError('Regenerated manifest differs from the original frozen manifest')
 known_outcomes={Path(row['original']).name for row in reused}
 if {p.name for p in (source_run/'outcomes').glob('*.json')}!=known_outcomes:
  raise ValueError('Original outcome has no corresponding regenerated plan entry')
 frozen.write_new(run_dir/'mutation_manifest.json',manifest)
 frozen.write_new(run_dir/'recovery_manifest.json',{'schema':'wp6-infrastructure-recovery-v1',
  'source_run':str(source_run),'original_manifest_sha256':sha(old_manifest) if old_manifest.exists() else None,
  'missing_evaluations':len(jobs),'reused_completed_outcomes':reused,'model_file_audits':audits,
  'interpretation':'Original attempt retained untouched; copied outcomes are the same observations, not additional evidence.'})
 return jobs

def verify_lock(path):
 data=json.loads(Path(path).read_text(encoding='utf8'))
 for name,expected in data['code_hashes'].items():
  if sha(ROOT/name)!=expected:raise ValueError('Frozen code hash mismatch: '+name)
 return data

def run_pending(jobs, run_dir, workers, accelerated):
 if accelerated:
  from experiments.detection_matrix_accelerated import accelerated_worker
  worker=accelerated_worker
 else: worker=frozen.evaluate_one
 with ProcessPoolExecutor(max_workers=workers) as executor:
  futures={executor.submit(worker,job):job for job in jobs}
  for future in as_completed(futures):
   job=futures[future]
   try: print(json.dumps(future.result()),flush=True)
   except Exception as exc:
    frozen.write_new(Path(run_dir)/'worker_failures'/Path(job['output']).name,
     {'metadata':job['metadata'],'exception':type(exc).__name__,'message':str(exc)})
    print(json.dumps({'id':job['metadata']['id'],'worker_failure':str(exc)}),flush=True)
 return frozen.aggregate(run_dir)

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--project',type=Path,action='append',required=True)
 parser.add_argument('--source-run',type=Path,required=True)
 parser.add_argument('--run-dir',type=Path,required=True)
 parser.add_argument('--dependency-inventory',type=Path,action='append',required=True)
 parser.add_argument('--workers',type=int,default=4)
 parser.add_argument('--accelerated',action='store_true')
 args=parser.parse_args()
 lock=verify_lock(ROOT/'prereg/wp6_amendments/002_infrastructure_recovery.sha256.json')
 if lock.get('status')!='frozen':raise ValueError('Recovery protocol is not frozen')
 base=verify_lock(ROOT/'prereg/WP6_PLAN.sha256.json')
 performance=verify_lock(ROOT/'prereg/wp6_amendments/001_performance_only.sha256.json') if args.accelerated else None
 dependencies=check_dependencies(args.dependency_inventory)
 sources=verify_sources(args.project,args.dependency_inventory)
 frozen.write_new(args.run_dir.with_name(args.run_dir.name+'_recovery_protocol.json'),
  {'recovery_lock':lock,'performance_lock':performance,'dependency_audit':dependencies,'python':sys.version,
   'platform':platform.platform(),'source_run':str(args.source_run),'projects':[str(p) for p in args.project],'source_provenance':sources})
 jobs=prepare_recovery(args.project,args.source_run,args.run_dir,base)
 print(json.dumps({'pending_models':len(jobs),'run_dir':str(args.run_dir)}),flush=True)
 summary=run_pending(jobs,args.run_dir,args.workers,args.accelerated)
 print(json.dumps({'evaluation_complete':summary['evaluation_complete'],'models_evaluated':summary['models_evaluated'],'worker_failures':summary['worker_failures']}),flush=True)
 return 0 if summary['evaluation_complete'] and not summary['worker_failures'] else 1
if __name__=='__main__':raise SystemExit(main())
