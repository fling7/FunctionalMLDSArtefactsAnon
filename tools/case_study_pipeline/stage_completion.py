from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .common import (
    load_manifest,
    read_json,
    update_manifest,
    verify_manifest_stage_integrity,
    write_json,
)


SCHEMA = "roomcontract_stage_completion_report"
SCHEMA_VERSION = "1.0"

REQUIRED_STAGES = [
    "case_initialization",
    "rdl_ingestion",
    "scene_semantics",
    "agent_roles",
    "knowledge_synthesis",
    "agent_placement",
    "roomcontract_assembly",
    "handoff_derivation",
    "roomcontract_v2_assembly",
    "project_materialization",
    "runtime_setup",
    "schema_validation",
    "roomcontract_invariants",
    "traceability_metrics",
    "placement_metrics",
    "handoff_metrics",
    "evaluation_questions",
    "chat_tests",
    "handoff_tests",
    "answer_grounding",
]

REQUIRED_VALIDATION_REPORTS = [
    Path("validation/rdl_ingestion_validation.json"),
    Path("validation/scene_semantics_validation.json"),
    Path("validation/agent_roles_validation.json"),
    Path("validation/knowledge_synthesis_validation.json"),
    Path("validation/agent_placement_validation.json"),
    Path("validation/roomcontract_invariants_validation.json"),
    Path("validation/handoff_derivation_validation.json"),
    Path("roomcontract/roomcontract.v2.assembly_report.json"),
    Path("validation/project_materialization_validation.json"),
    Path("validation/runtime_setup_validation.json"),
    Path("validation/schema_validation.json"),
    Path("validation/traceability_metrics.json"),
    Path("validation/placement_metrics.json"),
    Path("validation/handoff_metrics.json"),
    Path("validation/evaluation_questions.json"),
    Path("validation/chat_test_results.json"),
    Path("validation/handoff_test_results.json"),
    Path("validation/answer_grounding_results.json"),
]

REQUIRED_ARTIFACTS = [
    Path("stage_manifest.json"),
    Path("roomcontract/roomcontract.instance.generated.json"),
    Path("roomcontract/roomcontract.v2.instance.json"),
]


def _report_is_valid(path: Path) -> bool:
    try:
        payload = read_json(path)
    except Exception:
        return False
    return payload.get("status") == "valid"


def _stage_statuses(manifest: Mapping[str, Any]) -> Dict[str, str]:
    statuses: Dict[str, str] = {}
    for entry in manifest.get("stages") or []:
        if not isinstance(entry, Mapping):
            continue
        stage_id = str(entry.get("stage_id") or "").strip()
        if stage_id:
            statuses[stage_id] = str(entry.get("status") or "").strip()
    return statuses


def compute_stage_completion(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    errors: List[str] = []
    warnings: List[str] = []

    manifest_path = case_dir / "stage_manifest.json"
    manifest = load_manifest(case_dir) if manifest_path.exists() else {"stages": []}
    statuses = _stage_statuses(manifest)
    stage_entries = {
        str(entry.get("stage_id") or ""): entry
        for entry in manifest.get("stages") or []
        if isinstance(entry, Mapping) and str(entry.get("stage_id") or "")
    }
    missing_stages = [stage for stage in REQUIRED_STAGES if stage not in statuses]
    non_success_stages = {stage: statuses.get(stage) for stage in REQUIRED_STAGES if statuses.get(stage) != "success"}

    for stage in missing_stages:
        errors.append(f"Missing required stage in manifest: {stage}.")
    for stage, status in non_success_stages.items():
        if stage not in missing_stages:
            errors.append(f"Stage {stage} is not successful: {status}.")

    integrity_results = []
    for stage_id in REQUIRED_STAGES:
        entry = stage_entries.get(stage_id)
        if not entry:
            continue
        integrity = verify_manifest_stage_integrity(entry)
        integrity_results.append(integrity)
        for drift in integrity["drift"]:
            errors.append(
                f"Stage {stage_id} has stale {drift['role']} fingerprint "
                f"({drift['reason']}): {drift['path']}."
            )

    artifact_results = []
    for relative in REQUIRED_ARTIFACTS:
        path = case_dir / relative
        exists = path.exists()
        if not exists:
            errors.append(f"Missing required artifact: {relative}.")
        artifact_results.append({"path": str(relative), "exists": exists})

    validation_results = []
    for relative in REQUIRED_VALIDATION_REPORTS:
        path = case_dir / relative
        exists = path.exists()
        valid = _report_is_valid(path) if exists else False
        if not exists:
            errors.append(f"Missing validation report: {relative}.")
        elif not valid:
            errors.append(f"Validation report is not valid: {relative}.")
        validation_results.append({"path": str(relative), "exists": exists, "valid": valid})

    metrics = {
        "required_stage_count": len(REQUIRED_STAGES),
        "present_stage_count": len([stage for stage in REQUIRED_STAGES if stage in statuses]),
        "successful_stage_count": len([stage for stage in REQUIRED_STAGES if statuses.get(stage) == "success"]),
        "required_artifact_count": len(REQUIRED_ARTIFACTS),
        "present_artifact_count": sum(1 for item in artifact_results if item["exists"]),
        "required_validation_report_count": len(REQUIRED_VALIDATION_REPORTS),
        "valid_validation_report_count": sum(1 for item in validation_results if item["valid"]),
        "completion_ratio": round(
            (
                len([stage for stage in REQUIRED_STAGES if statuses.get(stage) == "success"])
                + sum(1 for item in artifact_results if item["exists"])
                + sum(1 for item in validation_results if item["valid"])
            )
            / (len(REQUIRED_STAGES) + len(REQUIRED_ARTIFACTS) + len(REQUIRED_VALIDATION_REPORTS)),
            6,
        ),
        "integrity_checked_stage_count": len(integrity_results),
        "integrity_checked_path_count": sum(
            item["checked_path_count"] for item in integrity_results
        ),
        "integrity_drift_count": sum(
            item["drift_count"] for item in integrity_results
        ),
    }
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "case_id": case_dir.name,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "required_stages": REQUIRED_STAGES,
        "stage_statuses": statuses,
        "missing_stages": missing_stages,
        "non_success_stages": non_success_stages,
        "stage_integrity": integrity_results,
        "required_artifacts": artifact_results,
        "validation_reports": validation_results,
    }


def run_stage_completion_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    output_path = case_dir / "validation" / "stage_completion_report.json"
    payload = compute_stage_completion(case_dir)
    write_json(output_path, payload)
    update_manifest(
        case_dir,
        stage_id="stage_completion",
        status="success" if payload["status"] == "valid" else "failed",
        input_paths=[
            case_dir / "stage_manifest.json",
            case_dir / "roomcontract" / "roomcontract.instance.generated.json",
            case_dir / "roomcontract" / "roomcontract.v2.instance.json",
            *[case_dir / relative for relative in REQUIRED_VALIDATION_REPORTS],
        ],
        output_paths=[output_path],
        errors=payload["errors"],
        warnings=payload["warnings"],
        metadata=payload["metrics"],
    )
    return {
        "case_id": case_dir.name,
        "status": "success" if payload["status"] == "valid" else "failed",
        "validation": {
            "status": payload["status"],
            "errors": payload["errors"],
            "warnings": payload["warnings"],
            "metrics": payload["metrics"],
        },
        "validation_path": str(output_path),
    }


def run_stage_completion_for_cases(case_dirs: Iterable[Path]) -> List[Dict[str, Any]]:
    return [run_stage_completion_for_case(case_dir) for case_dir in case_dirs]


def write_aggregate_stage_completion(out_root: Path, results: List[Dict[str, Any]]) -> Path:
    out_root = Path(out_root).resolve()
    output_path = out_root / "stage_completion_report.json"
    payload = {
        "schema": f"{SCHEMA}_aggregate",
        "schema_version": SCHEMA_VERSION,
        "case_count": len(results),
        "success_count": sum(1 for result in results if result["status"] == "success"),
        "failure_count": sum(1 for result in results if result["status"] != "success"),
        "results": results,
    }
    write_json(output_path, payload)
    return output_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate that every case-study stage and artifact is complete.")
    parser.add_argument("--case-dir", type=Path, action="append")
    parser.add_argument("--case-root", type=Path)
    parser.add_argument("--write-aggregate", action="store_true")
    args = parser.parse_args(argv)
    case_dirs = args.case_dir or []
    if args.case_root:
        case_dirs.extend(sorted(path for path in args.case_root.iterdir() if path.is_dir()))
    if not case_dirs:
        parser.error("Pass --case-dir or --case-root.")
    results = run_stage_completion_for_cases(case_dirs)
    aggregate_path = write_aggregate_stage_completion(args.case_root, results) if args.write_aggregate and args.case_root else None
    print(json.dumps({"results": results, "aggregate_path": str(aggregate_path) if aggregate_path else None}, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
