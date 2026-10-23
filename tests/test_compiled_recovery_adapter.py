"""Adapter gates only; no worker pool is launched by these tests."""
import hashlib,json,pickle,sys
import pytest
from experiments import recover_mutation_compiled_accelerated as adapter
from experiments import detection_matrix_accelerated,recover_mutation_run
from experiments.detection_matrix_compiled_accelerated import compiled_accelerated_worker

@pytest.fixture
def gate(tmp_path,monkeypatch):
 monkeypatch.setattr(adapter,"ROOT",tmp_path);monkeypatch.setattr(sys,"argv",["adapter","--accelerated","--run-dir",str(tmp_path/"run")])
 lock=tmp_path/"prereg/wp6_amendments/009_compiled_integration.sha256.json";lock.parent.mkdir(parents=True)
 return tmp_path,lock
@pytest.mark.parametrize("mode",["absent","draft","mismatch"])
def test_unfrozen_or_mismatched_refuses(gate,monkeypatch,mode):
 root,lock=gate;called=[];monkeypatch.setattr(recover_mutation_run,"main",lambda:called.append(1))
 if mode!="absent":
  (root/"source.py").write_text("x");lock.write_text(json.dumps({"status":"draft" if mode=="draft" else "frozen","code_hashes":{"source.py":"0"*64}}))
 with pytest.raises(SystemExit):adapter.main()
 assert called==[] and not (root/"run_compiled_protocol.json").exists()
@pytest.mark.parametrize("fails",[False,True])
def test_scoped_original_recovery_dispatch(gate,monkeypatch,fails):
 root,lock=gate;(root/"source.py").write_text("x");lock.write_text(json.dumps({"status":"frozen","code_hashes":{"source.py":hashlib.sha256(b"x").hexdigest()}}))
 original=detection_matrix_accelerated.accelerated_worker;argv=list(sys.argv);called=[]
 def run():
  called.append(1);assert detection_matrix_accelerated.accelerated_worker is compiled_accelerated_worker and sys.argv==argv
  if fails:raise RuntimeError("original failure")
  return 8
 monkeypatch.setattr(recover_mutation_run,"main",run)
 if fails:
  with pytest.raises(RuntimeError,match="original failure"):adapter.main()
 else:assert adapter.main()==8
 assert detection_matrix_accelerated.accelerated_worker is original
 assert json.loads((root/"run_compiled_protocol.json").read_text())["amendment"]==json.loads(lock.read_text())
 with pytest.raises(FileExistsError):adapter.main()
 assert called==[1]
def test_worker_spawn_pickling():assert pickle.loads(pickle.dumps(compiled_accelerated_worker)) is compiled_accelerated_worker
