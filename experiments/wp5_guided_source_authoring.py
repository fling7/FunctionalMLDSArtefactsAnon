"""Prospective geometry-guided source cohort; no calls until separate frozen review."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from experiments import wp5_extension as core
from repro.llm import Gateway,sanitize
ROOT=core.ROOT
EXPERIMENT="WP5.extension.guided_source_authoring_v2"
def read(path):return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def within(relative):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):raise RuntimeError("Guided source path escapes workspace")
    return path
def frozen(path):
    side=Path(path).with_suffix(".sha256")
    if not side.exists() or side.read_text(encoding="ascii").split()[0]!=sha(path):raise RuntimeError("Guided protocol is not frozen")
def load_plan():
    path=ROOT/"prereg/wp5_guided_source_authoring_v2/plan.json";frozen(path);plan=read(path)
    if plan.get("status")!="FROZEN":raise RuntimeError("Guided source calls are not authorized")
    for name in ("implementation_sha256","prompt_sha256"):
        for rel,pin in plan[name].items():
            if sha(within(rel))!=pin:raise RuntimeError("Guided reviewed source changed")
    core.load_plan(replay=True)
    for pin in plan["prior_evidence"].values():
        if sha(within(pin["path"]))!=pin["sha256"]:raise RuntimeError("Prior cohort evidence changed")
    ids=[s["source_id"] for s in plan["slots"]]
    if len(ids)!=12 or len(set(ids))!=12 or ids!=plan["fixed_order"]:raise RuntimeError("Registered source identities changed")
    initial=read(within(plan["prior_evidence"]["initial_terminal"]["path"]))
    if initial.get("terminal") is not True:raise RuntimeError("Prior initial block is not terminal")
    prior=read(within(plan["prior_evidence"]["first_authoring_terminal"]["path"]))
    if prior.get("terminal") is not True or prior["accepted_llm_sources"]!=plan["target"]["prior_valid_llm_sources"]:raise RuntimeError("Prior source denominator changed")
    old_ids={r["source_id"] for r in read(within(plan["prior_evidence"]["accepted_sources"]["path"]))["slots"]}
    if old_ids.intersection(ids):raise RuntimeError("Guided cohort reuses prior source identity")
    return plan,path
def instructions(slot,plan):
    text=within(plan["author_prompt_path"]).read_text(encoding="utf-8")
    scaffold=json.dumps(read(within(plan["geometry_scaffold_path"])),ensure_ascii=False,separators=(",",":"))
    return text.replace("{domain}",slot["domain"]).replace("{scene_id}",slot["source_id"]).replace("{scaffold}",scaffold)
def scaffold_comparison(value,plan):
    """Descriptive only: acceptance still uses the unchanged source validator."""
    fields=("objectId","group","position","rotation","dimensions","children")
    expected={o["objectId"]:o for o in read(within(plan["geometry_scaffold_path"]))}
    actual={o["objectId"]:o for o in value["scene"]["objects"]}
    differences=[{"object_id":oid,"fields":[key for key in fields if actual.get(oid,{}).get(key)!=obj[key]]} for oid,obj in expected.items()]
    differences=[row for row in differences if row["fields"]]
    return {"role":"descriptive_not_admission","exact_scaffold_match":not differences and set(actual)==set(expected),"differences":differences}

def author(slot,plan,plan_hash,*,replay=False,gateway=None):
    folder=ROOT/"results/raw/wp5_guided_source_authoring_v2"/slot["source_id"];final=folder/"result.json"
    if final.exists():
        old=read(final)
        if old["plan_sha256"]!=plan_hash or old["slot"]!=slot:raise RuntimeError("Guided retained identity changed")
        for rel,pin in old.get("artifact_sha256",{}).items():
            if sha(within(rel))!=pin:raise RuntimeError("Guided retained artifact changed")
        if old.get("source_path") and sha(within(old["source_path"]))!=old["source_sha256"]:raise RuntimeError("Guided retained source changed")
        return old
    gateway=gateway or Gateway(ROOT,replay=replay,count_input_tokens=True)
    original=instructions(slot,plan);attempts=[];previous="";errors=[]
    result={"source_id":slot["source_id"],"slot":slot,"plan_sha256":plan_hash,"family":"guided_llm_source_v2","guidance":"Fixed geometric scaffold; model emits complete source JSON with model-written domain content; no deterministic postresponse geometry changes.","status":"source_authoring_failed","attempts":attempts}
    for attempt in (1,2):
        prompt=original if attempt==1 else within(plan["repair_prompt_path"]).read_text(encoding="utf-8")
        input_text="Write the complete scene now." if attempt==1 else json.dumps({"original_request":original,"rejected_response":previous,"validation_errors":errors},ensure_ascii=False)
        payload={"model":slot["model"],"input":input_text,"instructions":prompt,"temperature":slot["temperature"],"max_output_tokens":slot["output_cap"],"text":{"format":{"type":"json_schema","name":"synthetic_source_scene","strict":True,"schema":core.source_schema()}}}
        where=folder/f"attempt_{attempt:02d}";core.write_once(where/"request.json",sanitize(payload))
        try:
            response=gateway.responses(payload,experiment_id=EXPERIMENT,item_id=slot["source_id"],repetition_id=f"authoring_attempt{attempt}",share="WP5",max_input_tokens=slot["input_ceiling"] if attempt==1 else slot["repair_input_ceiling"])
            core.write_once(where/"response.json",sanitize(response));previous=core.output_text(response)
        except Exception as exc:
            error={"error_code":getattr(exc,"code",type(exc).__name__)};attempts.append(error);core.write_once(where/"failure.json",error);result["budget_stop"]=core.budget_stop_record(error);break
        try:
            if response.get("status")!="completed":raise ValueError("Source response did not complete within output cap")
            value=json.loads(previous);validation=core.validate_authored_source(value,slot["source_id"])
            source=folder/"accepted_source.json";core.write_once(source,value)
            attempts.append({"attempt":attempt,"response_status":response.get("status"),"validation":validation})
            result.update(status="accepted",source_path=source.relative_to(ROOT).as_posix(),source_sha256=sha(source),validation=validation,scaffold_adherence=scaffold_comparison(value,plan));break
        except Exception as exc:
            errors=sanitize([type(exc).__name__,str(exc)[:1000]]);validation={"status":"invalid","errors":errors}
            attempts.append({"attempt":attempt,"response_status":response.get("status"),"validation":validation});core.write_once(where/"validation.json",validation)
    result.update(source_authoring_attempt_count=len(attempts),source_authoring_repaired=result["status"]=="accepted" and len(attempts)==2)
    result["artifact_sha256"]={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(folder.rglob("*.json")) if p!=final}
    core.write_once(final,result);return result
def run(*,replay=False):
    plan,path=load_plan();rows=[];stopped=False
    for slot in plan["slots"]:
        final=ROOT/"results/raw/wp5_guided_source_authoring_v2"/slot["source_id"]/"result.json"
        if stopped and not final.exists():
            value={"source_id":slot["source_id"],"slot":slot,"plan_sha256":sha(path),"family":"guided_llm_source_v2","status":"unexecuted_budget_stop","attempts":[],"source_authoring_attempt_count":0,"source_authoring_repaired":False};core.write_once(final,value)
        else:value=author(slot,plan,sha(path),replay=replay)
        stopped=stopped or value.get("budget_stop",False)
        rows.append({**value,"source_authoring_result_path":final.relative_to(ROOT).as_posix(),"source_authoring_result_sha256":sha(final)})
        print(json.dumps({"source":slot["source_id"],"status":value["status"]}),flush=True)
    result={"schema":"wp5-guided-source-cohort-v2","terminal":True,"plan_sha256":sha(path),"registered_slots":12,"accepted_sources":sum(r["status"]=="accepted" for r in rows),"prior_unguided_accepted_sources":plan["target"]["prior_valid_llm_sources"],"minimum_total_target":plan["target"]["minimum_total_valid_llm_sources"],"minimum_total_target_met":plan["target"]["prior_valid_llm_sources"]+sum(r["status"]=="accepted" for r in rows)>=plan["target"]["minimum_total_valid_llm_sources"],"rows":rows,"guidance_disclosure":"Geometry scaffold supplied prospectively; full JSON emitted by model; no deterministic postresponse correction. Original failed cohort remains separate.","downstream_pipeline_calls":0,"wp4_primary_selection_changed":False}
    core.write_once(ROOT/"results/raw/wp5_guided_source_authoring_v2/terminal.json",result);return result
def main():
    p=argparse.ArgumentParser();p.add_argument("--replay",action="store_true");args=p.parse_args();run(replay=args.replay)
if __name__=="__main__":main()
