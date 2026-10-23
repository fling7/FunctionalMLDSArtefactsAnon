import json,shutil
import pytest
from experiments.lib.backend_driver import Driver
from backend.roomcontract_v2_runtime import _sha256,load_project_contract,RoomContractContractError

def test_crlf_lf_same_but_semantic_and_whitespace_edits_differ(tmp_path):
    p=tmp_path/'model.json'; p.write_bytes(b'{\r\n"a":1\r\n}\r\n'); first=_sha256(p)
    p.write_bytes(b'{\n"a":1\n}\n'); assert _sha256(p)==first
    p.write_bytes(b'{\n"a":2\n}\n'); assert _sha256(p)!=first
    p.write_bytes(b'{\n"a": 1\n}\n'); assert _sha256(p)!=first

def test_example_loads_under_both_line_endings():
    d=Driver()
    try:
        p=d.project/'roomcontract.v2.instance.json'; lf=p.read_bytes().replace(b'\r\n',b'\n')
        p.write_bytes(lf); first=load_project_contract(d.project)
        p.write_bytes(lf.replace(b'\n',b'\r\n')); second=load_project_contract(d.project)
        assert first['model_sha256']==second['model_sha256']
        assert first['runtime_context']==second['runtime_context']
    finally:d.close()

def test_unknown_or_mismatched_scheme_refused():
    d=Driver()
    try:
        p=d.project/'project.json'; data=json.loads(p.read_bytes());data['roomcontract_digest_scheme']='unknown-v1';p.write_text(json.dumps(data))
        with pytest.raises(RoomContractContractError):load_project_contract(d.project)
    finally:d.close()

def test_legacy_raw_digest_is_still_supported():
    d=Driver()
    try:
        import hashlib
        digest=hashlib.sha256((d.project/'roomcontract.v2.instance.json').read_bytes()).hexdigest().upper()
        for name,field,schemefield in [('project.json','roomcontract_model_sha256','roomcontract_digest_scheme'),('trace_map.v2.json','model_sha256','digest_scheme')]:
            p=d.project/name;data=json.loads(p.read_bytes());data.pop(schemefield,None);data[field]=digest;p.write_text(json.dumps(data))
        assert load_project_contract(d.project)['model_sha256']==digest
    finally:d.close()
