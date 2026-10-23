"""Bridge lifecycle tests use a self-authored fake compiler, not oracle evidence."""
from types import SimpleNamespace
import copy
import pytest
from experiments.static_policy_compilation import static_policy_compilation

def bridge():
 calls=[]
 def reference(instance,trace,request,session):calls.append((copy.deepcopy(instance),copy.deepcopy(trace),copy.deepcopy(request),copy.deepcopy(session)));return {"reference":True,"tag":request["tag"]}
 module=SimpleNamespace(evaluate=reference)
 other=SimpleNamespace(other=True)
 imports=SimpleNamespace(import_module=lambda name,*a,**k:module if name=="verification.impl_b.policy_adapter" else other)
 return SimpleNamespace(importlib=imports),module,other,calls
class Compiler:
 def __init__(self):self.inputs=[]
 def __call__(self,instance,trace):
  self.inputs.append((instance,trace));snapshot=copy.deepcopy((instance,trace))
  class Compiled:
   mode="fake";reference_hashes={"test":"self-authored"};compile_seconds=0;statistics={"requests":0}
   def evaluate(self,request,session):
    self.statistics["requests"]+=1
    return {"snapshot":copy.deepcopy(snapshot),"tag":request["tag"],"digest":session["model_sha256"]}
  return Compiled()

def test_complete_inputs_and_fresh_requests_no_original_patch():
 matrix,module,other,refs=bridge();original=module.evaluate;compiler=Compiler();instance={"objects":[{"x":1}]};trace={"map":[1]};session={"model_sha256":"same"}
 with static_policy_compilation(matrix,compiler) as stats:
  evaluate=matrix.importlib.import_module("verification.impl_b.policy_adapter").evaluate
  assert module.evaluate is original and matrix.importlib.import_module("other") is other
  a=evaluate(instance,trace,{"tag":"a"},session);b=evaluate(instance,trace,{"tag":"b"},{"model_sha256":"stale"})
  assert stats["compilations"]==1 and stats["cache_hits"]==1 and a["tag"]!=b["tag"] and b["digest"]=="stale"
  instance["objects"][0]["x"]=2;evaluate(instance,trace,{"tag":"c"},session)
  trace["map"].append(2);evaluate(instance,trace,{"tag":"d"},session)
  assert stats["compilations"]==3 and compiler.inputs[0][0]["objects"][0]["x"]==1
 assert refs==[] and module.evaluate is original

@pytest.mark.parametrize("phase",["compile","evaluate"])
def test_failure_uses_original_and_restores(phase):
 matrix,module,other,refs=bridge();imports=matrix.importlib
 def compiler(instance,trace):
  if phase=="compile":raise ValueError("fixture")
  return SimpleNamespace(evaluate=lambda *args:(_ for _ in ()).throw(ValueError("fixture")),mode="fake")
 with static_policy_compilation(matrix,compiler) as stats:
  fn=matrix.importlib.import_module("verification.impl_b.policy_adapter").evaluate
  assert fn({}, {}, {"tag":"x"}, {})=={"reference":True,"tag":"x"}
  assert fn({}, {}, {"tag":"y"}, {})=={"reference":True,"tag":"y"}
  assert stats["compile_fallbacks" if phase=="compile" else "evaluation_fallbacks"]==2
 assert len(refs)==2 and matrix.importlib is imports

def test_restores_after_outer_exception():
 matrix,module,other,refs=bridge();imports=matrix.importlib
 with pytest.raises(RuntimeError):
  with static_policy_compilation(matrix,Compiler()):raise RuntimeError("fixture")
 assert matrix.importlib is imports

def test_original_error_still_propagates_after_compile_fallback():
 matrix,module,other,refs=bridge()
 def original(*args):raise KeyError("original error")
 module.evaluate=original
 def compiler(*args):raise ValueError("compile error")
 with static_policy_compilation(matrix,compiler) as stats:
  fn=matrix.importlib.import_module("verification.impl_b.policy_adapter").evaluate
  with pytest.raises(KeyError,match="original error"):fn({}, {}, {"tag":"x"}, {})
  assert stats["snapshots"][0]["compile_fallback"]=={"type":"ValueError","message":"compile error"}
