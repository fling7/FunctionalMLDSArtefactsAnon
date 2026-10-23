"""Offline natural-study harness tests. No real or scripted generation occurs."""
from pathlib import Path
from experiments.natural_faults import NoGeneration, runtime_admission, request_for, clustered_interval
from experiments.lib.backend_driver import Driver
from experiments.lib.model_builder import build_room
from verification.impl_a import reference
from verification.impl_b import policy_adapter

def test_admission_only_matches_independent_evaluators_without_generation(tmp_path):
    room=build_room({"case_id":"natural_unit","agents":["a","b"],"objects":["x"],
                     "owners":{"asset":{"x":["a"]}},"handoffs":[["b","a"]]},tmp_path/"room")
    driver=Driver(room.project_dir,client=NoGeneration())
    try:
        request=request_for("b",driver.targets[0],driver.setup["model_sha256"],driver.session.session_id)
        actual=runtime_admission(driver,request)
        expected={"decision":"ANSWER_AFTER_HANDOFF","reason":None,"provider":"a","action":actual["action"]}
        assert {k:actual[k] for k in expected}==expected
        assert actual["state_unchanged"] and actual["generation_calls"]==0 and actual["action"]
        session={"model_sha256":driver.setup["model_sha256"],"active_agent_mode":"client"}
        assert reference.evaluate(room.instance,room.trace,request,session)==expected
        assert policy_adapter.evaluate(room.instance,room.trace,request,session)==expected
    finally:driver.close()

def test_intervals_cluster_paired_models_by_source_and_do_not_inflate_n():
    rows=[{"source":{"scene_id":"a"},"rate":0},{"source":{"scene_id":"a"},"rate":1},
          {"source":{"scene_id":"b"},"rate":1}]
    result=clustered_interval(rows,lambda r:r["rate"])
    assert result["estimate"]==0.75
    assert result["source_clusters"]==2
    assert result==clustered_interval(rows,lambda r:r["rate"])
    single=clustered_interval(rows[:2],lambda r:r["rate"])
    assert single["source_clusters"]==1 and single["low"] is None

