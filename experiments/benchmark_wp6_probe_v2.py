"""Isolated engineering profile; excluded from WP6 research outcomes."""
from pathlib import Path
import cProfile,json,time,sys,pstats,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.mutations import Bundle,digest
from experiments.detection_matrix import validators,request_for,VARIANTS,independent_call
from experiments.static_input_memoization_v2 import static_input_memoization_v2 as static_model_memoization
from experiments.lib.backend_driver import Driver
from backend.guard_config import GuardConfig
import importlib

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=False)
 run_dir=ROOT/"results/raw/wp6_generated_recovery_v1";manifest=json.loads((run_dir/"mutation_manifest.json").read_text())
 meta=next(m for m in manifest["models"] if m["operators"]==["drop_handoff"] and m["status"]=="changed")
 project=run_dir/"models"/meta["storage_id"]/meta["room"];bundle=Bundle.load(project);records=[]
 (out/"provenance.json").write_text(json.dumps({"engineering_only":True,"model":meta,"project":str(project),"source_hashes":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [project/"roomcontract.v2.instance.json",project/"trace_map.v2.json",ROOT/"experiments/detection_matrix.py",ROOT/"experiments/static_model_memoization.py"]}},indent=2))
 def phase(name,call):
  pr=cProfile.Profile();wall=time.perf_counter();cpu=time.process_time();
  try:return call()
  finally:
   row={"phase":name,"wall_seconds":time.perf_counter()-wall,"cpu_seconds":time.process_time()-cpu};records.append(row);print(json.dumps(row),flush=True);
   (out/"progress.json").write_text(json.dumps(records,indent=2))
 with static_model_memoization() as counters:
  # No authoring validator repetition: measure the registered request loop only.
  driver=phase("setup",lambda:Driver(project))
  try:
   target=driver.targets[0];agent=next(o["sourceAgentId"] for o in bundle.instance["objects"] if o.get("type")=="Agent");req=request_for(agent,target,digest(bundle.instance));session={"model_sha256":digest(bundle.instance),"active_agent_mode":"client"}
   for label,module in [("I1","verification.impl_a.reference"),("I2","verification.impl_b.policy_adapter")]:
    evaluator=importlib.import_module(module).evaluate
    phase(label,lambda:independent_call(evaluator,bundle.instance,bundle.trace,req,session))
   for label,config in VARIANTS.items():
    driver.store.guard_config=GuardConfig(**config);phase(label,lambda:driver.probe(req))
   stale=json.loads(json.dumps(req));stale["spatial_context"]["model_sha256"]="0"*64
   for label,module in [("I1_stale","verification.impl_a.reference"),("I2_stale","verification.impl_b.policy_adapter")]:
    evaluator=importlib.import_module(module).evaluate;phase(label,lambda:independent_call(evaluator,bundle.instance,bundle.trace,stale,session))
   for label,config in [("runtime_stale",{}),("no_digest_stale",{"digest_check":False})]:
    driver.store.guard_config=GuardConfig(**config);phase(label,lambda:driver.probe(stale))
  finally:driver.close()
 (out/"counters.json").write_text(json.dumps(counters,indent=2));print(json.dumps({"done":True,"out":str(out)}),flush=True)
if __name__=="__main__":run(sys.argv[1])
