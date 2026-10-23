"""Actual loopback HTTP tests; deterministic model stub is unit-test-only."""
import contextlib,json,threading
from http.server import ThreadingHTTPServer
import pytest
from experiments.lib.backend_driver import Driver,ScriptedClient,http_json
from backend.guard_config import GuardConfig
from backend.roomcontract_v2_runtime import RoomContractContractError
import backend.server as server

@contextlib.contextmanager
def serving(monkeypatch,store):
    servers=[];ready=threading.Event()
    def factory(*args,**kwargs):
        httpd=ThreadingHTTPServer(*args,**kwargs);servers.append(httpd);ready.set();return httpd
    monkeypatch.setattr(server,"ThreadingHTTPServer",factory)
    thread=threading.Thread(target=server.start_http_server,args=("127.0.0.1",0,store),daemon=True);thread.start()
    assert ready.wait(5)
    try:yield "http://127.0.0.1:"+str(servers[0].server_port)
    finally:servers[0].shutdown();thread.join(5)

def local(d):
    t=d.targets[0]
    owner=next(a["sourceAgentId"] for a in d.contract["instance"]["objects"] if a.get("type")=="Agent" and t["id"] in a.get("groundedAsset",[]))
    return owner,t

def test_strict_switch_and_failed_append_roll_back_http(monkeypatch):
    d=Driver()
    try:
        d.store.guard_config=GuardConfig(active_agent_mode="server_strict")
        owner,target=local(d)
        with serving(monkeypatch,d.store) as url:
            other=next(a["id"] for a in d.setup["agents"] if a["id"]!=d.session.server_active_agent_id)
            status,error=http_json(url,"/chat",d.request(other,target))
            assert status==400 and error["code"]=="E_ACTIVE_AGENT_MISMATCH" and d.client.calls==0
            assert http_json(url,"/switch_agent",{"session_id":d.session.session_id,"active_agent_id":owner})[0]==200
            snap=d.store.snapshot_session_mutation(d.session.session_id)
            def fail(**kwargs):raise RoomContractContractError("Injected evidence error",code="E_EVIDENCE_APPEND")
            monkeypatch.setattr(server,"log_backend_events",fail)
            status,error=http_json(url,"/chat",d.request(owner,target))
            assert status==400 and error["code"]=="E_EVIDENCE_APPEND"
            assert d.store.snapshot_session_mutation(d.session.session_id)==snap
    finally:d.close()

@pytest.mark.parametrize("mode",["abort","drop_log"])
def test_fallback_proposal_http_result_and_evidence(monkeypatch,mode):
    d=Driver(client=ScriptedClient(proposal="unmodeled_target",fallback=True))
    try:
        d.store.guard_config=GuardConfig(proposal_mode=mode)
        owner,target=local(d);snap=d.store.snapshot_session_mutation(d.session.session_id)
        with serving(monkeypatch,d.store) as url:
            status,out=http_json(url,"/chat",d.request(owner,target))
        if mode=="abort":
            assert status==400 and out["code"]=="E_HANDOFF_PROPOSAL"
            assert d.store.snapshot_session_mutation(d.session.session_id)==snap
        else:
            assert status==200 and out["active_agent_id"]==owner
            assert "_guard_ignored_proposals" not in out
            from backend.runtime_trace import _runtime_log_path
            records=[json.loads(s) for s in _runtime_log_path(d.project).read_text(encoding="utf-8").splitlines()]
            assert any("unmodeled_target" in json.dumps(r) for r in records)
    finally:d.close()

@pytest.mark.parametrize("scope,expected",[("none",200),("digest_only",200),("full",400),("slice",200),("slice_prompt",200)])
def test_commit_scope_is_wired_through_http(monkeypatch,scope,expected):
    d=Driver()
    try:
        d.store.guard_config=GuardConfig(commit_variant=scope)
        d.setup=d.store.setup_from_request({"project_id":d.project.name,"session_id":"regression"})
        d.session=d.store.sessions["regression"]
        owner,target=local(d)
        original=d.client.create_structured_json
        def edit_during_generation(**kwargs):
            result=original(**kwargs)
            path=d.project/"trace_map.v2.json";trace=json.loads(path.read_text());trace["experimental_note"]="edited during call"
            path.write_text(json.dumps(trace),encoding="utf-8")
            return result
        d.client.create_structured_json=edit_during_generation
        snap=d.store.snapshot_session_mutation(d.session.session_id)
        with serving(monkeypatch,d.store) as url:status,out=http_json(url,"/chat",d.request(owner,target))
        assert status==expected,(scope,out)
        if status!=200:
            assert out["code"]=="E_CONTRACT_DRIFT"
            assert d.store.snapshot_session_mutation(d.session.session_id)==snap
        assert d.client.calls==1
    finally:d.close()
