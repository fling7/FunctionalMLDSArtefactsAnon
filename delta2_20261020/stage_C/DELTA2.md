# DELTA 2 - Stage C

1. No new model answers were generated. All 450 planned C1 observations remain scientifically NOT DONE. There is no evidence here that B1s improves rejection or that the two additional models perform better.
2. The existing authoritative ledger has an expired GO-sprint deadline (2026-10-19T11:47:57Z). It rejected new reservations. The deadline, allocations, ledger cap and gateway were preserved; no replacement ledger or bypass was used.
3. The original study has 45 distinct items per model/arm: 20 controls and 25 fault items. Its 40 controls per arm are pooled across two models. The 16 injected room variants share eight base sources. Reusing the exact retained items prevents denominator inflation.
4. A frozen 450-request plan and a disjoint classroom abstention example are included. The worked example was checked offline by Gate 0, I1 and I2. Preparation is not experimental evidence.
5. Access discovery returned gpt-6-astra and gpt-6-luna. Their model selection, published rates, default-temperature policy and 2048-token output caps were recorded before generation was attempted. Access listing alone does not prove successful inference access.

## Execution and failure accounting

There was one model-list request and 67 non-generation input-token-count requests, all with zero accounted cost. There are 66 complete raw refusal records and one token-count event interrupted before a row was written. Zero generation reservations and zero new model responses were obtained; ledger accounted spend did not increase. The 384 planned slots without raw rows and all 66 refused slots are unevaluated scientifically.

The generic runner recorded the SQLite IntegrityError as TECHNICAL_POSTPROCESS_ERROR. This is a handler-label defect: the retained exact message establishes that reservation failed before generation. Raw records are preserved. The report derives pre-generation refusal classification from that exact exception/message and the empty response-attempt list; it does not rewrite evidence or score a refusal as a model abstention. deadline_refusal_proof.json contains the ledger trigger and evidence hashes. No retry was made after the runner was stopped. Token counting happened before reservation in the existing gateway, explaining why 67 zero-cost discovery/count events exist despite the deadline. Initial model discovery adds one further event.

C1 status: NOT DONE due to authoritative deadline. C2: NOT DONE because C1 did not complete. D: NOT DONE (optional; not a substitute). Total extra accounted API spend: USD 0.0000000. No actual-generation invoice estimate is needed because there were no generation calls.

## Tables and uncertainty

report_v1/C1_outcomes_wilson_cluster.csv reports planned, retained, unsuccessful and missing counts for each arm/model and separates historical observations. Only the original 270 responses support performance estimates. New-model and B1s rates and confidence intervals are undefined, not zero performance or perfect rejection. Paired B1s comparisons are NOT DONE because there are no common successful pairs. Historical Wilson and room-cluster summaries use 10,000 resamples, seed 20261015; they are not a fresh replication. Raw technical labels and derived pre-generation counts are both documented.

## Frozen protocol and reproduction

The pre-call original design SHA256 is 6e94a329c0a74d49de11baf3541ba32800a9dbefd24a5fa8b6bbe64441901cf7. The original raw requests, context, runner and price hashes are pinned. New-model accounting conservatively uses 1.25 times standard uncached input rates to cover cache-write fees which the immutable gateway does not distinguish; no such generation charges occurred. Old-model rates remain unchanged. New-model caps allow space for default reasoning; capped incomplete outputs would have remained explicit outcomes, with no adaptive retry.

Official sources retrieved 2026-10-20: https://developers.openai.com/api/docs/models/gpt-6-astra ; https://developers.openai.com/api/docs/models/gpt-6-luna ; https://developers.openai.com/api/docs/guides/latest-model ; https://developers.openai.com/api/docs/pricing . Model pages give standard rates; discounted pricing entries must not be mistaken for standard billing.

The export is an anonymized derivative. Exported execution pins are recomputed solely for offline replay and are explicitly not a new preregistration. Historic source proof hashes retain their original meaning. Original and exported offline replay proofs cover zero response caches and therefore do not prove model reproducibility. MANIFEST.sha256 verifies delivered file bytes. All previous releases, data, claims and gates remain unchanged.

Scripts: drafts/delta2_20261020/agent_c_stageC/prepare_stage_c_draft.py, preflight_stage_c.py, stage_c_runner.py, finalize_blocked_c.py and stage_c_report.py. New number provenance is in numbers_c_execution.json and report_v1/comparisons_C1.json.
