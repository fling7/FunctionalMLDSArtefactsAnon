"""Fresh-batch engineering tests; recording executors never run evaluations."""
import copy,hashlib,json,sys
from pathlib import Path
from concurrent.futures import Future
import pytest
from experiments import run_mutation_compiled_batch as adapter
from experiments import detection_matrix as matrix
from experiments.lib.model_builder import build_room
from experiments.detection_matrix_compiled_accelerated import compiled_accelerated_worker

class RecordingExecutor:
 records=[]
 def __init__(self,*args,**kwargs):self.kwargs=kwargs
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def submit(self,function,job):
  self.records.append((function,copy.deepcopy(job)));future=Future();future.set_result({'engineering_only':job['metadata']['id']});return future

@pytest.fixture(scope='module')
def authored(tmp_path_factory):
 base=tmp_path_factory.mktemp('fresh-authored');project=build_room({'case_id':'fresh_engineering','agents':['a','b'],'objects':['one','two'],'owners':{'asset':{'one':['a'],'two':['b']}},'handoffs':[['a','b'],['b','a']]},base).project_dir
 result=base/'run_result.json';artifacts={str(path.resolve()):adapter.sha(path) for path in project.rglob('*') if path.is_file()};result.write_text(json.dumps({'artifact_sha256':artifacts}))
 native=(project/'roomcontract.v2.instance.json').read_bytes()
 row={'case_id':'fresh_engineering','source_room_id':'source_fresh','project_path':str(project.resolve()),'run_result_path':str(result.resolve()),'run_result_sha256':adapter.sha(result),'model_sha256':hashlib.sha256(native.replace(b'\r\n',b'\n')).hexdigest().upper(),'source_priority':1,'run_ordinal':1,'wp6_intake_status':'native_artifacts_available'}
 return row

def test_original_and_wrapped_all_planning_and_materialization_match(authored,tmp_path,monkeypatch):
 monkeypatch.setattr(matrix,'ProcessPoolExecutor',RecordingExecutor);monkeypatch.setattr(matrix,'aggregate',lambda _: {'models_evaluated':len(RecordingExecutor.records),'evaluation_complete':True,'worker_failures':0})
 original_argv=sys.argv;original_eval=matrix.evaluate_one;original_executor=matrix.ProcessPoolExecutor
 old=tmp_path/'original';new=tmp_path/'wrapped';RecordingExecutor.records=[]
 monkeypatch.setattr(sys,'argv',['original','--project',authored['project_path'],'--run-dir',str(old),'--workers','4']);matrix.main();old_jobs=RecordingExecutor.records[:]
 RecordingExecutor.records=[];adapter.run_fresh([authored],new,4,{'engineering_only':True},lambda:None);new_jobs=RecordingExecutor.records[:]
 assert json.loads((old/'mutation_manifest.json').read_text())==json.loads((new/'mutation_manifest.json').read_text())
 assert len(old_jobs)==len(new_jobs)>17
 for (old_fn,a),(new_fn,b) in zip(old_jobs,new_jobs):
  assert old_fn is original_eval and new_fn is compiled_accelerated_worker
  assert a['metadata']==b['metadata'] and Path(a['output']).name==Path(b['output']).name
  af={p.relative_to(a['project']).as_posix():p.read_bytes() for p in Path(a['project']).rglob('*') if p.is_file()};bf={p.relative_to(b['project']).as_posix():p.read_bytes() for p in Path(b['project']).rglob('*') if p.is_file()};assert af==bf
 assert matrix.evaluate_one is original_eval and matrix.ProcessPoolExecutor is original_executor
 assert json.loads(new.with_name('wrapped_dispatch_check.json').read_text())['unchanged']
 with pytest.raises(FileExistsError):adapter.run_fresh([authored],new,4,{},lambda:None)

@pytest.mark.parametrize('fault',['trace','project','run_result','digest','case'])
def test_source_pin_refusals(authored,tmp_path,fault):
 row=copy.deepcopy(authored)
 if fault in {'digest','case'}:row['model_sha256' if fault=='digest' else 'case_id']='bad'
 elif fault=='run_result':row['run_result_sha256']='0'*64
 else:
  # Independent copied fixture with registered stale pins, never alter shared fixture.
  import shutil
  source=Path(row['project_path']);target=tmp_path/'project';shutil.copytree(source,target);row['project_path']=str(target)
  original=json.loads(Path(row['run_result_path']).read_text());original['artifact_sha256']={str(target/Path(k).relative_to(source)):v for k,v in original['artifact_sha256'].items()};rp=tmp_path/'run.json';rp.write_text(json.dumps(original));row['run_result_path']=str(rp);row['run_result_sha256']=adapter.sha(rp)
  with (target/('trace_map.v2.json' if fault=='trace' else 'project.json')).open('ab') as f:f.write(b' ')
 with pytest.raises(ValueError):adapter.audit_sources([row])

@pytest.mark.parametrize('where',['entry','submit','body'])
def test_scoped_binding_restores_on_error(monkeypatch,where):
 monkeypatch.setattr(matrix,'ProcessPoolExecutor',RecordingExecutor);old=matrix.ProcessPoolExecutor;old_eval=matrix.evaluate_one
 def before():
  if where=='entry':raise RuntimeError('entry')
 with pytest.raises((RuntimeError,ValueError)):
  with adapter.scoped_executor_dispatch(matrix,compiled_accelerated_worker,before):
   with matrix.ProcessPoolExecutor(max_workers=4) as executor:
    if where=='submit':executor.submit(lambda _:None,{})
    else:raise RuntimeError('body')
 assert matrix.ProcessPoolExecutor is old and matrix.evaluate_one is old_eval

def test_pin_change_during_preparation_blocks_dispatch(authored,tmp_path,monkeypatch):
 old=matrix.ProcessPoolExecutor;called=[];original_argv=sys.argv;count=0
 def audit(_):
  nonlocal count
  count+=1;return [{'pin':count}]
 def original_main():
  with matrix.ProcessPoolExecutor(max_workers=4):called.append(1)
 monkeypatch.setattr(adapter,'audit_sources',audit);monkeypatch.setattr(matrix,'main',original_main)
 with pytest.raises(ValueError,match='changed during preparation'):adapter.run_fresh([authored],tmp_path/'blocked',4,{},lambda:None)
 assert called==[] and matrix.ProcessPoolExecutor is old and sys.argv is original_argv

@pytest.mark.parametrize('fault',['missing','duplicate','order','alias','refused'])
def test_batch_identity_and_order_refusals(authored,fault):
 a=copy.deepcopy(authored);b=dict(a,case_id='second',source_priority=2,project_path=a['project_path']+'_second');inventory={'rows':[a,b]};queue={'batches':[{'batch_ordinal':2,'projects':[{'case_id':a['case_id']},{'case_id':b['case_id']}]}]}
 if fault=='missing':queue['batches'][0]['projects'][0]['case_id']='absent'
 if fault=='duplicate':queue['batches'][0]['projects'][1]['case_id']=a['case_id']
 if fault=='order':queue['batches'][0]['projects'].reverse()
 if fault=='alias':b['project_path']=a['project_path']
 if fault=='refused':a['wp6_intake_status']='artifact_or_preparation_refused'
 with pytest.raises(ValueError):adapter.select_batch(queue,inventory,2)

@pytest.mark.parametrize('fault',['draft','changed'])
def test_lock_refusal(tmp_path,monkeypatch,fault):
 monkeypatch.setattr(adapter,'ROOT',tmp_path);source=tmp_path/'source.py';source.write_text('x');lock=tmp_path/'lock.json';lock.write_text(json.dumps({'status':'draft' if fault=='draft' else 'frozen','code_hashes':{'source.py':'0'*64}}))
 with pytest.raises(ValueError):adapter.verify_lock(lock)

@pytest.mark.parametrize('changed',['lock010.json','code010.py','lock008.json','code008.py','lock009.json','code009.py','inventory.json','queue.json'])
def test_execution_pin_tampering_during_preparation_blocks_dispatch(authored,tmp_path,monkeypatch,changed):
 monkeypatch.setattr(adapter,'ROOT',tmp_path)
 for name in ['code010.py','code008.py','code009.py']:(tmp_path/name).write_text('original')
 for name in ['inventory.json','queue.json']:(tmp_path/name).write_text('{}')
 for n in ['008','009']:
  (tmp_path/f'lock{n}.json').write_text(json.dumps({'status':'frozen','code_hashes':{f'code{n}.py':adapter.sha(tmp_path/f'code{n}.py')}}))
 lock=tmp_path/'lock010.json';lock.write_text(json.dumps({'status':'frozen','code_hashes':{'code010.py':adapter.sha(tmp_path/'code010.py')},'dependency_locks':{f'lock{n}.json':adapter.sha(tmp_path/f'lock{n}.json') for n in ['008','009']},'source_inventory':{'path':'inventory.json','sha256':adapter.sha(tmp_path/'inventory.json')},'ordered_queue':{'path':'queue.json','sha256':adapter.sha(tmp_path/'queue.json')}}))
 initial_sha=adapter.sha(lock);old=matrix.ProcessPoolExecutor;original_argv=sys.argv;entered=[]
 def verify():return adapter.verify_execution_pins(lock,initial_sha)
 def original_main():
  with (tmp_path/changed).open('ab') as f:f.write(b' ')
  with matrix.ProcessPoolExecutor(max_workers=4):entered.append(True)
 monkeypatch.setattr(adapter,'audit_sources',lambda _:[]);monkeypatch.setattr(matrix,'main',original_main)
 with pytest.raises(ValueError,match='changed'):adapter.run_fresh([authored],tmp_path/'blocked',4,{},verify)
 assert entered==[] and matrix.ProcessPoolExecutor is old and sys.argv is original_argv
 assert not (tmp_path/'blocked_dispatch_check.json').exists()
