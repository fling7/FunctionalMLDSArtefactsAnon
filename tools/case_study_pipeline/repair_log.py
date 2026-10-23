from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .common import read_json, write_json


SCHEMA = "roomcontract_repair_log"
SCHEMA_VERSION = "1.0"


def _read_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _stage_issue(stage: Mapping[str, Any]) -> str:
    errors = stage.get("errors") or []
    warnings = stage.get("warnings") or []
    if errors:
        return "; ".join(str(item) for item in errors)
    if warnings:
        return "; ".join(str(item) for item in warnings)
    return "No final validation error recorded."


def _entry(
    *,
    case_id: str,
    stage: Mapping[str, Any],
    issue: str,
    repair_type: str,
    attempt: int,
    result: str,
    source: str,
    llm_used: bool,
) -> Dict[str, Any]:
    metadata = stage.get("metadata") or {}
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "stage": stage.get("stage_id"),
        "fehler": issue,
        "repair_type": repair_type,
        "versuch": attempt,
        "ergebnis": result,
        "llm_used": bool(llm_used),
        "final_stage_status": stage.get("status"),
        "prompt_version": metadata.get("prompt_version"),
        "repair_prompt_version": metadata.get("repair_prompt_version"),
        "source": source,
    }


def repair_entries_for_case(case_dir: Path) -> List[Dict[str, Any]]:
    case_dir = Path(case_dir).resolve()
    manifest = _read_if_exists(case_dir / "stage_manifest.json")
    case_id = str(manifest.get("case_id") or case_dir.name)
    entries: List[Dict[str, Any]] = []

    for stage in manifest.get("stages") or []:
        if not isinstance(stage, Mapping):
            continue
        metadata = stage.get("metadata") or {}
        stage_id = str(stage.get("stage_id") or "")
        final_status = str(stage.get("status") or "")
        attempts_used = _as_int(metadata.get("attempts_used"))

        if metadata.get("recovered_without_llm") or metadata.get("recovered_without_rerun"):
            entries.append(
                _entry(
                    case_id=case_id,
                    stage=stage,
                    issue="Existing valid artefact was recovered and manifest was reconstructed.",
                    repair_type="deterministic_recovery",
                    attempt=1,
                    result="success" if final_status == "success" else final_status,
                    source="stage_manifest.metadata.recovered_without_*",
                    llm_used=False,
                )
            )

        if attempts_used > 0:
            for attempt in range(1, attempts_used + 1):
                is_repair = attempt > 1
                entries.append(
                    _entry(
                        case_id=case_id,
                        stage=stage,
                        issue=(
                            "Previous generated artefact failed validation; final manifest does not retain per-attempt errors."
                            if is_repair
                            else "Initial LLM generation attempt; no repair was required when attempts_used equals 1."
                        ),
                        repair_type="llm_repair_attempt" if is_repair else "llm_generation_attempt",
                        attempt=attempt,
                        result="success" if final_status == "success" and attempt == attempts_used else "continued",
                        source="stage_manifest.metadata.attempts_used",
                        llm_used=True,
                    )
                )

        if stage.get("errors"):
            entries.append(
                _entry(
                    case_id=case_id,
                    stage=stage,
                    issue=_stage_issue(stage),
                    repair_type="unresolved_error",
                    attempt=max(1, attempts_used),
                    result=final_status or "failed",
                    source="stage_manifest.errors",
                    llm_used=bool(metadata.get("llm_used") or attempts_used > 0),
                )
            )

        if stage.get("warnings"):
            entries.append(
                _entry(
                    case_id=case_id,
                    stage=stage,
                    issue=_stage_issue(stage),
                    repair_type="accepted_warning",
                    attempt=max(1, attempts_used),
                    result="accepted_with_warning" if final_status == "success" else final_status,
                    source="stage_manifest.warnings",
                    llm_used=bool(metadata.get("llm_used") or attempts_used > 0),
                )
            )

        if not attempts_used and not stage.get("errors") and not stage.get("warnings") and stage_id:
            continue

    return entries


def write_jsonl(path: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def write_repair_log_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    entries = repair_entries_for_case(case_dir)
    output_path = case_dir / "validation" / "repair_log.jsonl"
    write_jsonl(output_path, entries)
    repair_attempt_count = sum(1 for entry in entries if entry.get("repair_type") == "llm_repair_attempt")
    generation_attempt_count = sum(1 for entry in entries if entry.get("repair_type") == "llm_generation_attempt")
    deterministic_recovery_count = sum(1 for entry in entries if entry.get("repair_type") == "deterministic_recovery")
    warning_count = sum(1 for entry in entries if entry.get("repair_type") == "accepted_warning")
    return {
        "case_id": case_dir.name,
        "status": "success",
        "path": str(output_path),
        "metrics": {
            "entry_count": len(entries),
            "llm_generation_attempt_count": generation_attempt_count,
            "llm_repair_attempt_count": repair_attempt_count,
            "deterministic_recovery_count": deterministic_recovery_count,
            "accepted_warning_count": warning_count,
        },
    }


def run_repair_log(case_root: Path) -> Dict[str, Any]:
    case_root = Path(case_root).resolve()
    case_dirs = sorted(
        path
        for path in case_root.iterdir()
        if path.is_dir() and path.name != "paper_artifacts" and (path / "stage_manifest.json").exists()
    )
    results = [write_repair_log_for_case(case_dir) for case_dir in case_dirs]
    aggregate_entries: List[Dict[str, Any]] = []
    for case_dir in case_dirs:
        aggregate_entries.extend(repair_entries_for_case(case_dir))
    aggregate_jsonl = case_root / "repair_log.jsonl"
    write_jsonl(aggregate_jsonl, aggregate_entries)
    summary = {
        "schema": f"{SCHEMA}_aggregate",
        "schema_version": SCHEMA_VERSION,
        "status": "valid",
        "errors": [],
        "warnings": [],
        "metrics": {
            "case_count": len(case_dirs),
            "entry_count": len(aggregate_entries),
            "llm_generation_attempt_count": sum(
                1 for entry in aggregate_entries if entry.get("repair_type") == "llm_generation_attempt"
            ),
            "llm_repair_attempt_count": sum(
                1 for entry in aggregate_entries if entry.get("repair_type") == "llm_repair_attempt"
            ),
            "deterministic_recovery_count": sum(
                1 for entry in aggregate_entries if entry.get("repair_type") == "deterministic_recovery"
            ),
            "accepted_warning_count": sum(
                1 for entry in aggregate_entries if entry.get("repair_type") == "accepted_warning"
            ),
        },
        "case_results": results,
        "aggregate_jsonl_path": str(aggregate_jsonl),
    }
    summary_path = case_root / "repair_log_summary.json"
    write_json(summary_path, summary)
    aggregate_path = case_root / "aggregate_report.json"
    if aggregate_path.exists():
        aggregate = _read_if_exists(aggregate_path)
        aggregate["repair_log"] = summary
        write_json(aggregate_path, aggregate)
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write per-case and aggregate repair logs from stage manifests.")
    parser.add_argument("--case-root", type=Path, default=Path("output/case_studies"))
    args = parser.parse_args(argv)
    summary = run_repair_log(args.case_root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
