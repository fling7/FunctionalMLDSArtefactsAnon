"""Frozen, budgeted real pipeline runner and offline corpus reporting.

No generation runs until the orchestrator freezes prereg/wp5_plan.json by SHA256.
All prompts are synthetic. Unit tests use explicit doubles; real runs never do.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/"app/backend_root/agent_backend"
if str(BACKEND) not in sys.path: sys.path.insert(0,str(BACKEND))
from backend.roomcontract_adapter import RoomContractAdapter, COMMIT_STAGE_IDS
from repro.llm import experiment_context, sanitize
from repro import env as _credential_env
load_env = getattr(_credential_env, 'load_env')
from experiments.scenes.generate_scenes import generate, canonical

PLAN_PATH=ROOT/"prereg/wp5_plan.json"
FREEZE_PATH=ROOT/"prereg/wp5_plan.sha256"
MODELS=("gpt-4.1-mini-2025-04-14","gpt-4.1-2025-04-14")
LLM_STAGES={
    "scene_semantics":{"input_ceiling":12000,"output_cap":1800,"total_stage_attempts":2},
    "agent_roles":{"input_ceiling":16000,"output_cap":2200,"total_stage_attempts":2},
    "knowledge_synthesis":{"input_ceiling":18000,"output_cap":3200,"total_stage_attempts":2},
}
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stamp(): return datetime.now(timezone.utc).isoformat()

def write_once(path: Path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    text=canonical(value)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError("Refusing to overwrite an existing raw result.")
    else: path.write_text(text,encoding="utf-8",newline="\n")

def selected_sources(rows, count=30):
    candidates=[r for r in rows if r["split"]=="evaluation"]
    ranked=sorted(candidates,key=lambda r:hashlib.sha256(("wp5-eval-seed-20261015:"+r["scene_id"]).encode()).hexdigest())
    selected=[]
    for domain in sorted({r["domain"] for r in candidates}):
        selected.append(next(r for r in ranked if r["domain"]==domain))
    while len(selected)<count:
        counts={size:sum(r["object_count"]==size for r in selected) for size in (15,24,40,80)}
        available=[r for r in ranked if r not in selected]
        chosen=min(available,key=lambda r:(counts[r["object_count"]],ranked.index(r)))
        selected.append(chosen)
    return selected

def make_plan():
    if FREEZE_PATH.exists(): raise RuntimeError("Plan is frozen; append an amendment instead of rewriting it.")
    corpus=generate()
    prices=json.loads((ROOT/"repro/prices.json").read_text(encoding="utf-8-sig"))["models"]
    per_stage={}
    for model in MODELS:
        rates=prices[model]
        per_stage[model]={stage:format((Decimal(rates["input_per_million"])*settings["input_ceiling"]+
                                      Decimal(rates["output_per_million"])*settings["output_cap"])/1_000_000,".9f")
                          for stage,settings in LLM_STAGES.items()}
    costs={model:sum(Decimal(v) for v in stage_costs.values()) for model,stage_costs in per_stage.items()}
    selection=selected_sources(corpus["scenes"])
    development=[]
    for i,row in enumerate(r for r in corpus["scenes"] if r["split"]=="dev"):
        development.append({"scene_id":row["scene_id"],"source_path":row["path"],"source_sha256":row["sha256"],
                            "model":MODELS[i%2],"repetition":0,"phase":"development"})
    evaluation=[]
    # First pass prioritizes distinct rooms and alternates models; second pass pairs them.
    for block in (0,1):
        for i,row in enumerate(selection if block==0 else selection[:20]):
            evaluation.append({"scene_id":row["scene_id"],"source_path":row["path"],"source_sha256":row["sha256"],
                               "model":MODELS[(i+block)%2],"repetition":0,"phase":"evaluation","balanced_block":block})
    dev_cost=sum(costs[row["model"]] for row in development)
    eval_cost=sum(costs[row["model"]] for row in evaluation)
    implementation=[Path(__file__).resolve(),ROOT/"repro/llm.py",ROOT/"repro/budget.py",ROOT/"repro/prices.json",
                    ROOT/"experiments/scenes/generate_scenes.py",BACKEND/"backend/roomcontract_adapter.py",
                    BACKEND/"backend/openai_client.py",BACKEND/"backend/roomcontract_v2_runtime.py",
                    ROOT/"tools/dynamic_functional_rdl_v2_model.py",ROOT/"tools/validate_dynamic_functional_rdl_v2.py"]
    implementation += sorted((ROOT/"tools/case_study_pipeline").rglob("*.py"))
    implementation += sorted((ROOT/"tools/case_study_pipeline/schemas").glob("*.json"))
    implementation += [ROOT/"tools/routing_verifier.py"]
    prompts=sorted((ROOT/"tools/case_study_pipeline/prompts").glob("*.md"))
    plan={"schema":"wp5-frozen-plan-v1","created_at":stamp(),"models":list(MODELS),"temperature":0.3,
          "stage_order":list(COMMIT_STAGE_IDS),"llm_stages":LLM_STAGES,"development":development,"evaluation":evaluation,
          "selected_evaluation_sources":[r["scene_id"] for r in selection],
          "paired_evaluation_sources":[r["scene_id"] for r in selection[:20]],
          "unpaired_evaluation_sources":[r["scene_id"] for r in selection[20:]],
          "source_manifest_sha256":digest(ROOT/"experiments/scenes/sources/manifest.json"),
          "implementation_sha256":{p.relative_to(ROOT).as_posix():digest(p) for p in implementation},
          "prompt_sha256":{p.relative_to(ROOT).as_posix():digest(p) for p in prompts},
          "budget":{"total_cap_usd":"20.000000000","WP5_share_usd":"6.000000000","WP5_stop_usd":"5.400000000",
                    "first_attempt_room_ceiling_usd":{k:format(v,".9f") for k,v in costs.items()},
                    "stage_attempt_ceiling_usd":per_stage,"development_first_attempt_ceiling_usd":format(dev_cost,".9f"),
                    "evaluation_first_attempt_ceiling_usd":format(eval_cost,".9f"),
                    "baseline_total_ceiling_usd":format(dev_cost+eval_cost,".9f"),
                    "remaining_for_repairs_unknown_outcomes_usd":format(Decimal("5.4")-dev_cost-eval_cost,".9f"),
                    "all_stage_second_attempts_ceiling_usd":format(2*(dev_cost+eval_cost),".9f")},
          "preregistered_outcomes":["pipeline_success","failure_stage","infrastructure_error","needs_manual_review","repair_attempts",
                                    "before_and_after_artifacts","routing_verifier_report_if_materialized"],
          "failure_rule":"Keep every selected source/model run. Stop at first unsuccessful stage. Save all outputs and failed response evidence. Never replace a failure with a deterministic fake room.",
          "repair_rule":"Each LLM stage allows at most two stage attempts (one repair). HTTP retries are separately limited by the gateway and charged pessimistically.",
          "reduction_order":["Complete the first pass over distinct evaluation sources before paired second pass.",
                             "Stop immediately when the shared WP5 ledger refuses a reservation. Keep incomplete room as data.",
                             "Do not add LLM-written scenes, regeneration repeats, judges or evolution API work until an appended, frozen numeric amendment fits the remaining share."],
          "unfunded_targets":{"llm_written_source_scenes":8,"full_source_two_model_pipeline_runs":96,
                              "regeneration_scenes":12,"regenerations_per_scene_per_model":5},
          "limitations":"Successful-room minimum is not guaranteed. Worst case with every repair exceeds allocation. Original minimums not reached remain PARTIAL."}
    PLAN_PATH.parent.mkdir(exist_ok=True)
    PLAN_PATH.write_text(canonical(plan),encoding="utf-8",newline="\n")
    md=["# WP5 preregistered execution plan (pending orchestrator freeze)","",
        "Generated by python -m experiments.pipeline_runs --plan. Freeze wp5_plan.json by its SHA256 and commit before any development or evaluation generation.",
        "Only the frozen JSON defines selections, order, model snapshots, prompt hashes, implementation/analysis hashes and parameters.","",
        "The deterministic source corpus and synthetic programmatic builder are not LLM-generated room evidence.",
        "The first pass prioritizes 30 distinct rooms while alternating the two models; a second pass generates the paired counterparts for the first 20 sources. Ten sources remain explicitly unpaired. Three separate dev rooms precede evaluation. Development does not tune evaluation prompts.","",
        "| Quantity | USD ceiling |","|---|---:|"]
    for name,value in plan["budget"].items():
        if isinstance(value,str): md.append("| "+name+" | "+value+" |")
    md += ["","Per-room first-attempt ceilings, derived from fixed input ceilings and maximum output tokens:"]
    md += ["- "+model+": "+value+" USD." for model,value in plan["budget"]["first_attempt_room_ceiling_usd"].items()]
    md += ["","These are upper bounds for generation attempts accepted by the input/output ceilings, not forecasts. Exact token counts below the ceiling usually reserve less. Every stage can have one repair; HTTP 429/5xx retries and unknown outcomes also consume the allocation. The maximum if every stage repairs exceeds the stop threshold, so completion is conditional. Counts and failures are never hidden.","",
           "Source selection is fixed in selected_evaluation_sources; all selected files and all stage prompts are hashed. Output limits preserve packet values; the experiment-only hook sets temperature to the mission's main setting. Requests exceeding a fixed input ceiling stop before generation and are recorded as failures, rather than shortening prompts after seeing outcomes.","",
           "Before each call, preserve current intermediate and validation artifacts. Save each raw response, and preserve the final stage artifacts after validation. Original invalid results therefore remain available before repairs. Failures terminate the room pipeline and remain in the denominator. No generated project is written to the packet projects directory.","",
           "The runner generates an offline summary from raw run records; its own source hash is the analysis hash. Room is the primary unit; source/model runs and stage calls are nested observations. Natural-fault classification is delegated to the independently implemented checks and recorded separately.","",
           "Eight LLM-written scenes, the full two-model source corpus, and repeated regenerations are budget-conditional and currently unfunded. They must be reported PARTIAL unless later frozen amendments and real calls fund them.","",
           "No paid call is authorized by generating this file. The orchestrator must review the estimate, freeze the JSON, commit hooks, and then explicitly launch development or evaluation."]
    (ROOT/"prereg/WP5_PLAN.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    return plan

def load_frozen_plan():
    if not FREEZE_PATH.exists(): raise RuntimeError("WP5 plan is not frozen; paid runs are prohibited.")
    if FREEZE_PATH.read_text().strip().split()[0]!=digest(PLAN_PATH): raise RuntimeError("Frozen WP5 plan hash mismatch.")
    plan=json.loads(PLAN_PATH.read_text())
    expected_implementation=dict(plan["implementation_sha256"])
    prior_freeze=digest(PLAN_PATH)
    amendments=[]
    for sequence,path in enumerate(sorted((ROOT/"prereg/wp5_amendments").glob("*.json")),1):
        frozen=path.with_suffix(".sha256")
        if not frozen.exists() or frozen.read_text().strip().split()[0]!=digest(path):
            raise RuntimeError("Execution amendment is not frozen or its hash changed: "+path.name)
        amendment=json.loads(path.read_text())
        if amendment.get("sequence")!=sequence or amendment.get("prior_freeze_sha256")!=prior_freeze:
            raise RuntimeError("Execution amendment sequence or predecessor mismatch.")
        if amendment.get("kind")!="implementation-only":
            raise RuntimeError("Only implementation amendments are supported; frozen prompts and sample settings cannot change.")
        updates=amendment.get("implementation_updates",{})
        if not updates: raise RuntimeError("Execution amendment contains no implementation updates.")
        for rel,change in updates.items():
            resolved=(ROOT/rel).resolve()
            if not resolved.is_relative_to(ROOT.resolve()) or change.get("old_sha256")!=expected_implementation.get(rel):
                raise RuntimeError("Execution amendment path or old source hash mismatch.")
            expected_implementation[rel]=change["new_sha256"]
        prior_freeze=digest(path)
        amendments.append({"path":path.relative_to(ROOT).as_posix(),"sha256":prior_freeze,"sequence":sequence})
    for mapping in (expected_implementation,plan["prompt_sha256"]):
        for rel,expected in mapping.items():
            if digest(ROOT/rel)!=expected: raise RuntimeError("Frozen implementation or prompt changed: "+rel)
    if amendments: plan["_execution_amendments"]=amendments
    for row in [*plan["development"],*plan["evaluation"]]:
        if digest(ROOT/row["source_path"])!=row["source_sha256"]: raise RuntimeError("Frozen source scene changed.")
    return plan

@contextmanager
def environment(values):
    before={k:os.environ.get(k) for k in values}
    os.environ.update(values)
    try: yield
    finally:
        for k,value in before.items():
            if value is None: os.environ.pop(k,None)
            else: os.environ[k]=value

def archive_snapshot(case_dir: Path, destination: Path):
    for section in ("intermediate","validation","roomcontract"):
        source=case_dir/section
        if not source.exists(): continue
        for path in sorted(source.rglob("*")):
            if not path.is_file(): continue
            target=destination/section/path.relative_to(source)
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if digest(target)==digest(path): continue
                target=target.with_name(target.name+".retained-"+digest(path)[:12])
                if target.exists(): continue
            shutil.copyfile(path,target)

def run_case(row,plan,*,replay=False):
    model_tag="mini" if "mini" in row["model"] else "full"
    case_id=row["scene_id"]+"_"+model_tag+"_r"+str(row["repetition"])
    run_root=ROOT/"results/raw/wp5"/row["phase"]/case_id
    final_path=run_root/"run_result.json"
    if final_path.exists():
        prior=json.loads(final_path.read_text())
        if prior["plan_sha256"]!=digest(PLAN_PATH) or prior["source"]!=row:
            raise RuntimeError("Existing run belongs to a different frozen plan or source; preserve it and use an explicit amendment.")
        return prior
    source=json.loads((ROOT/row["source_path"]).read_text())
    runtime=ROOT/"results/wp5_runtime"
    runtime.mkdir(parents=True,exist_ok=True)
    adapter=RoomContractAdapter.discover(workspace_root=ROOT,backend_root=runtime,output_root=ROOT/"results/raw/wp5/cases")
    initialized=adapter.initialize_case_from_payload(source,case_id=case_id)
    case_dir=Path(initialized["case_dir"])
    write_once(run_root/"run_start.json",{"source":row,"plan_sha256":digest(PLAN_PATH),"case_id":case_id,"execution_amendments":plan.get("_execution_amendments",[])})
    records=[]
    result={"source":row,"case_id":case_id,"plan_sha256":digest(PLAN_PATH),"status":"success","stages":records,
            "project_dir":(runtime/"projects"/case_id).relative_to(ROOT).as_posix(),"replay":replay,
            "execution_amendments":plan.get("_execution_amendments",[])}
    with environment({"ROOMCONTRACT_LLM_GATEWAY":"1","LLM_REPLAY":"1" if replay else "0"}):
        if not replay: load_env()
        for stage in plan["stage_order"]:
            checkpoint=run_root/"stages"/(stage+".json")
            if checkpoint.exists():
                record=json.loads(checkpoint.read_text()); records.append(record)
                if record["status"]!="success":
                    result["status"]="failed"; result["failure_stage"]=stage; break
                continue
            settings=plan["llm_stages"].get(stage)
            archive_root=run_root/"stage_artifacts"/stage
            def before(index,payload):
                archive_snapshot(case_dir,archive_root/f"attempt_{index:02d}"/"before")
                write_once(archive_root/f"attempt_{index:02d}"/"request.json",sanitize(payload))
            def after(index,response):
                write_once(archive_root/f"attempt_{index:02d}"/"response.json",sanitize(response))
            started=time.perf_counter()
            kwargs={}
            if settings:
                kwargs={"model_override":row["model"],"max_repair_attempts":settings["total_stage_attempts"],"config_path":BACKEND/"config.json"}
            try:
                with experiment_context(experiment_id="WP5."+row["phase"],item_id=row["scene_id"],
                    repetition_id=str(row["repetition"])+"."+model_tag,share="WP5",stage_id=stage,root=ROOT,replay=replay,
                    max_output_tokens=settings["output_cap"] if settings else 4096,
                    max_input_tokens=settings["input_ceiling"] if settings else None,
                    model=row["model"],temperature=plan["temperature"],before_call=before,after_call=after):
                    with redirect_stdout(io.StringIO()):
                        stage_result=adapter.run_stage(case_dir,stage,**kwargs)
                record={"stage":stage,"status":stage_result.get("status","failed"),"result":sanitize(stage_result),
                        "elapsed_seconds":time.perf_counter()-started}
            except Exception as exc:
                record={"stage":stage,"status":"failed","error_code":getattr(exc,"code",type(exc).__name__),
                        "elapsed_seconds":time.perf_counter()-started}
            archive_snapshot(case_dir,archive_root/"after_stage")
            record["archived_call_attempts"]=len(list(archive_root.glob("attempt_*")))
            write_once(checkpoint,record)
            records.append(record)
            if record["status"]!="success":
                result["status"]="failed"; result["failure_stage"]=stage
                break
    result["stage_call_attempts"]=sum(r["archived_call_attempts"] for r in records)
    result["repair_attempts"]=sum(max(0,r["archived_call_attempts"]-1) for r in records)
    project_dir=runtime/"projects"/case_id
    if project_dir.exists():
        try:
            from tools.routing_verifier import load_and_verify
            verification=load_and_verify(project_dir/"roomcontract.v2.instance.json",project_dir/"trace_map.v2.json",project_dir/"project.json")
            write_once(run_root/"routing_verifier.json",verification)
        except Exception as exc:
            write_once(run_root/"routing_verifier_error.json",{"error_type":type(exc).__name__})
    result["artifact_sha256"]={p.relative_to(ROOT).as_posix():digest(p)
                               for directory in (run_root,case_dir,project_dir)
                               if directory.exists() for p in sorted(directory.rglob("*"))
                               if p.is_file() and p!=final_path}
    write_once(final_path,result)
    return result

def summarize():
    paths=sorted((ROOT/"results/raw/wp5").glob("*/*/run_result.json")) if (ROOT/"results/raw/wp5").exists() else []
    runs=[json.loads(p.read_text()) for p in paths]
    corpus=json.loads((ROOT/"experiments/scenes/sources/manifest.json").read_text())
    summary={"source_corpus":corpus["counts"],"source_size_range":corpus["size_range"],"pipeline_runs":len(runs),
             "successful_runs":sum(r["status"]=="success" for r in runs),"failed_runs":sum(r["status"]!="success" for r in runs),
             "distinct_evaluation_sources":len({r["source"]["scene_id"] for r in runs if r["source"]["phase"]=="evaluation"}),
             "successful_evaluation_sources":len({r["source"]["scene_id"] for r in runs if r["source"]["phase"]=="evaluation" and r["status"]=="success"}),
             "repair_attempts":sum(r["repair_attempts"] for r in runs),"rows":runs,
             "by_model":{model:{"runs":sum(r["source"]["model"]==model for r in runs),
                                  "successes":sum(r["source"]["model"]==model and r["status"]=="success" for r in runs)}
                         for model in MODELS},
             "paired_evaluation_sources_observed":sum(
                 len({r["source"]["model"] for r in runs if r["source"]["phase"]=="evaluation" and r["source"]["scene_id"]==sid})==2
                 for sid in {r["source"]["scene_id"] for r in runs if r["source"]["phase"]=="evaluation"}),
             "status":"NOT_RUN" if not runs else "PARTIAL",
             "limits":"Deterministic source scenes are not natural LLM-generated models. Success minima and optional LLM-authored/repeated corpora require real executed evidence."}
    path=ROOT/"results/processed/pipeline_summary.json"; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(canonical(summary),encoding="utf-8")
    lines=["# Corpus provenance and status","","Generated by python -m experiments.pipeline_runs --report from source manifest and raw run records.","",
           "| Measure | Count |","|---|---:|"]
    for key,value in {**{"source_"+k:v for k,v in summary["source_corpus"].items()},
                      **{k:v for k,v in summary.items() if type(v) is int}}.items():
        lines.append("| "+key+" | "+str(value)+" |")
    lines += ["","Pipeline status: "+summary["status"]+".",
              "", "The source generator uses an open grid with nonoverlapping footprints and validates every scene through packet ingestion. Domain vocabulary varies across rooms; geometric diversity is limited to this one family. Sources are synthetic authored inputs, not evidence of naturally occurring model faults.",
              "", "The three development sources are separate from evaluation. Exact selected evaluation sources and model order are in prereg/wp5_plan.json.",
              "", "Real LLM stage outputs, before-repair states, raw responses and final validation files are retained per run. A pipeline failure is a result, not an excluded source.",
              "", "Eight LLM-written scenes and the requested repeated-generation corpus are not currently funded; their absence remains an explicit partial-result limitation.",
              "", "The separate model builder creates canonical V2 fixtures for tests and mutations. Those fixtures must never be counted as LLM-generated rooms or independent external models."]
    (ROOT/"docs/CORPUS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return summary


def budget_stop_record(value):
    """Recognize explicit stop codes, never the gateway's generic label."""
    if isinstance(value, dict):
        if any(value.get(key) in {"BUDGET_STOP", "BudgetError"} for key in
               ("error_code", "gateway_error", "code", "status") if isinstance(value.get(key), str)):
            return True
        return any(budget_stop_record(item) for item in value.values())
    if isinstance(value, list):
        return any(budget_stop_record(item) for item in value)
    return isinstance(value, str) and value == "Budgeted gateway stopped request: BUDGET_STOP"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--plan",action="store_true")
    parser.add_argument("--report",action="store_true")
    parser.add_argument("--run",choices=("development","evaluation"))
    parser.add_argument("--replay",action="store_true")
    parser.add_argument("--limit",type=int,default=None,help="Run a prefix only; reports remain partial.")
    args=parser.parse_args()
    if args.limit is not None and args.limit < 1: parser.error("--limit must be positive")
    if args.plan:
        plan=make_plan(); print(json.dumps(plan["budget"]))
    if args.run:
        plan=load_frozen_plan()
        selected=plan[args.run][:args.limit]
        for row in selected:
            result=run_case(row,plan,replay=args.replay)
            print(json.dumps({"case_id":result["case_id"],"status":result["status"],"failure_stage":result.get("failure_stage")}))
            if budget_stop_record(result):
                break
    if args.report or args.run:
        summary=summarize()
        print(json.dumps({k:v for k,v in summary.items() if type(v) is int or k=="status"}))
if __name__=="__main__": main()

