# DELTA 2 - Stage B

## Five findings and qualifications

1. The new campaign covers 12 observed rooms out of 22 selected rooms, rather than reusing the six generated base cases of the original mutation cohort. Execution status: PARTIAL_TECHNICAL_OR_UNEXECUTED.
2. The non-oracle union has TP=49, FN=9, FP=0, TN=99 on determinate, eligible mutants. Misses and false positives are retained. Wilson and room-cluster intervals are reported alongside counts, not replaced by an unqualified success percentage.
3. There are 157 mutants with determinate ground truth among 374 planned operator slots. No-op, inapplicable, technical, unexecuted and oracle-disagreement cases are explicit; they are not silently counted as passes.
4. The subset was fixed before mutant execution: twenty-one native sources selected by source-origin and object-count strata, plus classroom. The full population is fifty-six native base sources plus classroom. This bounded sample does not establish prevalence across that population.
5. Backend setup and model/backend probes were deliberately excluded. The campaign measures offline checker detection, with agreement of Gate 0, I1 and compiled I2 as the truth requirement; it does not replace end-to-end backend validation.

At least twenty rooms actually started: **NOT MET** (12 started). This threshold alone does not establish complete scientific evaluation of all seventeen operators; technical failures remain unresolved.

## Method and reproduction

Stage B: new stratified cohort, separate from 908/153. Selection frozen before mutant outcomes. No backend setup, no backend/model probes; pure oracle queries only. I1, compiled I2 and Gate0 must agree for determinate ground truth. Technical errors, unknown truth, no-ops and inapplicable operators remain excluded with explicit counts. Results do not estimate prevalence across all 56 sources. Source-room bootstrap uses all selected rooms, including zero-eligible rooms, with 10000 resamples seed20261015; per-room scopes use their single room. Zero-denominator draws excluded and reported. Checker not-applicable rows excluded from that checker denominator. All planned slots retained, including exact retained TECHNICAL_TIMEOUT, TECHNICAL_FAILURE, BUDGET_STOP_NOT_EVALUATED, and never-started NOT_RUN statuses. Completion of execution is separate from determinate scientific ground truth. Single-room bootstrap intervals are degenerate and do not establish population certainty.
{
  "stageB_selected_rooms": 22,
  "stageB_observed_rooms": 12,
  "stageB_outcomes": 189,
  "stageB_planned_slots": 374,
  "stageB_groundtruth_eligible": 157,
  "stageB_status_counts": {
    "NOT_APPLICABLE": 12,
    "EVALUATED": 157,
    "TECHNICAL_TIMEOUT": 18,
    "TECHNICAL_INTERRUPTED": 5,
    "TECHNICAL_CONTROLLER_FAILURE": 1,
    "BUDGET_STOP_NOT_EVALUATED": 5,
    "NOT_RUN": 176
  },
  "stageB_oracle_queries": 10840,
  "stageB_backend_probes": 0,
  "stageB_api_calls": 0
}


Execution amendment: execution_amendment.json increased concurrent workers from two to six, preserving the original absolute one-hour deadline. The original controller and its two active workers were stopped before resumption; completed-file hashes were verified unchanged. The same registered queue, rooms, operators, seeds, validators and truth criteria were used. Only slots without completed outputs, including technical timeouts, were resumed; all earlier failure records remain available. This orchestration amendment was recorded after observing runtime and is not represented as the original preregistration. A later controller recovery handled a Windows taskkill race: only confirmed process termination is accepted. Previously started slots lacking scientific output were retained as explicit technical terminal records, with console/failure provenance, and not retried again. These are not successful mutant evaluations. See execution_recovery_v2.json.

Active preregistration: results/raw/delta2/stage_B/preregistration_v5.json, pinned by review/proof_b1.json. Earlier draft plans/scripts are retained as superseded, not executed studies. Active script: drafts/delta2_20261020/agent_b_stageB/stage_b_v5.py. Execute only in a fresh output workspace; retained checkpoints are never overwritten. The exported original plan preserves pre-anonymization source and script pins for provenance. The separate review/exported_input_manifest.json verifies anonymized model files; direct execution against those renamed copies requires a new, explicitly derivative job with those export hashes, not silent alteration of the original preregistration.

The requested analysis over actually started rooms is in actually_started_rooms/tables/T_B1_detection_machine_readable.csv; analysis_scope.json gives the actual room denominator and the outcome-independent worker-start selection rule. The original all-selected-room analysis remains in tables/T_B1_detection.csv, with JSON interval arrays in tables/T_B1_detection_machine_readable.csv. The derivative conversion changes scalar representation only and retains source/derivative hashes. Neither analysis repairs informative technical censoring or establishes coverage of unstarted rooms.

Room-cluster bootstrap uses seed 20261015 and 10000 resamples over all selected rooms, including rooms with zero eligible observations; single-room intervals are descriptive and degenerate. The supplied tables separate checker-specific eligibility and show all room/operator slots. Scientific completion and technical termination are separate.

API calls and extra API cost: zero. Original data, DELTA1, Stage A, claims and gates remain unchanged. This is a separate cohort and must not be pooled into generated 908 or classroom 153. Original source hashes refer to pre-anonymization inputs; MANIFEST.sha256 covers this exported payload.
