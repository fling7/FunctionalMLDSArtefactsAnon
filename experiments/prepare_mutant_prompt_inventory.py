"""Unpaid deterministic WP6 B0/B1 candidate inventory. No API client is created."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.routing_verifier import NativeRoutingIndex, verify_routing, lookup_route
from experiments.swap_semantic_lint import changed_targets
SEED=20261015
OPERATORS=("duplicate_asset_owner","remove_all_owners","move_owner_without_path","remove_action","duplicate_action","swap_owners_consistently","drop_handoff")
REASONS={"duplicate_asset_owner":"E_AMBIGUOUS_OWNER","remove_all_owners":"E_UNOWNED","move_owner_without_path":"E_NO_DECLARED_ACTION","remove_action":"E_NO_DECLARED_ACTION","duplicate_action":"E_ACTION_AMBIGUOUS","drop_handoff":"E_NO_HANDOFF_PATH"}
FIELDS=("decision","reason","provider","action")
def read(p): return json.loads(Path(p).read_text(encoding="utf-8-sig"))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable(*x): return hashlib.sha256(json.dumps([SEED,*x],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
def equal(a,b): return all(a.get(k)==b.get(k) for k in FIELDS)
def choose_probe(probes,operator,room,baseline,changed=()):
    candidates=[]
    for probe in probes:
        if not equal(probe["I1"],probe["I2"]): continue
        start,target=probe["start_agent"],probe["target"]
        old=lookup_route(baseline,start,target);new=probe["I1"]
        if old["decision"]=="REJECT": continue
        if operator=="swap_owners_consistently":
            eligible=target in changed and new["decision"]!="REJECT" and old.get("provider")!=new.get("provider")
        else: eligible=new.get("reason")==REASONS[operator]
        if eligible:candidates.append((stable(room,operator,start,target),probe,old))
    if not candidates:return None
    rank,probe,old=min(candidates,key=lambda x:x[0])
    return {"start_agent":probe["start_agent"],"target_id":probe["target"],"rank_sha256":rank,"candidate_count":len(candidates),"baseline_verdict":old,"verdict":probe["I1"],"I2":probe["I2"]}
def collect(run_dirs):
    records={};pins={}
    for run_dir in map(Path,run_dirs):
        manifest_path=run_dir/"mutation_manifest.json";manifest=read(manifest_path)
        pins[str(manifest_path)]=sha(manifest_path)
        recovery_path=run_dir/"recovery_manifest.json"
        recovery=read(recovery_path) if recovery_path.exists() else None
        if recovery:pins[str(recovery_path)]=sha(recovery_path)
        for meta in manifest["models"]:
            if len(meta.get("operators",[]))!=1:continue
            if meta["id"] in records:raise ValueError("Duplicate original/recovery observation: "+meta["id"])
            outcome_path=run_dir/"outcomes"/(meta["storage_id"]+".json")
            outcome=read(outcome_path) if outcome_path.exists() else None
            if outcome and outcome["metadata"]!=meta:raise ValueError("Outcome metadata mismatch")
            records[meta["id"]]={"metadata":meta,"run_dir":str(run_dir),"outcome":outcome,"outcome_path":str(outcome_path) if outcome else None,"outcome_sha256":sha(outcome_path) if outcome else None,"recovery_provenance_path":str(recovery_path) if recovery else None}
    return records,pins

def prepare(run_dirs,sources_path,out_dir):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=False)
    sources=read(sources_path)["sources"]
    rooms=sorted(sources,key=lambda x:(sources[x]["source_priority"] is not None,sources[x]["source_priority"] or 0,x))
    if len(rooms)!=5:raise ValueError("Draft design requires the frozen classroom plus four generated sources")
    records,pins=collect(run_dirs);pins[str(sources_path)]=sha(sources_path)
    intents=[{"block":i+1,"operator":op,"room":rooms[i%len(rooms)]} for i,op in enumerate(OPERATORS)]
    inventory=[];selected=[];bases={}
    for record in records.values():
        meta=record["metadata"];room=meta["room"];op=meta["operators"][0];outcome=record["outcome"]
        if room not in sources:raise ValueError("Unexpected source")
        project=Path(record["run_dir"])/"models"/meta["storage_id"]/Path(sources[room]["project_path"]).name
        public={k:v for k,v in record.items() if k!="outcome"}
        public.update(source_provenance=sources[room],project_path=str(project),setup_status=(outcome or {}).get("checkers",{}).get("backend_setup",{}).get("status","not_run"),groundtruth=(outcome or {}).get("groundtruth"))
        public["availability"]="operator_not_realized" if meta["status"] not in {"changed","incomplete"} else ("completed" if outcome else "routing_pending")
        inventory.append(public)
        intent=next((x for x in intents if x["room"]==room and x["operator"]==op),None)
        if not intent:continue
        selected_row={**intent,**public,"status":public["availability"],"probe":None}
        if outcome:
            if outcome.get("independent_disagreements") or outcome["groundtruth"].get("routing_faulty") is None:
                selected_row["status"]="unresolved_oracle"
            else:
                model=project/"roomcontract.v2.instance.json"
                if sha(model).upper()!=outcome["model_sha256"]:raise ValueError("Mutant digest mismatch")
                if room not in bases:
                    base=ROOT/sources[room]["project_path"];instance=read(base/"roomcontract.v2.instance.json");trace=read(base/"trace_map.v2.json")
                    pins[str(base/"roomcontract.v2.instance.json")]=sha(base/"roomcontract.v2.instance.json")
                    pins[str(base/"trace_map.v2.json")]=sha(base/"trace_map.v2.json")
                    bases[room]=(NativeRoutingIndex(instance,trace),verify_routing(instance,trace,model_sha256=sources[room]["model_sha256"]))
                old_index,baseline=bases[room];changed=[]
                if op=="swap_owners_consistently":
                    changed=[c["target"] for c in changed_targets(old_index,NativeRoutingIndex(read(model),read(project/"trace_map.v2.json")))]
                selected_row["probe"]=choose_probe(outcome["probes"],op,room,baseline,changed)
                selected_row["status"]="ready" if selected_row["probe"] else "no_intended_affected_agreed_probe"
                if selected_row["probe"]:
                    from experiments.routing_baselines import router_payload
                    from experiments.lib.wp4_common import profiles, MODELS
                    instance=read(model);target=next(x for x in instance["objects"] if x["id"]==selected_row["probe"]["target_id"])
                    context={"instance":instance,"agent_profiles":profiles(project)}
                    item={"target":target,"start_agent":selected_row["probe"]["start_agent"]}
                    payloads=[]
                    for model_name in MODELS:
                        for baseline_name in ("B0","B1"):
                            for abstain in (False,True):
                                for phrasing in (1,2,3):
                                    payload=router_payload(context,item,"What can you tell me about this selected object?",baseline_name,abstain,phrasing,model_name)
                                    payloads.append({"model":model_name,"baseline":baseline_name,"abstain":abstain,"phrasing":phrasing,"payload":payload})
                    destination=out/("block_%02d_payloads.json"%intent["block"])
                    destination.write_text(json.dumps(payloads,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
                    selected_row.update(payloads_path=destination.name,payloads_sha256=sha(destination),payload_count=len(payloads),native_setup_refused=selected_row["setup_status"]=="reject")
        selected.append(selected_row)
    result={"schema":"wp6-mutant-prompt-draft-v1","status":"DRAFT_NO_API_AUTHORIZATION","seed":SEED,"sampling_is_post_routing_pre_llm":True,"inventory":sorted(inventory,key=lambda x:x["metadata"]["id"]),"blocks":sorted(selected,key=lambda x:x["block"]),"fixed_block_intents":intents,"input_sha256":pins,"code_sha256":sha(__file__),"no_double_count":"One outcome per unique mutant ID; originals and recovery copies cannot both enter."}
    (out/"inventory.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    return result
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--run-dir",type=Path,action="append",required=True);p.add_argument("--sources",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);a=p.parse_args()
    r=prepare(a.run_dir,a.sources,a.output_dir);print(json.dumps({"inventory":len(r["inventory"]),"blocks":[{k:b[k] for k in ("block","operator","room","status","setup_status")} for b in r["blocks"]]}))
