"""Separately frozen extension natural-room analysis; original evaluator retained unchanged."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import random
import sys

from experiments.pipeline_runs import ROOT
sys.path.insert(0,str(ROOT))
from experiments.lib.backend_driver import Driver
from tools.routing_verifier import NativeRoutingIndex, load_and_verify, serialization_digest
from tools.case_study_pipeline.roomcontract_v2_assembler import validate_roomcontract_v2_instance
from tools.case_study_pipeline.validators.schema_validator import validate_case_schemas
from tools.case_study_pipeline.scene_semantics import validate_scene_semantics
from tools.case_study_pipeline.agent_roles import validate_agent_roles
from tools.case_study_pipeline.knowledge_synthesis import validate_knowledge
from verification.impl_a import reference as independent_a
from verification.impl_b import policy_adapter as independent_b

def read(path): return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stable_report(value):
    if isinstance(value,dict):return {k:stable_report(v) for k,v in value.items() if k!="generated_at"}
    if isinstance(value,list):return [stable_report(v) for v in value]
    return value
def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(data,sort_keys=True,indent=2,ensure_ascii=False)+"\n"
    if path.exists() and path.read_text(encoding="utf-8")!=text:
        raise FileExistsError("Preserve prior analysis; select a new analysis output directory.")
    path.write_text(text,encoding="utf-8",newline="\n")

class NoGeneration:
    """Tripwire only. This analysis calls production admission methods, never chat."""
    api_key=""
    calls=0
    def create_structured_json(self,**kwargs):
        raise AssertionError("Natural-fault analysis must not invoke generation.")
    create_json_object=create_structured_json

def request_for(agent,target,digest,session_id="natural"):
    return {"session_id":session_id,"active_agent_id":agent,"user_text":"Describe this object.",
            "interaction_mode":"deictic","spatial_context":{"model_sha256":digest,"state":"resolved",
            "entity_id":target["id"],"source_object_id":target["sourceId"],"hit_position":{"x":0,"y":0,"z":0},
            "distance_m":1,"selection_modality":"programmatic"}}

def runtime_admission(driver,request):
    """Execute the production model-only admission sequence, stopping before chat."""
    store,session=driver.store,driver.session
    before=store.snapshot_session_mutation(session.session_id)
    try:
        active=request["active_agent_id"]
        grounding=store._validate_spatial_context(session,request["spatial_context"])
        routing=store._resolve_spatial_route(session,active,grounding)
        provider=routing["selected_agent_id"]
        provider_entity=store._v2_provider_entity_id(session,provider)
        action=store._preflight_v2_interaction_action(st=session,session_id=session.session_id,
            action_kind="chat",interaction_mode="deictic",provider_entity_id=provider_entity,
            target_id=grounding["selected_entity_id"])["action"]
        store._preflight_v2_interaction_action(st=session,session_id=session.session_id,
            action_kind="handoff",interaction_mode="deictic",provider_entity_id=provider_entity,
            target_id=grounding["selected_entity_id"])
        result={"decision":"ANSWER_LOCAL" if provider==active else "ANSWER_AFTER_HANDOFF",
                "reason":None,"provider":provider,"action":action["runtime_action_id"]}
    except Exception as exc:
        result={"decision":"REJECT","reason":getattr(exc,"code",type(exc).__name__),"provider":None,"action":None}
    result["state_unchanged"]=before==store.snapshot_session_mutation(session.session_id)
    result["generation_calls"]=driver.client.calls
    return result

def graph_metrics(index):
    agents=sorted(index.agents)
    edges={(a,b) for a in agents for b in index.agents[a].get("handoffTarget",[]) if b in index.agents and a!=b}
    distances=[index.distance(a,b) for a in agents for b in agents if a!=b]
    finite=[d for d in distances if d is not None]
    return {"agent_count":len(agents),"edge_count":len(edges),
            "density":len(edges)/(len(agents)*(len(agents)-1)) if len(agents)>1 else 0,
            "isolated_agents":[index.wire[a] for a in agents if not any(a in e for e in edges)],
            "directed_diameter":max(finite,default=0) if len(finite)==len(distances) else None,
            "maximum_finite_distance":max(finite,default=0),
            "unreachable_agent_pairs":sum(d is None for d in distances)}

def candidate_reports(run_root):
    """Recheck exact retained stage artifacts; unavailable native pre-repair models stay unavailable."""
    output=[]
    filenames={"scene_semantics":"scene_semantics.json","agent_roles":"agent_roles.generated.json",
               "knowledge_synthesis":"knowledge.generated.json"}
    for stage,filename in filenames.items():
        base=run_root/"stage_artifacts"/stage
        snapshots=[*sorted(base.glob("attempt_*/before")),base/"after_stage"]
        for snapshot in snapshots:
            intermediate=snapshot/"intermediate";path=intermediate/filename
            if not path.exists():continue
            data=read(path);normalized=read(intermediate/"scene_graph.normalized.json")
            try:
                if stage=="scene_semantics":report=validate_scene_semantics(data,normalized)
                elif stage=="agent_roles":report=validate_agent_roles(data,scene_semantics=read(intermediate/"scene_semantics.json"),normalized_scene=normalized)
                else:report=validate_knowledge(data,normalized_scene=normalized,agent_roles=read(intermediate/"agent_roles.generated.json"))
            except Exception as exc:report={"status":"validator_error","error_type":type(exc).__name__}
            row={"stage":stage,"snapshot":snapshot.relative_to(ROOT).as_posix(),"artifact_sha256":sha(path),"authoring_validator":report}
            if stage=="agent_roles":
                ownership={}
                for agent in data.get("agents",[]):
                    for obj in agent.get("grounded_object_ids",[]):ownership.setdefault(obj,set()).add(agent["id"])
                row["ambiguous_asset_declarations"]={obj:sorted(owners) for obj,owners in ownership.items() if len(owners)>1}
            output.append(row)
    return output

def nearest_proxy(project,targets):
    source=read(project/"room_plan.json")["scene"]["objects"]
    positions={o["objectId"]:o["position"] for o in source}
    agents=read(project/"agents.json")["agents"]
    result={}
    for target in targets:
        pos=positions.get(target["sourceId"])
        if pos is None or not agents:continue
        result[target["id"]]=min(agents,key=lambda a:((a["position"]["x"]-pos["x"])**2+
            (a["position"]["z"]-pos["z"])**2,a["id"]))["id"]
    return result

def zone_lint(case,index):
    normalized=read(case/"intermediate/scene_graph.normalized.json")
    # The packet declares zone membership, not authoritative geometric polygons.
    # Bounding boxes are therefore only an indicative derived spatial check.
    source=read(case/"input/source_rdl.json")["scene"]["objects"]
    objects={o["objectId"]:o for o in source}
    boxes={}
    for zid,zone in index.zones.items():
        members=[objects[sid] for sid in zone.get("sourceObjectId",[]) if sid in objects]
        if members:
            boxes[zid]=(min(o["position"]["x"]-o["dimensions"]["width"]/2 for o in members),
                        max(o["position"]["x"]+o["dimensions"]["width"]/2 for o in members),
                        min(o["position"]["z"]-o["dimensions"]["depth"]/2 for o in members),
                        max(o["position"]["z"]+o["dimensions"]["depth"]/2 for o in members))
    rows=[]
    for target,obj in index.objects.items():
        _,owners=index.ownership(target)
        if len(owners)!=1 or obj["sourceId"] not in objects:continue
        o=objects[obj["sourceId"]]; p=o["position"]; d=o["dimensions"]
        owner_boxes=[boxes[z] for z in index.agents[owners[0]].get("responsibleZone",[]) if z in boxes]
        within=any(x0<=p["x"]-d["width"]/2 and p["x"]+d["width"]/2<=x1 and
                   z0<=p["z"]-d["depth"]/2 and p["z"]+d["depth"]/2<=z1 for x0,x1,z0,z1 in owner_boxes)
        rows.append({"target":target,"owner":index.wire[owners[0]],"zone_box_available":bool(owner_boxes),
                     "inside_owner_zone_box":within if owner_boxes else None})
    return {"kind":"indicative member-derived zone bounding boxes; not semantic ground truth","rows":rows,
            "llm_judges":"NOT_RUN: not funded or authorized in the frozen plan"}

def analyze_run(run_path,*,include_runtime=True):
    run=read(run_path);run_root=run_path.parent;project=ROOT/run["project_dir"] if run.get("project_dir") else run_root/"NO_PROJECT_WAS_PRODUCED"
    case=ROOT/run["case_dir"] if run.get("case_dir") else ROOT/"results/raw/wp5_extension/cases"/run["case_id"]
    result={"room":run["case_id"],"source":run["source"],"original_pipeline_status":run["status"],
            "failure_stage":run.get("failure_stage"),"repair_attempts":run["repair_attempts"],
            "candidate_reports":candidate_reports(run_root),"project_produced":project.exists(),
            "before_repair_native_models":"Not synthesized. Stage repairs precede native assembly; exact candidate artifacts are reported separately."}
    if not (project/"roomcontract.v2.instance.json").exists():return result
    model_path=project/"roomcontract.v2.instance.json";instance=read(model_path);trace=read(project/"trace_map.v2.json")
    gate0=load_and_verify(model_path,project/"trace_map.v2.json",project/"project.json")
    index=NativeRoutingIndex(instance,trace)
    result.update({"model_sha256":serialization_digest(model_path.read_bytes()),"Gate0":gate0,
                   "canonical_authoring":stable_report(validate_roomcontract_v2_instance(instance)),
                   "schema_authoring":validate_case_schemas(case_dir=case,backend_root=project.parent.parent),
                   "graph":graph_metrics(index),"geometric_lint":zone_lint(case,index),"probes":[]})
    result["object_faults"]={"objects":len(index.objects),
        "unowned":sum(not row["owners"] for row in gate0["ownership"].values()),
        "ambiguous_deciding_level":sum(len(row["owners"])>1 for row in gate0["ownership"].values()),
        "without_declared_action":sum(issue["invariant"]=="INV-077" for issue in gate0["issues"]),
        "latent_group_ambiguities":sum(x["kind"]=="group" for x in gate0["latent_ambiguities"]),
        "latent_zone_ambiguities":sum(x["kind"]=="zone" for x in gate0["latent_ambiguities"])}
    proxy=nearest_proxy(project,list(index.objects.values()))
    driver=None;setup_error=None
    if include_runtime:
        try:
            with redirect_stdout(io.StringIO()): driver=Driver(project,client=NoGeneration())
        except Exception as exc:setup_error=getattr(exc,"code",type(exc).__name__)
    try:
        for aid in sorted(index.agents,key=lambda a:index.wire[a]):
            agent=index.wire[aid]
            for target,obj in sorted(index.objects.items()):
                request=request_for(agent,obj,result["model_sha256"],driver.session.session_id if driver else "natural")
                session={"model_sha256":result["model_sha256"],"active_agent_mode":"client"}
                verdicts={"Gate0":gate0["routing_table"][agent][target]}
                for name,module in (("I1",independent_a),("I2",independent_b)):
                    try:verdicts[name]=module.evaluate(instance,trace,request,session)
                    except Exception as exc:verdicts[name]={"decision":"HARNESS_ERROR","reason":type(exc).__name__,"provider":None,"action":None}
                if driver:verdicts["I0"]=runtime_admission(driver,request)
                else:verdicts["I0"]={"decision":"SETUP_REFUSED" if setup_error else "NOT_RUN","reason":setup_error,"provider":None,"action":None}
                _,owners=index.ownership(target)
                distance=index.distance(aid,owners[0]) if len(owners)==1 else None
                path_ok=len(owners)==1 and not index.answering_path(owners[0],target)[0]
                compare=("I1","I2","Gate0")+(("I0",) if driver else ())
                agrees=len({tuple(verdicts[n].get(k) for k in ("decision","reason","provider","action")) for n in compare})==1
                result["probes"].append({"start_agent":agent,"target":target,"verdicts":verdicts,"agrees":agrees,
                    "shortest_handoffs":distance,"nearest_agent_proxy":proxy.get(target)==agent,
                    "static_admitted_at_hop_limit":{str(h):bool(path_ok and distance is not None and distance<=h) for h in (1,2,3)}})
    finally:
        if driver:driver.close()
    result["runtime_setup_error"]=setup_error
    result["pair_counts"]={"all":len(result["probes"]),"disagreements":sum(not p["agrees"] for p in result["probes"]),
         "more_than_one_handoff":sum(p["shortest_handoffs"] is not None and p["shortest_handoffs"]>1 for p in result["probes"]),
         "no_path_to_unique_owner":sum(p["shortest_handoffs"] is None and len(gate0["ownership"][p["target"]]["owners"])==1 for p in result["probes"])}
    result["rates"]={}
    for sample in ("all_pairs","nearest_agent"):
        probes=[p for p in result["probes"] if sample=="all_pairs" or p["nearest_agent_proxy"]]
        result["rates"][sample]={str(h):sum(p["static_admitted_at_hop_limit"][str(h)] for p in probes)/len(probes) if probes else None for h in (1,2,3)}
    return result

def safe_analyze_run(run_path,*,include_runtime=True):
    """A retained malformed/faulty native artifact is data, never a dropped row."""
    try:return analyze_run(run_path,include_runtime=include_runtime)
    except Exception as exc:
        run=read(run_path);project=ROOT/run["project_dir"] if run.get("project_dir") else None
        model=project/"roomcontract.v2.instance.json" if project else None
        gate_path=Path(run_path).parent/"routing_verifier.json"
        return {"room":run["case_id"],"source":run["source"],"original_pipeline_status":run["status"],
          "failure_stage":run.get("failure_stage"),"repair_attempts":run.get("repair_attempts",0),
          "candidate_reports":[],"project_produced":bool(model and model.exists()),
          "model_sha256":serialization_digest(model.read_bytes()) if model and model.exists() else None,
          "Gate0":read(gate_path) if gate_path.exists() else {},"probes":[],
          "analysis_error":{"error_type":type(exc).__name__,"error_code":getattr(exc,"code",None)},
          "independent_label_status":"unavailable_after_analysis_error","runtime_setup_error":type(exc).__name__,
          "before_repair_native_models":"Not synthesized. Retained failed artifact remains available for audit."}

def clustered_interval(rows,selector,seed=20261015,repetitions=2000):
    grouped={}
    for row in rows:
        value=selector(row)
        if value is not None:grouped.setdefault(row["source"]["scene_id"],[]).append(value)
    clusters=list(grouped.values())
    if not clusters:return {"estimate":None,"low":None,"high":None,"source_clusters":0}
    means=[sum(c)/len(c) for c in clusters]
    estimate=sum(means)/len(means)
    if len(means)<2:return {"estimate":estimate,"low":None,"high":None,"source_clusters":len(means)}
    rng=random.Random(seed)
    draws=sorted(sum(rng.choice(means) for _ in means)/len(means) for _ in range(repetitions))
    return {"estimate":estimate,"low":draws[int(.025*repetitions)],"high":draws[int(.975*repetitions)-1],
            "source_clusters":len(means),"bootstrap_repetitions":repetitions,"seed":seed}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--phase",choices=("initial","ownership_repair","cap_recovery","drift","source_edit","zone_rename"),required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--skip-runtime",action="store_true",help="Diagnostic only; reports explicitly NOT_RUN.")
    args=ap.parse_args()
    from experiments.wp5_extension import load_plan
    load_plan(replay=True)
    rows=[]
    for path in sorted((ROOT/"results/raw/wp5_extension"/args.phase).glob("*/run_result.json")):
        row=safe_analyze_run(path,include_runtime=not args.skip_runtime)
        write(args.output/"rooms"/(row["room"]+".json"),row);rows.append(row)
        print(json.dumps({"room":row["room"],"project_produced":row["project_produced"],"pairs":row.get("pair_counts",{})}),flush=True)
    metrics={}
    for model in sorted({r["source"]["model"] for r in rows}):
        subset=[r for r in rows if r["source"]["model"]==model and r["project_produced"] and "rates" in r]
        metrics[model]={sample:{str(h):clustered_interval(subset,lambda r:r["rates"][sample][str(h)]) for h in (1,2,3)}
                        for sample in ("all_pairs","nearest_agent")}
        metrics[model]["object_fault_rates"]={}
        for fault in ("unowned","ambiguous_deciding_level","without_declared_action"):
            interval=clustered_interval(subset,lambda r:r["object_faults"][fault]/r["object_faults"]["objects"]
                                        if r["object_faults"]["objects"] else None)
            denominator=sum(r["object_faults"]["objects"] for r in subset)
            interval["pooled_numerator"]=sum(r["object_faults"][fault] for r in subset)
            interval["pooled_denominator"]=denominator
            interval["pooled_rate"]=interval["pooled_numerator"]/denominator if denominator else None
            metrics[model]["object_fault_rates"][fault]=interval
    write(args.output/"summary.json",{"unit":"source room; model runs nested; probes secondary","phase":args.phase,
        "rooms":len(rows),"projects":sum(r["project_produced"] for r in rows),"source_cluster_intervals":metrics,
        "analysis_sha256":sha(__file__),"runtime_included":not args.skip_runtime,"status":"PARTIAL",
        "limits":"No native before-repair model is invented. LLM judgments are separate from routing ground truth. Hop2/3 are static graph metrics, not runtime policy changes."})
if __name__=="__main__":main()

