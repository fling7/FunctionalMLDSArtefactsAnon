## Addendum B — DONE

Recomputed the six retained completed shards only: 7000 rows, 4750 distinct model hashes, 5578 distinct configurations. The incomplete shard remains excluded; no top-up or new experiment.

The retained rows contain 10164 default-mode request probes: 2447 admitted and 7717 rejected. Rejection is an expected tested outcome, not a violation. Additionally, 2447 drop_log injected-proposal probes and 2447 commit success/drift pairs are evidenced by the pinned harness, per-shard counters and terminal pass rows. Setup refusals: 0; counterexample rows: 0. Across the 20 explicitly separated property assertions, 59480 assertion observations pass and 0 violate. Assertion counts overlap and must not be presented as independent models.

T13 gives per-assertion observations, passes, violations, setup refusals and distinct models. T13b gives per-guard-mode coverage. Default is {"active_agent_mode": "client", "commit_variant": "full", "digest_check": true, "generation_precheck": false, "proposal_mode": "packet", "publication_protocol": "packet", "routing_mode": "runtime"}. Other modes are explicitly NOT_TESTED_IN_THIS_CAMPAIGN, not assigned a pass. A terminal pass plus hash-pinned historical control flow establishes assertions whose operands were not fully serialized; the table distinguishes these from direct retained-field comparisons. No stronger claim of independent assertion re-execution is made.

All numeric old/new comparisons and input hashes are retained in the property addendum log/proof. No API calls, backend execution or network activity.
