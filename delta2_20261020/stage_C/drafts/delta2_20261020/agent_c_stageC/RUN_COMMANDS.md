# DRAFT execution commands — NOT RUN by preparer

Review and syntax-check after exclusive A1 timing stops. No current model IDs/prices are guessed. Root must supply exact accessible new small/flagship IDs and officially verified additive price file (including possible returned snapshot IDs).

Before discovery, save `preflight_context.json` with `starting_event_id` (authoritative events MAX(id)), `initial_accounted_usd` (sum COALESCE(charged,reserved)), `policy_sha256` (Budget.policy hash). Discovery must use new redirected logs and shared old ledger. This script does not perform discovery.

Offline candidate preparation (not final freeze):
```
.venv/Scripts/python.exe -B drafts/delta2_20261020/agent_c_stageC/prepare_stage_c_draft.py --output results/raw/delta2/stage_C/draft_preparation_v1
```

Freeze after review, verified prices, discovery and example proof:
```
.venv/Scripts/python.exe -B drafts/delta2_20261020/agent_c_stageC/stage_c_runner.py freeze --output results/raw/delta2/stage_C/c1 --candidates results/raw/delta2/stage_C/draft_preparation_v1/b1s_existing_models_candidates.json --prices results/raw/delta2/stage_C/new_models_prices.json --stage-context results/raw/delta2/stage_C/preflight_context.json --small EXACT_SMALL_ID --flagship EXACT_FLAGSHIP_ID
```
If official capability evidence already requires default temperature, add `--default-temperature-model EXACT_ID` before freeze (repeat for each applicable ID). Otherwise explicit unsupported-temperature error alone permits the frozen fallback, retaining the charged failure. No new model prices are written to the old registry.

Authorized execution, then network-disabled replay, then offline report:
```
.venv/Scripts/python.exe -B drafts/delta2_20261020/agent_c_stageC/stage_c_runner.py run --output results/raw/delta2/stage_C/c1 --live
.venv/Scripts/python.exe -B drafts/delta2_20261020/agent_c_stageC/stage_c_runner.py replay --output results/raw/delta2/stage_C/c1
.venv/Scripts/python.exe -B drafts/delta2_20261020/agent_c_stageC/stage_c_report.py --raw results/raw/delta2/stage_C/c1 --output deliverables/delta2_20261020/stage_C/report_v1
```

Planned C1 is450 new calls:90B1s for original2models then180new-small and180flagship. Each newmodel uses item-major4arm ordering to retain matched prefixes if budget stops. Budget failure is PARTLY, never C1complete. Existing270calls remain historical and are labelled in reports. Stopping never reallocates funds or replaces missing models/arms. C2 requires successful completeC1 and actual remaining budget plus a separate frozen C2request plan; this runner intentionally does not invent C2items. OptionalD is not silently substituted.

Package `filtered_stageC_events.jsonl`, new cache/rows/replay, frozen inputs and reports. Exclude redirected raw `logs/llm_calls.jsonl` from the stage package because Budget.record fills it with entire historical events. Preserve that raw local log and authoritative ledger. Initial discovery events (WP0.preflight /models after starting event ID) are retained in the filtered export. No other API experiment may run concurrently during this stage.

Pre-freeze review additions: new-model output budgets can be set with `--new-model-max-output-original N` and `--new-model-max-output-b1s N` if official model documentation requires room for default reasoning. Defaults remain96/128; old-model arms remain96/128. These values are stored in design/requests and cannot change after responses. Original-model order is derived from the retained design, not assumed from labels.

Accounting separates pre-generation refusals (budget/input-limit/key/claimed/token-count failure), generation/API errors, and technical postprocessing failures. Raw successful response is retained BEFORE parsing/classification, so a technical exception cannot lose paid evidence. Scientific FORMAT_ERROR is a valid observed outcome from a successful API response; it does not block completed C1. Missing responses, API errors and technical errors remain explicit and prevent successful-complete C1/C2 eligibility.
