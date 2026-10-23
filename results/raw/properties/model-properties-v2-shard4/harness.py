"""Generate random native publications; property assertions do not call I1/I2."""
from __future__ import annotations
import argparse,copy,hashlib,json,os,sys,tempfile,time,traceback,contextlib,io,threading
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hypothesis import given,settings,seed,strategies as st,HealthCheck
from experiments.lib.model_builder import build_room
from experiments.lib.backend_driver import Driver,ScriptedClient,http_json
from backend.guard_config import GuardConfig
from backend.roomcontract_v2_runtime import load_project_contract
from backend.runtime_trace import contract_runtime_fingerprint
import backend.server as server
from http.server import ThreadingHTTPServer

@st.composite
def rooms(draw):
    n=draw(st.integers(2,4));m=draw(st.integers(2,5))
    agents=[f"a{i}" for i in range(n)]
    groups=[f"g{i}" for i in range(draw(st.integers(1,3)))]
    zones=[f"z{i}" for i in range(draw(st.integers(1,3)))]
    objects=[{"id":f"o{i}","group":draw(st.sampled_from(groups)),
              "zones":draw(st.lists(st.sampled_from(zones),min_size=1,max_size=len(zones),unique=True))} for i in range(m)]
    owners={}
    for level,ids in (("asset",[o["id"] for o in objects]),("group",groups),("zone",zones)):
        owners[level]={x:draw(st.lists(st.sampled_from(agents),max_size=min(n,2),unique=True)) for x in ids}
    ownership_mode=draw(st.sampled_from(["asset_unique","group_unique","zone_unique","arbitrary"]))
    if ownership_mode!="arbitrary":
        owners={level:{} for level in ("asset","group","zone")}
        ids={"asset_unique":[o["id"] for o in objects],"group_unique":groups,"zone_unique":zones}[ownership_mode]
        level=ownership_mode.split("_")[0]
        owners[level]={x:[draw(st.sampled_from(agents))] for x in ids}
    handoffs=draw(st.lists(st.sampled_from([(a,b) for a in agents for b in agents if a!=b]),max_size=n*(n-1),unique=True))
    variant=draw(st.sampled_from(["normal","stale_digest","unknown_entity","mismatch_source","none","ambiguous","ambiguity_flag","candidate_conflict"]))
    actions=[]
    action_mode=draw(st.sampled_from(["resolved_single","random","missing","duplicate"]))
    for obj in objects:
        tiers=[owners["asset"].get(obj["id"],[]),owners["group"].get(obj["group"],[]),
               list(dict.fromkeys(a for z in obj["zones"] for a in owners["zone"].get(z,[])))]
        selected=next((x for x in tiers if x),agents)
        provider=selected[0] if action_mode in {"resolved_single","duplicate"} else draw(st.sampled_from(agents))
        count={"resolved_single":1,"missing":0,"duplicate":2}.get(action_mode)
        if count is None:count=draw(st.integers(0,2))
        actions.append({"target":obj["id"],"provider":provider,"count":count})
    spec={"actions":actions,"case_id":"property_room","agents":agents,"objects":objects,"groups":groups,"zones":zones,"owners":owners,"handoffs":handoffs}
    return spec,draw(st.sampled_from(agents)),draw(st.integers(0,m-1)),variant

def owners_of(instance,target):
    nodes=instance["objects"];agents=[x for x in nodes if x.get("type")=="Agent"]
    groups=set(target.get("objectGroup",[]))
    zones={x["id"] for x in nodes if x.get("kind")=="zone" and target["sourceId"] in x.get("sourceObjectId",[])}
    levels=[{a["id"] for a in agents if target["id"] in a.get("groundedAsset",[])},
            {a["id"] for a in agents if groups & set(a.get("groundedObjectGroup",[]))},
            {a["id"] for a in agents if zones & set(a.get("responsibleZone",[]))}]
    return next((s for s in levels if s),set())

def assert_admitted(instance,trace,request,result,target):
    nodes={o["id"]:o for o in instance["objects"]}
    agents={o["sourceAgentId"]:o for o in nodes.values() if o.get("type")=="Agent"}
    # G1: native unique source target and the request pin/identity.
    assert request["spatial_context"]["entity_id"]==target["id"]
    assert request["spatial_context"]["source_object_id"]==target["sourceId"]
    assert len([o for o in nodes.values() if o.get("entityRole")=="sceneObject" and o.get("sourceId")==target["sourceId"]])==1
    # G2: provider is the unique deciding owner; at most one native edge.
    owner=owners_of(instance,target)
    assert owner=={agents[result["provider"]]["id"]},("G2",owner,result)
    active=agents[request["active_agent_id"]]
    assert result["provider"]==request["active_agent_id"] or agents[result["provider"]]["id"] in active.get("handoffTarget",[])
    # G3: returned action has one native s->u->c->b->a path for this pair.
    matches=[]
    for u in nodes.values():
        if u.get("type")!="CapabilityUse" or u.get("provider")!=[agents[result["provider"]]["id"]] or target["id"] not in u.get("target",[]):continue
        for c in u.get("typeRef",[]):
            for b in nodes.values():
                if b.get("type")!="RuntimeBinding" or c not in b.get("capability",[]):continue
                for a in b.get("runtimeAction",[]):
                    action=nodes.get(a,{})
                    kinds=[]
                    for schema_id in action.get("inputSchema",[]):
                        try:kinds.append(json.loads(nodes[schema_id].get("text","{}")).get("applicationActionKind"))
                        except (KeyError,ValueError):pass
                    if "chat" in kinds:
                        steps=[s["id"] for s in nodes.values() if s.get("type")=="ScenarioStep" and u["id"] in s.get("capabilityUse",[])]
                        matches.extend((s,u["id"],c,b["id"],a) for s in steps)
    assert len(matches)==1 and matches[0][-1]==result["action"],("G3",matches,result)
    assert result["model_calls"]==1


@contextlib.contextmanager
def serve(store):
    servers=[];ready=threading.Event();original=server.ThreadingHTTPServer
    def factory(*args,**kwargs):
        httpd=ThreadingHTTPServer(*args,**kwargs);servers.append(httpd);ready.set();return httpd
    server.ThreadingHTTPServer=factory
    thread=threading.Thread(target=server.start_http_server,args=("127.0.0.1",0,store),daemon=True)
    thread.start()
    assert ready.wait(10),"HTTP test server did not start"
    try:yield "http://127.0.0.1:"+str(servers[0].server_port)
    finally:
        servers[0].shutdown();thread.join(10);server.ThreadingHTTPServer=original

def commit_properties(d,req,result):
    """Exercise the actual HTTP transaction on unchanged and drifted contracts."""
    d.store.guard_config=GuardConfig()
    d.client.proposal=None
    d.client.fallback=False
    before_contract=contract_runtime_fingerprint(load_project_contract(d.project))
    with serve(d.store) as url:
        calls=d.client.calls
        status,output=http_json(url,"/chat",req)
        assert status==200,("G4_valid_commit_failed",status,output)
        assert output["active_agent_id"]==result["provider"],("G5_committed_provider",output,result)
        assert d.client.calls==calls+1
        assert contract_runtime_fingerprint(load_project_contract(d.project))==before_contract,("G4_contract_mismatch_at_success",)
        snap=d.store.snapshot_session_mutation(d.session.session_id)
        evidence={p.relative_to(d.project).as_posix():p.read_bytes() for p in d.project.rglob("*.jsonl")}
        trace_path=d.project/"trace_map.v2.json";original_bytes=trace_path.read_bytes()
        invoke=d.client.create_structured_json
        def drift(**kwargs):
            value=invoke(**kwargs)
            trace=json.loads(original_bytes);trace["property_commit_drift"]="changed after admission"
            trace_path.write_text(json.dumps(trace),encoding="utf-8")
            return value
        d.client.create_structured_json=drift
        try:
            status,output=http_json(url,"/chat",req)
            assert status==400 and output.get("code")=="E_CONTRACT_DRIFT",("G4_drift_committed",status,output)
            assert d.store.snapshot_session_mutation(d.session.session_id)==snap,("G4_state_not_restored",)
            after={p.relative_to(d.project).as_posix():p.read_bytes() for p in d.project.rglob("*.jsonl")}
            assert after==evidence,("G4_failed_turn_appended",)
        finally:
            trace_path.write_bytes(original_bytes);d.client.create_structured_json=invoke
    return {"unchanged_commit_status":200,"drift_commit_status":400,"drift_reason":"E_CONTRACT_DRIFT",
            "rollback_byte_equal":True,"evidence_byte_equal":True}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--models",type=int,default=5000);ap.add_argument("--seed",type=int,default=20261015);ap.add_argument("--run-id",default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"));args=ap.parse_args()
    out=ROOT/"results/raw/properties"/args.run_id;out.mkdir(parents=True,exist_ok=False)
    counts=Counter();unique=set();model_hashes=set();start=time.perf_counter()
    raw=(out/"models.jsonl").open("w",encoding="utf-8")
    (out/"harness.py").write_bytes(Path(__file__).read_bytes())
    dependencies=[Path(__file__),ROOT/"experiments/lib/model_builder.py",ROOT/"experiments/lib/backend_driver.py"]
    dependencies+=list((ROOT/"app/backend_root/agent_backend/backend").glob("*.py"))
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
    (out/"source_hashes.json").write_text(json.dumps(hashes,indent=2),encoding="utf-8")
    @seed(args.seed)
    @settings(max_examples=args.models,deadline=None,suppress_health_check=list(HealthCheck))
    @given(rooms())
    def check(case):
        spec,active,index,variant=case
        case_hash=hashlib.sha256(json.dumps(case,sort_keys=True).encode()).hexdigest()
        counts["generated_cases"]+=1;unique.add(case_hash)
        for action in spec["actions"]:counts["declared_action_multiplicity_"+str(action["count"])]+=1
        row={"case_hash":case_hash,"spec":spec,"active":active,"target_index":index,"variant":variant}
        try:
            with tempfile.TemporaryDirectory(prefix="property-",dir=ROOT/"results/tmp") as folder:
                built=build_room(spec,Path(folder),allow_invalid=True)
                row["authoring_ok"]=built.validation["ok"]
                row["model_sha256"]=hashlib.sha256(json.dumps(built.instance,sort_keys=True).encode()).hexdigest()
                model_hashes.add(row["model_sha256"])
                try:d=Driver(built.project_dir)
                except Exception as e:
                    counts["setup_refused"]+=1;row.update({"status":"setup_refused","reason":getattr(e,"code",type(e).__name__)})
                    return
                try:
                    target=next(t for t in d.targets if t["sourceId"]==spec["objects"][index]["id"])
                    for request_variant in dict.fromkeys(("normal",variant)):
                        d.store.guard_config=GuardConfig()
                        d.client.proposal=None
                        req=d.request(active,target,request_variant)
                        result=d.probe(req);row.setdefault("requests",[]).append({"variant":request_variant,"result":result})
                        if result["decision"]=="REJECT":
                            counts["rejected_requests"]+=1
                            assert result["model_calls"]==0,("rejection_called_model",result)
                            assert result["unchanged_before_restore"],("rejection_mutated_state",result)
                        else:
                            counts["admitted_requests"]+=1
                            assert request_variant=="normal",("admitted_invalid_selection",request_variant,result)
                            assert_admitted(built.instance,built.trace,req,result,target)
                        # G5 property: an arbitrary unmodeled model handoff never
                        # changes derived provider in explicit drop-and-log mode.
                        if result["decision"]!="REJECT":
                            d.store.guard_config=GuardConfig(proposal_mode="drop_log")
                            d.client.proposal="unmodeled_agent"
                            injected=d.probe(req)
                            assert injected["decision"]==result["decision"] and injected["provider"]==result["provider"]
                            counts["proposal_properties"]+=1
                    d.client.proposal=None;d.store.guard_config=GuardConfig()
                    normal=next(r for r in row["requests"] if r["variant"]=="normal")["result"]
                    if normal["decision"]!="REJECT":
                        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                            row["commit_properties"]=commit_properties(d,d.request(active,target),normal)
                        counts["g4_success_and_drift_pairs"]+=1
                    row["status"]="pass"
                finally:d.close()
        except Exception:
            row["status"]="counterexample";row["error"]=traceback.format_exc()
            (out/"counterexample.json").write_text(json.dumps(row,indent=2),encoding="utf-8")
            raise
        finally:
            raw.write(json.dumps(row,ensure_ascii=False)+"\n");raw.flush()
    status="pass"
    try:check()
    except Exception:status="fail";traceback.print_exc()
    finally:raw.close()
    summary={"status":status,"unit":"generated model/request configuration","requested_examples":args.models,"unique_cases":len(unique),"unique_models":len(model_hashes),"counts":dict(counts),"elapsed_seconds":time.perf_counter()-start,
             "seed":args.seed,"harness_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "scope":"G1/G2/G3/G5 admission properties and rejected-call/state isolation; G4 actual HTTP success and drift rollback on every admitted normal request. Declared actions vary by provider and multiplicity. Known original-request schema defects remain covered by the separate differential suite.",
             "llm":"unit-test scripted stub; no real model evaluation"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");print(json.dumps(summary))
    return 0 if status=="pass" else 1
if __name__=="__main__":raise SystemExit(main())
