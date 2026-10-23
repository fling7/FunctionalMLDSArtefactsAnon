"""Export public WP5 provenance from frozen selections and retained run records."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def export(destination=ROOT/"results/processed/wp5_projects.json"):
    plan=read(ROOT/"prereg/wp5_plan.json")
    priorities={sid:i+1 for i,sid in enumerate(plan["selected_evaluation_sources"])}
    rows=[]
    for ordinal,selection in enumerate(plan["evaluation"],1):
        tag="mini" if "mini" in selection["model"] else "full"
        case_id=f"{selection['scene_id']}_{tag}_r{selection['repetition']}"
        result_path=ROOT/"results/raw/wp5/evaluation"/case_id/"run_result.json"
        if not result_path.exists():continue
        run=read(result_path)
        if run["source"]!=selection:raise ValueError("Run provenance differs from frozen selection.")
        project=ROOT/run["project_dir"];model=project/"roomcontract.v2.instance.json"
        if hashlib.sha256((ROOT/selection["source_path"]).read_bytes()).hexdigest()!=selection["source_sha256"]:
            raise ValueError("Frozen source file changed after generation.")
        if model.exists():
            expected=run.get("artifact_sha256",{}).get(model.relative_to(ROOT).as_posix())
            if expected is None or hashlib.sha256(model.read_bytes()).hexdigest()!=expected:
                raise ValueError("Native model bytes differ from the retained completed run.")
        stages={r["stage"]:r for r in run["stages"]}
        def passed(stage):return stages.get(stage,{}).get("status")=="success"
        verification=result_path.parent/"routing_verifier.json"
        gate0=read(verification) if verification.exists() else {}
        row={"source_room_id":selection["scene_id"],"source_priority":priorities[selection["scene_id"]],
             "run_ordinal":ordinal,"case_id":case_id,"project_path":run["project_dir"],"split":"evaluation",
             "pipeline_model":selection["model"],"repetition":selection["repetition"],
             "pipeline_success":run["status"]=="success","failure_stage":run.get("failure_stage"),
             "project_produced":model.exists(),"canonical_valid":passed("roomcontract_v2_assembly"),
             "schema_valid":passed("schema_validation"),"gate0_ok":gate0.get("ok"),
             "source_path":selection["source_path"],"source_sha256":selection["source_sha256"],
             "run_result_path":result_path.relative_to(ROOT).as_posix(),
             "run_result_sha256":hashlib.sha256(result_path.read_bytes()).hexdigest(),
             "model_sha256":hashlib.sha256(model.read_bytes().replace(b"\r\n",b"\n")).hexdigest().upper() if model.exists() else None}
        row["eligible_native_success"]=all(row[k] for k in ("pipeline_success","project_produced","canonical_valid","schema_valid"))
        rows.append(row)
    report={"schema":"wp5-public-project-provenance-v1",
            "base_plan_sha256":hashlib.sha256((ROOT/"prereg/wp5_plan.json").read_bytes()).hexdigest(),
            "unit":"source room with pipeline model runs nested","path_base":"workspace root",
            "selection_rule":"First distinct eligible sources by source_priority; preserve each selected model and run provenance.",
            "completed_runs":len(rows),"eligible_runs":sum(r["eligible_native_success"] for r in rows),
            "eligible_distinct_sources":len({r["source_room_id"] for r in rows if r["eligible_native_success"]}),
            "rows":rows}
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8",newline="\n")
    return report
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--output",type=Path,default=ROOT/"results/processed/wp5_projects.json")
    args=ap.parse_args();report=export(args.output)
    print(json.dumps({k:v for k,v in report.items() if type(v)is int}))

