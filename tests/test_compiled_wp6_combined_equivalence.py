"""Full frozen evaluate_one comparison; engineering fixtures only."""
import json
from pathlib import Path
import pytest
from experiments import detection_matrix as matrix
from experiments.mutations import Bundle,OPERATORS,mutate,refresh_projections
from experiments.lib.model_builder import build_room
from experiments.static_model_memoization import static_model_memoization
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
from experiments.static_policy_compilation import static_policy_compilation

def normalized(v):
 if isinstance(v,dict):return {k:normalized(x) for k,x in v.items() if k not in {"generated_at","elapsed_ms"}}
 if isinstance(v,(tuple,list)):return [normalized(x) for x in v]
 return v
@pytest.fixture(scope="module")
def room(tmp_path_factory):
 p=build_room({"case_id":"compiled_bridge_fixture","agents":["a","b","c"],"objects":["one","two","three"],"owners":{"asset":{"one":["a"],"two":["b"],"three":["c"]},"group":{"group_a":["a"]},"zone":{"zone_a":["a"]}},"handoffs":[["a","b"],["b","a"],["b","c"],["c","b"]]},tmp_path_factory.mktemp("room"))
 return Bundle.load(p.project_dir)

@pytest.mark.parametrize("operator",["baseline",*OPERATORS])
def test_full_frozen_matrix_equivalence(room,operator,tmp_path):
 bundle=room if operator=="baseline" else refresh_projections(mutate(room,operator,20261015)[0])
 project=tmp_path/bundle.instance["caseId"];matrix.materialize(Path(room.source),bundle,project)
 meta={"id":"engineering_"+operator,"room":bundle.instance["caseId"],"operators":[] if operator=="baseline" else [operator],"status":"engineering_fixture"}
 old_output=tmp_path/"original.json";new_output=tmp_path/"combined.json"
 with static_model_memoization():matrix.evaluate_one({"project":str(project),"output":str(old_output),"metadata":meta})
 with static_contract_memoization_v3() as contract:
  with static_policy_compilation(matrix) as policy:
   matrix.evaluate_one({"project":str(project),"output":str(new_output),"metadata":meta})
 old=json.loads(old_output.read_text());new=json.loads(new_output.read_text())
 matrix.write_new(tmp_path/"memo_diagnostics.json",{"contract":contract,"policy":policy,"engineering_only":True})
 assert normalized(old)==normalized(new)
 assert policy["calls"]==2*old["probe_count"]
 if operator=="baseline":
  assert old["probe_count"]==9 and old["checkers"]["backend_setup"]["status"]=="pass"
  assert policy["compilations"]==1 and policy["cache_hits"]==17
