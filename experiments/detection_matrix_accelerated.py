"""Amendment-gated acceleration launcher; never edits frozen v1 evaluation.

The worker executes the original evaluator inside a process-local memoization
scope. Request loops, variants, validators, mutation selection and aggregation
remain those of the original registered harness.
"""
from __future__ import annotations
import hashlib,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def accelerated_worker(job):
 from experiments.detection_matrix import evaluate_one,write_new
 from experiments.static_model_memoization import static_model_memoization
 with static_model_memoization() as counters:
  outcome=evaluate_one(job)
 output=Path(job['output'])
 write_new(output.parent.parent/'performance_memoization'/(output.stem+'.json'),{'model':job['metadata']['id'],'scope':'static WP6 model only; no publication/concurrency evidence','memoization':dict(counters)})
 return outcome


def main():
 from experiments import detection_matrix
 lock_path=ROOT/'prereg/wp6_amendments/001_performance_only.sha256.json'
 if not lock_path.exists():raise SystemExit('Performance amendment is not frozen; generated evaluation is disabled.')
 lock=json.loads(lock_path.read_text(encoding='utf-8'))
 if lock.get('status')!='frozen':raise SystemExit('Performance amendment is not frozen.')
 for path,expected in lock['code_hashes'].items():
  if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:raise SystemExit('Performance-amendment hash mismatch: '+path)
 try:run_dir=Path(sys.argv[sys.argv.index('--run-dir')+1])
 except (ValueError,IndexError):raise SystemExit('--run-dir is required')
 sidecar=run_dir.with_name(run_dir.name+'_performance_protocol.json')
 detection_matrix.write_new(sidecar,{'amendment':lock,'python':sys.version,'platform':platform.platform(),'semantics':'original v1 evaluator with scoped pure-lookup and successful trace-validation memoization'})
 detection_matrix.evaluate_one=accelerated_worker
 return detection_matrix.main()
if __name__=='__main__':raise SystemExit(main())
