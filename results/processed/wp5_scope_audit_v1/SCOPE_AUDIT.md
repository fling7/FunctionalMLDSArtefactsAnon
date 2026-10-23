# WP5 closed source/model scope

Fixed source identity by model snapshot; pipeline terminal identities include failures and are not equivalent to successful projects or paid responses.

Only the fixed original development/evaluation and initial-extension terminal cohorts are counted as observed pipeline identities. Guided source writing is complete, while its downstream pipeline remains a proposal. Ongoing drift is represented only by its preexisting frozen schedule.

| Source family | Sources | Required model pairs | Closed pipeline pairs | Successful native pairs | Missing closed pairs | Still uncovered after registered/proposed work |
|---|---:|---:|---:|---:|---:|---:|
| extension_deterministic | 12 | 24 | 12 | 9 | 12 | 0 |
| extension_llm | 2 | 4 | 2 | 1 | 2 | 2 |
| guided_llm_source_v2 | 12 | 24 | 0 | 0 | 24 | 12 |
| original_dev | 3 | 6 | 3 | 0 | 3 | 3 |
| original_evaluation | 45 | 90 | 50 | 20 | 40 | 40 |

No live drift outputs are read. Registered drift and proposed guided rows are prospective only; they are never credited as completed. Development sources remain separate. Repeated regenerations and targeted repairs cannot substitute for a missing source/model pair. This audit does not authorize new calls or budget changes.

Every pair and its exact evidence paths are listed in source_model_coverage.csv. Hashes for the closed inputs are in scope_summary.json. Archived-call-attempt counts are diagnostic; they do not certify returned model responses or cost.
