"""DRAFT amendment-gated combined adapter; never bypasses frozen recovery."""
from pathlib import Path
import argparse,hashlib,json,platform,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
 if "--accelerated" not in sys.argv:raise SystemExit("Combined adapter requires --accelerated")
 lock_path=ROOT/"prereg/wp6_amendments/009_compiled_integration.sha256.json"
 if not lock_path.exists():raise SystemExit("Combined integration amendment is not frozen")
 lock=json.loads(lock_path.read_text(encoding="utf8"))
 if lock.get("status")!="frozen":raise SystemExit("Combined integration amendment is not frozen")
 for name,expected in lock["code_hashes"].items():
  if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:raise SystemExit("Combined dependency changed: "+name)
 parser=argparse.ArgumentParser(add_help=False);parser.add_argument("--run-dir",type=Path,required=True);args,_=parser.parse_known_args()
 from experiments import detection_matrix_accelerated,recover_mutation_run
 from experiments.detection_matrix import write_new
 from experiments.detection_matrix_compiled_accelerated import compiled_accelerated_worker
 from experiments.recover_mutation_contract_accelerated import report_only_overlay
 write_new(args.run_dir.with_name(args.run_dir.name+"_compiled_protocol.json"),{"amendment":lock,"python":sys.version,"platform":platform.platform(),"worker":"experiments.detection_matrix_compiled_accelerated.compiled_accelerated_worker","semantics":"Original all-pairs evaluate_one and byte-verifying recovery, with static contract reuse and separately reviewed compiled I2 API; every fresh normal/stale request still evaluated."})
 original=detection_matrix_accelerated.accelerated_worker;detection_matrix_accelerated.accelerated_worker=compiled_accelerated_worker
 try:
  with report_only_overlay(recover_mutation_run,lock):return recover_mutation_run.main()
 finally:detection_matrix_accelerated.accelerated_worker=original
if __name__=="__main__":raise SystemExit(main())
