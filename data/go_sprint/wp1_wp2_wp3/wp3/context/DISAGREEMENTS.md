# Differential findings

One authored example room is the unit of analysis. Probe counts below describe exhaustive configurations within that room, not independent observations.

2448 probes; 720 disagreed. Decision/provider/action disagreements: 468; reason-only: 252. I1 versus I2 disagreements: 0.

| Variant | Classification | Disagreement probes | Decision disagreements | Disposition |
|---|---|---:|---:|---|
| user_text_number | backend bug | 117 | 117 | SPEC 4.3 requires the original request to satisfy its declared schema; numeric text is coerced by the packet. Default retained; no fix commit. |
| user_text_empty | backend bug | 27 | 0 | The packet checks empty utterance before ownership/reachability, contrary to SPEC first-failing-condition order. Default retained; no fix commit. |
| source_alias_conflict | backend bug | 144 | 117 | SPEC 4.3 requires consistent supplied identities; A001 explicitly covers both aliases. Default retained; no fix commit. |
| empty_candidates | spec ambiguity | 144 | 117 | SPEC v1 did not define empty candidate-list semantics; A001 chose exact singleton when supplied. Default retained; no fix commit. |
| ambiguity_reason_only | spec ambiguity | 144 | 117 | A001 distinguishes boolean ambiguity flags from explanatory text. Default retained; no fix commit. |
| active_and_digest | backend bug | 144 | 0 | SPEC 4.3 requires stale digest to be the first error, before active-agent membership. Default retained; no fix commit. |

A001 was frozen before these probes were evaluated. It was not revised in response to this run. All initial pending entries remain in the append-only ledger, followed by adjudication records. Do not add the two event types as separate disagreements.

Raw verdicts: results/raw/differential/example-initial/probes.jsonl. Processed counts: results/processed/differential_summary.json.

The extended schema-admission run adds numeric-utterance and empty-utterance precedence findings. The broader corpus, mutant comparison, and property counterexamples remain separate work; this table does not establish general agreement.
