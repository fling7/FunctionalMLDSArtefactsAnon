# Preregistration v1

Frozen before WP4-WP7 evaluation. Offline baseline regression and independent implementation unit tests preceded this freeze and are development evidence, not evaluation.

RQ1: Does publish-time verification agree with runtime model-only routing, and which request-bound checks remain? Unit: room and mutant. Primary outcome: differing decisions/providers/actions. Reason disagreement is separate.

RQ2: What disagreements arise between separately implemented admission semantics and the backend? Unit: model; probe counts are secondary. Preserve all disagreements and author amendments. Do not treat deterministic agreement as validation of the specification.

RQ3: How often do real-model routing baselines deviate from a declared room model, and what faults arise during authoring and regeneration? Unit: room, with room-clustered intervals. Deviation from the model does not imply disagreement with visitor intent. B0 and B1, each with/without abstention and three frozen prompt phrasings, compare with derived B2. Primary metrics are wrong-provider and silent-violation rates; invalid responses and API failures remain explicit outcomes. At least two API-verified models are sought, gpt-4.1-mini and gpt-4.1 snapshots; no availability is inferred from documentation.

RQ4: Under which publication and concurrency assumptions does commit preserve the admitted contract, and at what availability cost? Unit: edit and workload configuration. See the separately hashed WP7_PLAN.md for fixed offline designs. Its first counterexamples and every failed fault cell must be reported.

Hypotheses: H1, table and recomputation agree on model-only conditions for valid executable models. H2, independent code may expose conformance or specification problems; exploratory, no target agreement percentage. H3, B1 has fewer declared-model violations than B0; paired room analysis. H4, shared cooperative publication/commit locking removes the modeled check/append race under the stated assumptions; direct edits retain a residual window. No claim about answer correctness, deployment frequency, or user experience is tested.

Budget and reduction rules are in BUDGET.md. API errors after the fixed retry policy are API_ERROR; they are included in attempted totals and reported separately. Never silently replace failed runs or exclude hard rooms. Development uses at most three rooms identified before generation. No prompt/threshold/operator changes based on evaluation data.

Statistics: Wilson 95% intervals for binomial per-room/model outcomes; fixed-seed 10,000-resample room cluster bootstrap for pooled rates; exact McNemar or paired bootstrap for paired comparisons. No statistical population inference from deterministic mutation counts or exhaustive schedules. Seeds default to 20261015 and are recorded with each raw run.

This is a staged preregistration: WP7 offline is authorized by its frozen supplement. WP4, WP5, and WP6 remain pending until append-only amendments freeze their exact prompt hashes, sample allocation, operator list, and analysis-source hashes. These missing components must be fixed and committed before their first evaluation run. Every new or changed evaluation script records a pre-run source manifest; amendments must disclose changes after first observation. Never modify this file after freeze.
