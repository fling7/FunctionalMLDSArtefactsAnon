# A2 Deterministic assembly recovery

DONE. Replayed only the pure deterministic historical assembler on retained, hash-verified normalized scene, scene semantics and agent roles. Knowledge, placements and handoff-file availability were also checked; those are not inputs consumed by this pure function. The assembler, common helper and agent-role helper SHA256 match both the original WP5 and extension preregistered implementation pins. No contemporary replacement was substituted; no model/API calls or optimization occurred.

The 296 retained pipeline records comprise141 success records,118 attempted failures and37 not-attempted records. The 86 assembly failures are a subset of the118 attempted failures; remaining attempted failures are29 scene-semantics and3 agent-role failures. Drift and guided cohorts are subsets of those86, not additional failed attempts. Guided cohort is selected by guided_llm case-ID lineage (including completion runs); drift by source.phase=drift. Exact cases and source phases are tabulated. Recovered semantic faults are observed in retained pipeline outputs, not injected mutations, but these source scenes are synthetic and authoring attempts are dependent; this is not a deployment-prevalence estimate. The captured exception is the first assembler refusal, not an exhaustive inventory of every fault.

- pipeline_attempt_records: 296
- pipeline_attempted_failures: 118
- pipeline_not_attempted_records: 37
- pipeline_success_records: 141
- assembly_failures_total: 86
- assembly_all_duplicate_asset_owner: 84
- assembly_all_unowned_object: 0
- assembly_all_dangling_handoff: 0
- assembly_all_schema_format: 0
- assembly_all_other: 2
- assembly_all_UNRECOVERABLE: 0
- assembly_drift_duplicate_asset_owner: 44
- assembly_drift_unowned_object: 0
- assembly_drift_dangling_handoff: 0
- assembly_drift_schema_format: 0
- assembly_drift_other: 0
- assembly_drift_UNRECOVERABLE: 0
- assembly_guided_duplicate_asset_owner: 9
- assembly_guided_unowned_object: 0
- assembly_guided_dangling_handoff: 0
- assembly_guided_schema_format: 0
- assembly_guided_other: 1
- assembly_guided_UNRECOVERABLE: 0
- assembly_other_duplicate_asset_owner: 31
- assembly_other_unowned_object: 0
- assembly_other_dangling_handoff: 0
- assembly_other_schema_format: 0
- assembly_other_other: 1
- assembly_other_UNRECOVERABLE: 0
- assembly_status_RECOVERED_EXCEPTION: 86
- assembly_status_UNRECOVERABLE: 0
- assembly_status_REPLAY_DID_NOT_REPRODUCE: 0
- assembly_retained_scene_graph_normalized_json: 86
- assembly_retained_scene_semantics_json: 86
- assembly_retained_agent_roles_generated_json: 86
- assembly_retained_knowledge_generated_json: 86
- assembly_retained_agent_placements_json: 86
- assembly_retained_handoff_matrix_json: 86

Final reporting: all86 exception messages recovered:84 duplicate-asset-owner refusals and2 other refusals (asset owner lacks a responsible zone containing its object). Drift44/44 duplicate; guided9/10 duplicate plus1other; remaining32attempts31duplicate plus1other. Unclassified causes86 ->0. UNRECOVERABLE is0 newly measured; it was not previously established as86. Use numbers_a2_final.json and changes_a2_final.json for the merged delivery; initial log old=86 for UNRECOVERABLE is superseded by this explicit provenance correction.
