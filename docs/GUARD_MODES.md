# Executable guard modes

ROOM_GUARD_CONFIG is a server-controlled JSON object parsed into GuardConfig. All fields default to the packet's decision behavior. It is not taken from request JSON.

| Field | Values | Effect |
|---|---|---|
| active_agent_mode | client, server_strict | Client-addressed agent or explicit switch from last committed agent |
| proposal_mode | packet, abort, drop_log | Original fallback behavior, abort and restore, or ignore and record proposed handoff |
| routing_mode | runtime, firstmatch, reach_only, table | Existing resolver, deliberate ambiguity defect, omitted declaration check, or cached publication table |
| digest_check | true, false | Disable only request-versus-session digest check for ablation |
| publication_protocol | packet, cooperative | Original commit path or shared project lock, generation and paired journal |
| generation_precheck | false, true | Optional cheap generation comparison before model call |
| commit_variant | full, none, digest_only, slice, slice_prompt | Commit check scope; full is the packet fingerprint |

Commit-scope ablations retain the packet's full pre-call revalidation. They isolate the final commit check, not the complete admission cost. Cooperative publication always enforces generation equality, even for narrower fingerprint scopes.

The table cache uses the model digest plus a trace hash; digest-only cache identity would be unsound for trace edits. The table contains explicit reject cells for defective experimental publications. Deployment may require Gate-0 report.ok before publication. Runtime still checks the request pin, resolved identity, ambiguity, active agent, geometric wire fields and schema/wire constraints. It still revalidates before generation and at commit as configured; the current table mode does not eliminate all revalidation cost.

reach_only intentionally emits an unbound operation descriptor with no fabricated native action identifier. HTTP evidence labels the disabled declaration check and uses an experimental unbound validation record. It does not bypass global loader checks; malformed publications can be rejected before the ablated runtime gate is reached. Count wrongful admissions separately from the intentionally absent action binding.

The actual packet's unconstrained fallback suppresses a handoff rather than unconditionally aborting. Therefore packet is a separate default proposal mode. This contradicts the mission's description, and source evidence takes precedence. Explicit abort and drop_log modes are tested with scripted unit outputs; their natural frequency requires WP4 real-model evidence.

Tests: tests/test_guard_modes.py, tests/test_guard_http.py, tests/test_packet_regression.py, tests/test_publication.py. Initial HTTP evidence lookup used the wrong filename glob; the failing report is retained and only the test harness was corrected.
