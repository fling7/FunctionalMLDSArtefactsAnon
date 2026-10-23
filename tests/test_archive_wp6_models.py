from pathlib import Path
import json,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments import archive_wp6_models as arch


def fixture(tmp_path,complete=True):
 run=tmp_path/'unit_run';project=run/'models'/'m_unit'/'room';project.mkdir(parents=True);(run/'outcomes').mkdir()
 (project/'empty_directory').mkdir()
 files={'model.json':b'{"a":1}\r\n','kb/note.txt':'Greek: alpha; unicode: \u03b1'.encode(),'binary.dat':bytes(range(256))*4}
 for name,value in files.items():p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
 (run/'summary.json').write_text(json.dumps({'evaluation_complete':complete,'worker_failures':0}));(run/'mutation_manifest.json').write_text(json.dumps({'models':[{'id':'unit','storage_id':'m_unit','status':'changed'}]}));(run/'outcomes'/'m_unit.json').write_text('{}')
 return run,project,files


def test_roundtrip_preserves_every_byte_and_discovery_index(tmp_path):
 run,project,files=fixture(tmp_path);result=arch.archive_run(run)
 assert result[0]['status']=='archived' and (project/'ARCHIVED_MODEL.json').exists()
 assert all(not (project/n).exists() for n in files)
 arch.restore(run,'m_unit')
 assert all((project/n).read_bytes()==v for n,v in files.items())
 assert (run/'archives'/'m_unit.zip').exists()
 assert (project/'empty_directory').is_dir()


def test_active_run_refused_without_removing_files(tmp_path):
 run,project,files=fixture(tmp_path,False)
 with pytest.raises(ValueError):arch.archive_run(run)
 assert all((project/n).read_bytes()==v for n,v in files.items())


def test_corrupt_archive_keeps_all_originals(tmp_path,monkeypatch):
 run,project,files=fixture(tmp_path)
 def reject(*args):raise ValueError('roundtrip failure')
 monkeypatch.setattr(arch,'verify_archive',reject)
 with pytest.raises(ValueError):arch.archive_run(run)
 assert all((project/n).read_bytes()==v for n,v in files.items())


def test_changed_original_before_delete_is_preserved(tmp_path,monkeypatch):
 run,project,files=fixture(tmp_path);original=arch.verify_archive
 def verify_and_change(*args):original(*args);(project/'model.json').write_bytes(b'changed')
 monkeypatch.setattr(arch,'verify_archive',verify_and_change)
 with pytest.raises(ValueError):arch.archive_run(run)
 assert (project/'model.json').read_bytes()==b'changed' and (project/'binary.dat').read_bytes()==files['binary.dat']


def test_escaped_storage_path_refused(tmp_path):
 run,project,files=fixture(tmp_path);p=run/'mutation_manifest.json';p.write_text(json.dumps({'models':[{'id':'unit','storage_id':'../../outside','status':'changed'}]}))
 with pytest.raises(ValueError):arch.archive_run(run)
 assert all((project/n).read_bytes()==v for n,v in files.items())
