"""Single fixed-case remaining-cost diagnostic; no research timing claim."""
from pathlib import Path
import cProfile,json,time,sys,pstats,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.mutations import Bundle,digest
from experiments.detection_matrix import request_for,write_new
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
from experiments.lib.backend_driver import Driver

def main(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=False)
 directory=ROOT/"results/raw/wp6_generated_recovery_v1";manifest=json.loads((directory/"mutation_manifest.json").read_text())
 meta=next(m for m in manifest["models"] if m["operators"]==["drop_handoff"] and m["status"]=="changed")
 project=directory/"models"/meta["storage_id"]/meta["room"];bundle=Bundle.load(project)
 write_new(out/"provenance.json",{"model":meta,"project":str(project),"timer":"Explicit cProfile timer=time.process_time; process-CPU profiling with instrumentation overhead.","engineering_only":True,"sources":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [project/"roomcontract.v2.instance.json",project/"trace_map.v2.json",Path(__file__),ROOT/"experiments/static_contract_memoization_v3.py"]}})
 with static_contract_memoization_v3() as counters:
  driver=Driver(project)
  try:
   target=driver.targets[0];agent=next(o["sourceAgentId"] for o in bundle.instance["objects"] if o.get("type")=="Agent");request=request_for(agent,target,digest(bundle.instance))
   profile=cProfile.Profile(timer=time.process_time);profile.enable();result=driver.probe(request);profile.disable()
   rows=[{"file":key[0],"line":key[1],"function":key[2],"primitive_calls":v[0],"calls":v[1],"self_process_cpu_seconds":v[2],"cumulative_process_cpu_seconds":v[3]} for key,v in pstats.Stats(profile).stats.items()]
   write_new(out/"profile.json",sorted(rows,key=lambda r:-r["cumulative_process_cpu_seconds"])[:70]);write_new(out/"engineering_probe.json",result)
  finally:driver.close()
 write_new(out/"memo_counters.json",counters);print(json.dumps({"complete":True,"out":str(out)}))
if __name__=="__main__":main(sys.argv[1])
