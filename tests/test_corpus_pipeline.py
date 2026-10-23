"""Offline unit tests for corpus provenance, frozen execution and repair evidence."""
import copy
import hashlib
import json
from pathlib import Path
import pytest

from experiments.scenes.generate_scenes import generate, make_scene, validate_source
from experiments import pipeline_runs
from experiments.lib.model_builder import build_room

def test_corpus_has_required_shape_geometry_and_reproducible_selection(tmp_path):
    report=generate(tmp_path/"sources")
    assert report["counts"]=={"total":48,"domains":12,"dev":3,"evaluation":45,"llm_written":0}
    assert report["size_range"]==[15,80]
    assert generate(tmp_path/"sources")==report
    selected=pipeline_runs.selected_sources(report["scenes"])
    assert len(selected)==30 and len({r["scene_id"] for r in selected})==30
    assert len({r["domain"] for r in selected})==12
    assert all(row["split"]=="evaluation" for row in selected)
    first=json.loads((tmp_path/"sources"/(report["scenes"][0]["scene_id"]+".json")).read_text())
    assert set(first)=={"scene"}
    assert set(first["scene"])=={"sceneName","environment","objectGroups","objects"}
    assert set(first["scene"]["objects"][0])=={"objectId","objectType","position","rotation","dimensions","group","children","specification"}
    first["scene"]["objects"][1]["position"]=copy.deepcopy(first["scene"]["objects"][0]["position"])
    with pytest.raises(ValueError,match="overlap"): validate_source(first)

def test_frozen_plan_missing_or_changed_refuses_before_any_execution(monkeypatch,tmp_path):
    monkeypatch.setattr(pipeline_runs,"ROOT",tmp_path)
    monkeypatch.setattr(pipeline_runs,"PLAN_PATH",tmp_path/"plan.json")
    monkeypatch.setattr(pipeline_runs,"FREEZE_PATH",tmp_path/"freeze.sha256")
    with pytest.raises(RuntimeError,match="not frozen"): pipeline_runs.load_frozen_plan()
    target=tmp_path/"implementation.py"; target.write_text("first")
    plan={"implementation_sha256":{"implementation.py":pipeline_runs.digest(target)},"prompt_sha256":{},
          "development":[],"evaluation":[]}
    pipeline_runs.PLAN_PATH.write_text(json.dumps(plan))
    pipeline_runs.FREEZE_PATH.write_text(pipeline_runs.digest(pipeline_runs.PLAN_PATH))
    assert pipeline_runs.load_frozen_plan()==plan
    target.write_text("changed")
    with pytest.raises(RuntimeError,match="changed"): pipeline_runs.load_frozen_plan()

def test_repair_snapshot_retains_invalid_before_and_valid_after(tmp_path):
    case=tmp_path/"case"; path=case/"intermediate/roles.json"; path.parent.mkdir(parents=True)
    path.write_text('{"status":"invalid"}')
    pipeline_runs.archive_snapshot(case,tmp_path/"attempt_02/before")
    path.write_text('{"status":"valid"}')
    pipeline_runs.archive_snapshot(case,tmp_path/"after_stage")
    assert json.loads((tmp_path/"attempt_02/before/intermediate/roles.json").read_text())["status"]=="invalid"
    assert json.loads((tmp_path/"after_stage/intermediate/roles.json").read_text())["status"]=="valid"
    pipeline_runs.archive_snapshot(case,tmp_path/"attempt_02/before")
    assert len(list((tmp_path/"attempt_02/before/intermediate").glob("*")))==2

@pytest.mark.parametrize("level",["asset","group","zone"])
def test_model_builder_validates_ownership_levels_and_backend_loader(tmp_path,level):
    from backend.roomcontract_v2_runtime import load_project_contract
    target={"asset":"x","group":"g","zone":"z"}[level]
    spec={"case_id":"unit_"+level,"agents":["a","b"],"objects":[{"id":"x","group":"g","zones":["z"]}],
          "owners":{level:{target:["a"]}},"handoffs":[["b","a"]]}
    built=build_room(spec,tmp_path/level)
    assert built.validation["ok"],built.validation
    assert built.trace["runtime_actions"]
    contract=load_project_contract(built.project_dir)
    assert contract
    assert (built.project_dir/"roomcontract.v2.instance.json").exists()

def test_model_builder_invalid_ownership_is_explicit():
    spec={"agents":["a","b"],"objects":["x"],"owners":{"asset":{"x":["a","b"]}}}
    with pytest.raises(ValueError,match="validation"): build_room(spec)
    invalid=build_room(spec,allow_invalid=True)
    assert not invalid.validation["ok"] and invalid.validation["errors"]
    assert invalid.project_dir is None

def test_model_builder_rejects_unknown_and_colliding_identifiers():
    with pytest.raises(ValueError,match="Identifiers"):
        build_room({"agents":["A","a"],"objects":["x"]})
    with pytest.raises(ValueError,match="unknown"):
        build_room({"agents":["a"],"objects":["x"],"owners":{"asset":{"x":["missing"]}}})



def test_runner_refuses_result_from_other_plan(monkeypatch,tmp_path):
    monkeypatch.setattr(pipeline_runs,"ROOT",tmp_path)
    plan_path=tmp_path/"plan.json"; plan_path.write_text("{}")
    monkeypatch.setattr(pipeline_runs,"PLAN_PATH",plan_path)
    row={"scene_id":"unit","model":"gpt-4.1-mini-2025-04-14","repetition":0,"phase":"evaluation"}
    result=tmp_path/"results/raw/wp5/evaluation/unit_mini_r0/run_result.json"
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({"source":row,"plan_sha256":"different"}))
    with pytest.raises(RuntimeError,match="different frozen plan"):
        pipeline_runs.run_case(row,{})

def test_real_adapter_ingestion_preserves_isolated_source(tmp_path):
    root=pipeline_runs.ROOT
    runtime=tmp_path/"runtime"; runtime.mkdir()
    adapter=pipeline_runs.RoomContractAdapter.discover(workspace_root=root,backend_root=runtime,
                                                       output_root=tmp_path/"cases")
    source=make_scene("astronomy_gallery",15,7,scene_id="unit_ingestion")
    initialized=adapter.initialize_case_from_payload(source,case_id="unit_ingestion")
    case=Path(initialized["case_dir"])
    result=adapter.run_stage(case,"rdl_ingestion")
    assert result["status"]=="success"
    assert case.is_relative_to(tmp_path)
    assert (case/"validation/rdl_ingestion_validation.json").exists()



def test_execution_amendments_require_freeze_and_matching_predecessor(monkeypatch,tmp_path):
    monkeypatch.setattr(pipeline_runs,"ROOT",tmp_path)
    monkeypatch.setattr(pipeline_runs,"PLAN_PATH",tmp_path/"plan.json")
    monkeypatch.setattr(pipeline_runs,"FREEZE_PATH",tmp_path/"plan.sha256")
    implementation=tmp_path/"implementation.py";implementation.write_text("old")
    old=pipeline_runs.digest(implementation)
    plan={"implementation_sha256":{"implementation.py":old},"prompt_sha256":{},"development":[],"evaluation":[]}
    pipeline_runs.PLAN_PATH.write_text(json.dumps(plan))
    base_hash=pipeline_runs.digest(pipeline_runs.PLAN_PATH)
    pipeline_runs.FREEZE_PATH.write_text(base_hash)
    implementation.write_text("corrected")
    amendments=tmp_path/"prereg/wp5_amendments"; amendments.mkdir(parents=True)
    path=amendments/"001_fix.json"
    amendment={"sequence":1,"kind":"implementation-only","prior_freeze_sha256":base_hash,
               "implementation_updates":{"implementation.py":{"old_sha256":old,"new_sha256":pipeline_runs.digest(implementation)}}}
    path.write_text(json.dumps(amendment))
    with pytest.raises(RuntimeError,match="not frozen"):pipeline_runs.load_frozen_plan()
    path.with_suffix(".sha256").write_text(pipeline_runs.digest(path))
    loaded=pipeline_runs.load_frozen_plan()
    assert loaded["implementation_sha256"]==plan["implementation_sha256"]
    assert loaded["_execution_amendments"][0]["sequence"]==1
    assert pipeline_runs.digest(pipeline_runs.PLAN_PATH)==base_hash
    amendment["prior_freeze_sha256"]="0"*64
    path.write_text(json.dumps(amendment));path.with_suffix(".sha256").write_text(pipeline_runs.digest(path))
    with pytest.raises(RuntimeError,match="predecessor"):pipeline_runs.load_frozen_plan()



@pytest.mark.parametrize("record,expected",[
    ({"stages":[{"result":{"validation":{"errors":["Budgeted gateway stopped request: NETWORK_ERROR"]}}}]},False),
    ({"stages":[{"result":{"validation":{"errors":["Budgeted gateway stopped request: INPUT_TOKEN_LIMIT"]}}}]},False),
    ({"stages":[{"result":{"validation":{"errors":["Budgeted gateway stopped request: BUDGET_STOP"]}}}]},True),
    ({"stages":[{"error_code":"BudgetError"}]},True),
    ({"gateway_error":"BUDGET_STOP"},True),
    ({"status":"success","note":"budget estimate retained"},False),
])
def test_only_explicit_budget_failure_stops_remaining_registered_rows(record,expected):
    assert pipeline_runs.budget_stop_record(record) is expected

def test_completed_failure_resumes_without_reexecution_or_replacement(monkeypatch,tmp_path):
    monkeypatch.setattr(pipeline_runs,"ROOT",tmp_path)
    plan=tmp_path/"plan.json";plan.write_text("{}")
    monkeypatch.setattr(pipeline_runs,"PLAN_PATH",plan)
    row={"scene_id":"unit_failed","model":"gpt-4.1-mini-2025-04-14","repetition":0,"phase":"evaluation"}
    saved={"source":row,"plan_sha256":pipeline_runs.digest(plan),"status":"failed","failure_stage":"scene_semantics",
           "stages":[{"result":{"validation":{"errors":["Budgeted gateway stopped request: NETWORK_ERROR"]}}}]}
    path=tmp_path/"results/raw/wp5/evaluation/unit_failed_mini_r0/run_result.json"
    path.parent.mkdir(parents=True);path.write_text(json.dumps(saved))
    before=path.read_bytes()
    monkeypatch.setattr(pipeline_runs.RoomContractAdapter,"discover",lambda **kw:pytest.fail("Completed failure was reexecuted"))
    result=pipeline_runs.run_case(row,{})
    assert result==saved and path.read_bytes()==before
    assert not pipeline_runs.budget_stop_record(result)

