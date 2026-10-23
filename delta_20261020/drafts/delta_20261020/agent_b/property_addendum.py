"""Aggregate retained completed property shards. Never executes the property harness."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import ast
import csv
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "deliverables/delta_20261020"
BASE = ROOT / "data/go_sprint/wp1_wp2_wp3/wp2"
SCRIPT = Path(__file__).relative_to(ROOT).as_posix()
started = datetime.now(timezone.utc).isoformat()
inputs, rows, summaries = [], [], []
for folder in sorted((BASE / "completed").iterdir()):
    raw, summary, pins = (folder / name for name in ("models.jsonl", "summary.json", "source_hashes.json"))
    inputs.extend([raw, summary, pins])
    shard = json.loads(summary.read_text())
    assert shard["status"] == "pass"
    summaries.append(shard)
    for line in raw.read_text().splitlines():
        r = json.loads(line)
        r["_shard"] = folder.name
        rows.append(r)
harness = ROOT / "results/raw/properties/model-properties-v2-shard0/harness.py"
guard = ROOT / "app/backend_root/agent_backend/backend/guard_config.py"
inputs += [harness, guard, BASE / "completed_summary.json", ROOT / "numbers.json"]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
pins = json.loads((BASE / "completed/model-properties-v2-shard0/source_hashes.json").read_text())
assert sha(harness) == pins["verification/properties.py"]
assert sha(guard) == pins[guard.relative_to(ROOT).as_posix()]
assert all(s["harness_sha256"] == sha(harness) for s in summaries)
assert all(json.loads(p.read_text()) == pins for p in inputs if p.name == "source_hashes.json")
# Parse pinned configuration defaults without importing backend or opening network connections.
node = next(n for n in ast.parse(guard.read_text()).body if isinstance(n, ast.ClassDef) and n.name == "GuardConfig")
defaults = {n.target.id: ast.literal_eval(n.value) for n in node.body if isinstance(n, ast.AnnAssign)}
requests = [(r, q) for r in rows for q in r.get("requests", [])]
admitted = [(r, q) for r, q in requests if q["result"]["decision"] != "REJECT"]
rejected = [(r, q) for r, q in requests if q["result"]["decision"] == "REJECT"]
commits = [r for r in rows if "commit_properties" in r]
refused = [r for r in rows if r["status"] == "setup_refused"]
counterexamples = [r for r in rows if r["status"] == "counterexample"]
assert len(rows) == 7000
assert len({r["model_sha256"] for r in rows}) == 4750
assert not counterexamples
assert all(r["status"] in ("pass", "setup_refused") for r in rows)
old = json.loads((BASE / "completed_summary.json").read_text())
old_numbers = json.loads((ROOT / "numbers.json").read_text())
log = []

def record(key, value, previous=None):
    item = dict(key=key, old=previous, new=value, script=SCRIPT,
                flag="NEW_ESTIMATE" if previous is None else ("UNCHANGED" if previous == value else "CHANGED"))
    log.append(item)
    print(json.dumps(item))

def save_csv(name, data):
    with (OUT / "tables" / name).open("x", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)
    for i, row in enumerate(data):
        for k, value in row.items():
            if isinstance(value, int):
                record(f"{name}[{i}].{k}", value)

property_rows = []
def assertion(name, group, guard_mode, unit, predicate=None, note=""):
    records = [x[0] if isinstance(x, tuple) else x for x in group]
    # Status=pass is written only after all applicable assertions execute. Some
    # values are not serialized; their pass evidence is the pinned harness + terminal row.
    if predicate:
        outcomes = [bool(predicate(x)) for x in group]
        passed = sum(outcomes)
        evidence = "direct retained field comparison"
    else:
        passed = sum(r["status"] == "pass" for r in records)
        evidence = "terminal pass plus pinned harness control flow; assertion operands not fully serialized"
    property_rows.append(dict(
        property_assertion=name, guard_mode=guard_mode, observation_unit=unit,
        observations=len(group), passes=passed, violations=len(group)-passed,
        setup_refusals=len(refused), distinct_models_observed=len({r["model_sha256"] for r in records}),
        campaign_rows_not_applicable=len(rows)-len({(r["_shard"], r["case_hash"], id(r)) for r in records}),
        evidence=evidence, qualification=note))

for name in ("G1_entity_id_matches", "G1_source_object_id_matches", "G1_unique_native_source_target",
             "G2_unique_deciding_owner", "G2_self_or_one_native_handoff_edge", "G3_unique_native_action_path"):
    assertion(name, admitted, "default", "admitted request")
assertion("G1_G3_only_normal_request_admitted", admitted, "default", "admitted request",
          lambda x: x[1]["variant"] == "normal")
assertion("admission_exactly_one_scripted_model_call", admitted, "default", "admitted request",
          lambda x: x[1]["result"]["model_calls"] == 1)
assertion("rejection_zero_scripted_model_calls", rejected, "default", "rejected request",
          lambda x: x[1]["result"]["model_calls"] == 0)
assertion("rejection_state_unchanged", rejected, "default", "rejected request",
          lambda x: x[1]["result"]["unchanged_before_restore"] is True)
for name in ("G5_unmodeled_proposal_preserves_decision", "G5_unmodeled_proposal_preserves_provider"):
    assertion(name, admitted, "proposal_mode=drop_log; other defaults", "injected proposal probe",
              note="Injected-probe result is not serialized separately; counted by terminal pass and shard proposal_properties.")
assertion("G4_unchanged_HTTP_status_200", commits, "default", "commit pair",
          lambda r: r["commit_properties"]["unchanged_commit_status"] == 200)
for name in ("G5_committed_active_provider_matches", "G4_success_one_additional_scripted_model_call",
             "G4_success_contract_fingerprint_unchanged"):
    assertion(name, commits, "default", "commit pair")
assertion("G4_drift_HTTP_status_400", commits, "default", "commit pair",
          lambda r: r["commit_properties"]["drift_commit_status"] == 400)
assertion("G4_drift_reason_E_CONTRACT_DRIFT", commits, "default", "commit pair",
          lambda r: r["commit_properties"]["drift_reason"] == "E_CONTRACT_DRIFT")
assertion("G4_drift_session_rollback_byte_equal", commits, "default", "commit pair",
          lambda r: r["commit_properties"]["rollback_byte_equal"] is True)
assertion("G4_drift_evidence_byte_equal", commits, "default", "commit pair",
          lambda r: r["commit_properties"]["evidence_byte_equal"] is True)
assert len(admitted) == sum(s["counts"].get("proposal_properties", 0) for s in summaries)
assert len(commits) == sum(s["counts"].get("g4_success_and_drift_pairs", 0) for s in summaries)
assert len(refused) == sum(s["counts"].get("setup_refused", 0) for s in summaries)
save_csv("T13_property_assertion_coverage.csv", property_rows)
mode_rows = []
for mode, group, unit in (
    ("default", requests, "request probe"),
    ("proposal_mode=drop_log; other defaults", admitted, "injected proposal probe"),
    ("default", commits, "commit pair; two HTTP transactions")):
    records = [x[0] if isinstance(x, tuple) else x for x in group]
    mode_rows.append(dict(guard_mode=mode, observation_unit=unit, observations=len(group),
                          passes=sum(r["status"] == "pass" for r in records), violations=0,
                          setup_refusals=len(refused), distinct_models=len({r["model_sha256"] for r in records}),
                          status="OBSERVED", interpretation="Pass means applicable assertions passed; rejected requests count as tested, not violations."))
for mode in ["routing_mode=firstmatch", "routing_mode=reach_only", "routing_mode=table",
             "digest_check=false", "active_agent_mode=server_strict", "proposal_mode=abort",
             "publication_protocol=cooperative", "generation_precheck=true",
             "commit_variant=none", "commit_variant=digest_only", "commit_variant=slice",
             "commit_variant=slice_prompt"]:
    mode_rows.append(dict(guard_mode=mode, observation_unit="not applicable", observations=0,
                          passes="NOT_APPLICABLE", violations="NOT_OBSERVED", setup_refusals="NOT_APPLICABLE",
                          distinct_models=0, status="NOT_TESTED_IN_THIS_CAMPAIGN",
                          interpretation="No mode-specific property guarantee; other campaigns excluded."))
save_csv("T13b_property_guard_mode_coverage.csv", mode_rows)
totals = dict(property_rows=len(rows), property_distinct_models=len({r["model_sha256"] for r in rows}),
              property_distinct_configurations=len({r["case_hash"] for r in rows}),
              property_request_observations=len(requests), property_admitted_requests=len(admitted),
              property_rejected_requests=len(rejected), property_setup_refusals=len(refused),
              property_counterexample_rows=len(counterexamples), property_commit_pairs=len(commits),
              property_proposal_injection_probes=len(admitted),
              property_assertion_observations=sum(r["observations"] for r in property_rows),
              property_assertion_violations=sum(r["violations"] for r in property_rows))
previous = dict(old_numbers, property_distinct_configurations=old["distinct_configuration_hashes"],
                property_commit_pairs=old["g4_commit_pairs"],
                property_request_observations=sum(old["request_decision_counts"].values()),
                property_rejected_requests=old["request_decision_counts"]["REJECT"],
                property_admitted_requests=old["request_decision_counts"]["ANSWER_LOCAL"]+old["request_decision_counts"]["ANSWER_AFTER_HANDOFF"])
for key, value in totals.items():
    record(f"numbers.{key}", value, previous.get(key))
totals["delta_property_guard_defaults"] = defaults
totals["delta_property_scope"] = {
    "unit_warning": "7000 configuration observations, 4750 distinct model hashes, not 7000 independent models.",
    "assertion_evidence": "Direct retained fields where present, otherwise terminal pass plus hash-pinned harness control flow. No re-execution.",
    "untested_modes": [r["guard_mode"] for r in mode_rows if r["status"] != "OBSERVED"],
    "interrupted_shard": "excluded",
    "setup_refusal_semantics": "Campaign-level pre-request setup refusals; repeated in assertion rows for visibility, never summed.",
    "model_calls": "Scripted stub calls in historical tests, not API calls.",
    "default_guard_config": defaults,
}
(OUT / "review/numbers_property_b.json").write_text(json.dumps(totals, indent=2) + "\n")
(OUT / "review/property_addendum_numeric_log_b.jsonl").write_text("".join(json.dumps(x)+"\n" for x in log))
proof = dict(status="DONE", started_utc=started, ended_utc=datetime.now(timezone.utc).isoformat(),
             script=SCRIPT, script_sha256=sha(Path(__file__)), inputs={p.relative_to(ROOT).as_posix(): sha(p) for p in inputs},
             api_calls=0, new_experiments=0, harness_pin_verified=True, guard_defaults_pin_verified=True,
             incomplete_shard_included=False, assertion_rows=len(property_rows))
(OUT / "review/property_addendum_proof_b.json").write_text(json.dumps(proof, indent=2) + "\n")
notes = f"""## Addendum B — DONE

Recomputed the six retained completed shards only: {totals['property_rows']} rows, {totals['property_distinct_models']} distinct model hashes, {totals['property_distinct_configurations']} distinct configurations. The incomplete shard remains excluded; no top-up or new experiment.

The retained rows contain {len(requests)} default-mode request probes: {len(admitted)} admitted and {len(rejected)} rejected. Rejection is an expected tested outcome, not a violation. Additionally, {len(admitted)} drop_log injected-proposal probes and {len(commits)} commit success/drift pairs are evidenced by the pinned harness, per-shard counters and terminal pass rows. Setup refusals: {len(refused)}; counterexample rows: {len(counterexamples)}. Across the {len(property_rows)} explicitly separated property assertions, {totals['property_assertion_observations']} assertion observations pass and {totals['property_assertion_violations']} violate. Assertion counts overlap and must not be presented as independent models.

T13 gives per-assertion observations, passes, violations, setup refusals and distinct models. T13b gives per-guard-mode coverage. Default is {json.dumps(defaults, sort_keys=True)}. Other modes are explicitly NOT_TESTED_IN_THIS_CAMPAIGN, not assigned a pass. A terminal pass plus hash-pinned historical control flow establishes assertions whose operands were not fully serialized; the table distinguishes these from direct retained-field comparisons. No stronger claim of independent assertion re-execution is made.

All numeric old/new comparisons and input hashes are retained in the property addendum log/proof. No API calls, backend execution or network activity.
"""
(OUT / "review/item_notes_property_b.md").write_text(notes, encoding="utf-8")
