# WP1, WP2 and WP3 data handoff

This package contains actual retained JSON/JSONL data and CSV tables, not only links. No evaluator, test suite or model API was run to create it. Original copied files are byte-identical; `SOURCE_MANIFEST.json` records their source paths and SHA-256 hashes. Derived tables are labelled separately. This is original research data, **not an anonymized publication release or a complete executable artifact**.

Start with `CURRENT_SUMMARY.json`. CSV files use UTF-8, a header row and one-based `source_line` values. Original JSONL rows retain nested requests, generated specifications and verdicts.

## WP1 — metamodel and traceability

`wp1/metamodel_delta.json` and `.csv` compare canonical declarations: 118 classes, 2 datatypes, 157 associations and 8 views remain unchanged; numbered invariants increase from 74 to 81. `invariant_traceability.csv` contains all 81 invariant rows. The ledger records 7 enforced, 72 not enforced, 1 warning and 1 report. Declaration counts do not establish enforcement. “Not enforced” means the ledger lacks a complete check-and-negative-fixture audit; it does not assert that no related code check exists. Report-adapter adoption proof is included with its narrow original scope.

## WP2 — completed and interrupted evidence are separate

`wp2/completed/` contains all six terminal shard summaries, original source-hash records and **all 7,000 original observation rows**. `completed_summary.json`, `completed_observations.csv`, `completed_shards.csv` and `distinct_models.csv` are fresh aggregations of these retained rows. The primary unit is a distinct generated native model hash: **4,750 models**, not 7,000 independent models. There are **5,578 distinct configuration hashes**. The 5,000-model target is **unmet**. Within-shard distinct counts overlap and must not be added.

Completed row statuses: {'pass': 7000}. Retained request decisions: {'ANSWER_LOCAL': 2192, 'REJECT': 7717, 'ANSWER_AFTER_HANDOFF': 255}. These generated cases use scripted model responses; they are not sampled natural rooms or real-LLM evaluations.

`wp2/interrupted_shard6/` contains the separate **124/500-observation prefix**, seed 20261026, its original interruption record and a zero-byte trailing fragment. It has no terminal summary and is excluded from every completed denominator. Including the prefix would describe 4,826 observed model hashes, which is still below target and is not a completed campaign. The registered no-repeat-seed rule remains in force. The synthetic first-match counterexample is included separately as one mechanism example, not prevalence evidence.

## WP3 — original disagreements and isolated opt-in results

`wp3/differential/` includes both complete original datasets and all **2,448 dependent probes from one authored room**. The per-dataset `disagreements.jsonl` records refer to a subset of the same probes (`probe` joins to `probes.jsonl` field `id`); do not add them as extra observations. Their original `pending adjudication` labels are preserved. The later completed classifications are in `summary.json` and `disagreement_categories.csv`. The default backend differs on **720 probes**: 468 decision differences and 252 reason-only differences. I1 and I2 have no retained disagreement. The six documented input categories and SPEC/A001 context are included; 432 probes are historically classified as backend bugs and 288 as specification ambiguities. These categories are not six independent populations.

`wp3/isolated_opt_in/` contains all **4,896 replay observations**, 2,448 per mode. `packet` matches historical I0 and therefore preserves all 720 specification disagreements. `spec_a001_candidate` matches the retained I1/I2 verdicts. A row's `pass` means agreement with its mode-specific expected result; it does **not** mean the default is SPEC-conformant. Join replay CSV rows to `differential/<dataset>/probes.jsonl` using `differential_dataset` and `differential_source_line`. The isolated prototype did not change the live backend or independent evaluators and does not establish arbitrary-schema/global equivalence.

## Selection and limitations

`OMISSIONS.json` identifies omitted source files and hashes, including the stale historical 3,300-model property summary and redundant materialized replay cases. No historical result was overwritten. Executable source trees, environments, figures and other work packages are omitted. Original records may contain historical project identifiers and local provenance paths; no anonymity claim is made. The source paths in original records refer to the original workspace; copied package locations are mapped in `SOURCE_MANIFEST.json`.

`SHA256SUMS` covers every packaged file except itself. The manifest distinguishes byte-for-byte original copies from derived extraction/counting outputs. All source files were checked again at package close to detect concurrent changes.
