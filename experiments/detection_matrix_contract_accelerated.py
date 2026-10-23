"""DRAFT worker adapter: frozen all-pairs evaluator in a static cache scope."""
from pathlib import Path

def contract_accelerated_worker(job):
 from experiments.detection_matrix import evaluate_one,write_new
 from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
 with static_contract_memoization_v3() as stats:
  outcome=evaluate_one(job)
 output=Path(job["output"])
 write_new(output.parent.parent/"performance_contract_memoization"/(output.stem+".json"),{"model":job["metadata"]["id"],"scope":"static WP6 only; no publication/concurrency/WP8 evidence","memoization":stats})
 return outcome
