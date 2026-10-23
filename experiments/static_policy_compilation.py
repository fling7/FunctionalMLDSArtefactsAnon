"""DRAFT per-case I2 compiled API bridge; no independent source is modified."""
from collections import OrderedDict
from contextlib import contextmanager
from types import SimpleNamespace
import copy,pickle

@contextmanager
def static_policy_compilation(matrix,compiler=None):
 original_importlib=matrix.importlib
 original_module=original_importlib.import_module("verification.impl_b.policy_adapter")
 reference=original_module.evaluate
 if compiler is None:
  from verification.impl_b.compiled_policy import compile_model
  compiler=compile_model
 stats={"calls":0,"compilations":0,"cache_hits":0,"input_key_failures":0,"compile_fallbacks":0,"evaluation_fallbacks":0,"snapshots":[],"scope":"Static immutable-model WP6 only; no request/outcome cache or timing claim."}
 cache=OrderedDict()
 def evaluate(instance,trace,request,session):
  stats["calls"]+=1
  try:key=pickle.dumps((instance,trace),protocol=5)
  except Exception:
   stats["input_key_failures"]+=1;return reference(instance,trace,request,session)
  if key in cache:
   compiled,diagnostic=cache[key];cache.move_to_end(key);stats["cache_hits"]+=1
  else:
   try:compiled=compiler(copy.deepcopy(instance),copy.deepcopy(trace))
   except Exception as exc:
    stats["compile_fallbacks"]+=1
    stats["snapshots"].append({"compile_fallback":{"type":type(exc).__name__,"message":str(exc)}})
    return reference(instance,trace,request,session)
   stats["compilations"]+=1
   diagnostic={"mode":getattr(compiled,"mode",None),"fallback_reason":getattr(compiled,"fallback_reason",None),"reference_hashes":copy.deepcopy(getattr(compiled,"reference_hashes",None)),"compile_seconds":getattr(compiled,"compile_seconds",None),"requests":0}
   stats["snapshots"].append(diagnostic)
   cache[key]=(compiled,diagnostic)
   while len(cache)>2:cache.popitem(last=False)
  diagnostic["requests"]+=1
  try:result=compiled.evaluate(request,session)
  except Exception as exc:
   stats["evaluation_fallbacks"]+=1;diagnostic["last_fallback_exception"]={"type":type(exc).__name__,"message":str(exc)}
   return reference(instance,trace,request,session)
  diagnostic["statistics"]=copy.deepcopy(getattr(compiled,"statistics",None))
  return result
 def import_module(name,*args,**kwargs):
  if name=="verification.impl_b.policy_adapter":return SimpleNamespace(evaluate=evaluate)
  return original_importlib.import_module(name,*args,**kwargs)
 matrix.importlib=SimpleNamespace(import_module=import_module)
 try:yield stats
 finally:matrix.importlib=original_importlib
