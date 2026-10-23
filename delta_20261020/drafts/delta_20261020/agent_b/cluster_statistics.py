"""Offline room-cluster estimates from retained observations; no network imports."""
from pathlib import Path
import collections
import csv
import hashlib
import json
from datetime import datetime, timezone
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "deliverables/delta_20261020"
SCRIPT = Path(__file__).relative_to(ROOT).as_posix()
SEED, RESAMPLES = 20261015, 10000
started = datetime.now(timezone.utc).isoformat()
inputs = [ROOT / "data/go_sprint/wp4_wp5/routing_primary_525.jsonl",
          ROOT / "numbers.json", ROOT / "tables/T2_routing_baselines.csv"]
old_numbers = json.loads(inputs[1].read_text())
old_table = list(csv.DictReader(inputs[2].open(newline="", encoding="utf-8-sig")))
primary = [json.loads(s) for s in inputs[0].read_text().splitlines()]
primary = [r for r in primary if r["split"] == "evaluation" and r["baseline"] in ("B0", "B1")]
reject_files = sorted((ROOT / "data/go_sprint/sprint/w3/rows").glob("reject_sprint_*.json"))
inputs += reject_files
reject = [json.loads(p.read_text()) for p in reject_files]
for r in primary:
    r["room"] = r["source_room_id"]
assert len(primary) == 480 and len({r["room"] for r in primary}) == 20
assert len(reject) == 270
assert all(r["status"] == "SUCCESS" for r in primary + reject)
assert len({r["item_id"] for r in primary}) == 480
assert len({r["item_id"] for r in reject}) == 270
log = []

def record(key, old, new):
    changed = old is not None and old != new
    entry = dict(key=key, old=old, new=new, script=SCRIPT,
                 flag="CHANGED" if changed else ("NEW_ESTIMATE" if old is None else "UNCHANGED"))
    log.append(entry)
    print(json.dumps(entry, ensure_ascii=True))

def ci(draws):
    return [float(x) for x in np.quantile(draws, [.025, .975], method="linear")]

def bootstrap(rows, arms, outcome):
    rooms = sorted({r["room"] for r in rows})
    count = np.array([[sum(r["room"] == room and r["baseline"] == arm for r in rows)
                       for arm in arms] for room in rooms], dtype=int)
    hits = np.array([[sum(r["room"] == room and r["baseline"] == arm and r["outcome"] == outcome for r in rows)
                      for arm in arms] for room in rooms], dtype=int)
    assert (count > 0).all(), "Unpaired room/arm cell"
    # Preserve every call within each selected room and pair identical room draws across arms.
    idx = np.random.default_rng(SEED).integers(0, len(rooms), (RESAMPLES, len(rooms)))
    call_draws = hits[idx].sum(axis=1) / count[idx].sum(axis=1)
    room_draws = (hits / count)[idx].mean(axis=1)
    return rooms, count, hits, call_draws, room_draws

def write_table(name, rows, old_lookup=None):
    dest = OUT / "tables" / name
    with dest.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for i, row in enumerate(rows):
            writer.writerow(row)
            for key, value in row.items():
                if isinstance(value, (int, float, list)):
                    record(f"{name}[{i}].{key}", old_lookup(row, key) if old_lookup else None, value)

rooms, n, hits, draws, room_draws = bootstrap(primary, ["B0", "B1"], "WRONG_PROVIDER")
assert (n == 12).all()
primary_rows = []
for i, room in enumerate(rooms):
    rr = [r for r in primary if r["room"] == room and r["outcome"] == "WRONG_PROVIDER"]
    primary_rows.append(dict(room=room, B0_calls=int(n[i, 0]), B1_calls=int(n[i, 1]),
                             B0_wrong=int(hits[i, 0]), B1_wrong=int(hits[i, 1]),
                             wrong_rate_B0_minus_B1=float(hits[i, 0]/n[i, 0]-hits[i, 1]/n[i, 1]),
                             deviation_models=";".join(sorted(collections.Counter(r["model"] for r in rr))),
                             deviation_item_ids=";".join(r["item_id"] for r in rr)))
write_table("T2b_primary_per_room.csv", primary_rows)
primary_summary = dict(n_calls=len(primary), n_rooms=len(rooms), calls_per_arm=int(n[:, 0].sum()),
                       B0_wrong=int(hits[:, 0].sum()), B1_wrong=int(hits[:, 1].sum()),
                       wrong_rate_B0_minus_B1=float(hits[:, 0].sum()/n[:, 0].sum()-hits[:, 1].sum()/n[:, 1].sum()),
                       room_cluster_percentile95=ci(draws[:, 0]-draws[:, 1]),
                       rooms_with_deviations=sum(r["B0_wrong"] > 0 for r in primary_rows),
                       bootstrap_resamples=RESAMPLES, bootstrap_seed=SEED)
write_table("T2b_primary_cluster_summary.csv", [primary_summary])
models = ["ALL"] + sorted({r["model"] for r in reject})
faults = ["ALL"] + sorted({r["fault_class"] for r in reject})
summary, paired, per_room = [], [], []
arms = ["B0", "B1", "B1r"]
for model in models:
    for fault in faults:
        subset = [r for r in reject if (model == "ALL" or r["model"] == model)
                  and (fault == "ALL" or r["fault_class"] == fault)]
        if fault in ("duplicate_asset_owner", "remove_all_owners"):
            assert len({r["room"] for r in subset}) == 8
        for outcome in ["SILENT_VIOLATION", "ABSTAIN_OK"]:
            room_ids, counts, successes, samples, equal_samples = bootstrap(subset, arms, outcome)
            assert (counts[:, 0] == counts[:, 1]).all() and (counts[:, 1] == counts[:, 2]).all()
            for j, arm in enumerate(arms):
                row = dict(arm=arm, model=model, fault_class=fault, outcome=outcome,
                           n_calls=int(counts[:, j].sum()), n_rooms=len(room_ids),
                           count=int(successes[:, j].sum()),
                           call_weighted_rate=float(successes[:, j].sum()/counts[:, j].sum()),
                           call_weighted_room_cluster95=ci(samples[:, j]),
                           equal_room_rate=float((successes[:, j]/counts[:, j]).mean()),
                           equal_room_cluster95=ci(equal_samples[:, j]))
                summary.append(row)
                for i, room in enumerate(room_ids):
                    per_room.append(dict(arm=arm, model=model, fault_class=fault, outcome=outcome,
                                         room=room, n_calls=int(counts[i, j]),
                                         count=int(successes[i, j]),
                                         rate=float(successes[i, j]/counts[i, j])))
            for left, right in [(2, 1), (2, 0), (1, 0)]:
                paired.append(dict(contrast=f"{arms[left]}-minus-{arms[right]}", model=model,
                                   fault_class=fault, outcome=outcome, n_paired_rooms=len(room_ids),
                                   calls_per_arm=int(counts[:, left].sum()),
                                   call_weighted_difference=float(successes[:, left].sum()/counts[:, left].sum()-successes[:, right].sum()/counts[:, right].sum()),
                                   paired_room_cluster95=ci(samples[:, left]-samples[:, right]),
                                   equal_room_difference=float((successes[:, left]/counts[:, left]-successes[:, right]/counts[:, right]).mean()),
                                   equal_room_paired95=ci(equal_samples[:, left]-equal_samples[:, right])))
                for i, room in enumerate(room_ids):
                    per_room.append(dict(arm=f"{arms[left]}-minus-{arms[right]}", model=model,
                                         fault_class=fault, outcome=outcome, room=room,
                                         n_calls=int(counts[i, left]),
                                         count=int(successes[i, left]-successes[i, right]),
                                         rate=float(successes[i, left]/counts[i, left]-successes[i, right]/counts[i, right])))

def old_reject(row, key):
    match = [r for r in old_table if r["cohort"] == "reject_sprint" and r["baseline"] == row["arm"]
             and r["model"] == row["model"] and r["fault_class"] == row["fault_class"]]
    if len(match) != 1:
        return None
    r = match[0]
    if key == "n_calls": return int(r["successful_calls"])
    if key == "n_rooms": return int(r["rooms"])
    if key == "count": return int(r[row["outcome"]])
    if key == "call_weighted_rate": return int(r[row["outcome"]])/int(r["successful_calls"])
    if key == "call_weighted_room_cluster95" and row["outcome"] == "SILENT_VIOLATION":
        return json.loads(r["silent_violation_room_cluster95"])
    return None

write_table("T2c_reject_room_cluster.csv", summary, old_reject)
write_table("T2d_reject_paired_room_differences.csv", paired)
write_table("T2e_reject_per_room.csv", per_room)
number_delta = {
    "B0_primary_wrong": primary_summary["B0_wrong"],
    "B1_primary_wrong": primary_summary["B1_wrong"],
    "routing_evaluation_calls": len(primary), "routing_evaluation_rooms": len(rooms),
    "reject_experiment_retained": len(reject), "reject_experiment_successful_calls": len(reject),
    "delta_primary_cluster_statistics": primary_summary,
    "delta_reject_cluster_statistics": {
        "effective_resampling_unit": "source room; all calls and arms in each selected room retained together",
        "fault_class_distinct_rooms": {f: len({r["room"] for r in reject if r["fault_class"] == f})
                                      for f in ("duplicate_asset_owner", "remove_all_owners")},
        "bootstrap_seed": SEED, "bootstrap_resamples": RESAMPLES,
        "interval": "two-sided 95% percentile, NumPy linear quantile",
        "estimands": "call-weighted rates (primary) and equal-room rates (sensitivity); paired arm differences",
        "rows": summary, "paired_contrasts": paired,
    },
}
for key, value in number_delta.items():
    record(f"numbers.{key}", old_numbers.get(key), value)
(OUT / "review/numbers_b.json").write_text(json.dumps(number_delta, indent=2) + "\n")
proof = dict(status="DONE", started_utc=started, ended_utc=datetime.now(timezone.utc).isoformat(),
             script=SCRIPT, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             inputs={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
             assertions=["480 primary calls, 20 rooms, 240 per arm",
                         "all 270 reject calls successful and unique",
                         "8 distinct rooms per manipulated fault class (per model and overall)",
                         "exact equal within-room call denominators across every paired arm"],
             api_calls=0, numpy_version=np.__version__)
(OUT / "review/cluster_statistics_proof_b.json").write_text(json.dumps(proof, indent=2) + "\n")
(OUT / "review/cluster_statistics_numeric_log_b.jsonl").write_text(
    "".join(json.dumps(r, ensure_ascii=True) + "\n" for r in log))
deviant = "; ".join(f"{r['room']}: {r['B0_wrong']}" for r in primary_rows if r["B0_wrong"])
notes = f"""## Item 2 — DONE

Saved-script recomputation only; original data/tables/numbers untouched. Primary routing retains {len(primary)} cells over {len(rooms)} rooms, {primary_summary['calls_per_arm']} calls per arm. B0/B1 wrong-provider counts remain {primary_summary['B0_wrong']}/{primary_summary['B1_wrong']}. The B0-minus-B1 wrong-provider rate difference is {primary_summary['wrong_rate_B0_minus_B1']:.12g}, with room-cluster 95% percentile CI {primary_summary['room_cluster_percentile95']}. The deviations occur in {primary_summary['rooms_with_deviations']} room(s): {deviant}.

All {len(reject)} reject-study calls are retained, including direct/local controls. Each manipulated fault class has exactly 8 distinct source rooms, verified separately for each model and pooled. Repeated calls/model/arm observations are not independent rooms. T2c reports counts, call-weighted rates and room-cluster intervals for every arm/model/fault, plus pooled rows. T2d contains paired contrasts B1r-minus-B1, B1r-minus-B0 and B1-minus-B0, for silent violation and valid abstention. T2e exposes all per-room rates and contrasts.

Decision: resample rooms with replacement, retaining all within-room observations and shared paired arm indices; seed {SEED}, {RESAMPLES} resamples per estimand. Main estimand is pooled call-weighted rate, matching old T2; equal-room means/intervals are provided as sensitivity because rooms have unequal call counts. These are distinct estimands, not changes in outcomes. No smoothing, pseudocounts or independent-call CI. Constant outcomes can produce degenerate [0,0] or [1,1] percentile intervals, which do not establish population certainty. Eight rooms per manipulated class is a small effective sample.

Old matched T2 counts and rates are checked in cluster_statistics_numeric_log_b.jsonl; any different interval is explicitly CHANGED. New estimands have old=null / NEW_ESTIMATE. Full retained-data SHA256 pins are in cluster_statistics_proof_b.json. Scripts make zero API calls.
"""
(OUT / "review/item_notes_b.md").write_text(notes, encoding="utf-8")
