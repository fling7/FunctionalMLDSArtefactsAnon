# Current budget policy and phase readiness

This reader-facing note describes the already enacted allocation amendment. It does not replace the frozen initial [BUDGET.md](BUDGET.md), authorize another transfer, or authorize an experiment. The initial document remains byte-identical (SHA256 `4bf6e4f855234e31dd5a4dd7575259a457fa2bfec9fe5708519360fae5bb93c8`). Its WP5 stop of USD 5.40 describes the initial allocation.

The authority for the current allocation is [amendment 001](budget_amendments/001_unused_wp7_to_wp5.json), SHA256 `501218c00264d2fc9fa7f443a06ec07f44d927ede8a33d7f2b24e0688232c7c3`. The audited migration event occurred at **2026-10-15 17:16:27.540900 UTC**. Its [completed proof](../results/raw/budget_migration_001/proof.json), SHA256 `bd6a49de2d1467fa058aeba914f892b35c9a8d0d7000e5c06574ab9b7c1094e2`, preserves all 127 reservations, 127 claims and 383 earlier events, appends exactly one policy event, and leaves the accounted total at that cutover unchanged. The before/after databases and ordered audits remain in the same evidence directory. Do not rerun the migration.

| Share | Allocation | Enforced 90% stop (USD) |
| --- | ---: | ---: |
| WP4 routing and HTTP | 35% | 6.30 |
| WP5 generation | 40% | 7.20 |
| Optional real-model WP7 | 0% | 0.00 |
| Judges and question generation | 10% | 1.80 |
| Reserve | 15% | 2.70 |

The global hard cap remains **USD 20**. Only the unused optional WP7 allocation moved to WP5. No reserve or other share transfer is implied. The SQLite policy is authoritative on every reservation, including stale-client inserts. Pending reservations count at their reserved maxima; unknown outcomes remain conservatively charged. Neither category may be silently released to make another phase fit.

## WP4 questions and later phases

The closed corpus has 20 evaluation rooms plus the separate authored example. Its frozen unique-object union contains 277 question targets (264 evaluation and 13 example). One call requests two questions per object, so the planned maximum is 554 question texts. Fifteen distinct admitted agent/object pairs per evaluation room provide 600 planned core HTTP slots across the two models; this is not a guarantee of valid generations.

- Questions: 277 first attempts have a **USD 0.7782592** ceiling, charged to **judges**, whose stop is USD 1.80. The all-five-transport-attempt ceiling is USD 3.891296 and does not fit that share; the gateway stops before an unaffordable reservation. Failed, oversized and invalid responses remain data without regeneration or fabricated replacements.
- WP4 core routing, example and HTTP calls have a separate **USD 5.3312832** first-attempt ceiling charged to **WP4**, whose stop is USD 6.30. Question generation does not consume this allocation.
- [Questions-only authorization](../results/raw/wp4_questions_root_authorization_v1.json) covers the frozen command and fresh output `results/raw/wp4_questions_parallel_v1`. It explicitly withholds routing and HTTP authorization. Questions must become terminal and be hash-frozen before that separate review.

The [readiness record](../results/raw/wp4_questions_readiness_v1.json) separates share balances, pending reservations, charged unknown outcomes and the active global total. It is a diagnostic snapshot while WP5 drift continues, not a quiescent accounting closure. The ledger guards remain controlling during concurrent work.

The [questions-only terminal audit](../results/raw/wp4_questions_terminal_v1.json) subsequently closed all277 fixed object identities with277 successful responses and554 texts passing the preregistered format, distinctness and object-name/reference checks. The277 charged reservations reconcile to **USD0.057150800**, charged to judges. No response was regenerated. The frozen questions SHA256 is `ac4114c11c9f8d3dca2f10a7bcc80d219e5221b9fb7db8fffd1baf9235ecf407`. This is a question-generation outcome; routing and HTTP remain subject to their separate authorization and do not inherit a valid-generation guarantee.

## WP5 phases still requiring settled review

The registered 120 drift attempts continue in their fixed order. At their terminal boundary, hold the next paid WP5 phase for a settled accounting capture and review. Guided downstream generation and the 57-slot completion proposal have no execution authorization from this note.

| Proposed cohort | First-attempt ceiling (USD) | All stage and transport attempts ceiling (USD) | Updated reference forecast (USD) |
| --- | ---: | ---: | ---: |
| Fixed 12 guided-source mini pipelines | 0.217440000 | 2.174400000 | 0.103724667 |
| Fixed 57 completion pipelines | 5.187920000 | 51.879200000 | 1.967875509 |

The [interim outlook](../results/raw/wp5_budget_outlook_v2.json) pins the first three complete balanced drift rounds (72 terminal rows, all successes and failures retained) used for the updated small-scene means. It preserves the earlier forecasts and unchanged ceilings. The projected total across all proposed WP5 phases is USD 7.612154676, above the USD 7.20 stop. These means are not bounds, do not guarantee successful native rooms, and do not establish affordability. Original source-size-mixed costs, new authored scenes, stage repairs, retries and unknown outcomes can differ. Keep the fixed completion order (40 original evaluation pairs, 14 LLM full-model counterparts, then 3 development counterparts) and retain every failed or unexecuted identity; any execution decision requires the later settled review.
