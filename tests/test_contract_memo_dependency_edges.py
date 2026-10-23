"""Additional audited path/fallback tests, separate from the 46-test record."""
import json
import pytest
from experiments.lib.model_builder import build_room
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
from experiments.lib import backend_driver
from backend import roomcontract_v2_runtime as runtime

@pytest.fixture
def project(tmp_path):
 return build_room({"case_id":"edge_fixture","agents":["a"],"objects":["one"],"owners":{"asset":{"one":["a"]}},"handoffs":[]},tmp_path).project_dir

def caught(call):
 try:return ("value",call())
 except Exception as e:return (type(e).__name__,str(e),getattr(e,"code",None))
def metadata(p,change):
 f=p/"project.json";m=json.loads(f.read_text());change(m);f.write_text(json.dumps(m),encoding="utf8")

@pytest.mark.parametrize("field,value",[("generation_mode","unsupported"),("metamodelVersion","legacy"),("roomcontract_model_version",None)])
def test_unaudited_branch_falls_back(project,field,value):
 metadata(project,lambda m:m.__setitem__(field,value))
 expected=caught(lambda:runtime.load_project_contract(project))
 with static_contract_memoization_v3() as stats:
  assert caught(lambda:runtime.load_project_contract(project))==expected
  assert caught(lambda:runtime.load_project_contract(project))==expected
  assert stats["contract_bypasses"]==2 and stats["contract_hits"]==0

def test_added_and_removed_default_version_trace_is_fresh(project):
 metadata(project,lambda m:m.pop("roomcontract_trace_map_path",None))
 optional=project/"trace_map.json"
 optional.unlink(missing_ok=True)
 assert not optional.exists()
 with static_contract_memoization_v3() as stats:
  before=caught(lambda:runtime.load_project_contract(project));assert before[0]=="value"
  optional.write_text('{"schema":"future-incompatible"}',encoding="utf8")
  bad=caught(lambda:runtime.load_project_contract(project));assert bad[0]!="value" and stats["contract_hits"]==0
  optional.unlink();assert caught(lambda:runtime.load_project_contract(project))==before
 optional.write_text('{"schema":"future-incompatible"}',encoding="utf8")
 assert caught(lambda:runtime.load_project_contract(project))==bad

def test_v2_alias_keeps_default_native_version_hint_keyed(project):
 native=project/"roomcontract.v2.instance.json";alias=project/"alias.json";alias.write_bytes(native.read_bytes())
 def change(m):m.pop("roomcontract_model_path",None);m["roomcontract_v2_path"]="alias.json"
 metadata(project,change)
 with static_contract_memoization_v3() as stats:
  first=caught(lambda:runtime.load_project_contract(project))
  native.write_bytes(b"{")
  bad=caught(lambda:runtime.load_project_contract(project));assert bad[0]!="value" and stats["contract_hits"]==0
 assert caught(lambda:runtime.load_project_contract(project))==bad

def test_unsupported_file_kind_falls_back(project):
 f=project/"agents.json";f.unlink();f.mkdir()
 expected=caught(lambda:runtime.load_project_contract(project))
 with static_contract_memoization_v3() as stats:
  assert caught(lambda:runtime.load_project_contract(project))==expected
  assert stats["contract_bypasses"]==1 and stats["contract_hits"]==0
