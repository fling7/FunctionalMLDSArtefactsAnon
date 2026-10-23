"""Rebuild the two closed authored differential reports from explicit pinned inputs."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import re
import stat

ROOT = Path(__file__).resolve().parents[1]
CASES = ["example-initial", "schema-admission-v1"]
RAW = [f"results/raw/differential/{case}/probes.jsonl" for case in CASES]
SUMMARIES = [f"results/raw/differential/{case}/summary.json" for case in CASES]
SOURCES = ["repro/__init__.py", "repro/analyze_differential.py", "repro/report_differential.py"]
OUTPUTS = ["results/processed/differential_summary.json", "docs/DISAGREEMENTS.md",
           "paper_inputs/tables/T9_disagreements.csv", "paper_inputs/tables/T9_disagreements.tex"]
SHA = re.compile(r"^[0-9a-f]{64}$")


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or any(c in value for c in ":*?[]\0"):
        raise ValueError("noncanonical relative path")
    p = PurePosixPath(value)
    if p.is_absolute() or p.as_posix() != value or any(x in {".", ".."} for x in p.parts):
        raise ValueError("noncanonical relative path")
    return value


def safe(root, value):
    root = Path(root).resolve()
    p = root / relative(value)
    if not p.resolve().is_relative_to(root):
        raise ValueError("path escapes root")
    q = p
    while q != root:
        if q.exists():
            metadata = q.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 1024:
                raise ValueError("linked/reparse path")
        q = q.parent
    return p


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root, doc):
    if not isinstance(doc, dict) or set(doc) != {"schema", "inputs", "summaries", "outputs", "pins"}:
        raise ValueError("manifest keys")
    if doc["schema"] != "sealed-differential-report-manifest-v1":
        raise ValueError("manifest schema")
    if doc["inputs"] != RAW or doc["summaries"] != SUMMARIES or doc["outputs"] != OUTPUTS:
        raise ValueError("exact ordered input and output sets required")
    pins = doc["pins"]
    if not isinstance(pins, dict) or set(pins) != set(RAW + SUMMARIES + SOURCES):
        raise ValueError("exact pin set required")
    for path, value in pins.items():
        relative(path)
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise ValueError("invalid pin")
    # Finish schema validation before reading any declared file.
    for path, value in pins.items():
        p = safe(root, path)
        if not p.is_file() or digest(p) != value:
            raise ValueError("missing or changed pin: " + path)
    for raw_path, summary_path in zip(RAW, SUMMARIES):
        raw = safe(root, raw_path).read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise ValueError("closed nonempty JSONL required")
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        summary = json.loads(safe(root, summary_path).read_text(encoding="utf-8"))
        actual = {
            "unit": "room", "rooms": len({r["room"] for r in rows}), "probes": len(rows),
            "disagreement_probes": sum(not r["agrees"] for r in rows),
            "decision_disagreement_probes": sum(not r["agrees"] and not r["decision_agrees"] for r in rows),
            "reason_only_disagreement_probes": sum(not r["agrees"] and r["decision_agrees"] for r in rows),
        }
        if any(summary.get(k) != v for k, v in actual.items()):
            raise ValueError("closed summary does not describe probe rows")
    return doc


def execute(manifest, root=ROOT):
    root = Path(root).resolve()
    manifest = relative(manifest)
    if not manifest.startswith("data/replay/") or not manifest.endswith(".json"):
        raise ValueError("manifest must be a declared replay JSON")
    validate(root, json.loads(safe(root, manifest).read_text(encoding="utf-8")))
    from repro import analyze_differential
    if Path(analyze_differential.ROOT).resolve() != root:
        raise ValueError("reporter root differs from validated root")
    return analyze_differential.main()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    execute(parser.parse_args().manifest)


if __name__ == "__main__":
    main()
