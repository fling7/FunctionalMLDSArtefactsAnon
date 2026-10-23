"""DRAFT fresh-batch dispatch adapter; preserves the original WP6 main."""
from pathlib import Path
from contextlib import contextmanager
import argparse,hashlib,json,platform,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pinned(path,expected):
 if sha(path)!=expected:raise ValueError('Pinned file changed: '+str(path))
 return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def verify_lock(path):
 value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
 if value.get('status')!='frozen':raise ValueError('Execution amendment is not frozen: '+str(path))
 for name,expected in value['code_hashes'].items():
  if sha(ROOT/name)!=expected:raise ValueError('Frozen code changed: '+name)
 return value

def verify_execution_pins(lock_path,expected_lock_sha256):
 pinned(lock_path,expected_lock_sha256);lock=verify_lock(lock_path)
 for path,expected in lock['dependency_locks'].items():pinned(ROOT/path,expected);verify_lock(ROOT/path)
 for key in ['source_inventory','ordered_queue']:pinned(ROOT/lock[key]['path'],lock[key]['sha256'])
 return lock

def audit_sources(rows):
 from experiments.prepare_wp6_corpus_scope import audit_project_pins
 result=[]
 for row in rows:
  project=ROOT/row['project_path'];run=pinned(ROOT/row['run_result_path'],row['run_result_sha256'])
  if row.get('source_path') and sha(ROOT/row['source_path'])!=row['source_sha256']:raise ValueError('Source hash changed: '+row['case_id'])
  audit=audit_project_pins(project,run)
  if not audit['ok']:raise ValueError('Registered project input mismatch: '+row['case_id'])
  native=(project/'roomcontract.v2.instance.json').read_bytes()
  if hashlib.sha256(native.replace(b'\r\n',b'\n')).hexdigest().upper()!=row['model_sha256'].upper():raise ValueError('Model digest changed: '+row['case_id'])
  if json.loads(native.decode('utf-8-sig')).get('caseId')!=row['case_id']:raise ValueError('Native case identity differs: '+row['case_id'])
  result.append({'case_id':row['case_id'],'project_path':Path(row['project_path']).as_posix(),'source_room_id':row['source_room_id'],'registered_input_audit':audit})
 return result

@contextmanager
def scoped_executor_dispatch(matrix,worker,before_enter):
 original=matrix.ProcessPoolExecutor;frozen_evaluator=matrix.evaluate_one
 class Dispatch:
  def __init__(self,*args,**kwargs):self.args=args;self.kwargs=kwargs;self.executor=None
  def __enter__(self):
   before_enter();self.executor=original(*self.args,**self.kwargs);self.executor.__enter__();return self
  def submit(self,function,*args,**kwargs):
   if function is not frozen_evaluator:raise ValueError('Unexpected submitted callable')
   return self.executor.submit(worker,*args,**kwargs)
  def __exit__(self,*exc):return self.executor.__exit__(*exc)
 matrix.ProcessPoolExecutor=Dispatch
 try:yield
 finally:matrix.ProcessPoolExecutor=original

def run_fresh(rows,run_dir,workers,protocol,verify_execution):
 from experiments import detection_matrix as matrix
 from experiments.detection_matrix_compiled_accelerated import compiled_accelerated_worker
 run_dir=Path(run_dir)
 if run_dir.exists():raise FileExistsError(run_dir)
 execution_before=verify_execution()
 first=audit_sources(rows)
 matrix.write_new(run_dir.with_name(run_dir.name+'_fresh_protocol.json'),dict(protocol,workers=workers,source_audits_before_preparation=first,python=sys.version,platform=platform.platform(),execution='Unchanged frozen main; only exact evaluate_one submissions route to the reviewed combined worker.'))
 def before_enter():
  execution_after=verify_execution()
  if execution_after!=execution_before:raise ValueError('Execution pins changed during preparation')
  second=audit_sources(rows)
  if second!=first:raise ValueError('Source inputs changed during preparation')
  matrix.write_new(run_dir.with_name(run_dir.name+'_dispatch_check.json'),{'source_audits_after_preparation':second,'execution_pins_reverified':True,'unchanged':True,'workers':workers})
 argv=sys.argv
 try:
  sys.argv=['detection_matrix.py','--run-dir',str(run_dir),'--workers',str(workers)]
  for row in rows:sys.argv+=['--project',str(ROOT/row['project_path'])]
  with scoped_executor_dispatch(matrix,compiled_accelerated_worker,before_enter):return matrix.main()
 finally:sys.argv=argv

def select_batch(queue,inventory,ordinal):
 batches=[row for row in queue['batches'] if row['batch_ordinal']==ordinal]
 if len(batches)!=1:raise ValueError('Unknown/duplicate batch ordinal')
 ids=[row['case_id'] for row in batches[0]['projects']]
 if len(set(ids))!=len(ids):raise ValueError('Duplicate batch case identity')
 lookup={}
 for row in inventory['rows']:
  if row['case_id'] in lookup:raise ValueError('Duplicate inventory case identity')
  lookup[row['case_id']]=row
 rows=[]
 for case in ids:
  if case not in lookup:raise ValueError('Batch case missing from complete inventory')
  row=lookup[case]
  if row['wp6_intake_status']!='native_artifacts_available':raise ValueError('Registered intake refusal remains explicit: '+case)
  rows.append(row)
 paths=[str((ROOT/row['project_path']).resolve()) for row in rows]
 if len(set(paths))!=len(paths):raise ValueError('Project path aliases in batch')
 ordered=sorted(rows,key=lambda row:(row['source_priority'],row['run_ordinal'],row['case_id']))
 if rows!=ordered:raise ValueError('Batch order differs from frozen inventory order')
 return rows

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch-ordinal',type=int,required=True);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--workers',type=int,choices=[4,8],required=True);a=p.parse_args()
 lock_path=ROOT/'prereg/wp6_amendments/010_fresh_batch_dispatch.sha256.json';lock_sha256=sha(lock_path)
 def verify_execution():return verify_execution_pins(lock_path,lock_sha256)
 lock=verify_execution()
 inventory=pinned(ROOT/lock['source_inventory']['path'],lock['source_inventory']['sha256']);queue=pinned(ROOT/lock['ordered_queue']['path'],lock['ordered_queue']['sha256'])
 if queue['source_inventory_sha256']!=lock['source_inventory']['sha256']:raise ValueError('Queue/inventory pin differs')
 rows=select_batch(queue,inventory,a.batch_ordinal)
 return run_fresh(rows,a.run_dir,a.workers,{'amendment':lock,'batch_ordinal':a.batch_ordinal,'ordered_case_ids':[row['case_id'] for row in rows],'source_inventory':lock['source_inventory'],'ordered_queue':lock['ordered_queue'],'execution_lock_sha256':lock_sha256},verify_execution)
if __name__=='__main__':raise SystemExit(main())
