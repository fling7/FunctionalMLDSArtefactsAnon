"""Separately preregistered exploratory WP5 extension; no default production changes.

This staged file is not executable until the reviewed plan, implementation, source
and budget-policy freezes are present. Unit tests use explicit mocked gateways.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import time
import jsonschema
from experiments.pipeline_runs import (ROOT,BACKEND,COMMIT_STAGE_IDS,digest,write_once,
    environment,archive_snapshot,RoomContractAdapter,budget_stop_record)
from experiments.scenes.generate_scenes import validate_source
from repro.llm import Gateway,GatewayError,experiment_context,sanitize
from repro import env as _credential_env
load_env = getattr(_credential_env, 'load_env')
from repro.budget import Budget
PLAN_PATH=ROOT/"prereg/wp5_extension_v1/plan.json"
FREEZE_PATH=PLAN_PATH.with_suffix(".sha256")
SOURCE_PATH=PLAN_PATH.parent/"accepted_sources.json"
def read(p):return json.loads(Path(p).read_text(encoding="utf-8-sig"))
def safe_path(relative):
    p=(ROOT/relative).resolve()
    if not p.is_relative_to(ROOT.resolve()):raise RuntimeError("Path escapes workspace")
    return p
def verify_freeze(path):
    side=path.with_suffix(".sha256")
    if not side.exists() or side.read_text(encoding="ascii").strip().split()[0]!=digest(path):
        raise RuntimeError("Required artifact freeze is missing or changed")
def load_plan(*,replay=False):
    verify_freeze(PLAN_PATH);plan=read(PLAN_PATH)
    if plan.get("status")!="FROZEN":raise RuntimeError("Extension plan is not authorized")
    for key in ("implementation_sha256","prompt_sha256","original_pipeline_prompt_sha256"):
        if not plan.get(key):raise RuntimeError("Required source registry is absent")
        for rel,expected in plan[key].items():
            if digest(safe_path(rel))!=expected:raise RuntimeError("Frozen source changed: "+rel)
    for row in plan["new_deterministic_sources"]:
        if digest(safe_path(row["path"]))!=row["sha256"]:raise RuntimeError("Deterministic source changed")
    policy_pin=plan.get("budget_policy_amendment")
    if not isinstance(policy_pin,dict):raise RuntimeError("Reviewed budget amendment and migration proof are not pinned")
    amendment_path=safe_path(policy_pin["path"]);proof_path=safe_path(policy_pin["proof_path"])
    verify_freeze(amendment_path)
    if digest(amendment_path)!=policy_pin["sha256"] or digest(proof_path)!=policy_pin["proof_sha256"]:raise RuntimeError("Frozen budget policy evidence changed")
    amendment=read(amendment_path);proof=read(proof_path)
    if amendment.get("kind")!="unused_wp7_to_wp5" or proof.get("amendment_sha256")!=policy_pin["sha256"] or proof.get("terminal") is not True or not proof.get("checks") or not all(proof["checks"].values()):raise RuntimeError("Budget migration proof is incomplete")
    if not replay:
        summary=Budget(ROOT/"logs/api_budget.sqlite3","20").summary()
        if summary["cap_usd"]!="20.000000000" or summary["allocations"]["WP5"]["stop_usd"]!="7.200000000" or summary["allocations"]["WP7"]["stop_usd"]!="0.000000000":
            raise RuntimeError("Reviewed budget migration has not been applied")
    return plan
def load_sources(plan):
    verify_freeze(SOURCE_PATH);manifest=read(SOURCE_PATH)
    if manifest["plan_sha256"]!=digest(PLAN_PATH):raise RuntimeError("Accepted sources belong to another plan")
    jsonschema.validate(manifest,read(safe_path(plan["accepted_source_schema_path"])))
    expected=[(r["family"],r["source_id"]) for r in plan["initial_baselines"]]
    if [(r["family"],r["source_id"]) for r in manifest["slots"]]!=expected:
        raise RuntimeError("Source freeze order differs from initial plan")
    for row in manifest["slots"]:
        if row["status"]=="accepted" and digest(safe_path(row["source_path"]))!=row["source_sha256"]:
            raise RuntimeError("Accepted source bytes changed")
        if row.get("source_authoring_result_path") and digest(safe_path(row["source_authoring_result_path"]))!=row["source_authoring_result_sha256"]:
            raise RuntimeError("Retained source-authoring provenance changed")
    return manifest
def source_schema():
    number={"type":"number"}
    vec={"type":"object","properties":{k:number for k in ("x","y","z")},"required":["x","y","z"],"additionalProperties":False}
    dims={"type":"object","properties":{k:number for k in ("width","height","depth")},"required":["width","height","depth"],"additionalProperties":False}
    group={"type":"object","properties":{"color":{"type":"string"}},"required":["color"],"additionalProperties":False}
    light={"type":"object","properties":{"lightType":{"type":"string"},"intensity":number,"color":{"type":"string"}},"required":["lightType","intensity","color"],"additionalProperties":False}
    env={"type":"object","properties":{"type":{"type":"string"},"dimensions":dims,"lighting":{"type":"array","items":light},"background":{"type":"string"}},"required":["type","dimensions","lighting","background"],"additionalProperties":False}
    obj={"type":"object","properties":{"objectId":{"type":"string"},"objectType":{"type":"string"},"position":vec,"rotation":vec,"dimensions":dims,"group":{"type":"string"},"children":{"type":"array","items":{"type":"string"}},"specification":{"type":"string"}},"required":["objectId","objectType","position","rotation","dimensions","group","children","specification"],"additionalProperties":False}
    scene={"type":"object","properties":{"sceneName":{"type":"string"},"environment":env,"objectGroups":{"type":"object","properties":{k:group for k in ("collection_1","collection_2","collection_3")},"required":["collection_1","collection_2","collection_3"],"additionalProperties":False},"objects":{"type":"array","items":obj}},"required":["sceneName","environment","objectGroups","objects"],"additionalProperties":False}
    return {"type":"object","properties":{"scene":scene},"required":["scene"],"additionalProperties":False}
def validate_authored_source(value,source_id):
    import math
    jsonschema.validate(value,source_schema())
    scene=value["scene"];objects=scene["objects"]
    if scene["sceneName"]!=source_id or len(objects)!=15:raise ValueError("Wrong scene identity or object count")
    if {o["objectId"] for o in objects}!={f"object_{i:03d}" for i in range(1,16)}:raise ValueError("Wrong object identities")
    if any(o["children"] for o in objects):raise ValueError("Authored source children must be empty")
    if any(any(v!=0 for v in o["rotation"].values()) for o in objects):raise ValueError("Axis-aligned source required")
    if any(not math.isfinite(v) or v<=0 for o in objects for v in o["dimensions"].values()):raise ValueError("Invalid dimensions")
    if scene["environment"]["dimensions"]!={"width":20,"height":4,"depth":20}:raise ValueError("Room dimensions must be 20 by 20 by 4 metres")
    if any(not math.isfinite(v) for o in objects for v in o["position"].values()):raise ValueError("Invalid position")
    if any(not .6<=o["dimensions"][k]<=1.0 for o in objects for k in ("width","depth")) or any(not .5<=o["dimensions"]["height"]<=1.8 for o in objects):raise ValueError("Authored object dimensions outside registered ranges")
    import re
    colors=[g["color"] for g in scene["objectGroups"].values()]
    if len(set(c.upper() for c in colors))!=3 or any(not re.fullmatch('#[0-9A-Fa-f]{6}',c) for c in colors):raise ValueError("Expected three distinct six-digit hex group colors")
    for i,o in enumerate(objects):
        for axis,dimension in (("x","width"),("z","depth")):
            if abs(o["position"][axis])+o["dimensions"][dimension]/2>9:raise ValueError("Full footprint must be inside the registered margin")
        for other in objects[i+1:]:
            dx=max(0,abs(o["position"]["x"]-other["position"]["x"])-(o["dimensions"]["width"]+other["dimensions"]["width"])/2)
            dz=max(0,abs(o["position"]["z"]-other["position"]["z"])-(o["dimensions"]["depth"]+other["dimensions"]["depth"])/2)
            if math.hypot(dx,dz)<1-1e-8:raise ValueError("Footprints must have at least one metre clearance")
    if any(abs(o["position"]["y"]-o["dimensions"]["height"]/2)>1e-8 for o in objects):raise ValueError("Object bottom must be on floor")
    if any(sum(o["group"]==g for o in objects)!=5 for g in scene["objectGroups"]):raise ValueError("Expected five objects per group")
    report=validate_source(value)
    report["geometry"]="nonoverlapping axis-aligned footprints inside room; model-authored layout, no deployment claim"
    return report
def output_text(response):
    return "\n".join(c["text"] for o in response.get("output",[]) if o.get("type")=="message" for c in o.get("content",[]) if c.get("type")=="output_text")
def author_source(slot,plan,*,replay=False,gateway=None):
    folder=ROOT/"results/raw/wp5_extension/source_authoring"/slot["source_id"]
    final=folder/"result.json"
    if final.exists():
        record=read(final)
        if record["plan_sha256"]!=digest(PLAN_PATH) or record["slot"]!=slot:raise RuntimeError("Existing authoring identity changed")
        return record
    gateway=gateway or Gateway(ROOT,replay=replay,count_input_tokens=True)
    prompt=safe_path("prereg/wp5_extension_v1/prompts/llm_source_v1.txt").read_text(encoding="utf-8")
    for key in ("domain","scene_id","layout"):
        prompt=prompt.replace("{"+key+"}",slot["source_id"] if key=="scene_id" else slot[key])
    attempts=[];previous_text="";previous_errors=[]
    result={"source_id":slot["source_id"],"slot":slot,"plan_sha256":digest(PLAN_PATH),"status":"source_authoring_failed","attempts":attempts}
    for attempt in (1,2):
        if attempt==1:instructions=prompt;input_text="Write the complete scene now."
        else:
            instructions=safe_path("prereg/wp5_extension_v1/prompts/llm_source_repair_v1.txt").read_text(encoding="utf-8")
            input_text=json.dumps({"original_request":prompt,"rejected_response":previous_text,"validation_errors":previous_errors},ensure_ascii=False)
        payload={"model":slot["model"],"input":input_text,"instructions":instructions,"temperature":slot["temperature"],
          "max_output_tokens":slot["output_cap"] if attempt==1 else slot["repair_output_cap"],
          "text":{"format":{"type":"json_schema","name":"synthetic_source_scene","strict":True,"schema":source_schema()}}}
        ap=folder/f"attempt_{attempt:02d}"
        write_once(ap/"request.json",sanitize(payload))
        try:
            response=gateway.responses(payload,experiment_id="WP5.extension.source_authoring",
              item_id=slot["source_id"],repetition_id=f"authoring_attempt{attempt}",share="WP5",
              max_input_tokens=slot["input_ceiling"] if attempt==1 else slot["repair_input_ceiling"])
            write_once(ap/"response.json",sanitize(response));previous_text=output_text(response)
        except Exception as exc:
            error={"error_code":getattr(exc,"code",type(exc).__name__)}
            write_once(ap/"failure.json",error);attempts.append(error)
            result["budget_stop"]=budget_stop_record(error);break
        try:
            if response.get("status")!="completed":raise ValueError("Source response did not complete within the registered output cap")
            candidate=json.loads(previous_text)
            validation=validate_authored_source(candidate,slot["source_id"])
            source_path=folder/"accepted_source.json";write_once(source_path,candidate)
            attempts.append({"attempt":attempt,"validation":validation,"response_status":response.get("status")})
            result.update(status="accepted",source_path=source_path.relative_to(ROOT).as_posix(),
                          source_sha256=digest(source_path),validation=validation);break
        except Exception as exc:
            previous_errors=[type(exc).__name__,str(exc)[:1000]]
            attempts.append({"attempt":attempt,"validation":{"status":"invalid","errors":sanitize(previous_errors)},"response_status":response.get("status")})
            write_once(ap/"validation.json",attempts[-1]["validation"])
    result["source_authoring_attempt_count"]=len(attempts)
    result["source_authoring_repaired"]=result["status"]=="accepted" and len(attempts)==2
    write_once(final,result)
    return result
def author_sources(plan,*,replay=False):
    slots=[];stopped=False
    for i,row in enumerate(plan["new_deterministic_sources"],1):
        slots.append({"source_id":row["source_id"],"family":"extension_deterministic","source_family_order":i,
          "status":"accepted","source_path":row["path"],"source_sha256":row["sha256"],
          "source_authoring_attempt_count":0,"source_authoring_repaired":False,
          "source_authoring_result_path":None,"source_authoring_result_sha256":None,"validation":row["validation"]})
    for i,row in enumerate(plan["llm_authored_sources"],1):
        result_path=ROOT/"results/raw/wp5_extension/source_authoring"/row["source_id"]/"result.json"
        if stopped and not result_path.exists():
            result={"source_id":row["source_id"],"slot":row,"plan_sha256":digest(PLAN_PATH),"status":"unexecuted_budget_stop","attempts":[],"source_authoring_attempt_count":0,"source_authoring_repaired":False}
            write_once(result_path,result)
        else:result=author_source(row,plan,replay=replay)
        stopped=stopped or result.get("budget_stop",False)
        slots.append({"source_id":row["source_id"],"family":"extension_llm","source_family_order":i,
          "status":result["status"],"source_path":result.get("source_path"),"source_sha256":result.get("source_sha256"),
          "source_authoring_attempt_count":result["source_authoring_attempt_count"],"source_authoring_repaired":result["source_authoring_repaired"],
          "source_authoring_result_path":result_path.relative_to(ROOT).as_posix(),"source_authoring_result_sha256":digest(result_path),"validation":result.get("validation",{"status":"invalid","attempts":result["attempts"]})})
        print(json.dumps({"source":row["source_id"],"status":result["status"]}),flush=True)
    candidate={"schema":"wp5-extension-accepted-sources-v1","plan_sha256":digest(PLAN_PATH),"authoring_terminal":True,"slots":slots}
    jsonschema.validate(candidate,read(safe_path(plan["accepted_source_schema_path"])))
    write_once(PLAN_PATH.parent/"accepted_sources.pending.json",candidate)
    return candidate
def source_row(selection,slot,phase):
    return {"scene_id":selection["source_id"],"model":selection["model"],"repetition":selection["repetition"],
      "case_id":selection["case_id"],"source_path":slot["source_path"],"source_sha256":slot["source_sha256"],
      "phase":phase,"arm":selection["arm"],"family":slot["family"]}
def registered_identity(row):
    return {"plan_sha256":digest(PLAN_PATH),"family":row["family"],"source_id":row["scene_id"],"pipeline_model":row["model"],"repetition":row["repetition"],"arm":row["arm"]}
def skipped_run(row,reason):
    path=ROOT/"results/raw/wp5_extension"/row["phase"]/row["case_id"]/"run_result.json"
    value={"source":row,"case_id":row["case_id"],"plan_sha256":digest(PLAN_PATH),"status":"failed",
      "terminal_status":"unexecuted_budget_stop" if reason=="BUDGET_STOP" else "failed",
      "failure_stage":"not_attempted","error_code":reason,"stages":[],"stage_call_attempts":0,"repair_attempts":0,
      "project_dir":None,"artifact_sha256":{},"registered_identity":registered_identity(row),"source_freeze_sha256":digest(SOURCE_PATH) if SOURCE_PATH.exists() else None}
    if path.exists():
        prior=read(path)
        if prior["plan_sha256"]!=digest(PLAN_PATH) or prior["source"]!=row:raise RuntimeError("Retained terminal identity changed")
        return prior
    write_once(path,value);return value
def run_case(row,plan,*,replay=False,seed_artifacts=None):
    model_tag="mini" if "mini" in row["model"] else "full"
    case_id=row["case_id"]
    run_root=ROOT/"results/raw/wp5_extension"/row["phase"]/case_id
    final_path=run_root/"run_result.json"
    if final_path.exists():
        prior=json.loads(final_path.read_text(encoding="utf-8-sig"))
        if prior["plan_sha256"]!=digest(PLAN_PATH) or prior["source"]!=row:
            raise RuntimeError("Existing run belongs to a different frozen plan or source; preserve it and use an explicit amendment.")
        return prior
    if digest(ROOT/row["source_path"])!=row["source_sha256"]: raise RuntimeError("Frozen source hash changed")
    source=read(ROOT/row["source_path"])
    runtime=ROOT/"results/wp5_extension_runtime"
    runtime.mkdir(parents=True,exist_ok=True)
    adapter=RoomContractAdapter.discover(workspace_root=ROOT,backend_root=runtime,output_root=ROOT/"results/raw/wp5_extension/cases")
    initialized=adapter.initialize_case_from_payload(source,case_id=case_id)
    case_dir=Path(initialized["case_dir"])
    if seed_artifacts:
        import shutil
        for filename,path in seed_artifacts.items():
            destination=case_dir/"intermediate"/filename
            if destination.exists() and destination.read_bytes()!=Path(path).read_bytes():raise RuntimeError("Seeded authoring artifact changed")
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
        if "knowledge.generated.json" in seed_artifacts:
            from tools.case_study_pipeline.knowledge_synthesis import materialize_knowledge_files
            materialize_knowledge_files(case_dir,read(case_dir/"intermediate/knowledge.generated.json"))

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
                record=json.loads(checkpoint.read_text(encoding="utf-8-sig")); records.append(record)
                if record["status"]!="success":
                    result["status"]="failed"; result["failure_stage"]=stage; break
                continue
            settings=plan["llm_stages"].get(stage)
            if settings and row.get("arm")=="cap_recovery":
                settings={**settings,"input_ceiling":{"scene_semantics":12000,"agent_roles":16000,"knowledge_synthesis":18000}[stage]}
                if stage=="scene_semantics":settings={**settings,"output_cap":3600}
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
                with experiment_context(experiment_id="WP5.extension."+row["phase"],item_id=row["scene_id"],
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
    result["registered_identity"]=registered_identity(row)
    result["source_freeze_sha256"]=digest(SOURCE_PATH) if SOURCE_PATH.exists() else None
    result["terminal_status"]="completed" if result["status"]=="success" else "failed"
    result["case_dir"]=case_dir.relative_to(ROOT).as_posix()
    result["reused_authoring_artifacts"]={Path(path).relative_to(ROOT).as_posix():digest(path) for path in (seed_artifacts or {}).values()}
    result["stage_call_attempts"]=row.get("external_generation_attempts",0)+sum(r["archived_call_attempts"] for r in records)
    result["repair_attempts"]=row.get("external_generation_attempts",0)+sum(max(0,r["archived_call_attempts"]-1) for r in records)
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


def run_initial(plan,*,replay=False):
    sources=load_sources(plan);slots={r["source_id"]:r for r in sources["slots"]}
    results=[];stopped=False
    for selection in plan["initial_baselines"]:
        slot=slots[selection["source_id"]];row=source_row(selection,slot,"initial")
        if slot["status"]!="accepted":result=skipped_run(row,"SOURCE_AUTHORING_FAILED" if slot["status"]=="source_authoring_failed" else "BUDGET_STOP")
        elif stopped:result=skipped_run(row,"BUDGET_STOP")
        else:result=run_case(row,plan,replay=replay)
        stopped=stopped or budget_stop_record(result)
        results.append({"case_id":row["case_id"],"status":result["status"],"failure_stage":result.get("failure_stage")})
        print(json.dumps(results[-1]),flush=True)
    write_once(ROOT/"results/raw/wp5_extension/initial_terminal_v1.json",
      {"plan_sha256":digest(PLAN_PATH),"source_freeze_sha256":digest(SOURCE_PATH),"terminal":True,
       "registered_rows":len(plan["initial_baselines"]),"rows":results,"budget_stopped":stopped})
    return results

def run_drift(plan,*,replay=False):
    sources=load_sources(plan);slots={r["source_id"]:r for r in sources["slots"]}
    stopped=False;results=[]
    for selection in plan["fresh_drift_runs"]:
        row=source_row(selection,slots[selection["source_id"]],"drift")
        round_started=any((ROOT/"results/raw/wp5_extension/drift"/s["case_id"]/"run_start.json").exists() for s in plan["fresh_drift_runs"] if s["repetition"]==selection["repetition"])
        if selection["source_id"]==plan["new_deterministic_sources"][0]["source_id"] and selection["model"]==plan["models"][0] and not replay and not round_started:
            summary=Budget(ROOT/"logs/api_budget.sqlite3","20").summary()
            remaining=Decimal(summary["allocations"]["WP5"]["stop_usd"])-Decimal(summary["allocations"]["WP5"]["accounted_usd"])
            forecast=Decimal(plan["budget"]["fresh_drift_round_start_forecast_with15percent_contingency_usd"])
            if remaining<forecast:stopped=True
        result=skipped_run(row,"BUDGET_STOP") if stopped else run_case(row,plan,replay=replay)
        stopped=stopped or budget_stop_record(result)
        results.append({"case_id":row["case_id"],"status":result["status"]})
        print(json.dumps(results[-1]),flush=True)
    write_once(ROOT/"results/raw/wp5_extension/drift_terminal_v1.json",
       {"plan_sha256":digest(PLAN_PATH),"terminal":True,"registered_rows":len(plan["fresh_drift_runs"]),"rows":results,"budget_stopped":stopped})
    return results

def native_sources():
    """Distinct actual, valid, Gate0-native source identities across labeled arms."""
    result=set()
    roots=(ROOT/"results/raw/wp5/evaluation",ROOT/"results/raw/wp5_extension/initial",ROOT/"results/raw/wp5_extension/ownership_repair",ROOT/"results/raw/wp5_extension/cap_recovery")
    for root in roots:
        for path in root.glob("*/run_result.json"):
            run=read(path);stages={r["stage"]:r for r in run["stages"]};gate=path.parent/"routing_verifier.json"
            if run["status"]=="success" and all(stages.get(x,{}).get("status")=="success" for x in ("roomcontract_v2_assembly","schema_validation")) and gate.exists() and read(gate).get("ok") is True:
                project=ROOT/run["project_dir"];model=project/"roomcontract.v2.instance.json"
                if digest(model)!=run["artifact_sha256"].get(model.relative_to(ROOT).as_posix()):raise RuntimeError("Native source artifact changed")
                result.add(run["source"]["scene_id"])
    return result

def experiment_spend(experiment):
    import sqlite3
    with sqlite3.connect(ROOT/"logs/api_budget.sqlite3") as c:
        amount=c.execute("SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM reservations WHERE experiment=?",(experiment,)).fetchone()[0]
    return Decimal(amount)/1_000_000_000

def run_recovery(plan,*,replay=False):
    settings=plan["recovery"];results=[];attempted=0;stopped=False
    for selection in settings["rows"]:
        row={"scene_id":selection["source_id"],"model":selection["model"],"repetition":selection["repetition"],
            "source_path":selection["source_path"],"source_sha256":selection["source_sha256"],"case_id":selection["case_id"],
            "phase":"cap_recovery","family":selection["family"],"arm":selection["arm"]}
        existing=ROOT/"results/raw/wp5_extension/cap_recovery"/row["case_id"]/"run_result.json"
        if existing.exists():
            result=run_case(row,plan,replay=replay);attempted+=result.get("failure_stage")!="not_attempted"
        else:
            reason=None
            sources=native_sources()
            if len(sources)>=settings["distinct_source_target"]:reason="BREADTH_TARGET_ALREADY_MET"
            elif row["scene_id"] in sources:reason="SOURCE_ALREADY_HAS_NATIVE_PROJECT"
            elif attempted>=settings["maximum_room_attempts"]:reason="REGISTERED_RECOVERY_ATTEMPT_LIMIT"
            elif stopped:reason="BUDGET_STOP"
            elif replay:raise RuntimeError("Recovery replay requires retained per-row stopping decisions")
            elif experiment_spend("WP5.extension.cap_recovery")+Decimal(settings["full_room_all_stage_and_transport_attempts_ceiling_usd"])>Decimal(settings["sublimit_usd"]):reason="RECOVERY_SUBLIMIT"
            if reason:result=skipped_run(row,reason)
            else:result=run_case(row,plan,replay=replay);attempted+=1
        stopped=stopped or budget_stop_record(result)
        results.append({"case_id":row["case_id"],"status":result["status"],"error_code":result.get("error_code")})
        print(json.dumps(results[-1]),flush=True)
    write_once(ROOT/"results/raw/wp5_extension/recovery_terminal_v1.json",{"terminal":True,"plan_sha256":digest(PLAN_PATH),"rows":results,"attempted_rooms":attempted,"distinct_native_sources":sorted(native_sources())})
    return results

def run_edits(plan,*,replay=False):
    results=[];stopped=False
    for selection in plan["source_edits"]:
        row={"scene_id":selection["source_id"],"model":selection["model"],"repetition":selection["repetition"],
            "source_path":selection["source_path"],"source_sha256":selection["source_sha256"],"case_id":selection["case_id"],
            "phase":"source_edit","family":selection["family"],"arm":selection["arm"],"edit":selection["edit"],"parent":selection["parent"]}
        result=skipped_run(row,"BUDGET_STOP") if stopped else run_case(row,plan,replay=replay)
        stopped=stopped or budget_stop_record(result);results.append(result)
        print(json.dumps({"case_id":row["case_id"],"status":result["status"]}),flush=True)
    write_once(ROOT/"results/raw/wp5_extension/source_edits_terminal_v1.json",{"terminal":True,"plan_sha256":digest(PLAN_PATH),"rows":results})
    return results

def run_zone_rename(plan,*,replay=False):
    base_id=plan["zone_rename"]["base_case_id"];base_path=ROOT/"results/raw/wp5_extension/initial"/base_id/"run_result.json"
    destination=ROOT/"results/raw/wp5_extension/zone_rename"/(base_id+"_zone_rename_v1")
    final=destination/"edit_result.json"
    if final.exists():return read(final)
    base=read(base_path)
    result={"plan_sha256":digest(PLAN_PATH),"arm":"scripted_zone_rename","before_case_id":base_id,"source_run_sha256":digest(base_path),"generation_calls":0}
    if base["status"]!="success":
        result.update(status="not_executed",reason="Preselected baseline did not produce a successful project; no replacement source.")
        write_once(final,result);return result
    case=ROOT/base["case_dir"];sem_path=case/"intermediate/scene_semantics.json";semantics=read(sem_path)
    paths={name:case/"intermediate"/name for name in ("scene_semantics.json","agent_roles.generated.json","knowledge.generated.json")}
    for path in paths.values():
        if base["artifact_sha256"].get(path.relative_to(ROOT).as_posix())!=digest(path):raise RuntimeError("Selected authoring input changed")
    zone=min(semantics["semantic_zones"],key=lambda z:z["zone_id"])
    result.update(zone_id=zone["zone_id"],old_name=zone["name"],new_name=zone["name"]+" (renamed)")
    write_once(destination/"before/scene_semantics.json",semantics)
    zone["name"]=result["new_name"];edited=destination/"after/scene_semantics.json";write_once(edited,semantics)
    paths["scene_semantics.json"]=edited
    row={**base["source"],"case_id":base_id+"_zone_rename_v1","phase":"zone_rename","arm":"scripted_zone_rename","family":"extension_edit"}
    deterministic={**plan,"stage_order":[stage for stage in plan["stage_order"] if stage not in plan["llm_stages"]]}
    run=run_case(row,deterministic,replay=replay,seed_artifacts=paths)
    result.update(status=run["status"],after_case_id=row["case_id"],after_project_path=run.get("project_dir"),before_project_path=base["project_dir"])
    write_once(final,result);return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("phase",choices=("author_sources","initial","repair","recovery","drift","edits","zone_rename","verify"))
    ap.add_argument("--replay",action="store_true")
    args=ap.parse_args();plan=load_plan(replay=args.replay)
    if args.phase=="author_sources":author_sources(plan,replay=args.replay)
    elif args.phase=="initial":run_initial(plan,replay=args.replay)
    elif args.phase=="drift":run_drift(plan,replay=args.replay)
    elif args.phase=="recovery":run_recovery(plan,replay=args.replay)
    elif args.phase=="edits":run_edits(plan,replay=args.replay)
    elif args.phase=="zone_rename":run_zone_rename(plan,replay=args.replay)
    elif args.phase=="repair":
        from experiments.wp5_extension_repair import run_repairs
        run_repairs(plan,replay=args.replay)
    else:print(json.dumps({"plan_sha256":digest(PLAN_PATH),"status":"verified"}))
if __name__=="__main__":main()
