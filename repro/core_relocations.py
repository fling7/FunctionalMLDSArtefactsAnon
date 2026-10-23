"""Exact, explicit raw-file relocation for the bounded writer handover."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from repro.scan_secrets import scan

SCHEMA = "handover-core-raw-relocations-v1"
LEGACY_PATCH = "patches/0004-routing-verifier.patch"
LEGACY_PATCH_SHA256 = "a380fd18fd2b13ee15565eef3b31d3b58289d3fa3e7ac4d848e42c1d5581da84"
LEGACY_COUNTERPART = "patches/complete-series-20261015a/0010-Verify-native-routing-at-publication-and-expose-inva.patch"
LEGACY_COUNTERPART_SHA256 = "7e2d7db5704256a77aecb7928762a0f2e0449838e90cff14efd423229e0c87a7"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def contained_file(root, relative, prefix):
    parts = PurePosixPath(relative).parts
    if (not parts or "\\" in relative or ":" in relative or ".." in parts
            or relative.startswith("/") or (not relative.startswith(prefix) and not
                (prefix == "results/processed/" and relative == LEGACY_PATCH))):
        raise ValueError("Unsafe relocation path")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Relocation escapes workspace")
    if not path.is_file():
        raise ValueError("Relocation file is missing")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError("Relocations cannot traverse links")
    if prefix == "results/processed/" and relative == LEGACY_PATCH:
        if sha(path.read_bytes()) != LEGACY_PATCH_SHA256:
            raise ValueError("Exact legacy patch bytes changed")
        counterpart = contained_file(root, LEGACY_COUNTERPART, "patches/complete-series-20261015a/")
        if sha(counterpart.read_bytes()) != LEGACY_COUNTERPART_SHA256:
            raise ValueError("Retained complete-series counterpart changed")
    return path


def verify(root, registry):
    """Refuse omissions unless both source and complete archive match their pins."""
    root = Path(root).resolve()
    if registry.get("schema") != SCHEMA or not registry.get("entries"):
        raise ValueError("Unknown or empty relocation registry")
    archive = contained_file(root, registry["archive"], "deliverables/")
    if archive.stat().st_size != registry["archive_bytes"] or sha(archive.read_bytes()) != registry["archive_sha256"]:
        raise ValueError("Relocation archive hash changed")
    rows = registry["entries"]
    paths = [r["path"] for r in rows]
    if LEGACY_PATCH in paths and paths != [LEGACY_PATCH]:
        raise ValueError("Legacy patch requires its own exact companion")
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate relocation source")
    manifest = "".join(r["sha256"] + "  " + r["path"] + "\n" for r in rows).encode("utf-8")
    with zipfile.ZipFile(archive) as z:
        expected = ["raw/" + p for p in paths] + ["raw/MANIFEST.sha256"]
        if sorted(z.namelist()) != sorted(expected):
            raise ValueError("Relocation archive entry set differs")
        if z.read("raw/MANIFEST.sha256") != manifest:
            raise ValueError("Relocation archive manifest changed")
        for row in rows:
            source = contained_file(root, row["path"], "results/processed/")
            data = source.read_bytes()
            if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                raise ValueError("Relocation source changed: " + row["path"])
            if z.read("raw/" + row["path"]) != data:
                raise ValueError("Relocated bytes differ: " + row["path"])
    return set(paths)


def create(root, paths, archive_relative, registry_path):
    root = Path(root).resolve()
    archive = root / archive_relative
    if (not archive_relative.startswith("deliverables/")
            or not archive.resolve().is_relative_to(root / "deliverables")
            or archive.exists() or Path(registry_path).exists()):
        raise ValueError("New contained archive and registry paths required")
    if len(set(paths)) != len(paths) or not paths:
        raise ValueError("Explicit unique source list required")
    if LEGACY_PATCH in paths and paths != [LEGACY_PATCH]:
        raise ValueError("Legacy patch requires its own exact companion")
    files = [contained_file(root, p, "results/processed/") for p in sorted(paths)]
    findings = scan(files)
    if findings:
        raise ValueError("Raw relocation scan refused source; no archive created")
    rows = [{"path":p.relative_to(root).as_posix(), "bytes":p.stat().st_size,
             "sha256":sha(p.read_bytes())} for p in files]
    temporary = archive.with_suffix(".tmp.zip")
    if temporary.exists():
        raise ValueError("Preserve existing temporary archive")
    archive.parent.mkdir(parents=True, exist_ok=True)
    def store(z, name, data):
        info = zipfile.ZipInfo("raw/" + name, (2026, 10, 15, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        z.writestr(info, data, compresslevel=9)
    with zipfile.ZipFile(temporary, "w") as z:
        for row, path in zip(rows, files):
            data = path.read_bytes()
            if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                raise ValueError("Source changed after scan/pin")
            store(z, row["path"], data)
        manifest = "".join(r["sha256"] + "  " + r["path"] + "\n" for r in rows)
        store(z, "MANIFEST.sha256", manifest.encode("utf-8"))
    if temporary.stat().st_size > 500_000_000:
        raise ValueError("Raw relocation archive exceeds 500 MB part limit")
    temporary.replace(archive)
    registry = {"schema":SCHEMA, "archive":archive_relative,
                "archive_sha256":sha(archive.read_bytes()), "archive_bytes":archive.stat().st_size,
                "reason":("Exact legacy routing-verifier transport preserved in a separate companion. Its complete-series counterpart remains in core; all original bytes and workspace files are retained." if paths == [LEGACY_PATCH] else "Closed raw mutation-input snapshots moved from core to raw to meet the decimal 25 MB limit. Original workspace files remain unchanged; all derived reports/tables stay in core."),
                "scan":{"clean":True,"hits":0,"files":len(rows)}, "entries":rows}
    verify(root, registry)
    Path(registry_path).write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", type=Path, required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args()
    registry = create(Path(__file__).resolve().parents[1], json.loads(args.paths.read_text(encoding="utf-8")), args.archive, args.registry)
    print(json.dumps({"archive":registry["archive"], "bytes":registry["archive_bytes"], "files":len(registry["entries"]), "verified":True}))


if __name__ == "__main__":
    main()
