# WP4 preregistration: real routing and guarded HTTP turns

This plan must be committed and hashed by the orchestrator before any WP4 evaluation or paid question call. Unit tests use explicitly labeled stubs only; no unit output is experimental evidence. No development model calls or prompt tuning are planned. Local-only tokenizer sizing was permitted before freeze; it sends no room data and generates no answers. The retained local preflight reports text/serialized-request token estimates, not exact provider message/schema framing counts. Separate B0/B1 ceilings retain all ownership context and provide headroom; the gateway still enforces exact provider counts at runtime. Tiktoken 0.12.0 with o200k_base was used for sizing. Exact prompts, runner, analysis and production source hashes are in wp4_plan.json. The separate questions plan must also be frozen before question generation.

## Questions and interpretation

Primary exploratory question: how do profile-only B0 and ownership-informed B1 differ in routing deviation from the declared model across the two registered model snapshots? Directional expectation: B1 reduces deviations when explicit ownership and one-hop constraints determine a unique answer. B2 executes native deterministic admission through the generation boundary and observes its provider/action; it supplies no mocked model response. Correctness is relative to I1 checked against I2 on the pinned model. No finding establishes visitor intent, semantic ownership quality, Unity behavior, or deployment reliability.

Secondary questions: does explicit abstention trade silent violations for abstentions; how sensitive are outcomes to the three frozen phrasings and repeat calls; how often do actual models propose handoffs in constrained versus forced JSON mode; and do abort/drop_log differ in committed-turn availability? Proposal rates in the forced fallback condition are diagnostic, not estimates of naturally occurring fallback incidence. Same author/specification limitations of independent implementations remain as documented in INDEPENDENCE.md.

## Corpus and units

Wait for the registered WP5 sequence to complete or terminate at its budget stop. Use the first twenty distinct successful native-valid evaluation source rooms in the frozen WP5 source order, choosing each source's earliest successful registered model variant in the registered model order. Never count two authoring-model versions as two rooms. Record every unsuccessful/ineligible source and all eligibility conditions. Use the public wp5_projects manifest; development sources are excluded. If fewer than twenty are available, an explicitly labeled insufficient-corpus run may use all available sources and fails the minimum; no synthetic replacements or extra source selection based on router outcomes. The authored example is a separate stratum.

For each room enumerate agent/object requests with valid neutral text, the pinned digest, and resolved selection. Evaluate public I1 and I2 interfaces plus native admission. Retain all disagreements; exclude only I1/I2-disagreed probes from labeled LLM comparison, retaining counts and reasons. Do not exclude native disagreements from the reference-labeled sample. Independent implementations are not modified to fit native behavior. Numeric text and empty-text fault findings belong to the separate robustness evidence and are not silently repaired by this experiment.

Build up to forty-eight candidates per room by seeded ordering within local/direct/multi-hop/unreachable/ambiguous/unowned/other-reject strata and round-robin stratum selection. Multi-hop/unreachable subdivision is harness graph metadata, not a changed independent decision. The primary source's preferred stratum rotates in the listed order; take the first available class in that rotated order. Missing strata are reported, never fabricated. HTTP uses fifteen admitted candidates, cycling a smaller finite set transparently. All probes, questions and repeated calls remain nested within source room. Primary confidence intervals use room clusters, not pooled probe trials.

## Router conditions and outcomes

B0 includes every agent id, display name, persona and expertise, selected object id/name/type/group/zone, active agent, and visitor question. B1 adds the complete ownership table with object/group/zone membership and all directed handoff edges. Both receive the same policy explanation and all three frozen phrasings. With-abstention explicitly allows null recipient/true; forced-choice constrains a listed recipient/false. Full context is retained even if it exceeds the hard input ceiling: INPUT_TOKEN_LIMIT is then a counted failure.

Primary neutral question is identical across cells. Natural questions are generated once and frozen before evaluation. Constructed mismatches select A but ask the frozen question about B with a different unique owner. They test declared-selection versus textual-intent divergence, not unobserved real user mistakes. Optional blocks are processed in fixed order, never cherry-picked after model outcomes.

A valid named recipient on an admitted pair is CORRECT if it equals the independent provider and WRONG_PROVIDER otherwise. Abstention on an admitted pair is WRONG_PROVIDER with abstention explicitly recorded. On a rejected pair, a valid named recipient is SILENT_VIOLATION and an allowed abstention is ABSTAIN_OK. Invalid JSON, inconsistent null/abstain values, unknown agent ids, refused/incomplete output, or schema violations are FORMAT_ERROR. API, budget, input-limit and missing-question errors remain separate rows and in all-attempt availability denominators. They are not scored as correct decisions or silently omitted.

## Native HTTP conditions

Use actual native loopback HTTP /setup and /chat with isolated project copies and fresh sessions. Keep production preflight, generated-answer handling, snapshot rollback, evidence append, and response serialization. The experimental client calls the shared gateway from the HTTP worker thread. Normal mode preserves the native constrained schema; grounded handoff options are empty. Forced JSON mode raises an in-memory schema-unsupported signal before sending any constrained API request, allowing the native JSON fallback branch to issue exactly one real call. Its frozen extra prompt mentions handoff fields and lists agents without authorizing execution. Both modes get the same short-answer instruction. No model output is injected or manufactured.

Slots zero through eight are constrained neutral/natural-1/natural-2, repeated on differing admitted candidates. Slot nine is constrained mismatch. Slots ten and eleven use identical neutral pair/question inputs with fallback abort and fallback drop_log at the main temperature. Slots twelve and fourteen use identical mismatch pair/question inputs with fallback abort and drop_log at temperature zero. Slot thirteen resends the identical wire request after slot twelve's handoff abort; the runner verifies request and full model-payload identity. If no handoff abort occurred it is a fresh constrained neutral temperature-zero turn, labeled ineligible for abort retry. Every intended row and any missing natural question remains reported.

Admission, completed real response, valid generated JSON, and commit are distinct. A native offline fallback after API failure can commit but never counts toward the real-generation minimum. Malformed/incomplete output does not count as a valid real generation. Keep raw response, proposed target, whether the target is a declared edge from the derived answering agent, HTTP status, rollback equality, tokens, latency and evidence. A repeated proposal following an identical temperature-zero aborted request is the registered livelock indicator; finite repeated calls do not establish inevitable livelock.

After core HTTP, if either model has fewer than the minimum valid generations, process the fixed supplemental source-round-robin queue of neutral constrained two-model pairs. At most ten additional pairs per source. Stop when both meet the minimum, or before the first pair that the remaining ledger cannot cover. Preserve all failed core/supplemental attempts. No call repair or retry of a failed response beyond gateway's registered transport retries. The unit remains source room.

## Budget, order and failures

Exact arithmetic below is generated from repro/prices.json. Gateway exact input counting bounds paid generation; maximum output is fixed. Shared ledger charges retries, unknown outcomes and in-flight reservations. Full next balanced blocks must fit before they begin. If a transport failure interrupts a block, retain the partial block and report it; never fabricate its missing partner. Cache identities include distinct repeats and conditions. A replay never substitutes one cached identity for a new repeated call. After observing any outcomes, changes require a dated deviation and preserved original raw/source hashes.

```json
{
  "global_cap_usd": "20",
  "share_usd": "7",
  "stop_usd": "6.3",
  "routing_one_call_usd": {
    "gpt-4.1-mini-2025-04-14": {
      "B0": "0.0007536",
      "B1": "0.0029536"
    },
    "gpt-4.1-2025-04-14": {
      "B0": "0.003768",
      "B1": "0.014768"
    }
  },
  "http_one_call_usd": {
    "gpt-4.1-mini-2025-04-14": "0.0014048",
    "gpt-4.1-2025-04-14": "0.007024"
  },
  "primary_routing_calls": 480,
  "primary_routing_ceiling_usd": "2.6691840",
  "example_routing_calls": 24,
  "example_routing_ceiling_usd": "0.1334592",
  "core_http_calls": 600,
  "core_http_ceiling_usd": "2.5286400",
  "core_total_ceiling_usd": "5.3312832",
  "headroom_for_retries_supplements_extras_usd": "0.9687168",
  "repeat_calls": 144,
  "repeat_ceiling_usd": "0.8007552",
  "optional_one_source_question_block_calls": 24,
  "optional_one_source_question_block_ceiling_usd": "0.1334592",
  "supplemental_two_model_http_pair_ceiling_usd": "0.0084288"
}
```

Local sizing retained at `results/raw/wp4_token_preflight_local_20261015T131718`; these deterministic request counts are not LLM trials and do not establish exact provider framing.

```json
{
  "B0": {
    "maximum": 604,
    "minimum": 506,
    "over3000": 0,
    "over4000": 0,
    "requests": 72
  },
  "B1": {
    "maximum": 5269,
    "minimum": 1679,
    "over3000": 36,
    "over4000": 36,
    "requests": 72
  },
  "HTTP_constrained": {
    "maximum": 985,
    "minimum": 689,
    "over3000": 0,
    "over4000": 0,
    "requests": 36
  },
  "HTTP_fallback": {
    "maximum": 1147,
    "minimum": 850,
    "over3000": 0,
    "over4000": 0,
    "requests": 36
  }
}
```

## Analysis fixed before outcomes

Report all phrasings, abstention settings, models and available fault strata. Primary misroute rate is the mean of within-source-room deviation proportions conditional on valid scored decisions; valid-scored coverage and availability appear alongside it. All-attempt deviation is a diagnostic lower bound on observed errors, never a success rate when responses are missing. API/input-limit/format failures remain separately counted against all attempts; rooms with no valid scored decision are reported as unavailable, not assigned a zero error rate. Use ten thousand seeded room-cluster bootstrap resamples for rate and paired B1-minus-B0 effect intervals. Report the paired decisions and room counts, exact McNemar as a secondary descriptive comparison, and no significance search. One-room strata have no cluster interval. Stability is agreement of distinct repeat calls on identical items; temperature-zero stability is descriptive rather than proof of determinism. Latency/token summaries describe these network calls and are not microbenchmark claims with two hundred timing repetitions.

For HTTP report valid real generations, commits, proposals, declared-target proposals, proposal aborts, repeated proposals after abort, and aborted-call tokens/latency. A simple lexical monitor records redirection verbs near agent names, other exact object source identifiers, and mismatch questions naming another source id. It is exploratory and is not a semantic judge. Two independent content judges and B3 are not claimed by this plan; their absence is an explicit limitation unless separately preregistered later. Outputs are T2_routing_baselines, T5_guarded_llm_turns (policy ablation supplement), F3_routing and F3b_handoff_channel. TeX uses booktabs. Every table/figure is regenerated from retained raw JSON without API access by analyze_wp4.py.

Official structured-output interface checked on the preregistration date: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses . The gateway's recorded model-access preflight and dated price registry establish the two snapshot choices; no model alias migration is performed.
