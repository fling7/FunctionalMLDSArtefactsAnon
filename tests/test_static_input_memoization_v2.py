"""Engineering equivalence only: no mutation-corpus outcomes counted here."""
import copy,json
from pathlib import Path
import pytest
from experiments.mutations import Bundle,OPERATORS,mutate,refresh_projections,digest
from experiments.detection_matrix import validators,materialize,VARIANTS
from experiments.lib.model_builder import build_room
from experiments.lib.backend_driver import Driver
from experiments.static_input_memoization_v2 import static_input_memoization_v2,SuccessMemo
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
 old=validators(b)
 with static_input_memoization_v2():
  new=validators(b);again=validators(b)
 assert normalized(old)==normalized(new)==normalized(again)
 assert b==before

@pytest.mark.parametrize("operator",["baseline",*OPERATORS])
def test_all_pairs_variants_setup_errors_equal(room,operator,tmp_path):
 b=room if operator=="baseline" else refresh_projections(mutate(room,operator,20261015)[0])
 project=tmp_path/"project";materialize(Path(room.source),b,project)
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
 old=run()
 with static_input_memoization_v2():new=run()
 assert old==new

def caught(call):
 try:return ("value",call())
 except Exception as e:return (type(e).__name__,str(e),getattr(e,"code",None))
@pytest.mark.parametrize("raw",[b'{"x":[1,2]}',b'{\r\n"x":1,\r\n}',b'[]',b'{"x":',b'\xff',b'\xef\xbb\xbf{"x":1}'])
def test_read_failures_and_successes_identical(raw,tmp_path):
 p=tmp_path/"input.json";p.write_bytes(raw);old=caught(lambda:runtime._read_json(p))
 with static_input_memoization_v2():
  assert caught(lambda:runtime._read_json(p))==old
  assert caught(lambda:runtime._read_json(p))==old

def test_fresh_reads_changed_bytes_and_independent_copy(tmp_path,monkeypatch):
 p=tmp_path/"x.json";p.write_bytes(b'{"x":[1]}');original=Path.read_bytes;calls=[]
 def read(path):calls.append(path);return original(path)
 monkeypatch.setattr(Path,"read_bytes",read)
 with static_input_memoization_v2() as stats:
  a=runtime._read_json(p);a["x"].append(9);assert runtime._read_json(p)=={"x":[1]}
  assert len(calls)==2 and stats["json_hits"]==1
  p.write_bytes(b'{"x":[2]}');assert runtime._read_json(p)=={"x":[2]} and stats["json_misses"]==2
  p.write_bytes(b'{');assert caught(lambda:runtime._read_json(p))[0]!="value";assert caught(lambda:runtime._read_json(p))[0]!="value"
  assert stats["json_failures_not_cached"]==2
  p.write_bytes(b'{"x":[1]}');assert runtime._read_json(p)=={"x":[1]}
  p.unlink();assert caught(lambda:runtime._read_json(p))[0]=="RoomContractContractError"

def test_instance_context_inputs_and_failed_validation_not_cached(room):
 value=copy.deepcopy(room.instance);trace=copy.deepcopy(room.trace);pin=digest(value)
 with static_input_memoization_v2() as stats:
  a=runtime._validate_v2_instance(value);b=runtime._validate_v2_instance(copy.deepcopy(value));assert a==b and a is not b
  first=runtime._build_v2_runtime_context(value,trace,pin);second=runtime._build_v2_runtime_context(copy.deepcopy(value),copy.deepcopy(trace),pin)
  assert first==second and first is not second
  assert stats["instance_hits"]==1 and stats["context_hits"]==1
  for i in range(3):
   args=[copy.deepcopy(value),copy.deepcopy(trace),pin]
   if i==0:args[0]["caseId"]="changed"
   if i==1:args[1]["case_id"]="changed"
   if i==2:args[2]="0"*64
   runtime._build_v2_runtime_context(*args)
  assert stats["context_misses"]==4
  invalid=copy.deepcopy(value);invalid["schema"]="wrong"
  for _ in range(2):assert caught(lambda:runtime._validate_v2_instance(invalid))[0]=="RoomContractContractError"
  assert stats["instance_failures_not_cached"]==2
  assert runtime._validate_v2_instance(value)==a

def test_restores_functions_on_error():
 from tools import validate_dynamic_functional_rdl_v2 as s
 old=(runtime._read_json,runtime._validate_v2_instance,runtime._build_v2_runtime_context,s._simple)
 with pytest.raises(RuntimeError):
  with static_input_memoization_v2():raise RuntimeError("fixture")
 assert old==(runtime._read_json,runtime._validate_v2_instance,runtime._build_v2_runtime_context,s._simple)

def test_bounded_success_only_cache():
 stats={"x_hits":0,"x_misses":0,"x_failures_not_cached":0};cache=SuccessMemo("x",stats,limit=1)
 assert cache.call((1,),lambda:[1])==[1]
 assert cache.call((2,),lambda:[2])==[2]
 assert cache.call((1,),lambda:[1])==[1]
 assert stats["x_misses"]==3
