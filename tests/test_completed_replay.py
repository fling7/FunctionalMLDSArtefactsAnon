from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from repro import completed_replay as r

def test_existing_output_refused_without_write(tmp_path):
 p=tmp_path/'results/replay/kept';p.mkdir(parents=True);(p/'keep').write_bytes(b'old')
 with pytest.raises(ValueError,match='already exists'):r.destination(tmp_path,p)
 assert (p/'keep').read_bytes()==b'old'

@pytest.mark.parametrize('path',['results/processed/new','../escape','results/replay/../../docs'])
def test_output_cannot_escape_replay_scope(tmp_path,path):
 with pytest.raises(ValueError,match='under results/replay'):r.destination(tmp_path,path)

def test_missing_bundle_retains_failure_manifest(tmp_path):
 with pytest.raises(ValueError,match='Missing sealed replay bundle'):r.replay(tmp_path,'results/replay/failed',('WP1',),False)
 doc=json.loads((tmp_path/'results/replay/failed/manifest.json').read_text())
 assert doc['status']=='failed' and not doc['all_scope_G9'] and doc['reports']=={}
 assert (tmp_path/'results/replay/failed/missing_scope.json').is_file()

def test_tampered_selector_not_imported(tmp_path):
 p=tmp_path/r.BUNDLE/r.SELECTOR;p.parent.mkdir(parents=True);p.write_text('raise RuntimeError("must not import")')
 with pytest.raises(ValueError,match='pin mismatch'):r.load_bundle(tmp_path)

def test_subset_does_not_run_closeout_or_global_numbers(tmp_path,monkeypatch):
 seen=[];fake=SimpleNamespace(validate=lambda *a:None)
 monkeypatch.setattr(r,'load_bundle',lambda root:(root,'3.12',{('WP2','3.12'):{}},fake))
 monkeypatch.setattr(r,'run_group',lambda root,out,group,prepared:seen.append(group) or {'status':'complete','outputs':{}})
 monkeypatch.setattr(r,'run_closeout',lambda *a:pytest.fail('unexpected global report'))
 result=r.replay(tmp_path,'results/replay/one',('WP2',),False)
 assert seen==['WP2'] and result['status']=='complete_declared_scope_only'
 assert result['no_global_numbers_or_handover_mutation'] and not result['research_complete']

def test_failure_preserves_completed_group_and_stops(tmp_path,monkeypatch):
 seen=[];fake=SimpleNamespace(validate=lambda *a:None)
 monkeypatch.setattr(r,'load_bundle',lambda root:(root,'3.12',{(g,'3.12'):{} for g in ('WP1','WP2','WP7')},fake))
 def group(root,out,g,prepared):
  seen.append(g)
  if g=='WP2':raise ValueError('retained test failure')
  return {'status':'complete','outputs':{}}
 monkeypatch.setattr(r,'run_group',group)
 with pytest.raises(ValueError,match='retained'):r.replay(tmp_path,'results/replay/fail',('WP1','WP2','WP7'),False)
 manifest=json.loads((tmp_path/'results/replay/fail/manifest.json').read_text())
 assert seen==['WP1','WP2'] and manifest['reports']['WP1']['status']=='complete' and manifest['status']=='failed'

@pytest.mark.parametrize('args',[['--llm'],['--replay','--only','WP4'],['--replay','--offline']])
def test_unavailable_or_conflicting_modes_refuse_before_dispatch(monkeypatch,args):
 monkeypatch.setattr(r,'replay',lambda *a:pytest.fail('unexpected dispatch'))
 with pytest.raises(SystemExit):r.main(args)

def test_offline_is_report_only_alias(monkeypatch):
 seen=[]
 monkeypatch.setattr(r,'replay',lambda root,out,groups,close:seen.append((groups,close)) or {'status':'complete_declared_scope_only'})
 assert r.main(['--offline','--only','WP1'])==0
 assert seen==[(('WP1',),False)]

def test_closeout_no_api_environment_and_exact_outputs(tmp_path,monkeypatch):
 p=tmp_path/'repro/report_closeout.py';p.parent.mkdir();p.write_text('# trusted synthetic report')
 out=tmp_path/'out';out.mkdir();monkeypatch.setenv('OPENAI_API_KEY','synthetic-never-forwarded')
 def run(command,**kwargs):
  assert 'OPENAI_API_KEY' not in kwargs['env'] and command[1:3]==['-I','-B']
  assert command[-2]=='--output';target=Path(command[-1]);target.mkdir()
  for name in ('summary.json','evidence_table.csv','number_sources.json'):(target/name).write_bytes(b'{}')
  return SimpleNamespace(returncode=0,stdout=b'ok',stderr=b'')
 monkeypatch.setattr(r.subprocess,'run',run)
 result=r.run_closeout(tmp_path,out)
 assert len(result['outputs'])==3 and result['source_sha256']==r.sha(p)

def test_closeout_failure_keeps_stderr(tmp_path,monkeypatch):
 p=tmp_path/'repro/report_closeout.py';p.parent.mkdir();p.write_text('# synthetic')
 out=tmp_path/'out';out.mkdir()
 monkeypatch.setattr(r.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout=b'',stderr=b'typed refusal'))
 with pytest.raises(ValueError,match='refused'):r.run_closeout(tmp_path,out)
 assert (out/'closeout.stderr.txt').read_bytes()==b'typed refusal'
