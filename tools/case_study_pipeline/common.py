from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash a directory deterministically from relative paths and file hashes."""

    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def slugify(value: str, fallback: str = "case") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def relative_to_or_absolute(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def ensure_dirs(case_dir: Path) -> None:
    for name in (
        "input",
        "intermediate",
        "roomcontract",
        "interactive_agents_project",
        "runtime_logs",
        "validation",
        "paper_artifacts",
    ):
        (case_dir / name).mkdir(parents=True, exist_ok=True)


def load_manifest(case_dir: Path) -> Dict[str, Any]:
    path = case_dir / "stage_manifest.json"
    if not path.exists():
        return {"case_id": case_dir.name, "created_at": utc_now_iso(), "stages": []}
    return read_json(path)


def _normalized_path_key(value: Any) -> str:
    return str(Path(str(value or "")).resolve())


def manifest_stage_inputs_match(
    case_dir: Path,
    stage_id: str,
    input_paths: Iterable[Path],
    *,
    exact: bool = True,
) -> bool:
    """Return whether a successful stage has the current declared inputs.

    Matching the exact dependency set prevents a stale stage from being reused
    merely because a caller checked a subset of its prompts, model, project or
    implementation files.
    """

    manifest = load_manifest(case_dir)
    stage = next(
        (
            entry
            for entry in manifest.get("stages") or []
            if isinstance(entry, Mapping) and entry.get("stage_id") == stage_id
        ),
        None,
    )
    if not stage or stage.get("status") != "success":
        return False

    recorded = {
        _normalized_path_key(item.get("path")): item.get("sha256")
        for item in stage.get("inputs") or []
        if isinstance(item, Mapping) and item.get("path")
    }
    expected_paths = [Path(path) for path in input_paths]
    expected_keys = {_normalized_path_key(path) for path in expected_paths}
    if exact and set(recorded) != expected_keys:
        return False
    if not expected_keys.issubset(recorded):
        return False
    for path in expected_paths:
        if not path.exists() or not path.is_file():
            return False
        if recorded.get(_normalized_path_key(path)) != sha256_file(path):
            return False
    return True


def manifest_stage_metadata_matches(
    case_dir: Path,
    stage_id: str,
    expected: Mapping[str, Any],
) -> bool:
    """Compare selected nested metadata keys using dotted paths."""

    manifest = load_manifest(case_dir)
    stage = next(
        (
            entry
            for entry in manifest.get("stages") or []
            if isinstance(entry, Mapping) and entry.get("stage_id") == stage_id
        ),
        None,
    )
    if not stage:
        return False
    metadata: Any = stage.get("metadata") or {}
    for dotted_key, expected_value in expected.items():
        current: Any = metadata
        for part in dotted_key.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return False
            current = current[part]
        if current != expected_value:
            return False
    return True


def verify_manifest_stage_integrity(stage: Mapping[str, Any]) -> Dict[str, Any]:
    """Verify all recorded file/tree fingerprints for one manifest stage."""

    drift: List[Dict[str, Any]] = []
    checked = 0
    for role in ("inputs", "outputs"):
        for item in stage.get(role) or []:
            if not isinstance(item, Mapping) or not item.get("path"):
                continue
            path = Path(str(item["path"]))
            checked += 1
            if not path.exists():
                drift.append(
                    {"role": role, "path": str(path), "reason": "missing"}
                )
                continue
            if item.get("sha256") is not None:
                if not path.is_file():
                    drift.append(
                        {
                            "role": role,
                            "path": str(path),
                            "reason": "expected_file",
                        }
                    )
                else:
                    actual = sha256_file(path)
                    if actual != item.get("sha256"):
                        drift.append(
                            {
                                "role": role,
                                "path": str(path),
                                "reason": "sha256_mismatch",
                                "recorded": item.get("sha256"),
                                "actual": actual,
                            }
                        )
            elif item.get("tree_sha256") is not None:
                if not path.is_dir():
                    drift.append(
                        {
                            "role": role,
                            "path": str(path),
                            "reason": "expected_directory",
                        }
                    )
                else:
                    actual = sha256_tree(path)
                    if actual != item.get("tree_sha256"):
                        drift.append(
                            {
                                "role": role,
                                "path": str(path),
                                "reason": "tree_sha256_mismatch",
                                "recorded": item.get("tree_sha256"),
                                "actual": actual,
                            }
                        )
            else:
                drift.append(
                    {
                        "role": role,
                        "path": str(path),
                        "reason": "unfingerprinted",
                    }
                )
    return {
        "stage_id": stage.get("stage_id"),
        "checked_path_count": checked,
        "drift_count": len(drift),
        "valid": not drift,
        "drift": drift,
    }


def update_manifest(
    case_dir: Path,
    *,
    stage_id: str,
    status: str,
    input_paths: Iterable[Path],
    output_paths: Iterable[Path],
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    manifest = load_manifest(case_dir)
    manifest["case_id"] = case_dir.name
    manifest["updated_at"] = utc_now_iso()

    inputs = []
    for path in input_paths:
        path = Path(path)
        entry = {"path": str(path)}
        if path.exists() and path.is_file():
            entry["sha256"] = sha256_file(path)
        inputs.append(entry)

    outputs = []
    for path in output_paths:
        path = Path(path)
        entry = {"path": str(path)}
        if path.exists() and path.is_file():
            entry["sha256"] = sha256_file(path)
        elif path.exists() and path.is_dir():
            entry["tree_sha256"] = sha256_tree(path)
        outputs.append(entry)

    stage_entry = {
        "stage_id": stage_id,
        "status": status,
        "updated_at": utc_now_iso(),
        "inputs": inputs,
        "outputs": outputs,
        "errors": errors or [],
        "warnings": warnings or [],
        "metadata": metadata or {},
    }

    stages = [s for s in manifest.get("stages", []) if s.get("stage_id") != stage_id]
    stages.append(stage_entry)
    manifest["stages"] = stages
    write_json(case_dir / "stage_manifest.json", manifest)
