# WP6 preregistration: exhaustive mutation detection

Status: frozen before the formal WP6 corpus evaluation. Synthetic unit tests are engineering checks only; their raw smoke output is retained separately under results/raw/wp6_unit and excluded from research denominators.

## Corpus and unit of analysis

The first corpus is the supplied classroom project. The same code and selection rules apply to each subsequently supplied WP5 generated project, retaining the provenance and room ID. Models produced by mutation are mutant models, never new rooms. The mutant model is the unit for detection proportions; probes are correlated within it. The first run directory is results/raw/wp6_example_v1. A run directory is new and refuses overwrite. All operator attempts and projection failures are retained.

## Operators and deterministic selection

The seed is 20261015. There is one deterministic single mutant per eligible core operator per room and one successful composition target per unordered operator pair. With 17 core operators, there are 136 core pairs. Candidate tuples are lexicographically sorted by their JSON encoding and selected using Python random.Random with the first eight SHA-256 bytes of the documented seed/room/operator key. Every actual seed and target is recorded. The second operator recomputes its candidates on the first result and prefers targets disjoint from the first operation. This preference is syntactic, not a claim of semantic independence.

For a pair, try canonical operator-list order. If a mutation is not applicable or cancels, retain that attempt and try the reversed order on the original model. A changed first operation followed by an inapplicable second one is retained and evaluated as an incomplete attempt; it is not credited as a tested two-fault combination. If no target exists in either order, the pair remains explicitly uncovered. No-op, inapplicable and incomplete counts are reported. Masked lower-level ownership edits remain real model edits but are not assumed to introduce routing faults.

| Operator | Exact intervention |
| --- | --- |
| drop_handoff | Delete one existing directed non-self handoff edge. |
| add_handoff | Add one absent directed edge between distinct agents. |
| move_owner_without_path | Move one uniquely asset-owned object to another agent; keep its capability-use providers. |
| move_owner_with_path | Move one uniquely asset-owned object and all provider/performer declarations targeting it to another agent. |
| duplicate_asset_owner | Add another agent to an existing asset responsibility; keep more general relations. |
| duplicate_group_owner | Add another agent to an existing group responsibility; do not remove asset overrides. |
| duplicate_zone_owner | Add another agent to an existing zone responsibility; do not remove asset/group overrides. |
| remove_asset_owner | Remove one existing asset-responsibility reference; fallback remains possible. |
| remove_group_owner | Remove one existing group-responsibility reference; other levels remain. |
| remove_zone_owner | Remove one existing zone-responsibility reference; other levels remain. |
| remove_all_owners | Remove every responsibility reference that can own a selected scene object at asset/group/zone level. |
| remove_action | Remove one answering RuntimeAction and its owned locator/schema/parameter records; remove references to those deleted records. Empty bindings remain invalid rather than being repaired. |
| duplicate_action | Clone one answering RuntimeAction and its owned locator/schema/parameter records into the same binding, yielding an additional answering path. |
| swap_owners_consistently | Exchange the unique asset owners of two objects with different owners; move every targeted capability-use provider/performer path with them. |
| reassign_group_owner | Move one existing group responsibility reference to an agent not already responsible for that group. |
| merge_agents | Merge one Agent into another, union its responsibilities/capabilities, redirect references, remove resulting self-handoffs and duplicate references. |
| rename_agent_dangling | Rename one native Agent ID without updating its references, intentionally leaving them dangling. |

The eighteenth operator is an observed natural diff. It runs only when WP5 supplies actual before/after published projects and a pair ID, through --evolution-pairs JSONL fields pair_id, before_project, after_project. The observed after model is evaluated, plus natural-diff then each core operator using disjoint-target preference. No natural result is synthesized if those inputs are unavailable. The absence of natural pairs is a missing evidence class, not a zero observed failure rate.

## Projection handling

Native records are mutated first. The trace is then derived from complete native links using the existing trace rows as metadata templates. Scenario-step provider projections, action input/output modelBinding annotations, deployed agent references and placement projection hash, and the model digest declarations are updated. Ownership-only changes do not move capability-use paths; the consistent-move and swap operators explicitly do. A projection exception is retained with the mutated native bytes and stale projection rather than discarded. No schema, invariant, or loader validator is bypassed in reported checker results.

## Checkers on every resulting mutant

V-a is the original structural validate_instance API used by the packet CLI, with Gate 0 disabled. V-b is reported separately for native serialization schema, native canonical/domain validation, trace schema, legacy roomcontract_invariants applied to an explicit native-to-legacy validation view, and handoff metrics on the native role/edge projection. The validation view is not a claimed lossless exporter; unit tests check a valid fixture and a known broken binding. Its checked-element count is retained, and zero elements are not credited as a pass. Original knowledge-generation and placement-intention artifacts are absent from native mutation units; the corresponding traceability/placement metrics are explicitly not applicable. No full V-b union PASS is inferred when a constituent check is unavailable.

V-c separately executes loader-level native-instance and trace validation. Actual backend setup refusal is a separate result. Gate 0 is run on every native model, with canonical digest declarations verified, and produces every agent/object table entry. I1 and I2 are called through their public evaluate interfaces on every pair and every stale-digest variant. No evaluator implementation is edited or inspected by this harness.

For every start-agent/scene-object pair, the real SessionStore is executed in runtime, firstmatch, reach_only, table, and no_digest configurations when setup succeeds. Requests use resolved entity/source identifiers, the published digest, a fixed benign utterance, hit position (0,0,0), distance 1 m and programmatic modality. An additional request copy with the all-zero digest is executed for runtime and no_digest, with I1/I2 cross-checks; these are request mutations, not extra model mutants. Each probe snapshots/restores its session through the shared driver. Setup refusals prevent a session from existing and are reported as not-run probes, never fabricated runtime verdicts. The driver uses the explicitly labelled ScriptedClient solely for deterministic admission testing. It does not run the HTTP commit/evidence path; commit variants belong to WP7, not this admission matrix.

I3_rejection_atomicity checks the observed default runtime: a rejected normal request makes zero ScriptedClient calls and leaves the pre-restore session snapshot unchanged. This property does not use I1/I2 verdicts. It is reported as behavior-property pass/violation/applicability counts, not as a model-fault confusion classifier: a correct rejection on a faulty model should satisfy the property. The separate WP2 Hypothesis experiment supplies broader generated-model G1–G5 checks; it is not represented as an independent binary classifier on these mutants. Real-LLM B0/B1 and geometric/LLM plausibility judgments are not substituted with stubs; absent inputs or budget/API authorization remain missing evidence, stated explicitly.

## Ground truth and endpoints

A mutant is routing-faulty only if I1 reports at least one E_UNOWNED, E_AMBIGUOUS_OWNER, E_NO_DECLARED_ACTION or E_ACTION_AMBIGUOUS on its normal all-pairs probes and I2 agrees on every normal decision, reason, provider and action. An I1/I2 disagreement, evaluator error, or unexpected normal-request failure class makes ground truth unresolved and excludes that model from confusion denominators, with the count retained. No majority vote resolves it. No-path/multi-hop policy restrictions are reported as reachability behavior, not model faults. A consistent ownership swap can change the table while remaining fault-free relative to the published model; semantic sensibility is outside this oracle.

Report TP/FP/FN/TN over mutant models per checker, room, operator and ownership/action fault class. Wilson 95% intervals are computed for sensitivity and false-positive proportions. Report all unavailable checker/model cells. The strict V-a/V-b and authoring/loader unions can reject if any constituent rejects; otherwise incomplete applicability remains unknown. Perfect I1/reference detection is by definition and is not a scientific finding.

A wrongly admitted normal probe is an executed admission whose decision/provider/action differs from the agreed I1/I2 verdict. It includes admitting an oracle rejection or executing a different provider/action. Report wrongly admitted probes and models per executed variant. Stale-digest ablation is reported separately. Do not inflate n by pooling normal and stale probes as independent models.

All raw checker reports, exceptions, model/projection bytes, requests and verdicts are preserved. Every worker failure is retained and makes evaluation_complete false. A run is not reported as exhaustive until every planned changed/incomplete model has an outcome. Natural, LLM and plausibility classes that are unavailable remain explicit limitations.

## Freeze and changes

WP6_PLAN.sha256.json records this document and the mutation/harness source hashes. The formal runner refuses source hash mismatch. Revisions require a numbered preregistration amendment and a new versioned run directory; prior raw runs remain. Backend/evaluator dependency versions must be recorded with the run and any corrections routed through the root disagreement protocol. Selection rules cannot be changed after observing corpus outcomes without being labelled exploratory.
