"""Engineering tests only: no WP6 evaluator or independent implementation calls."""
import hashlib,json
from pathlib import Path
import pytest
from experiments import resume_wp6_compiled as r

def meta(sid,status='changed'):
 return {'storage_id':sid,'status':status,'room':'room','id':'room__'+sid}
def test_partition_retains_plan_order_and_never_repeats_completed(tmp_path):
 rows=[meta('a'),meta('b','no_op'),meta('c','incomplete'),meta('d')]
 planned,jobs=r.plan_jobs({'models':rows},{'a':{}},tmp_path)
 assert [x['storage_id'] for x in planned]==['a','c','d']
 assert [x['metadata']['storage_id'] for x in jobs]==['c','d']
 assert jobs[0]['project']==str(tmp_path/'models/c/room')
@pytest.mark.parametrize('rows,complete', [([meta('a'),meta('a')],{}),([meta('a')],{'other':{}}),([meta('a','no_op')],{'a':{}})])
def test_invalid_completed_partition_refused(rows,complete,tmp_path):
 with pytest.raises(ValueError):r.plan_jobs({'models':rows},complete,tmp_path)

def fixture(root):
 src=root/'old';src.mkdir();(src/'recovery_manifest.json').write_bytes(b'prior');(src/'a').write_bytes(b'raw')
 return [{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(src.iterdir())]
def test_exact_copy_preserves_previous_provenance_and_source(tmp_path):
 rows=fixture(tmp_path);copy=r.copy_registered(tmp_path,rows,Path('old'),tmp_path/'new')
 assert len(copy)==2 and (tmp_path/'new/prior_recovery_manifest.json').read_bytes()==b'prior'
 assert (tmp_path/'old/recovery_manifest.json').read_bytes()==b'prior'
 assert (tmp_path/'new/a').read_bytes()==b'raw'
 with pytest.raises(FileExistsError):r.copy_registered(tmp_path,rows,Path('old'),tmp_path/'new')
@pytest.mark.parametrize('change',['bytes','missing','extra','foreign','duplicate'])
def test_changed_retained_scope_refused_without_source_mutation(tmp_path,change):
 rows=fixture(tmp_path)
 if change=='bytes':(tmp_path/'old/a').write_bytes(b'changed')
 elif change=='missing':(tmp_path/'old/a').unlink()
 elif change=='extra':(tmp_path/'old/extra').write_bytes(b'extra')
 elif change=='foreign':rows[0]['path']='other/a'
 else:rows.append(rows[0])
 before={p.name:p.read_bytes() for p in (tmp_path/'old').iterdir()}
 with pytest.raises(ValueError):r.copy_registered(tmp_path,rows,Path('old'),tmp_path/'new')
 assert {p.name:p.read_bytes() for p in (tmp_path/'old').iterdir()}==before
@pytest.mark.parametrize('path',['../escape','a/config.json','a/\x2eenv','a/excluded_client/file'])
def test_unsafe_paths_refused(tmp_path,path):
 with pytest.raises(ValueError):r.safe(tmp_path,path)
def test_failure_stops_new_submissions_preserves_attempt(tmp_path,monkeypatch):
 calls=[]
 class F:
  def __init__(self,job):self.job=job
  def result(self):raise RuntimeError('scripted engineering failure')
 class Pool:
  def __init__(self,max_workers):assert max_workers==2
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def submit(self,fn,job):calls.append(job);return F(job)
 monkeypatch.setattr(r,'verify_execution',lambda:None)
 monkeypatch.setattr(r,'ProcessPoolExecutor',Pool)
 monkeypatch.setattr(r,'wait',lambda futures,return_when:({next(iter(futures))},set()))
 jobs=[{'metadata':meta(str(i)),'output':str(tmp_path/'outcomes'/f'{i}.json')} for i in range(4)]
 assert r.dispatch(jobs,[],tmp_path,2)==1
 assert len(calls)==2 and len(list((tmp_path/'worker_failures').glob('*.json')))==2
 assert json.loads((tmp_path/'terminal.json').read_bytes())['status']=='WORKER_FAILURE_STOPPED_NEW_SUBMISSIONS'
