"""Unit tests only: synthetic transports verify opt-in hooks, never model results."""
import importlib
import json
from pathlib import Path
import sys
import pytest
from repro.llm import experiment_context, production_response, GatewayError
from tools.case_study_pipeline.llm_client import ResponsesClient, LlmSettings, load_llm_settings

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app/backend_root/agent_backend"))
from backend.openai_client import OpenAIResponsesClient, OpenAIHTTPError, create_tts_audio

def body():
    return {"model":"gpt-4.1-mini","output":[{"type":"message","content":[{"type":"output_text","text":'{"ok":true}'}]}]}

class UnitHTTP:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return json.dumps(body()).encode()

def test_backend_default_retains_original_transport(monkeypatch):
    monkeypatch.delenv("ROOMCONTRACT_LLM_GATEWAY",raising=False)
    calls=[]
    monkeypatch.setattr("backend.openai_client.urllib.request.urlopen",lambda req,**kw:(calls.append(req) or UnitHTTP()))
    assert OpenAIResponsesClient("unit-key").create({"model":"gpt-4.1-mini","input":"unit"})==body()
    assert len(calls)==1

def test_backend_opt_in_uses_gateway_and_disables_audio(monkeypatch):
    monkeypatch.setenv("ROOMCONTRACT_LLM_GATEWAY","1")
    calls=[]
    monkeypatch.setattr("repro.llm.production_response",lambda payload,**kw:(calls.append((payload,kw)) or body()))
    assert OpenAIResponsesClient("unit-key").create({"input":"unit"})==body()
    assert calls[0][1]["source"]=="backend"
    with pytest.raises(OpenAIHTTPError):
        create_tts_audio(api_key="unit-key",text="unit",voice="alloy",model="unpriced-audio")

def test_pipeline_default_and_opt_in_keep_output_parsing(monkeypatch,tmp_path):
    settings=LlmSettings("unit-key","https://api.openai.com/v1/responses","gpt-4.1-mini",60,tmp_path/"config.json")
    calls=[]
    monkeypatch.delenv("ROOMCONTRACT_LLM_GATEWAY",raising=False)
    monkeypatch.setattr("tools.case_study_pipeline.llm_client.urllib.request.urlopen",lambda req,**kw:(calls.append("legacy") or UnitHTTP()))
    args={"input_messages":[{"role":"user","content":"unit"}],"schema":{"type":"object"},"schema_name":"unit"}
    assert ResponsesClient(settings).create_structured_json(**args)[0]=={"ok":True}
    monkeypatch.setenv("ROOMCONTRACT_LLM_GATEWAY","1")
    monkeypatch.setattr("repro.llm.production_response",lambda payload,**kw:(calls.append("gateway") or body()))
    assert ResponsesClient(settings).create_structured_json(**args)[0]=={"ok":True}
    assert calls==["legacy","gateway"]

def test_context_provides_stable_stage_attempts_and_bound(monkeypatch,tmp_path):
    captures=[]
    class UnitGateway:
        def __init__(self,*args,**kwargs): assert kwargs["count_input_tokens"]
        def responses(self,payload,**kwargs):
            captures.append((payload,kwargs)); return body()
    monkeypatch.setattr("repro.llm.Gateway",UnitGateway)
    for restart in range(2):
        with experiment_context(experiment_id="WP5.unit",item_id="scene01",repetition_id=0,share="WP5",
                                stage_id="roles",root=tmp_path,max_output_tokens=100,model="gpt-4.1-mini-2025-04-14"):
            production_response({"model":"gpt-4.1","max_output_tokens":200},api_key="unit-key")
            production_response({"model":"gpt-4.1","max_output_tokens":200},api_key="unit-key")
    assert captures[0]==captures[2] and captures[1]==captures[3]
    assert captures[0][1]["item_id"].endswith("roles.attempt01")
    assert captures[1][1]["item_id"].endswith("roles.attempt02")
    assert captures[0][0]["max_output_tokens"]==100
    assert captures[0][0]["model"]=="gpt-4.1-mini-2025-04-14"

def test_missing_hook_identity_fails_before_network(monkeypatch):
    for name in ("LLM_EXPERIMENT_ID","LLM_ITEM_ID","LLM_REPETITION_ID","LLM_BUDGET_SHARE"):
        monkeypatch.delenv(name,raising=False)
    with pytest.raises(GatewayError) as exc:
        production_response({"model":"gpt-4.1-mini","input":"unit"})
    assert exc.value.code=="MISSING_EXPERIMENT_IDENTITY"



def test_context_enforces_parameters_and_records_each_attempt(monkeypatch,tmp_path):
    events=[]
    class UnitGateway:
        def __init__(self,*args,**kwargs): pass
        def responses(self,payload,**kwargs):
            events.append(("gateway",payload,kwargs)); return body()
    monkeypatch.setattr("repro.llm.Gateway",UnitGateway)
    with experiment_context(experiment_id="WP5.unit",item_id="scene",repetition_id=0,share="WP5",
                            root=tmp_path,temperature=0.3,max_input_tokens=123,max_output_tokens=456,
                            before_call=lambda n,p:events.append(("before",n,p)),
                            after_call=lambda n,r:events.append(("after",n,r))):
        production_response({"model":"gpt-4.1-mini","input":"unit","max_output_tokens":1000,"temperature":0.2})
    assert [e[0] for e in events]==["before","gateway","after"]
    assert events[0][1]==events[-1][1]==1
    assert events[1][1]["temperature"]==0.3
    assert events[1][1]["max_output_tokens"]==456
    assert events[1][2]["max_input_tokens"]==123

def test_pipeline_replay_loads_no_credentials(monkeypatch,tmp_path):
    monkeypatch.setenv("ROOMCONTRACT_LLM_GATEWAY","1")
    monkeypatch.setenv("LLM_REPLAY","1")
    def forbidden(*args,**kwargs): pytest.fail("Replay loaded credentials")
    monkeypatch.setattr("repro\x2eenv.load_env",forbidden)
    monkeypatch.setattr("tools.case_study_pipeline.llm_client._load_api_key",forbidden)
    config=tmp_path/"config.json"; config.write_text("{}")
    assert load_llm_settings(config_path=config).api_key==""

