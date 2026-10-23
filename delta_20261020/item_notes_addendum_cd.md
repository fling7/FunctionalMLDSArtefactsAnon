# Addendum C/D

C DONE with retained-evidence limitation. The requested 86 assembly +29 scene-semantics +3 agent-role failed attempts are all accounted for in T3d. Classification applies conservative regexes to retained terminal-stage messages only; category counts may overlap if a message has multiple semantic faults. Other includes explicit infrastructure/JSON/schema failures; unclassified means no detailed refusal message was retained. All 86 assembly checkpoints store only error_code ValueError, not the exception text (the original pipeline catch handler retained the exception class only); consequently all 86 remain unclassified rather than being guessed as duplicate ownership. Exact safe messages/codes are preserved in the row-level table, with input file/line provenance. No new assembly or model run was attempted.

D DONE. 134 audited native model records map to59 literal source IDs and56 base sources; three additional edit IDs derive from the astronomy-gallery base. The source-level provenance table joins retained registries and verifies each source file hash. Source authoring must be distinguished from downstream native pipeline authoring: deterministic source scenes can still feed LLM-driven native generation. Guided LLM sources use a fixed geometric scaffold, with model-written full source JSON/domain content; they are not unconstrained natural scenes.

- pipeline_failure_attempts_roomcontract_assembly: 86
- pipeline_failure_roomcontract_assembly_duplicate_asset_owner: 0
- pipeline_failure_roomcontract_assembly_unowned_object: 0
- pipeline_failure_roomcontract_assembly_dangling_handoff: 0
- pipeline_failure_roomcontract_assembly_other: 0
- pipeline_failure_roomcontract_assembly_unclassified: 86
- pipeline_failure_attempts_scene_semantics: 29
- pipeline_failure_scene_semantics_duplicate_asset_owner: 0
- pipeline_failure_scene_semantics_unowned_object: 0
- pipeline_failure_scene_semantics_dangling_handoff: 0
- pipeline_failure_scene_semantics_other: 29
- pipeline_failure_scene_semantics_unclassified: 0
- pipeline_failure_attempts_agent_roles: 3
- pipeline_failure_agent_roles_duplicate_asset_owner: 0
- pipeline_failure_agent_roles_unowned_object: 0
- pipeline_failure_agent_roles_dangling_handoff: 0
- pipeline_failure_agent_roles_other: 3
- pipeline_failure_agent_roles_unclassified: 0
- confirmed_native_models: 134
- confirmed_raw_native_source_ids: 59
- confirmed_native_base_sources: 56
- confirmed_edit_source_variants: 3
- native_base_sources_deterministic: 49
- native_models_from_deterministic_sources: 126
- native_base_sources_LLM_written: 7
- native_models_from_LLM_written_sources: 8
- pipeline_failure_message_redactions: 0
