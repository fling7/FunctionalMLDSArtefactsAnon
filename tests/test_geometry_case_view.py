"""Verify derived auxiliary input cannot alter the frozen geometry calculation."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.geometry_case_view import make_view,verify_unused_normalized_value
from experiments.natural_faults import zone_lint

def source_case(path):
 source={'scene':{'sceneName':'geometry_view_engineering','environment':{'type':'indoor','dimensions':{'width':20,'height':4,'depth':20},'lighting':[],'background':'#ffffff'},'objectGroups':{'group':{'color':'#888888'}},'objects':[{'objectId':'one','objectType':'display','position':{'x':0,'y':0.5,'z':0},'rotation':{'x':0,'y':0,'z':0},'dimensions':{'width':1,'height':1,'depth':1},'group':'group','children':[],'specification':'Engineering fixture only.'}]}}
 (path/'input').mkdir(parents=True)
 (path/'input/source_rdl.json').write_bytes(json.dumps(source,indent=2).replace('\n','\r\n').encode())
 return path

def test_view_preserves_original_source_bytes_and_validation(tmp_path):
 case=source_case(tmp_path/'source');raw=(case/'input/source_rdl.json').read_bytes()
 report=make_view(case,tmp_path/'view')
 assert (tmp_path/'view/input/source_rdl.json').read_bytes()==raw
 assert (case/'input/source_rdl.json').read_bytes()==raw
 assert report['original_source_sha256']==report['copied_source_sha256']
 assert json.loads((tmp_path/'view/ingestion_report.json').read_text())['status']=='valid'

def test_normalized_artifact_changes_do_not_change_lint(tmp_path):
 case=source_case(tmp_path/'source');make_view(case,tmp_path/'view')
 idx=SimpleNamespace(zones={'z':{'sourceObjectId':['one']}},objects={'o':{'sourceId':'one'}},agents={'a':{'responsibleZone':['z']}},wire={'a':'agent_a'},ownership=lambda _:('asset',['a']))
 before=zone_lint(tmp_path/'view',idx)
 (tmp_path/'view/intermediate/scene_graph.normalized.json').write_text(json.dumps({'unrelated':'completely different artifact','objects':[{'x':1e9}]}))
 after=zone_lint(tmp_path/'view',idx)
 assert before==after
 assert before['rows'][0]['inside_owner_zone_box'] is True
 assert verify_unused_normalized_value()=={'normalized_stores':1,'normalized_loads':0}

def test_missing_source_geometry_refused(tmp_path):
 with pytest.raises(FileNotFoundError):make_view(tmp_path/'absent',tmp_path/'view')
 assert not (tmp_path/'view').exists()

def test_existing_view_never_overwritten(tmp_path):
 case=source_case(tmp_path/'source');make_view(case,tmp_path/'view')
 with pytest.raises(FileExistsError):make_view(case,tmp_path/'view')
