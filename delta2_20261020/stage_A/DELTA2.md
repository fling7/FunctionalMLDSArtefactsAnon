# DELTA 2 — Stage A

## Five findings that affect the paper

1. Table-mode admission was measured with digest checking, paired with runtime admission on the same local-answer request and session. 36/40 timing cells completed. The results below include all slow and unfinished cases. This measures the admission pipeline, not just dictionary lookup.
2. All 86 historical assembly refusals were reproducible from retained inputs with the historically pinned assembler: 84 duplicate asset-owner declarations and 2 owner/zone conflicts. These are retained pipeline-attempt faults, not a representative estimate of fault prevalence.
3. Removing only the object-owner override makes 5/12 latent cases ambiguous under all three oracles, not the expected twelve. Seven remain resolved by group ownership. The requested twelve span original-natural and ownership-repair cohorts; they are not twelve classroom faults.
4. All-non-oracle misses remain 72 in generated mutants and 11 in classroom mutants; every miss involves the duplicate-action operator. Per-operator singles and pairs are separated. These results do not establish universal detector coverage.
5. Classroom's 27 pairs outside one handoff comprise 9 finite two-hop pairs and 18 unreachable pairs. Stored timestamps precede October 15, but the author/tool is unestablished. Drift preserves the ownership partition in 44/45 comparable pairs; partition equality alone does not establish semantic equivalence.

## Paired admission medians

| Scene-object size | table, digest=true | runtime, digest=true |
| --- | ---: | ---: |
| classroom | 345.028 ms | 318.612 ms |
| 100 | 1085.024 ms | 1215.852 ms |
| 300 | 9051.689 ms | 8055.269 ms |
| 1000 | 68777.729 ms | 59697.725 ms |

The complete table includes ten repetitions after two discarded warmups, inclusive IQR, minimum and maximum, exact native-element counts and preparation status. One worker ran at a time; desktop applications remained running. One ANSWER_LOCAL query per size is a case measurement, not a representative query mixture. The admission endpoint includes state snapshots and both preflights. The inherited no-guard baseline bypasses admission checks and exercises scripted SessionStore.chat plus snapshot/restore. It does not invoke the outer HTTP endpoint or Gate4 logger, which is measured separately; do not subtract or divide these different endpoints to claim total end-to-end guard overhead.

Cold memory means clearing the routing-table cache, with the verifier already imported. The OS file cache was uncontrolled. Production has no persistent disk-table load implementation; JSON persist/load is separately labelled artifact I/O, and true OS-cold loading is NOT DONE. The production default remains runtime routing; table mode was explicitly selected for its paired measurements. No application optimization was made.

The retained 300-object cProfile run identifies the action preflight/contract-reload path, especially trace validation, as the main cumulative-time consumer. Profiling itself adds overhead; its wall-clock duration is not a replacement timing sample, and nested cumulative times must not be added together.

## Checker provenance

The table has 20 component/dependency rows, not that many independent checkers. Seven rows are study-written, eight are inherited files changed for the study, and five are unchanged. Structural V-a functions, V-b schema functions and V-c loader functions remain AST-identical to the retained original implementation even where their containing files changed. The requested August 6 V-a import is verified; local history also retains an earlier July 27 addition. Gate 0, I1, I2 and study adapters must not be described as independent pre-existing tools.

## Detailed item notes

A1 measured production table and runtime admission with digest_check=true on the same request/session, alternating paired order, two discarded warmups then ten repetitions. No optimization. Gate4 uses the unchanged packet/full protocol. JSON persist/read measures artifact serialization only: the backend actually caches verified tables in memory and has no disk-table load path. Cold memory means clearing that cache; OS-cold disk loading is NOT DONE because OS cache was not evicted. Other desktop applications and OS services remained running. Completed sizes, min/max/median/IQR and all unfinished cells appear in A1_table_lookup_timing.csv. A retained complete1000-object project is reused from Delta1 preparation; its original timing cells remain untouched.

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

## A3 checker provenance — DONE

All evidence is read-only local Git history, retained files and AST comparison. Physical LOC includes comments/blank lines; nonblank LOC and callable-span LOC are also provided. File LOC is repeated for components sharing a file and must not be summed as independent checker size. First commit is a retained-history bound, not an authoring date; copied-file mtime is not creation evidence. No personal identities or commit-author fields are exported.

The original structural validator predates the contract study. The named 2026-08-06 import commit is verified, but original project HEAD history also retains an earlier 2026-07-27 add commit. Therefore 2026-08-06 is a re-import milestone, not proven first creation. Current V-a file was changed during the study; the structural InstanceValidator/validate_instance ASTs are unchanged from the 2026-10-15 preserved packet. New routing checks are an opt-in profile, and the metamodel dependency has its own row. This must not be described as an entirely untouched pre-existing checker stack.

The table identifies inherited files changed during the study and entirely study-written files. Gate 0, I1, I2, the backend test driver and mutation projection adapters were written for the study after 2026-08-06. Their oracle or adapter roles are explicit. V-b placement and traceability metrics exist but are not applicable to the retained mutation-unit evaluation; presence is not execution evidence. Backend setup combines a study-written driver with inherited backend components, which are separately listed. Byte differences do not alone show whether a particular checker behavior changed; callable AST comparison gives narrower evidence where possible.

A zero API cost, no re-execution provenance exercise. Old LOC is the preserved packet at commit 954f199; new LOC is the current retained file. Full commit hashes/dates, baseline hashes and current input hashes are retained in the proof, without author identities.

A4 DONE:17 single-operator rows per cohort, pair combinations separate; all Vb components including unavailable-status counts, Vb union, loader/backend, missed-all and separate oracle block. Existing908generated/153classroom only.

A5a DONE: classroom long-handoff pairs recomputed and listed; stored metadata/mtime precedes2026-10-15, but human author and exact authoring tool are unestablished. Supplied authored example, not natural LLM fault incidence.

A5b DONE with explicit scope: requested12=original-natural1group + ownership-repair2groups9zones. Classroom itself has3groups0zones. Counterfactuals remove ONLY object-level ownership, for all members of each latent entity; no group override removed to force expected result. All members/allagents measured. Exact results in numbers/table, including masking/null outcomes. These are injected counterfactual faults, not12observed natural deciding-level faults.

A5c DONE:45comparable fresh-regeneration pairs separated from4edit/rename pairs; partition comparison on matched,defined objects. Equality does not prove semantic equivalence.

No existing raw/cache/table/claims/gates/delta1 file modified. All retained inputs rehashed; no API calls.

A5a wording correction: the27one-handoff rejections are9finite two-hop pairs plus18unreachable pairs. New table A5_classroom_outside_one_handoff_pairs.csv listsall27; finite-only table lists9. Do not describeall27as finite distance>1.


## Scope, numeric provenance and reproduction

All baseline and DELTA1 artifacts, raw files, caches, claims and gates remain unchanged. No GO decision is re-evaluated in this supplement. Stage A uses no API calls and spends USD 0. New tables, numbers files and old/new/script logs are authoritative only for this supplement. Source hashes pin originals before anonymization; MANIFEST.sha256 pins the delivered transformed payload.

Scripts are supplied under drafts/delta2_20261020, with new raw results under results/raw/delta2/stage_A. Use the existing repository environment and exact retained inputs referenced by proofs; scripts do not download dependencies or call models. Existing result outputs intentionally refuse overwrite where applicable. Preserve this delivery when reproducing in a fresh output tree. The original source registry, model paths and all cohort distinctions remain in the proofs.

Stages B and C are separate deliveries and are not claimed complete here.
