"""Fixed large-model engineering loop; not population/WP8 latency evidence."""
from pathlib import Path
import hashlib,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments import detection_matrix as matrix
from experiments.mutations import Bundle,digest
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
from experiments.static_policy_compilation import static_policy_compilation
from experiments.lib.backend_driver import Driver
from backend.guard_config import GuardConfig

def main(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=False)
 directory=ROOT/"results/raw/wp6_generated_recovery_v1";manifest=json.loads((directory/"mutation_manifest.json").read_text())
 meta=next(m for m in manifest["models"] if m["operators"]==["drop_handoff"] and m["status"]=="changed")
 project=directory/"models"/meta["storage_id"]/meta["room"];bundle=Bundle.load(project);records=[];outcomes={}
 files=[Path(__file__),ROOT/"experiments/static_contract_memoization_v3.py",ROOT/"experiments/static_policy_compilation.py",ROOT/"verification/impl_b/compiled_policy.py",ROOT/"verification/impl_b/policy_adapter.py",ROOT/"verification/impl_b/admission.lp",project/"roomcontract.v2.instance.json",project/"trace_map.v2.json"]
 matrix.write_new(out/"provenance.json",{"engineering_only":True,"model":meta,"source_hashes":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},"scope":"Fixed80-object first drop-handoff model and first agent/target. Original versus compiled normal/stale values asserted equal. Timing under changing contention; compile and warm query costs separated, no corpus/performance claim."})
 def phase(name,fn):
  wall=time.perf_counter();cpu=time.process_time();result=fn()
  row={"phase":name,"wall_seconds":time.perf_counter()-wall,"cpu_seconds":time.process_time()-cpu};records.append(row);print(json.dumps(row),flush=True)
  (out/"progress.json").write_text(json.dumps(records,indent=2));return result
 reference=matrix.importlib.import_module("verification.impl_b.policy_adapter").evaluate
 with static_contract_memoization_v3() as contract:
  with static_policy_compilation(matrix) as policy:
   driver=phase("setup",lambda:Driver(project))
   try:
    target=driver.targets[0];agent=next(o["sourceAgentId"] for o in bundle.instance["objects"] if o.get("type")=="Agent");request=matrix.request_for(agent,target,digest(bundle.instance));session={"model_sha256":digest(bundle.instance),"active_agent_mode":"client"}
    compiled=matrix.importlib.import_module("verification.impl_b.policy_adapter").evaluate
    outcomes["I2_original"]=phase("I2_original",lambda:reference(bundle.instance,bundle.trace,request,session))
    outcomes["I2_first"]=phase("I2_compile_plus_first",lambda:compiled(bundle.instance,bundle.trace,request,session))
    outcomes["I2_warm"]=phase("I2_warm",lambda:compiled(bundle.instance,bundle.trace,request,session))
    assert outcomes["I2_original"]==outcomes["I2_first"]==outcomes["I2_warm"]
    for label,config in matrix.VARIANTS.items():
     driver.store.guard_config=GuardConfig(**config);outcomes[label]=phase(label,lambda:driver.probe(request))
    stale=json.loads(json.dumps(request));stale["spatial_context"]["model_sha256"]="0"*64
    outcomes["I2_original_stale"]=phase("I2_original_stale",lambda:reference(bundle.instance,bundle.trace,stale,session))
    outcomes["I2_compiled_stale"]=phase("I2_compiled_stale",lambda:compiled(bundle.instance,bundle.trace,stale,session))
    assert outcomes["I2_original_stale"]==outcomes["I2_compiled_stale"]
    for label,config in [("runtime_stale",{}),("no_digest_stale",{"digest_check":False})]:
     driver.store.guard_config=GuardConfig(**config);outcomes[label]=phase(label,lambda:driver.probe(stale))
   finally:driver.close()
 matrix.write_new(out/"counters.json",{"contract":contract,"policy":policy});matrix.write_new(out/"engineering_outcomes.json",outcomes);print(json.dumps({"complete":True,"out":str(out)}))
if __name__=="__main__":main(sys.argv[1])
