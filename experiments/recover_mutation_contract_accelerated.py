"""DRAFT amendment-gated adapter around the frozen verified-recovery runner."""
from pathlib import Path
from contextlib import contextmanager
import json,hashlib,sys,platform,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

@contextmanager
def report_only_overlay(recovery,lock):
 """One root-reviewed exact old/new report hash; no evaluator exception."""
 overlay=lock.get("report_only_overlay")
 if overlay is None:
  yield;return
 name="experiments/analyze_wp7.py"
 if overlay.get("path")!=name:raise ValueError("Unrecognized report-only overlay path")
 if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=overlay["current_sha256"]:raise ValueError("Report-only overlay current hash changed")
 original=recovery.check_dependencies;exclusions=recovery.NON_EVALUATION_FILES
 def checked(paths):
  for path in paths:
   inventory=json.loads(Path(path).read_text(encoding="utf8"))
   prior=inventory.get("sha256",{}).get(name)
   if prior is not None and prior!=overlay["original_sha256"]:raise ValueError("Report-only overlay original hash differs")
  recovery.NON_EVALUATION_FILES=set(exclusions)|{name}
  try:return original(paths)
  finally:recovery.NON_EVALUATION_FILES=exclusions
 recovery.check_dependencies=checked
 try:yield
 finally:
  recovery.check_dependencies=original;recovery.NON_EVALUATION_FILES=exclusions

def main():
 if "--accelerated" not in sys.argv:raise SystemExit("This adapter requires --accelerated; it never silently changes the original profile")
 lock_path=ROOT/"prereg/wp6_amendments/007_contract_memoization.sha256.json"
 if not lock_path.exists():raise SystemExit("Contract-cache amendment is not frozen; no recovery launched")
 lock=json.loads(lock_path.read_text(encoding="utf8"))
 if lock.get("status")!="frozen":raise SystemExit("Contract-cache amendment is not frozen")
 for name,expected in lock["code_hashes"].items():
  if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:raise SystemExit("Contract-cache dependency changed: "+name)
 parser=argparse.ArgumentParser(add_help=False);parser.add_argument("--run-dir",type=Path,required=True)
 args,_=parser.parse_known_args()
 from experiments.detection_matrix import write_new
 write_new(args.run_dir.with_name(args.run_dir.name+"_contract_memo_protocol.json"),{"amendment":lock,"python":sys.version,"platform":platform.platform(),"worker":"experiments.detection_matrix_contract_accelerated.contract_accelerated_worker","semantics":"Original registered all-pairs evaluator and original byte-verifying recovery, with scoped static contract construction reuse; no timing/publication claims."})
 from experiments import detection_matrix_accelerated,recover_mutation_run
 from experiments.detection_matrix_contract_accelerated import contract_accelerated_worker
 original=detection_matrix_accelerated.accelerated_worker
 detection_matrix_accelerated.accelerated_worker=contract_accelerated_worker
 try:
  with report_only_overlay(recover_mutation_run,lock):return recover_mutation_run.main()
 finally:detection_matrix_accelerated.accelerated_worker=original
if __name__=="__main__":raise SystemExit(main())
