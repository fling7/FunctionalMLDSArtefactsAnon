"""Engineering tests for interruption recovery; never corpus observations."""
import copy,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments import recover_mutation_run as recovery
from experiments.mutations import Bundle,digest,encoded,mutation_plan
from experiments.lib.model_builder import build_room

@pytest.fixture(scope='module')
def room(tmp_path_factory):
 result=build_room({'case_id':'recovery_engineering','agents':['a','b'],'objects':['one','two'],
  'owners':{'asset':{'one':['a'],'two':['b']}},'handoffs':[['a','b'],['b','a']]},tmp_path_factory.mktemp('recovery-room'))
 return result.project_dir

@pytest.fixture(scope='module')
def selected_plan(room):
 bundle=Bundle.load(room)
 chosen=[pair for pair in mutation_plan(bundle) if pair[0]['operators'] in [['drop_handoff'],['move_owner_without_path']]]
 assert len(chosen)==2
 return chosen

@pytest.fixture
def prepared(tmp_path,room,selected_plan,monkeypatch):
 chosen=selected_plan
 monkeypatch.setattr(recovery,'mutation_plan',lambda _:copy.deepcopy(chosen))
 empty=tmp_path/'empty';empty.mkdir()
 original=tmp_path/'original'
 freeze=json.loads((ROOT/'prereg/WP6_PLAN.sha256.json').read_text())
 jobs=recovery.prepare_recovery([room],empty,original,freeze)
 return room,original,jobs,freeze

def outcome(job):
 bundle=Bundle.load(job['project'])
 agents=[o['sourceAgentId'] for o in bundle.instance['objects'] if o.get('type')=='Agent']
 targets=[o['id'] for o in bundle.instance['objects'] if o.get('entityRole')=='sceneObject']
 probes=[{'start_agent':a,'target':t,'I1':{},'I2':{},'Gate0':{},
  'variants':{k:{} for k in recovery.frozen.VARIANTS},'stale_request':{k:{} for k in ['I1','I2','runtime','no_digest']}}
  for a in agents for t in targets]
 return {'metadata':job['metadata'],'model_sha256':digest(bundle.instance),'probe_count':len(probes),'probes':probes}

def test_reuses_only_verified_complete_outcome(prepared,tmp_path):
 room,original,jobs,freeze=prepared
 data=outcome(jobs[0]);old=Path(jobs[0]['output']);old.write_bytes(encoded(data))
 before=recovery.inventory(original)
 pending=recovery.prepare_recovery([room],original,tmp_path/'recovered',freeze)
 assert [j['metadata']['id'] for j in pending]==[jobs[1]['metadata']['id']]
 copied=tmp_path/'recovered/outcomes'/old.name
 assert copied.read_bytes()==old.read_bytes()
 assert recovery.inventory(original)==before
 report=json.loads((tmp_path/'recovered/recovery_manifest.json').read_text())
 assert len(report['reused_completed_outcomes'])==1
 assert all(a['identical'] for a in report['model_file_audits'])

@pytest.mark.parametrize('fault',['metadata','digest','pair_order','missing_pair','variant','stale'])
def test_rejects_invalid_completed_record(prepared,tmp_path,fault):
 room,original,jobs,freeze=prepared
 data=outcome(jobs[0])
 if fault=='metadata':data['metadata']['attempt']=999
 elif fault=='digest':data['model_sha256']='0'*64
 elif fault=='pair_order':data['probes'].reverse()
 elif fault=='missing_pair':data['probes'].pop()
 elif fault=='variant':data['probes'][0]['variants'].pop('runtime')
 elif fault=='stale':data['probes'][0]['stale_request'].pop('runtime')
 Path(jobs[0]['output']).write_bytes(encoded(data))
 with pytest.raises(ValueError):recovery.prepare_recovery([room],original,tmp_path/'refused',freeze)

@pytest.mark.parametrize('has_outcome',[False,True])
def test_partial_model_is_never_silently_reused(prepared,tmp_path,has_outcome):
 room,original,jobs,freeze=prepared
 if has_outcome:Path(jobs[0]['output']).write_bytes(encoded(outcome(jobs[0])))
 changed=Path(jobs[0]['project'])/'roomcontract.v2.instance.json';changed.write_bytes(b'partial interrupted write')
 before=recovery.inventory(original)
 if has_outcome:
  with pytest.raises(ValueError,match='model bytes'):recovery.prepare_recovery([room],original,tmp_path/'refused',freeze)
 else:
  pending=recovery.prepare_recovery([room],original,tmp_path/'recovered',freeze)
  assert len(pending)==2
  report=json.loads((tmp_path/'recovered/recovery_manifest.json').read_text())
  assert report['model_file_audits'][0]['different']==['roomcontract.v2.instance.json']
 assert recovery.inventory(original)==before

def test_missing_original_manifest_and_models_retained(prepared,tmp_path):
 room,original,jobs,freeze=prepared
 (original/'mutation_manifest.json').unlink()
 pending=recovery.prepare_recovery([room],original,tmp_path/'recovered',freeze)
 assert len(pending)==2
 assert not (original/'mutation_manifest.json').exists()

def test_manifest_conflict_refused(prepared,tmp_path):
 room,original,jobs,freeze=prepared
 file=original/'mutation_manifest.json';data=json.loads(file.read_text());data['seed']+=1;file.write_bytes(encoded(data))
 with pytest.raises(ValueError,match='manifest differs'):recovery.prepare_recovery([room],original,tmp_path/'refused',freeze)

def test_existing_recovery_directory_never_overwritten(prepared,tmp_path):
 room,original,jobs,freeze=prepared
 with pytest.raises(FileExistsError):recovery.prepare_recovery([room],original,original,freeze)

def test_dependency_change_requires_exact_non_evaluation_exception(tmp_path):
 inventory=tmp_path/'deps.json'
 inventory.write_text(json.dumps({'sha256':{'experiments/mutations.py':'bad'}}))
 with pytest.raises(ValueError,match='dependency changed'):recovery.check_dependencies([inventory])
 inventory.write_text(json.dumps({'sha256':{'experiments/report_mutation_analysis.py':'bad'}}))
 audit=recovery.check_dependencies([inventory])
 assert audit[0]['changed'] and audit[0]['excluded_non_evaluation_file']

def test_run_pending_dispatches_only_supplied_jobs_to_frozen_worker(monkeypatch,tmp_path):
 from concurrent.futures import Future
 submitted=[]
 class Executor:
  def __init__(self,**kw):pass
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def submit(self,worker,job):
   submitted.append((worker,job));future=Future();future.set_result({'id':job['metadata']['id']});return future
 monkeypatch.setattr(recovery,'ProcessPoolExecutor',Executor)
 monkeypatch.setattr(recovery.frozen,'aggregate',lambda _: {'evaluation_complete':True})
 jobs=[{'metadata':{'id':'missing'},'output':str(tmp_path/'missing.json')}]
 assert recovery.run_pending(jobs,tmp_path,4,False)=={'evaluation_complete':True}
 assert submitted==[(recovery.frozen.evaluate_one,jobs[0])]

@pytest.mark.parametrize('fault',[None,'digest','selection'])
def test_original_source_selection_and_native_digest(room,tmp_path,fault):
 import hashlib
 file=Path(room)/'roomcontract.v2.instance.json'
 native_digest=hashlib.sha256(file.read_bytes().replace(b'\r\n',b'\n')).hexdigest().upper()
 data={'selected_projects':[{'project_path':str(room),'model_sha256':native_digest,'source_priority':1,'source_room_id':'engineering_only'}]}
 if fault=='digest':data['selected_projects'][0]['model_sha256']='0'*64
 inventory=tmp_path/'sources.json';inventory.write_text(json.dumps(data))
 projects=[] if fault=='selection' else [room]
 if fault:
  with pytest.raises(ValueError):recovery.verify_sources(projects,[inventory])
 else:
  verified=recovery.verify_sources(projects,[inventory]);assert verified[0]['model_sha256']==native_digest
