"""DRAFT combined performance worker; original evaluate_one remains intact."""
from pathlib import Path

def compiled_accelerated_worker(job):
 from experiments import detection_matrix as matrix
 from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
 from experiments.static_policy_compilation import static_policy_compilation
 with static_contract_memoization_v3() as contract:
  with static_policy_compilation(matrix) as policy:
   outcome=matrix.evaluate_one(job)
 output=Path(job["output"])
 matrix.write_new(output.parent.parent/"performance_compiled_memoization"/(output.stem+".json"),{"model":job["metadata"]["id"],"scope":"Static WP6 only; no publication/concurrency/WP8 evidence","contract":contract,"policy":policy})
 return outcome
