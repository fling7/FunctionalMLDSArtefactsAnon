"""Offline gates and adapter dispatch; never starts a corpus pool."""
import hashlib,json,pickle,sys
from pathlib import Path
import pytest
from experiments import recover_mutation_contract_accelerated as adapter
from experiments import detection_matrix_accelerated,recover_mutation_run
from experiments.detection_matrix_contract_accelerated import contract_accelerated_worker

@pytest.fixture
def gate(tmp_path,monkeypatch):
 monkeypatch.setattr(adapter,"ROOT",tmp_path)
 monkeypatch.setattr(sys,"argv",["adapter","--accelerated","--run-dir",str(tmp_path/"run")])
 p=tmp_path/"prereg/wp6_amendments/007_contract_memoization.sha256.json";p.parent.mkdir(parents=True)
 return tmp_path,p

@pytest.mark.parametrize("mode",["absent","draft","mismatch"])
def test_unapproved_or_changed_source_never_dispatches(gate,monkeypatch,mode):
 root,lock=gate;called=[]
 monkeypatch.setattr(recover_mutation_run,"main",lambda:called.append(True))
 if mode!="absent":
  (root/"source.py").write_text("x",encoding="utf8")
  lock.write_text(json.dumps({"status":"draft" if mode=="draft" else "frozen","code_hashes":{"source.py":"0"*64}}),encoding="utf8")
 with pytest.raises(SystemExit):adapter.main()
 assert called==[] and not (root/"run_contract_memo_protocol.json").exists()

def test_explicit_accelerated_profile_required(gate,monkeypatch):
 monkeypatch.setattr(sys,"argv",["adapter"])
 with pytest.raises(SystemExit,match="requires --accelerated"):adapter.main()

@pytest.mark.parametrize("fails",[False,True])
def test_scoped_dispatch_preserves_arguments_and_restores(gate,monkeypatch,fails):
 root,lock=gate;source=root/"source.py";source.write_text("x",encoding="utf8")
 lock.write_text(json.dumps({"status":"frozen","code_hashes":{"source.py":hashlib.sha256(source.read_bytes()).hexdigest()}}),encoding="utf8")
 original=detection_matrix_accelerated.accelerated_worker;argv=list(sys.argv);called=[]
 def runner():
  assert detection_matrix_accelerated.accelerated_worker is contract_accelerated_worker
  assert sys.argv==argv;called.append(True)
  if fails:raise RuntimeError("original runner failure")
  return 17
 monkeypatch.setattr(recover_mutation_run,"main",runner)
 if fails:
  with pytest.raises(RuntimeError,match="original runner failure"):adapter.main()
 else:assert adapter.main()==17
 assert called==[True] and detection_matrix_accelerated.accelerated_worker is original
 sidecar=json.loads((root/"run_contract_memo_protocol.json").read_text())
 assert sidecar["amendment"]==json.loads(lock.read_text())
 assert sidecar["worker"].endswith("contract_accelerated_worker")
 with pytest.raises(FileExistsError):adapter.main()
 assert called==[True]

def test_worker_is_spawn_picklable():
 assert pickle.loads(pickle.dumps(contract_accelerated_worker)) is contract_accelerated_worker

@pytest.mark.parametrize("mode",["exact","new_changed","old_changed","wrong_path"])
def test_report_overlay_is_exact_and_restored(tmp_path,monkeypatch,mode):
 monkeypatch.setattr(adapter,"ROOT",tmp_path)
 name="experiments/analyze_wp7.py";p=tmp_path/name;p.parent.mkdir();p.write_text("new",encoding="utf8")
 old=hashlib.sha256(b"old").hexdigest();new=hashlib.sha256(b"new").hexdigest()
 inventory=tmp_path/"inventory.json";inventory.write_text(json.dumps({"sha256":{name:old if mode!="old_changed" else "1"*64}}),encoding="utf8")
 overlay={"path":name if mode!="wrong_path" else "experiments/detection_matrix.py","original_sha256":old,"current_sha256":new if mode!="new_changed" else "0"*64}
 original=recover_mutation_run.check_dependencies;exclusions=recover_mutation_run.NON_EVALUATION_FILES
 monkeypatch.setattr(recover_mutation_run,"ROOT",tmp_path)
 if mode=="exact":
  with adapter.report_only_overlay(recover_mutation_run,{"report_only_overlay":overlay}):
   rows=recover_mutation_run.check_dependencies([inventory]);assert rows[0]["changed"] and rows[0]["excluded_non_evaluation_file"]
 else:
  with pytest.raises(ValueError):
   with adapter.report_only_overlay(recover_mutation_run,{"report_only_overlay":overlay}):recover_mutation_run.check_dependencies([inventory])
 assert recover_mutation_run.check_dependencies is original and recover_mutation_run.NON_EVALUATION_FILES is exclusions
