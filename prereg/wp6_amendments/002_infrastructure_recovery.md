# WP6 amendment: infrastructure recovery after process loss

Scope: continue the two interrupted registered batches without changing operators, seeds, eligibility, probes, validators, variants, ground truth or aggregation. The original frozen evaluator remains authoritative. This is recovery of missing work, not a new statistical replicate or an added room. The interruption record is `results/raw/wp6_interruption_20261015.json`.

Both prior tool sessions became unknown and no WP6 Python process remained when inspected at 2026-10-15T13:34:20 UTC. The classroom attempt retained 20 completed outcomes and its 153-model manifest; the generated attempt retained 434 model directories but no manifest or outcomes. Neither recorded worker failures. The process termination cause is unconfirmed; no scientific failure or success is inferred from it.

## Preservation and verification

Use a new versioned recovery directory for each original run. Never alter, overwrite, delete, aggregate or archive the interrupted original directories as part of recovery. Regenerate the exact model plans through the frozen mutation functions, retain all statuses, and materialize fresh copies through the frozen materializer. Compare all model-file SHA-256 values with each original copy. Any differing, missing or extra original files are explicitly recorded. An incomplete model with no completed outcome is regenerated in the new directory; its old bytes remain untouched.

Reuse a completed outcome only when its original model files exactly match deterministic regeneration, its metadata and model digest match, and it contains the exact ordered all-agent/object pair list, every registered routing variant and every stale-request variant. Copy the raw outcome byte-for-byte and record both paths and its SHA-256. These copied rows are the same observations and must not be double-counted with their original attempt. Reject unrecognized original outcomes, original manifest disagreement, prior worker failures awaiting adjudication, existing recovery destinations, changed frozen code or changed evaluation dependencies.

After preparation, schedule only missing outcomes through the original `evaluate_one`; generated work uses the already frozen acceleration wrapper and scoped memoization. The classroom retains the original non-memoized evaluator. The original aggregate function combines the preserved observations and newly completed missing observations. All fresh failures are retained. A final coverage claim requires every planned evaluation and zero unresolved worker failures.

## Dependency checks and lifecycle

Check the original preregistration lock, performance amendment lock where applicable, and this recovery lock before execution. Audit the launch dependency inventory. Its broad scope contains seven files unrelated to WP6 evaluation: WP4 analysis, guarded turns, common utilities, preregistration, routing baselines and token preflight, plus WP6 report generation. Changes to those exact named files may be recorded without rejection; no evaluator/backend/schema/model/helper exception is allowed. The wrapper never imports those excluded files. Keep original dependency inventories and record actual current hashes.

Use the same frozen four-project generated source selection as the original attempt. Save a current WP5 source manifest separately for future batches; priorities above 20 are provisional while earlier-source counterparts remain pending. Use 4 classroom and at most 8 generated workers. Keep the owning agent active while tool-managed child jobs run, using bounded polls. Do not pool accelerated or recovery wall-clock values into WP8 timing. No publication, concurrency, HTTP commit or real-LLM evidence is added by this recovery.

## Required engineering checks before execution

Test byte-preserving completed outcome reuse; dispatch only missing jobs to the frozen worker; mismatched model files, metadata, digest, pair order/count, routing variants and stale variants; interrupted model regeneration without altering originals; missing/conflicting manifests; existing destination refusal; and evaluation dependency changes. Retain test results and exact hashes before root freeze. No finite fixture suite is represented as a proof over all inputs.
