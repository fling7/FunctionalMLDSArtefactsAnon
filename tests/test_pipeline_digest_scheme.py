"""Regression for canonical publication digests; no model generation."""
import hashlib
import pytest
from tools.case_study_pipeline.validators.schema_validator import _sha256_file

def test_lf_scheme_is_invariant_to_crlf_but_legacy_remains_byte_based(tmp_path):
    lf=tmp_path/"lf.json"; crlf=tmp_path/"crlf.json"
    lf.write_bytes(b'{\n  "a": 1\n}\n'); crlf.write_bytes(lf.read_bytes().replace(b"\n",b"\r\n"))
    expected=hashlib.sha256(lf.read_bytes()).hexdigest().upper()
    assert _sha256_file(lf,"sha256-lf-v1")==expected
    assert _sha256_file(crlf,"sha256-lf-v1")==expected
    assert _sha256_file(crlf)==hashlib.sha256(crlf.read_bytes()).hexdigest().upper()
    assert _sha256_file(lf)!=_sha256_file(crlf)

def test_unknown_scheme_is_rejected(tmp_path):
    path=tmp_path/"model.json";path.write_bytes(b"{}")
    with pytest.raises(ValueError,match="Unsupported"):
        _sha256_file(path,"silently-invented-scheme")

