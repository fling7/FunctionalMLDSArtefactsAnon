"""Offline experimental V2 room builder using the packet's deterministic assemblers.

Intentional routing faults are accepted only with allow_invalid=True and retain
their validation reports. No generated file is a model result from an LLM.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from tools.case_study_pipeline.roomcontract_assembler import assemble_roomcontract_instance
from tools.case_study_pipeline.roomcontract_v2_assembler import (
    _build_native_instance, import_v05, validate_roomcontract_v2_instance)
from tools.case_study_pipeline.rdl_ingestion import normalize_scene, summarize_object_groups
from tools.case_study_pipeline.agent_placement import generate_agent_placements
from tools.case_study_pipeline.project_materializer import (
    build_trace_map_v2, _placement_artifact_deployment_metadata, placement_projection_sha256)
from tools.dynamic_functional_rdl_v2_model import MODEL
from tools.validate_dynamic_functional_rdl_v2 import validate_instance

def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n")

def token(value):
    return re.sub(r"[^a-z0-9_-]+","_",str(value).lower()).strip("_").upper()

@dataclass
class BuiltRoom:
    instance: dict
    trace: dict
    validation: dict
    project_dir: Path | None
    id_maps: dict
    source: dict

def build_room(spec: dict, destination: Path | None = None, *, allow_invalid=False) -> BuiltRoom:
    spec=copy.deepcopy(spec)
    case_id=str(spec.get("case_id","generated_room"))
    agents=[str(x["id"] if isinstance(x,dict) else x) for x in spec.get("agents",["agent_a","agent_b"])]
    objects=[{"id":x} if isinstance(x,str) else dict(x) for x in spec.get("objects",[{"id":"object_a"}])]
    if not agents or not objects or len(agents)!=len(set(agents)):
        raise ValueError("Room needs unique agents and at least one object.")
    for i,obj in enumerate(objects):
        obj.setdefault("group","group_a"); obj.setdefault("zones",["zone_a"])
    groups=list(dict.fromkeys([*spec.get("groups",[]),*[o["group"] for o in objects]]))
    zones=list(dict.fromkeys([*spec.get("zones",[]),*[z for o in objects for z in o["zones"]]]))
    for ids in (agents,[o["id"] for o in objects],groups,zones):
        if len(ids)!=len(set(ids)) or len({token(x) for x in ids})!=len(ids) or any(not re.fullmatch(r"[a-zA-Z0-9_-]+",x) for x in ids):
            raise ValueError("Identifiers must be unique safe ASCII strings with distinct normalized forms.")
    owners=spec.get("owners")
    if owners is None:
        owners={"asset":{o["id"]:[agents[i%len(agents)]] for i,o in enumerate(objects)},"group":{},"zone":{}}
    owners={level:owners.get(level,{}) for level in ("asset","group","zone")}
    for level,ids in (("asset",[o["id"] for o in objects]),("group",groups),("zone",zones)):
        if any(k not in ids or any(a not in agents for a in values) for k,values in owners[level].items()):
            raise ValueError("Ownership contains unknown target or agent.")
    handoffs=[list(edge) for edge in spec.get("handoffs",[])]
    if any(len(edge)!=2 or any(a not in agents for a in edge) for edge in handoffs):
        raise ValueError("Handoff contains an unknown endpoint.")
    def resolved(obj):
        tiers=[owners["asset"].get(obj["id"],[]),owners["group"].get(obj["group"],[]),
               list(dict.fromkeys(a for zone in obj["zones"] for a in owners["zone"].get(zone,[])))]
        return next((list(dict.fromkeys(t)) for t in tiers if t),[])
    selected={obj["id"]:(resolved(obj) or [agents[0]])[0] for obj in objects}
    source_objects=[]
    columns=max(2,int(len(objects)**0.5)+1)
    for i,obj in enumerate(objects):
        source_objects.append({"objectId":obj["id"],"objectType":obj.get("type","educational_display"),
            "position":{"x":float((i%columns)*3),"y":0.5,"z":float((i//columns)*3)},
            "rotation":{"x":0.0,"y":0.0,"z":0.0},"dimensions":{"width":0.6,"height":1.0,"depth":0.6},
            "group":obj["group"],"children":[],"specification":str(obj.get("description","Synthetic model-builder display."))})
    extent=float(max(12,(len(objects)+2)*3))
    source={"scene":{"sceneName":case_id,"environment":{"type":"indoor","dimensions":{"width":extent,"height":4.0,"depth":extent},
                "lighting":[],"background":"#ECECEC"},"objectGroups":{g:{"color":"#888888"} for g in groups},"objects":source_objects}}
    normalized,ingestion=normalize_scene(source)
    if ingestion["status"]!="valid": raise ValueError("Builder source rejected by ingestion.")
    semantics={"semantic_zones":[{"zone_id":z,"name":z,"purpose":"Synthetic zone.",
                      "object_ids":[o["id"] for o in objects if z in o["zones"]]} for z in zones]}
    # Scaffold one asset owner and all corresponding zone memberships so the
    # packet assembler creates every scene object and complete action path.
    scaffold={"agents":[{"id":a,"display_name":a,"persona":"Synthetic educational guide.","expertise":["synthetic room"],
        "knowledge_tags":["room"],"responsible_zone_ids":zones,
        "grounded_object_ids":[o["id"] for o in objects if selected[o["id"]]==a],
        "handoff_targets":[edge[1] for edge in handoffs if edge[0]==a and edge[1]!=a],
        "voice":"alloy","voice_gender":"neutral","voice_style":"neutral","tts_model":"gpt-4o-mini-tts"} for a in agents],"handoffs":[]}
    v05=assemble_roomcontract_instance(case_id=case_id,normalized_scene=normalized,scene_semantics=semantics,agent_roles=scaffold)
    maps={"agents":{a:f"AG-{token(case_id).replace(chr(45),chr(95))}-{token(a)}" for a in agents},
          "objects":{o["id"]:f"ENT-ASSET-{token(o['id'])}" for o in objects},
          "groups":{g:f"ENT-GROUP-{token(g)}" for g in groups},"zones":{z:f"ENT-ZONE-{token(z)}" for z in zones}}
    # Explicit empty groups not referenced by source objects need their own entity.
    present={e["id"] for e in v05["entities"]}
    for group in groups:
        if maps["groups"][group] not in present:
            v05["entities"].append({"id":maps["groups"][group],"name":group,"kind":"asset","source_id":"group:"+group,
                                   "entityRole":"objectGroup","source_group":group,"source_object_ids":[]})
    for agent in v05["agents"]:
        a=agent["source_agent_id"]
        asset=[o["id"] for o in objects if a in owners["asset"].get(o["id"],[])]
        group=[g for g in groups if a in owners["group"].get(g,[])]
        zone=[z for z in zones if a in owners["zone"].get(z,[])]
        agent.update({"grounded_object_ids":asset,"groundedAssetEntityIds":[maps["objects"][x] for x in asset],
          "grounded_object_groups":group,"groundedObjectGroupEntityIds":[maps["groups"][x] for x in group],
          "responsible_zone_ids":zone,"responsibleZoneEntityIds":[maps["zones"][x] for x in zone],
          "handoff_targets":[e[1] for e in handoffs if e[0]==a],
          "handoffTargetAgentIds":[maps["agents"][e[1]] for e in handoffs if e[0]==a]})
    action_spec=spec.get("actions")
    if action_spec is not None:
        action_rows={}
        for action in action_spec:
            if action["target"] not in maps["objects"] or action["provider"] not in maps["agents"] or int(action.get("count",1))<0:
                raise ValueError("Invalid explicit action declaration.")
            action_rows.setdefault(action["target"],[]).extend([action["provider"]]*int(action.get("count",1)))
        for obj in objects:
            existing=next(u for u in v05["capabilityUses"] if maps["objects"][obj["id"]] in u.get("target_entity_ids",[]) and u["capability_id"].endswith("ANSWER-ROOM-GROUNDED-QUESTION"))
            providers=action_rows.get(obj["id"],[])
            v05["capabilityUses"].remove(existing)
            new_uses=[]
            for j,provider in enumerate(providers):
                u=copy.deepcopy(existing)
                u["id"]=existing["id"]+(f"-COPY{j}" if j else "")
                u["preferred_provider_entity_id"]=f"ENT-AGENT-{token(provider)}"
                new_uses.append(u)
            v05["capabilityUses"].extend(new_uses)
            for use_case in v05["requirementsModel"]["useCases"]:
                for scenario in use_case.get("scenarios",[]):
                    for step in scenario.get("steps",[]):
                        if existing["id"] in step.get("capabilityUseIds",[]):
                            step["capabilityUseIds"]=[u["id"] for u in new_uses]
                            if not new_uses: step["kind"]="actorIntent"; step["performedBy"]="ACT-VISITOR"
    instance=_build_native_instance(import_v05(v05))
    validation=validate_roomcontract_v2_instance(instance)
    if not allow_invalid and not validation["ok"]:
        raise ValueError("Built model failed canonical/domain validation: "+json.dumps(validation["errors"][:5]))
    roles=copy.deepcopy(scaffold)
    for role in roles["agents"]:
        a=role["id"]
        role["grounded_object_ids"]=[o["id"] for o in objects if a in owners["asset"].get(o["id"],[])]
        role["responsible_zone_ids"]=[z for z in zones if a in owners["zone"].get(z,[])]
        role["handoff_targets"]=[e[1] for e in handoffs if e[0]==a]
    placements=generate_agent_placements(normalized_scene=normalized,scene_semantics=semantics,agent_roles=roles)
    # In-memory mode is useful for property generation and avoids filesystem cost.
    base=Path(destination).resolve() if destination is not None else Path("builder_memory")/case_id
    case_dir=base/"cases"/case_id; project_dir=base/"projects"/case_id
    model_text=json.dumps(instance,sort_keys=True,indent=2,ensure_ascii=False)+"\n"
    digest=hashlib.sha256(model_text.encode()).hexdigest().upper()
    try:
        trace=build_trace_map_v2(case_dir=case_dir,project_dir=project_dir,roomcontract_instance=instance,agent_roles=roles,model_sha256=digest)
    except ValueError as exc:
        if not allow_invalid: raise
        trace={"schema":"invalid_builder_trace","runtime_actions":[],"builder_error":str(exc)}
        validation["trace_error"]=str(exc)
    if destination is None:
        return BuiltRoom(instance,trace,validation,None,maps,source)
    write(case_dir/"input/source_rdl.json",source)
    write(case_dir/"intermediate/scene_graph.normalized.json",normalized)
    write(case_dir/"intermediate/object_group_summary.json",summarize_object_groups(normalized))
    write(case_dir/"intermediate/scene_semantics.json",semantics)
    write(case_dir/"intermediate/agent_roles.generated.json",roles)
    write(case_dir/"intermediate/agent_placements.json",placements)
    write(case_dir/"roomcontract/roomcontract.instance.generated.json",v05)
    write(case_dir/"roomcontract/roomcontract.v2.instance.json",instance)
    write(case_dir/"validation/builder_validation.json",validation)
    write(base/"builder_spec.json",spec)
    write(project_dir/"roomcontract.v2.instance.json",instance)
    write(project_dir/"roomcontract.v05.instance.json",v05)
    deployed=[]
    for role,placement in zip(roles["agents"],placements["agent_placements"]):
        a=role["id"]
        native=next(x for x in instance["objects"] if x.get("type")=="Agent" and x.get("sourceAgentId")==a)
        deployed.append({**role,"position":placement["position"],"forward":placement["forward"],
            "preferred_zone_ids":role["responsible_zone_ids"],"roomcontract_agent_ref":native["id"],
            "roomcontract_entity_ref":native["id"],"provided_capability_ids":native.get("providedCapability",[]),
            "plays_actor_ids":native.get("playsActor",[])})
    deployment={**_placement_artifact_deployment_metadata(placements),"placement_projection_sha256":placement_projection_sha256(deployed)}
    project={"id":case_id,"display_name":case_id,"description":"Synthetic deterministic model-builder fixture.",
        "created_ms":0,"updated_ms":0,"generation_mode":"roomcontract","metamodelVersion":"2.0.0-model",
        "roomcontract_model_version":"2.0.0-model","roomcontract_model_schema":"dynamic_functional_rdl_v2_instance",
        "roomcontract_profile":"executable","roomcontract_model_sha256":digest,"roomcontract_digest_scheme":"sha256-lf-v1",
        "roomcontract_model_path":"roomcontract.v2.instance.json","roomcontract_legacy_path":"roomcontract.v05.instance.json",
        "roomcontract_trace_map_path":"trace_map.v2.json","roomcontract_trace_schema_version":trace.get("trace_schema_version","2.0"),
        "roomcontract_case_dir":os.path.relpath(case_dir,project_dir).replace("\\","/"),
        "roomcontract_trace_path":"roomcontract.v05.instance.json","source_rdl_path":"room_plan.json",**deployment}
    trace.update(deployment)
    write(project_dir/"project.json",project); write(project_dir/"agents.json",{**deployment,"agents":deployed})
    write(project_dir/"room_plan.json",source)
    write(project_dir/"trace_map.v2.json",trace); write(project_dir/"trace_map.json",trace)
    (project_dir/"kb").mkdir(exist_ok=True)
    (project_dir/"kb/room.md").write_text("Synthetic model-builder room knowledge. Each display is a declared educational fixture.\n",encoding="utf-8")
    return BuiltRoom(instance,trace,validation,project_dir,maps,source)

