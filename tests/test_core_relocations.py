import copy
import json
from pathlib import Path
import zipfile

import pytest

from repro.core_relocations import create, verify, sha


def retained(tmp_path):
    rel = "results/processed/closed_snapshot/outcome.json"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"retained":true}\r\n')
    registry = create(tmp_path, [rel], "deliverables/raw.zip", tmp_path / "registry.json")
    return rel, path, registry


def test_exact_crlf_archive_and_sources_preserved(tmp_path):
    rel, path, registry = retained(tmp_path)
    assert verify(tmp_path, registry) == {rel}
    with zipfile.ZipFile(tmp_path / registry["archive"]) as z:
        assert z.read("raw/" + rel) == path.read_bytes() == b'{"retained":true}\r\n'
    assert json.loads((tmp_path / "registry.json").read_text()) == registry


@pytest.mark.parametrize("change", ["source", "missing_archive", "archive", "duplicate", "extra_member", "escape"])
def test_refuses_unsafe_or_unverifiable_relocation(tmp_path, change):
    rel, path, registry = retained(tmp_path)
    registry = copy.deepcopy(registry)
    archive = tmp_path / registry["archive"]
    if change == "source":
        path.write_bytes(b"changed")
    elif change == "missing_archive":
        archive.unlink()
    elif change == "archive":
        archive.write_bytes(b"changed")
    elif change == "duplicate":
        registry["entries"].append(registry["entries"][0])
    elif change == "extra_member":
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr("raw/unregistered", b"extra")
        registry["archive_sha256"] = sha(archive.read_bytes())
        registry["archive_bytes"] = archive.stat().st_size
    else:
        registry["entries"][0]["path"] = "results/processed/../../outside"
    with pytest.raises(ValueError):
        verify(tmp_path, registry)


def test_existing_archive_is_never_replaced(tmp_path):
    rel, _, registry = retained(tmp_path)
    archive = tmp_path / registry["archive"]
    before = archive.read_bytes()
    with pytest.raises(ValueError):
        create(tmp_path, [rel], registry["archive"], tmp_path / "another.json")
    assert archive.read_bytes() == before
