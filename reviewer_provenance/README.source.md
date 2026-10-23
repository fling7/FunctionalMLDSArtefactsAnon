# Room routing research artifact

This artifact studies model-relative routing admission and publication consistency. It contains two separately authored evaluators, a backend implementation, retained experimental data and offline reporting code. Several experimental and release requirements remain incomplete; this is an honest research snapshot.

Requirements: Python 3.11 or 3.12 and packages in repro/requirements.lock. Install dependencies before going offline.

```text
python -m pip install -r repro/requirements.lock
python repro/run_all.py --replay
python -m pytest -q tests
python verification/differential.py --run-id anonymous_check
```

The replay reads data/go_sprint, checks every input hash and generates results/replay/go_sprint/numbers.json, T1ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“T12 CSV tables and F3ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“F8 PDF/SVG figures. It validates current cached request/response hashes, recomputes routing outcomes and links successful HTTP receipts before rebuilding the report. It performs no network calls and does not regenerate missing experiments. data/llm_cache holds retained request/response cache entries; repro/verify_replay_cache.py verifies cache integrity separately. Dependency installation requires network access; reporting does not.

| Directory | Purpose |
|---|---|
| app/backend_root/agent_backend | Backend |
| tools | Native model validation and routing table |
| verification | Separate reference and policy evaluators |
| tests | Regression tests |
| data/go_sprint | Hash-pinned descriptive reporting inputs |
| data/llm_cache | Retained model-call cache |
| repro | Offline reproduction tools |

| Claim IDs | Script | Output / limitation |
|---|---|---|
| C01, C02 | verification/differential.py; repro/run_all.py --replay | T9; shared specification limits independence |
| C03 | python -m pytest tests/test_digest.py | CRLF/LF digest test report |
| C04, C05, C07 | repro/run_all.py --replay | Unsupported superiority, prevalence and complete anonymous replay claims withdrawn |
| C06 | repro/run_all.py --replay | T6 cooperative protocol evidence |
| C08 | repro/run_all.py --replay | Retained first-match counterexample; property summaries |
| C09 | repro/run_all.py --replay | T4, T5 complete scheduled mutation cohorts |
| C10 | repro/run_all.py --replay | T1, T3 native fault and audit outcomes |
| C11, C12 | repro/run_all.py --replay | T2 routing; retained source-cluster drift analysis |
| C13, C14 | repro/run_all.py --replay | T7, T12 regeneration and evolution |

Limits: enforcement is relative to a published model, not visitor intent, answer correctness or semantic appropriateness. The evaluators share a specification and coding-model family. The scheduled mutation cohort is complete:908 generated mutants and153 classroom mutants, reported separately. Of the generated cohort,710 backend setups succeed and198 are refused with retained reasons. Historical default-backend disagreements are retained; a successful harness run does not mean zero disagreements. Publication-readiness and clean-platform execution are not asserted unless backed by the final verification report.

Code license: MIT, Anonymous Authors. Dependencies keep their own licenses.

Current exported calls are in data/llm_cache_sprint; historical repinned cache remains in data/llm_cache. Exact offline cache replay passes480/480 primary and270/270 reject-study calls. The initial72-record discrepancy was a Windows text-decoding bug in the audit script, corrected using explicit UTF8; original cache files were unchanged and strict hash checks retained. Default report replay integrates strict cache and outcome checks with retained-summary regeneration. Missing experiments remain missing.

Test isolation: the included pytest.ini anchors imports to this artifact. All 1,726 test assertions were exercised; one missing retained fixture was repaired and its related 11 tests pass. The Python 3.12.8 host emits process-spawn access-violation diagnostics despite successful assertions and zero exit status. The stdlib-only repro/runtime_spawn_control.py reproduces these diagnostics independently of artifact code, with all results correct; the same control and gateway concurrency test pass cleanly on Python 3.13.2. This is not a clean full-platform certification for either Python version.

repro/differential_full.py executes the original independent evaluators on every request and reuses only pure backend model construction and fingerprint work. The older differential_static.py additionally compiles the policy and checks encountered outcome classes against the original evaluator; it is not exhaustive equivalence proof. Execution verification is recorded in docs/VERIFICATION.json. The fresh full harness reproduced all 2448 historical verdicts, including 720 known default-backend disagreements, with no I1/I2 disagreement. Run both `python repro/differential_full.py --run-id local_main` and `python repro/differential_full.py --extended-only --run-id local_extended` for all 17 request variants.
