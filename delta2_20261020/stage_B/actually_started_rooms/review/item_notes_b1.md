Stage B: new stratified cohort, separate from 908/153. Selection frozen before mutant outcomes. No backend setup, no backend/model probes; pure oracle queries only. I1, compiled I2 and Gate0 must agree for determinate ground truth. Technical errors, unknown truth, no-ops and inapplicable operators remain excluded with explicit counts. Results do not estimate prevalence across all 56 sources. Source-room bootstrap uses all selected rooms, including zero-eligible rooms, with 10000 resamples seed20261015; per-room scopes use their single room. Zero-denominator draws excluded and reported. Checker not-applicable rows excluded from that checker denominator. All planned slots retained, including exact retained TECHNICAL_TIMEOUT, TECHNICAL_FAILURE, BUDGET_STOP_NOT_EVALUATED, and never-started NOT_RUN statuses. Completion of execution is separate from determinate scientific ground truth. Single-room bootstrap intervals are degenerate and do not establish population certainty.
{
  "stageB_selected_rooms": 12,
  "stageB_observed_rooms": 12,
  "stageB_outcomes": 189,
  "stageB_planned_slots": 204,
  "stageB_groundtruth_eligible": 157,
  "stageB_status_counts": {
    "NOT_APPLICABLE": 12,
    "EVALUATED": 157,
    "TECHNICAL_TIMEOUT": 18,
    "TECHNICAL_INTERRUPTED": 5,
    "TECHNICAL_CONTROLLER_FAILURE": 1,
    "BUDGET_STOP_NOT_EVALUATED": 5,
    "NOT_RUN": 6
  },
  "stageB_oracle_queries": 10840,
  "stageB_backend_probes": 0,
  "stageB_api_calls": 0
}
