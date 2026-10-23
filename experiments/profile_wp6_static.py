"""Isolated engineering profile; excluded from WP6 research outcomes."""
from pathlib import Path
import cProfile,json,time,sys,pstats,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.mutations import Bundle,digest
from experiments.detection_matrix import validators,request_for,VARIANTS,independent_call
from experiments.static_model_memoization import static_model_memoization
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
  pr=cProfile.Profile();wall=time.perf_counter();cpu=time.process_time();pr.enable()
  try:return call()
  finally:
   pr.disable();row={"phase":name,"wall_seconds":time.perf_counter()-wall,"cpu_seconds":time.process_time()-cpu};records.append(row);print(json.dumps(row),flush=True);pr.dump_stats(str(out/(name+".prof")))
   stats=pstats.Stats(pr);top=sorted(stats.stats.items(),key=lambda x:x[1][3],reverse=True)[:45]
   (out/(name+"_top.json")).write_text(json.dumps([{ "file":k[0],"line":k[1],"function":k[2],"primitive_calls":v[0],"total_calls":v[1],"self_cpu":v[2],"cumulative_cpu":v[3]} for k,v in top],indent=2))
   (out/"progress.json").write_text(json.dumps(records,indent=2))
 with static_model_memoization() as counters:
  phase("validators",lambda:validators(bundle))
  driver=phase("setup",lambda:Driver(project))
  try:
   target=driver.targets[0];agent=next(o["sourceAgentId"] for o in bundle.instance["objects"] if o.get("type")=="Agent");req=request_for(agent,target,digest(bundle.instance));session={"model_sha256":digest(bundle.instance),"active_agent_mode":"client"}
   for label,module in [("I1","verification.impl_a.reference"),("I2","verification.impl_b.policy_adapter")]:
    evaluator=importlib.import_module(module).evaluate
    phase(label,lambda:independent_call(evaluator,bundle.instance,bundle.trace,req,session))
   for label,config in VARIANTS.items():
    driver.store.guard_config=GuardConfig(**config);phase(label,lambda:driver.probe(req))
   phase("runtime_repeat",lambda:driver.probe(req))
  finally:driver.close()
 (out/"counters.json").write_text(json.dumps(counters,indent=2));print(json.dumps({"done":True,"out":str(out)}),flush=True)
if __name__=="__main__":run(sys.argv[1])
