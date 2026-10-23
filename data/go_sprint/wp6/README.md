# WP6 bounded mutation data

This directory contains **304 unique completed scientific mutant outcomes**, counted once: 303 retained observations plus 1 new completed recovery observation. The two campaigns registered 908 scheduled evaluations; **604 remain missing** (4 interrupted and 600 not started in the last attempt). This is not full WP6 or a full-mission PASS.

Files:

- `outcomes/part_*.jsonl`: one complete original outcome object per line; at most 50 outcomes and 32 MB per file, including every checker and pair/variant result. JSON formatting is compacted; no values are removed or normalized.
- `outcomes_flat.csv` and `outcomes_flat.jsonl`: one row per completed mutant, suitable for direct analysis.
- `coverage.json`: exact denominators, completed source-room counts, negative findings and limitations.
- `missing_outcomes.jsonl`: every scheduled missing mutant with explicit last-attempt status.
- `registered_attempts.jsonl`: the complete two-manifest planning inventory, including not-applicable/no-op attempts; these are not counted as missing scheduled evaluations.
- `excluded_worker_failures.jsonl`: retained worker-failure records, if any; excluded from scientific completed outcomes.
- `source_manifest.json`: repository-relative source references, original byte hashes, exported line hashes, and closure pins.
- `SHA256SUMS.json`: checksums of all other delivered files.

**Unit:** one mutant model. The 70800 agent-object pair rows and multiple backend variants are correlated within each model and must not be treated as independent samples. Setup refusals and negative validator findings are scientific results and remain included. Missing/interrupted attempts are not negative findings. Null ground truth remains null.

This folder deliberately covers only the requested two stopped campaigns. The separate classroom cohort, later original batches, wider all-native corpus and natural-diff scope are not represented as completed here. No engineering benchmark repeat is included. No new evaluation or provider call was made to create this export. Backend responses use ScriptedClient; they are not real-LLM results, and Driver.probe does not exercise HTTP commit/evidence publication.

Read without project code:

    import json
    from pathlib import Path
    for part in sorted(Path("outcomes").glob("part_*.jsonl")):
        with part.open(encoding="utf-8") as stream:
            for line in stream:
                outcome = json.loads(line)

All data are self-contained JSON/CSV. Source paths are provenance references, not runtime dependencies. Original diagnostic strings are retained verbatim; this folder does not claim a fresh anonymous-publication audit.

The source manifest maps each flat-table global JSONL ordinal to its exact shard and local line. Concatenating shards in listed order is byte-identical to the retained unsharded intermediate.
