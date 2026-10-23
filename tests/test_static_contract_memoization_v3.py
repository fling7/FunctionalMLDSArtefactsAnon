"""Engineering equivalence only: no mutation-corpus outcomes counted here."""
import copy,json
from pathlib import Path
import pytest
from experiments.mutations import Bundle,OPERATORS,mutate,refresh_projections,digest
from experiments.detection_matrix import validators,materialize,VARIANTS
from experiments.lib.model_builder import build_room
from experiments.lib.backend_driver import Driver
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
from experiments.static_model_memoization import static_model_memoization
from backend import roomcontract_v2_runtime as runtime
from backend.guard_config import GuardConfig

def normalized(v):
 if isinstance(v,dict):return {k:normalized(x) for k,x in v.items() if k not in {"generated_at","elapsed_ms"}}
 if isinstance(v,(tuple,list)):return [normalized(x) for x in v]
 return v
@pytest.fixture(scope="module")
def room(tmp_path_factory):
 p=build_room({"case_id":"memo2_fixture","agents":["a","b","c"],"objects":["one","two","three"],"owners":{"asset":{"one":["a"],"two":["b"],"three":["c"]},"group":{"group_a":["a"]},"zone":{"zone_a":["a"]}},"handoffs":[["a","b"],["b","a"],["b","c"],["c","b"]]},tmp_path_factory.mktemp("room"))
 return Bundle.load(p.project_dir)
@pytest.mark.parametrize("operator",["baseline",*OPERATORS])
def test_all_checker_fields_equal(room,operator):
 b=room if operator=="baseline" else refresh_projections(mutate(room,operator,20261015)[0]);before=copy.deepcopy(b)
 with static_model_memoization():old=validators(b)
 with static_contract_memoization_v3():
  new=validators(b);again=validators(b)
 assert normalized(old)==normalized(new)==normalized(again)
 assert b==before

@pytest.mark.parametrize("operator",["baseline",*OPERATORS])
def test_all_pairs_variants_setup_errors_equal(room,operator,tmp_path):
 b=room if operator=="baseline" else refresh_projections(mutate(room,operator,20261015)[0])
 project=tmp_path/b.instance["caseId"];materialize(Path(room.source),b,project)
 def run():
  try:d=Driver(project)
  except Exception as e:return {"exception":type(e).__name__,"message":str(e),"reason":getattr(e,"code",None)}
  try:
   result=[]
   for a in [o["sourceAgentId"] for o in b.instance["objects"] if o.get("type")=="Agent"]:
    for target in d.targets:
     for cfg in VARIANTS.values():
      d.store.guard_config=GuardConfig(**cfg);result.append(d.probe(d.request(a,target)))
     for cfg in [{},{"digest_check":False}]:
      d.store.guard_config=GuardConfig(**cfg);result.append(d.probe(d.request(a,target,"stale_digest")))
   return result
  finally:d.close()
 with static_model_memoization():old=run()
 with static_contract_memoization_v3():new=run()
 assert old==new
 if operator=="baseline":assert isinstance(old,list) and len(old)==63


def caught(call):
 try:return ("value",call())
 except Exception as e:return (type(e).__name__,str(e),getattr(e,"code",None))
def materialized(room,tmp_path):
 p=tmp_path/room.instance["caseId"];materialize(Path(room.source),room,p);return p

def test_fresh_reads_digest_and_isolated_return(room,tmp_path,monkeypatch):
 p=materialized(room,tmp_path);reads=[];hashes=[];read=Path.read_bytes;digest=runtime._sha256
 def tracked(path):reads.append(str(path));return read(path)
 def hashed(path,**kwargs):hashes.append(str(path));return digest(path,**kwargs)
 monkeypatch.setattr(Path,"read_bytes",tracked);monkeypatch.setattr(runtime,"_sha256",hashed)
 with static_contract_memoization_v3() as stats:
  first=runtime.load_project_contract(p);expected=copy.deepcopy(first);first["instance"]["objects"][0]["fixture_marker"]="must not leak"
  reads.clear();hashes.clear();second=runtime.load_project_contract(p)
  assert second==expected and stats["contract_hits"]==1 and hashes
  assert str((p/"roomcontract.v2.instance.json").resolve()) in reads
  assert str((p/"trace_map.v2.json").resolve()) in reads
  assert str((p/"agents.json").resolve()) in reads
  assert str((p/"project.json").resolve()) in reads

@pytest.mark.parametrize("filename",["project.json","roomcontract.v2.instance.json","trace_map.v2.json","agents.json"])
def test_changed_missing_invalid_then_valid_dependency(room,tmp_path,filename):
 p=materialized(room,tmp_path);f=p/filename;original=f.read_bytes()
 with static_contract_memoization_v3() as stats:
  baseline=caught(lambda:runtime.load_project_contract(p));assert baseline[0]=="value"
  f.write_bytes(b"{")
  invalid=caught(lambda:runtime.load_project_contract(p));assert invalid[0]!="value"
  assert caught(lambda:runtime.load_project_contract(p))==invalid
  f.unlink();missing=caught(lambda:runtime.load_project_contract(p));assert missing[0]!="value"
  f.write_bytes(original);assert caught(lambda:runtime.load_project_contract(p))==baseline
  changed=json.loads(original);changed["future_fixture_field"]="changed";f.write_text(json.dumps(changed),encoding="utf8")
  hit_count=stats["contract_hits"];observed=caught(lambda:runtime.load_project_contract(p));assert stats["contract_hits"]==hit_count
 # Direct original must give every same error/reason on the same changed input.
 assert caught(lambda:runtime.load_project_contract(p))==observed
 f.write_bytes(b"{");assert caught(lambda:runtime.load_project_contract(p))==invalid
 f.unlink();assert caught(lambda:runtime.load_project_contract(p))==missing


def test_added_previously_absent_optional_agents_causes_miss(room,tmp_path):
 p=materialized(room,tmp_path)
 for name in ("project.json","trace_map.v2.json"):
  f=p/name;j=json.loads(f.read_text())
  for field in runtime.PLACEMENT_DEPLOYMENT_FIELDS:j.pop(field,None)
  f.write_text(json.dumps(j),encoding="utf8")
 (p/"agents.json").unlink()
 with static_contract_memoization_v3() as stats:
  runtime.load_project_contract(p);runtime.load_project_contract(p);hits=stats["contract_hits"]
  (p/"agents.json").write_text('{"agents":[]}',encoding="utf8")
  runtime.load_project_contract(p);assert stats["contract_hits"]==hits


def test_unknown_metadata_or_external_path_falls_back(room,tmp_path):
 p=materialized(room,tmp_path);f=p/"project.json";meta=json.loads(f.read_text())
 with static_contract_memoization_v3() as stats:
  runtime.load_project_contract(p)
  meta["future_loader_dependency"]="unknown";f.write_text(json.dumps(meta),encoding="utf8")
  observed=caught(lambda:runtime.load_project_contract(p));assert stats["contract_bypasses"]==1
 assert caught(lambda:runtime.load_project_contract(p))==observed
 meta.pop("future_loader_dependency");external=tmp_path/"external.json";external.write_bytes((p/"roomcontract.v2.instance.json").read_bytes());meta["roomcontract_model_path"]=str(external);f.write_text(json.dumps(meta),encoding="utf8")
 with static_contract_memoization_v3() as stats:
  observed=caught(lambda:runtime.load_project_contract(p));assert stats["contract_bypasses"]==1
 assert caught(lambda:runtime.load_project_contract(p))==observed


def test_publication_protocol_wrapper_remains_live(room,tmp_path,monkeypatch):
 from backend import publication
 p=materialized(room,tmp_path);calls=[]
 def barrier(path,loader):calls.append(str(path));return loader(path)
 monkeypatch.setattr(publication,"load_consistent_contract",barrier)
 with static_contract_memoization_v3() as stats:
  runtime.load_project_contract(p,publication_protocol="cooperative")
  runtime.load_project_contract(p,publication_protocol="cooperative")
  assert len(calls)==2 and stats["contract_hits"]==1
  assert caught(lambda:runtime.load_project_contract(p,publication_protocol="unknown"))[0]=="RoomContractContractError"


def test_reload_preflight_refuses_changed_file(room,tmp_path):
 p=materialized(room,tmp_path)
 with static_contract_memoization_v3():
  d=Driver(p)
  try:
   target=d.targets[0];a=next(o["sourceAgentId"] for o in room.instance["objects"] if o.get("type")=="Agent")
   request=d.request(a,target);d.probe(request)
   f=d.project/"trace_map.v2.json";raw=f.read_bytes();f.write_bytes(b"{")
   bad=d.probe(request);assert bad["decision"]=="REJECT" and bad["reason"]=="E_PUBLICATION_INCONSISTENT" and bad["model_calls"]==0
   f.write_bytes(raw);assert d.probe(request)["reason"] is None
  finally:d.close()


def test_restores_on_exception():
 from tools import validate_dynamic_functional_rdl_v2 as structural
 old=(runtime._load_project_contract_unchecked,structural._simple)
 with pytest.raises(RuntimeError):
  with static_contract_memoization_v3():raise RuntimeError("fixture")
 assert old==(runtime._load_project_contract_unchecked,structural._simple)
