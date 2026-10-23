# Threat model and enforcement boundaries

The contract protects routing relative to published model declarations. Client observation fields and language-model output are untrusted. Backend code, the loader, its dependencies, and the publication store are trusted. Authoring may publish an internally consistent but semantically inappropriate assignment. The experiment assumes authorized cooperative publishers; this backend is not a network authorization boundary.

| Input or boundary | Enforced rule | Executed evidence | Residual risk |
|---|---|---|---|
| session_id | Session must exist; HTTP serializes turns per session | tests/test_guard_http.py; tests/test_guard_modes.py | Session identifiers are not authenticated user identities; process death loses sessions |
| active_agent_id | Must name a pinned agent; server_strict also compares last committed agent | strict-switch HTTP test | Explicit switch can choose any modeled agent; visitor choice remains application semantics |
| switch_agent target | Modeled membership; audit append before active-state change | logged-switch unit/HTTP tests | Does not authorize the human caller |
| model_sha256 | Matches session pin; default does not trust client to choose a new publication | stale regression and digest tests | no_digest is intentionally unsafe ablation; pin is not a signature |
| entity_id, source_object_id, source_id | Resolve against pinned entities | captured regression; differential raw probes | Packet ignores a conflicting secondary source alias; open conformance finding |
| state, ambiguous, ambiguity, candidates | Resolved selection and ambiguity checks | full Gate-1 regression variants | Empty candidates and reason-only ambiguity differ from amended SPEC; documented in DISAGREEMENTS |
| object_group_id, zone_id | Checked against model-derived membership | loader/selection code; further adversarial coverage pending | Model memberships may themselves be inappropriate |
| hit_position, distance_m, modality | Type, bounds, finite-value and enumeration checks | existing production validation; dedicated geometric tests pending | No Unity raycast or physical observation is verified |
| display_name, synonyms | Bounded presentation hints; canonical identity from model | source inspection; targeted spoofing tests pending | Names and text can influence content; no intent guarantee |
| interaction_mode | Deictic mode requires spatial context; non-deictic contract separate | native contract tests | Core independent evaluator concerns deictic admission only |
| user_text and extra request fields | Basic wire checks in packet; declared schema conformance under differential review | extended schema-admission run | Text does not select provider; content can still redirect or discuss another object |
| client provider/action claims | Provider and operation derive from model path | differential; property oracle in progress | Model can faithfully encode a wrong assignment |
| language-model handoff field | Grounded schema restricts handoff; opt-in abort or drop_log enforces fallback behavior | constrained/fallback unit tests; HTTP tests | Packet fallback suppresses proposals differently; real frequency unmeasured |
| answer text | Returned as text; outside routing contract | no content-safety result | No promise of truth, intent alignment, grounding or prompt-injection defense |
| project files during turn | Full preflight; chosen commit scope; cooperative generation/manifest check | WP7 raw stress, explorer, faults | Direct edits bypass lock; code/dependency changes outside fingerprint |
| setup project and authoring endpoints | Native contract consistency checks; HTTP setup failure removes/restores session | server transaction path | Paths, project writes and authoring are privileged deployment surfaces; no authentication is added by this research patch |
| external effects | Test-only effect ordering demonstrated | WP7 effects raw records | In-memory rollback cannot compensate arbitrary external side effects; duplicate delivery is not exactly once |

A passing test supports only its stated condition. Rows marked inspection or pending are not counted as adversarially verified. German error messages retain their original text; structured codes are the machine interface.

The cooperative protocol assumes shared project locking across participating processes, local filesystem atomic replacement, and cooperating readers of the paired journal. Spawned process execution was tested on Windows. Fork during a held lock, network filesystems, and Linux execution remain outside the executed evidence. Strict generation equality can abort a turn even when a routing slice is unchanged.
