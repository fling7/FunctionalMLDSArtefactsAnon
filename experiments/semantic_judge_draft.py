"""Pure preparation for a draft indicative semantic study. No API calls."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
SEED=20261015
MODELS=("gpt-4.1-mini-2025-04-14","gpt-4.1-2025-04-14")
INPUT_CAP=5000
OUTPUT_CAP=192
LABELS=("plausible","implausible","insufficient_evidence")
ROOT=Path(__file__).resolve().parents[1]
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
def stable(*args):return hashlib.sha256(canonical([SEED,*args])).hexdigest()
def source_order(rows,limit=30):
    """Rows must expose a unique, frozen global source priority and run order."""
    eligible=sorted((r for r in rows if r.get("eligible_native_success")),key=lambda r:(r["source_priority"],r["run_ordinal"],r["case_id"]))
    selected={}
    for row in eligible:
        sid=row["source_room_id"]
        if sid not in selected:selected[sid]=row
    priorities=[r["source_priority"] for r in selected.values()]
    if len(priorities)!=len(set(priorities)):raise ValueError("Global source priorities must be unique across distinct sources")
    return list(selected.values())[:limit]
def primary_rows(manifest):
    for name in ("original_terminal","initial_block_terminal","manifest_is_complete"):
        if manifest.get(name) is not True:raise ValueError("Primary source manifest is not terminal: "+name)
    for name in ("extension_plan_sha256","source_freeze_manifest_sha256"):
        if not isinstance(manifest.get(name),str) or len(manifest[name])!=64:raise ValueError("Missing primary provenance: "+name)
    return source_order(manifest["rows"])
def choose_object(index,source_id):
    eligible=[t for t in index.objects if len(index.ownership(t)[1])==1]
    return min(eligible,key=lambda t:stable("natural-object",source_id,index.objects[t].get("sourceId"),t)) if eligible else None

def grounding(source,target_source_id,profiles,owner):
    scene=source["scene"];objects=scene["objects"]
    matches=[x for x in objects if x.get("objectId")==target_source_id]
    if len(matches)!=1:raise ValueError("Selected original source-object ID must be unique")
    if len({x["id"] for x in profiles})!=len(profiles):raise ValueError("Duplicate agent profile ID")
    if owner not in {x["id"] for x in profiles}:raise ValueError("Assigned owner has no profile")
    compact=[]
    for obj in sorted(objects,key=lambda x:x["objectId"]):
        position=obj.get("position",{});dimensions=obj.get("dimensions",{})
        compact.append([obj["objectId"],obj.get("objectType"),obj.get("group"),[position.get(k) for k in ("x","y","z")],[dimensions.get(k) for k in ("width","height","depth")]])
    return {"room":{k:scene[k] for k in ("sceneName","environment","objectGroups") if k in scene},"inventory_columns":["source_object_id","object_type","source_group","position_xyz","dimensions_width_height_depth"],"complete_room_inventory":compact,"selected_original_object":matches[0],"agent_profiles":sorted(profiles,key=lambda x:x["id"]),"proposed_agent_id":owner}
def payload(item,model):
    if model not in MODELS:raise ValueError("Unregistered judge model")
    schema={"type":"object","additionalProperties":False,"required":["judgment","reason","supporting_source_ids"],"properties":{"judgment":{"type":"string","enum":list(LABELS)},"reason":{"type":"string"},"supporting_source_ids":{"type":"array","items":{"type":"string"},"maxItems":3}}}
    prompt=(ROOT/"experiments/prompts/semantic_judges/assignment_plausibility.txt").read_text(encoding="utf8").strip()
    return {"model":model,"temperature":0,"max_output_tokens":OUTPUT_CAP,"input":[{"role":"developer","content":prompt},{"role":"user","content":canonical(item).decode()}],"text":{"format":{"type":"json_schema","name":"semantic_assignment_judgment","strict":True,"schema":schema}}}
def blind_order(items):
    """Input records contain private key/provenance; payload never contains them."""
    prepared=[]
    for row in items:
        public_id=stable("blind-item",row["key"])
        prepared.append({**row,"blind_id":public_id,"order_key":stable("judge-order",public_id)})
    if len({r["blind_id"] for r in prepared})!=len(prepared):raise ValueError("Duplicate study item")
    return sorted(prepared,key=lambda r:r["order_key"])
def valid_label(parsed,source_ids):
    if not isinstance(parsed,dict) or set(parsed)!={"judgment","reason","supporting_source_ids"}:return "FORMAT_ERROR"
    ids=parsed["supporting_source_ids"]
    if parsed["judgment"] not in LABELS or not isinstance(parsed["reason"],str) or not parsed["reason"].strip():return "FORMAT_ERROR"
    if not isinstance(ids,list) or len(ids)>3 or any(not isinstance(x,str) or x not in source_ids for x in ids):return "FORMAT_ERROR"
    return parsed["judgment"]
def agreement(pairs):
    eligible=[(a,b) for a,b in pairs if a in LABELS and b in LABELS]
    n=len(eligible);agree=sum(a==b for a,b in eligible)
    expected=sum(sum(a==v for a,b in eligible)*sum(b==v for a,b in eligible) for v in LABELS)/(n*n) if n else None
    observed=agree/n if n else None
    return {"planned_or_observed_pair_rows":len(pairs),"valid_paired_items":n,"invalid_or_missing_pairs":len(pairs)-n,"agreement_count":agree,"agreement_rate":observed,"cohen_kappa":(observed-expected)/(1-expected) if n and expected!=1 else None,"kappa_undefined_reason":"no_valid_pairs" if not n else ("constant_marginals" if expected==1 else None),"insufficient_evidence_model_A":sum(a=="insufficient_evidence" for a,b in pairs),"insufficient_evidence_model_B":sum(b=="insufficient_evidence" for a,b in pairs)}
