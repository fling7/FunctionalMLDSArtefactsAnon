import copy
import pytest
from experiments.prepare_wp6_corpus_scope import select_rows

def rows():
 return {"completed_runs":3,"rows":[{"source_priority":2,"run_ordinal":2,"case_id":"b","source_room_id":"same","project_produced":True,"project_path":"p/b","gate0_ok":False,"eligible_native_success":False},{"source_priority":2,"run_ordinal":1,"case_id":"a","source_room_id":"same","project_produced":True,"project_path":"p/a","gate0_ok":True,"eligible_native_success":True},{"source_priority":1,"run_ordinal":3,"case_id":"fail","project_produced":False}]}
def test_counterparts_and_failures_remain_without_outcome_filtering():
 m=rows();before=copy.deepcopy(m);chosen=select_rows(m,3)
 assert [r["case_id"] for r in chosen]==["fail","a","b"] and m==before
 assert [r["wp6_intake_status"] for r in chosen]==["no_project_produced","produced_project_pending_preparation","produced_project_pending_preparation"]
 for r in m["rows"]:r["gate0_ok"]=not r.get("gate0_ok");r["eligible_native_success"]=False
 assert [r["case_id"] for r in select_rows(m,3)]==["fail","a","b"]
@pytest.mark.parametrize("kind",["nonterminal","duplicate_id","alias"])
def test_invalid_inventory_refused(kind):
 m=rows()
 if kind=="nonterminal":m["completed_runs"]=2
 elif kind=="duplicate_id":m["rows"][0]["case_id"]="a"
 else:m["rows"][0]["project_path"]="p/a"
 with pytest.raises(ValueError):select_rows(m,3)


def fixture_manifest(tmp_path):
 import hashlib,json
 from pathlib import Path
 project=tmp_path/"project";project.mkdir();(project/"kb").mkdir()
 for name in ("project.json","roomcontract.v2.instance.json","trace_map.v2.json","agents.json","room_plan.json","kb/topic.txt"):(project/name).write_text("{}",encoding="utf8")
 run=tmp_path/"run.json";run.write_text(json.dumps({"artifact_sha256":{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in project.rglob("*") if f.is_file()}}),encoding="utf8")
 row={"source_priority":1,"run_ordinal":1,"case_id":"x","project_produced":True,"project_path":str(project),"model_sha256":hashlib.sha256(b"{}").hexdigest(),"run_result_path":str(run),"run_result_sha256":hashlib.sha256(run.read_bytes()).hexdigest()}
 manifest=tmp_path/"manifest.json";manifest.write_text(json.dumps({"completed_runs":1,"rows":[row]}),encoding="utf8")
 return project,manifest,row

def test_native_digest_mismatch_preserved_as_refusal(tmp_path):
 import json
 from experiments.prepare_wp6_corpus_scope import catalog
 project,manifest,row=fixture_manifest(tmp_path)
 assert catalog(manifest,1)["rows"][0]["wp6_intake_status"]=="native_artifacts_available"
 row["model_sha256"]="0"*64;manifest.write_text(json.dumps({"completed_runs":1,"rows":[row]}),encoding="utf8")
 assert catalog(manifest,1)["rows"][0]["wp6_intake_status"]=="artifact_or_preparation_refused"

@pytest.mark.parametrize("name",["project.json","trace_map.v2.json","agents.json","room_plan.json","kb/topic.txt"])
def test_changed_copied_input_refused_with_unchanged_native(tmp_path,name):
 from experiments.prepare_wp6_corpus_scope import catalog
 project,manifest,row=fixture_manifest(tmp_path);native=(project/"roomcontract.v2.instance.json").read_bytes()
 (project/name).write_text('{"changed":true}',encoding="utf8")
 result=catalog(manifest,1)["rows"][0]
 assert (project/"roomcontract.v2.instance.json").read_bytes()==native
 assert result["wp6_intake_status"]=="artifact_or_preparation_refused"
 assert any(r["path"]==name and not r["matches"] for r in result["registered_project_input_check"]["files"])

@pytest.mark.parametrize("mode",["added","removed","changed_run_pin"])
def test_unregistered_missing_or_untrusted_inputs_refused(tmp_path,mode):
 from experiments.prepare_wp6_corpus_scope import catalog
 project,manifest,row=fixture_manifest(tmp_path)
 if mode=="added":(project/"new_input.json").write_text("{}")
 elif mode=="removed":(project/"room_plan.json").unlink()
 else:
  from pathlib import Path
  Path(row["run_result_path"]).write_text("{}")
 assert catalog(manifest,1)["rows"][0]["wp6_intake_status"]=="artifact_or_preparation_refused"

def test_original_copytree_ignored_logs_do_not_become_inputs(tmp_path):
 from experiments.prepare_wp6_corpus_scope import catalog
 project,manifest,row=fixture_manifest(tmp_path)
 (project/"runtime_test.jsonl").write_text("ignored");(project/"foo.log").write_text("ignored");(project/"__pycache__").mkdir();(project/"__pycache__/x.pyc").write_bytes(b"ignored")
 assert catalog(manifest,1)["rows"][0]["wp6_intake_status"]=="native_artifacts_available"
