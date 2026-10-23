from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from jsonschema import Draft202012Validator

from ..common import read_json, update_manifest, write_json
from ..project_materializer import DEFAULT_BACKEND_ROOT


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


@dataclass(frozen=True)
class ArtifactTarget:
    artifact_id: str
    schema_name: str
    path: Path
    canonical_v2: bool = False


@dataclass(frozen=True)
class ContractDiscovery:
    mode: str
    instance_targets: tuple[ArtifactTarget, ...]
    related_paths: tuple[Path, ...]
    errors: tuple[str, ...]


V05_TRACE_SCHEMA = "roomcontract_trace_map"
V2_TRACE_SCHEMA = "roomcontract_trace_map_v2"
V2_MODEL_VERSION = "2.0.0-model"
V2_TRACE_VERSION = "2.0"
V2_INSTANCE_SCHEMA = "dynamic_functional_rdl_v2_instance"
V2_PROFILE = "executable"
V2_INSTANCE_SCHEMA_NAME = "dynamic_functional_rdl_v2_instance.schema.json"
V2_PROJECT_INSTANCE_FILENAME = "roomcontract.v2.instance.json"
V05_PROJECT_INSTANCE_FILENAME = "roomcontract.v05.instance.json"
V2_GENERATED_INSTANCE_FILENAME = "roomcontract.v2.instance.json"
V2_ASSEMBLY_REPORT_FILENAME = "roomcontract.v2.assembly_report.json"
V05_GENERATED_INSTANCE_FILENAME = "roomcontract.instance.generated.json"
V2_VERSIONED_TRACE_FILENAME = "trace_map.v2.json"
V05_VERSIONED_TRACE_FILENAME = "trace_map.v05.json"


def _schema_path(schema_name: str) -> Path:
    return SCHEMA_DIR / schema_name


def _json_path(path: Path) -> Path:
    return Path(path).resolve()


def _format_json_path(error_path: Iterable[Any]) -> str:
    parts = [str(part) for part in error_path]
    return "$" if not parts else "$." + ".".join(parts)


def _load_schema(schema_name: str) -> Dict[str, Any]:
    return read_json(_schema_path(schema_name))


def _validate_payload(*, artifact_id: str, schema_name: str, payload: Any) -> List[str]:
    schema = _load_schema(schema_name)
    validator = Draft202012Validator(schema)
    return [
        f"{artifact_id} {_format_json_path(error.absolute_path)}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    ]


def _sha256_file(path: Path, scheme: str = "sha256-raw-v1") -> str:
    if scheme == "sha256-lf-v1":
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()
    if scheme != "sha256-raw-v1":
        raise ValueError("Unsupported serialization digest scheme.")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _validate_v2_payload(*, artifact_id: str, payload: Any) -> List[str]:
    """Apply both the native serialization schema and canonical V2 semantics."""

    errors: List[str] = []
    try:
        errors.extend(
            _validate_payload(
                artifact_id=artifact_id,
                schema_name=V2_INSTANCE_SCHEMA_NAME,
                payload=payload,
            )
        )
    except Exception as exc:
        errors.append(f"{artifact_id} JSON Schema: {exc}")

    try:
        from ..roomcontract_v2_assembler import validate_roomcontract_v2_instance

        report = validate_roomcontract_v2_instance(payload)
        if not report.get("ok"):
            issues = report.get("issues") or []
            if not issues:
                errors.append(f"{artifact_id} canonical V2 validation failed without issue details")
            for issue in issues:
                if not isinstance(issue, Mapping) or issue.get("severity", "error") != "error":
                    continue
                code = str(issue.get("code") or "V2")
                location = str(issue.get("location") or "instance")
                message = str(issue.get("message") or "canonical V2 validation failed")
                errors.append(f"{artifact_id} canonical {code} {location}: {message}")
    except Exception as exc:
        errors.append(f"{artifact_id} canonical V2 validator: {exc}")
    return errors


def _validate_trace_variant(*, artifact_id: str, definition_name: str, payload: Any) -> List[str]:
    try:
        schema = _load_schema("interactive_agents_project.schema.json")
        definition = (schema.get("$defs") or {}).get(definition_name)
        if not isinstance(definition, Mapping):
            raise KeyError(f"missing $defs.{definition_name}")
        validator = Draft202012Validator(dict(definition))
        return [
            f"{artifact_id} {_format_json_path(error.absolute_path)}: {error.message}"
            for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
        ]
    except Exception as exc:
        return [f"{artifact_id}: {exc}"]


def _discover_contract(*, case_dir: Path, backend_root: Path) -> ContractDiscovery:
    case_dir = case_dir.resolve()
    project_dir = backend_root.resolve() / "projects" / case_dir.name
    active_trace_path = project_dir / "trace_map.json"
    project_json_path = project_dir / "project.json"
    errors: List[str] = []
    trace: Mapping[str, Any] = {}
    project: Mapping[str, Any] = {}
    try:
        if active_trace_path.exists():
            trace = read_json(active_trace_path)
    except Exception as exc:
        errors.append(f"active trace_map.json cannot be read: {exc}")
    try:
        if project_json_path.exists():
            project = read_json(project_json_path)
    except Exception as exc:
        errors.append(f"project.json cannot be read for contract discovery: {exc}")

    trace_schema = str(trace.get("schema") or "")
    project_version = str(project.get("roomcontract_model_version") or "")
    project_v2_path = project_dir / V2_PROJECT_INSTANCE_FILENAME
    is_v2 = trace_schema == V2_TRACE_SCHEMA or project_version == V2_MODEL_VERSION or project_v2_path.exists()

    if is_v2:
        if trace_schema != V2_TRACE_SCHEMA:
            errors.append(
                f"dual V2 project requires active trace_map.json schema {V2_TRACE_SCHEMA!r}, found {trace_schema!r}"
            )
        v2_source = case_dir / "roomcontract" / V2_GENERATED_INSTANCE_FILENAME
        v2_assembly_report = case_dir / "roomcontract" / V2_ASSEMBLY_REPORT_FILENAME
        v05_source = case_dir / "roomcontract" / V05_GENERATED_INSTANCE_FILENAME
        related_paths = (
            project_v2_path,
            project_dir / V05_PROJECT_INSTANCE_FILENAME,
            project_dir / V2_VERSIONED_TRACE_FILENAME,
            project_dir / V05_VERSIONED_TRACE_FILENAME,
            active_trace_path,
            v2_source,
            v2_assembly_report,
            v05_source,
        )
        return ContractDiscovery(
            mode="v2-dual",
            instance_targets=(
                ArtifactTarget(
                    "roomcontract_v2_instance",
                    V2_INSTANCE_SCHEMA_NAME,
                    project_v2_path,
                    canonical_v2=True,
                ),
                ArtifactTarget(
                    "roomcontract_v05_instance",
                    "roomcontract_case_study.schema.json",
                    project_dir / V05_PROJECT_INSTANCE_FILENAME,
                ),
            ),
            related_paths=related_paths,
            errors=tuple(errors),
        )

    if trace_schema not in {"", V05_TRACE_SCHEMA}:
        errors.append(f"unsupported active trace_map.json schema {trace_schema!r}")
    legacy_path = case_dir / "roomcontract" / V05_GENERATED_INSTANCE_FILENAME
    return ContractDiscovery(
        mode="v0.5",
        instance_targets=(
            ArtifactTarget(
                "roomcontract_instance",
                "roomcontract_case_study.schema.json",
                legacy_path,
            ),
        ),
        related_paths=(active_trace_path, legacy_path),
        errors=tuple(errors),
    )


def _read_required_json(path: Path, label: str, errors: List[str]) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        errors.append(f"{label} fehlt: {path}")
        return None
    try:
        value = read_json(path)
    except Exception as exc:
        errors.append(f"{label} is invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return None
    return value


def _declared_basename_errors(project: Mapping[str, Any], expected: Mapping[str, str]) -> List[str]:
    errors: List[str] = []
    for field_name, filename in expected.items():
        declared = str(project.get(field_name) or "").strip()
        if not declared:
            errors.append(f"project.json {field_name} is required for V2")
        elif Path(declared).name != filename:
            errors.append(f"project.json {field_name} must reference {filename}, found {Path(declared).name}")
    return errors


def _runtime_contract_errors(*, project_dir: Path, expected_mode: str) -> List[str]:
    """Run the same fail-closed contract loader used by the backend runtime.

    JSON Schema deliberately remains a structural first line of defence.  The
    runtime loader is the shared authority for cross-file chain semantics, so a
    schema-valid but semantically forged trace must fail here exactly as it does
    when Unity starts a session.
    """

    repository_root = Path(__file__).resolve().parents[3]
    runtime_root = (
        repository_root
        / "app"
        / "backend_root"
        / "agent_backend"
    )
    runtime_root_text = str(runtime_root)
    if runtime_root_text not in sys.path:
        sys.path.insert(0, runtime_root_text)
    try:
        from backend.roomcontract_v2_runtime import load_project_contract  # type: ignore

        contract = load_project_contract(project_dir)
    except Exception as exc:
        return [f"shared runtime contract validation failed: {exc}"]

    expected_kind = "v2" if expected_mode == "v2-dual" else "v05"
    if contract.get("kind") != expected_kind:
        return [
            "shared runtime contract validation selected "
            f"{contract.get('kind')!r}; expected {expected_kind!r}."
        ]
    return []


def _validate_project_contract(
    *,
    case_dir: Path,
    backend_root: Path,
    project_payload: Mapping[str, Any],
    discovery: ContractDiscovery,
) -> List[str]:
    """Validate cross-file facts that JSON Schema cannot express."""

    errors = list(discovery.errors)
    trace = project_payload.get("trace_map") if isinstance(project_payload, Mapping) else None
    if not isinstance(trace, Mapping):
        return [*errors, "active trace_map.json must be a JSON object"]
    if discovery.mode != "v2-dual":
        project_dir = backend_root.resolve() / "projects" / case_dir.name
        errors.extend(
            _runtime_contract_errors(project_dir=project_dir, expected_mode=discovery.mode)
        )
        return errors

    case_dir = case_dir.resolve()
    project_dir = backend_root.resolve() / "projects" / case_dir.name
    paths = {
        "active_trace": project_dir / "trace_map.json",
        "v2_trace": project_dir / V2_VERSIONED_TRACE_FILENAME,
        "v05_trace": project_dir / V05_VERSIONED_TRACE_FILENAME,
        "v2_project": project_dir / V2_PROJECT_INSTANCE_FILENAME,
        "v05_project": project_dir / V05_PROJECT_INSTANCE_FILENAME,
        "v2_source": case_dir / "roomcontract" / V2_GENERATED_INSTANCE_FILENAME,
        "v2_assembly_report": case_dir / "roomcontract" / V2_ASSEMBLY_REPORT_FILENAME,
        "v05_source": case_dir / "roomcontract" / V05_GENERATED_INSTANCE_FILENAME,
    }
    documents = {
        name: _read_required_json(path, name, errors)
        for name, path in paths.items()
    }
    project = project_payload.get("project")
    if not isinstance(project, Mapping):
        errors.append("project.json must be a JSON object")
        return errors

    active_trace = documents["active_trace"]
    v2_trace = documents["v2_trace"]
    v05_trace = documents["v05_trace"]
    v2_project = documents["v2_project"]
    v05_project = documents["v05_project"]
    v2_source = documents["v2_source"]
    v2_assembly_report = documents["v2_assembly_report"]
    v05_source = documents["v05_source"]

    if active_trace is not None:
        errors.extend(
            _validate_trace_variant(
                artifact_id="active trace_map.json",
                definition_name="traceMapV2",
                payload=active_trace,
            )
        )
    if v2_trace is not None:
        errors.extend(
            _validate_trace_variant(
                artifact_id=V2_VERSIONED_TRACE_FILENAME,
                definition_name="traceMapV2",
                payload=v2_trace,
            )
        )
    if v05_trace is not None:
        errors.extend(
            _validate_trace_variant(
                artifact_id=V05_VERSIONED_TRACE_FILENAME,
                definition_name="traceMapV05",
                payload=v05_trace,
            )
        )
    if active_trace is not None and v2_trace is not None and active_trace != v2_trace:
        errors.append("active trace_map.json must be JSON-identical to trace_map.v2.json")
    if v05_project is not None:
        if v05_project.get("schema") != "roomcontract_case_study":
            errors.append("roomcontract.v05.instance.json schema must be 'roomcontract_case_study'")
        if v05_project.get("metamodelVersion") != "v0.5":
            errors.append("roomcontract.v05.instance.json metamodelVersion must be 'v0.5'")
    if v05_project is not None and v05_source is not None and v05_project != v05_source:
        errors.append("roomcontract.v05.instance.json must preserve the generated v0.5 instance exactly")
    if v2_project is not None and v2_source is not None and v2_project != v2_source:
        errors.append("project roomcontract.v2.instance.json must preserve the assembled case V2 instance exactly")
    if v2_assembly_report is not None:
        if v2_assembly_report.get("status") != "valid" or v2_assembly_report.get("ok") is not True:
            errors.append(f"{V2_ASSEMBLY_REPORT_FILENAME} must record a valid canonical V2 assembly")
        if v2_assembly_report.get("errors"):
            errors.append(f"{V2_ASSEMBLY_REPORT_FILENAME} must not contain validation errors")
        expected_object_count = len((v2_project or {}).get("objects") or [])
        actual_object_count = ((v2_assembly_report.get("metrics") or {}).get("object_count"))
        if actual_object_count != expected_object_count:
            errors.append(f"{V2_ASSEMBLY_REPORT_FILENAME} object_count does not match the V2 instance")

    trace_scheme = str((active_trace or {}).get("digest_scheme") or "sha256-raw-v1")
    project_scheme = str(project.get("roomcontract_digest_scheme") or "sha256-raw-v1")
    if trace_scheme != project_scheme:
        errors.append("trace_map.json and project.json serialization digest schemes differ")
    declared_hashes = {
        "trace_map.json model_sha256": (str((active_trace or {}).get("model_sha256") or "").upper(), trace_scheme),
        "project.json roomcontract_model_sha256": (str(project.get("roomcontract_model_sha256") or "").upper(), project_scheme),
    }
    for label, (declared_hash, scheme) in declared_hashes.items():
        try:
            actual_model_hash = _sha256_file(paths["v2_project"], scheme) if paths["v2_project"].is_file() else ""
        except ValueError:
            errors.append(f"{label} declares an unsupported serialization digest scheme")
            continue
        if not declared_hash or declared_hash != actual_model_hash:
            errors.append(f"{label} does not match roomcontract.v2.instance.json SHA-256")

    expected_values = {
        "metamodelVersion": V2_MODEL_VERSION,
        "roomcontract_model_version": V2_MODEL_VERSION,
        "roomcontract_model_schema": V2_INSTANCE_SCHEMA,
        "roomcontract_profile": V2_PROFILE,
        "roomcontract_trace_schema_version": V2_TRACE_VERSION,
    }
    for field_name, expected_value in expected_values.items():
        if project.get(field_name) != expected_value:
            errors.append(f"project.json {field_name} must be {expected_value!r}")
    errors.extend(
        _declared_basename_errors(
            project,
            {
                "roomcontract_model_path": V2_PROJECT_INSTANCE_FILENAME,
                "roomcontract_legacy_path": V05_PROJECT_INSTANCE_FILENAME,
                "roomcontract_trace_map_path": V2_VERSIONED_TRACE_FILENAME,
                "roomcontract_legacy_trace_map_path": V05_VERSIONED_TRACE_FILENAME,
            },
        )
    )

    if project.get("id") != case_dir.name:
        errors.append("project.json id must match the case directory")
    if active_trace is not None:
        if active_trace.get("case_id") != case_dir.name:
            errors.append("trace_map.json case_id must match the case directory")
        if Path(str(active_trace.get("roomcontract_path") or "")).name != V05_GENERATED_INSTANCE_FILENAME:
            errors.append(f"trace_map.json roomcontract_path must reference {V05_GENERATED_INSTANCE_FILENAME}")
        if Path(str(active_trace.get("roomcontract_v2_path") or "")).name != V2_GENERATED_INSTANCE_FILENAME:
            errors.append(f"trace_map.json roomcontract_v2_path must reference {V2_GENERATED_INSTANCE_FILENAME}")
    if v05_project is not None and v05_project.get("caseId") != case_dir.name:
        errors.append("roomcontract.v05.instance.json caseId must match the case directory")
    if v2_project is not None:
        instance_case_id = v2_project.get("caseId") or v2_project.get("id")
        if instance_case_id != case_dir.name:
            errors.append("roomcontract.v2.instance.json case identity must match the case directory")
    errors.extend(
        _runtime_contract_errors(project_dir=project_dir, expected_mode=discovery.mode)
    )
    return errors


def _target_report(
    *,
    artifact_id: str,
    schema_name: str,
    path: Optional[Path],
    errors: List[str],
) -> Dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "schema": schema_name,
        "path": str(path) if path is not None else None,
        "status": "valid" if not errors else "invalid",
        "error_count": len(errors),
        "errors": errors,
    }


def _read_artifact(target: ArtifactTarget) -> Any:
    if not target.path.exists():
        raise FileNotFoundError(f"{target.artifact_id} fehlt: {target.path}")
    return read_json(target.path)


def _project_payload(*, case_dir: Path, backend_root: Path) -> tuple[Dict[str, Any], List[Path]]:
    project_dir = backend_root.resolve() / "projects" / case_dir.name
    paths = {
        "project": project_dir / "project.json",
        "agents": project_dir / "agents.json",
        "room_plan": project_dir / "room_plan.json",
        "trace_map": project_dir / "trace_map.json",
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Projektdateien fehlen: {', '.join(missing)}")
    return {name: read_json(path) for name, path in paths.items()}, list(paths.values())


def validate_case_schemas(*, case_dir: Path, backend_root: Path = DEFAULT_BACKEND_ROOT) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    backend_root = backend_root.resolve()
    discovery = _discover_contract(case_dir=case_dir, backend_root=backend_root)
    targets = [
        ArtifactTarget(
            "normalized_scene",
            "normalized_scene.schema.json",
            case_dir / "intermediate" / "scene_graph.normalized.json",
        ),
        ArtifactTarget(
            "scene_semantics",
            "scene_semantics.schema.json",
            case_dir / "intermediate" / "scene_semantics.json",
        ),
        ArtifactTarget(
            "knowledge",
            "knowledge.schema.json",
            case_dir / "intermediate" / "knowledge.generated.json",
        ),
        *discovery.instance_targets,
    ]

    reports: List[Dict[str, Any]] = []
    errors: List[str] = []
    warning_messages: List[str] = []
    input_paths: List[Path] = []

    for target in targets:
        input_paths.append(target.path)
        try:
            payload = _read_artifact(target)
            if target.canonical_v2:
                target_errors = _validate_v2_payload(
                    artifact_id=target.artifact_id,
                    payload=payload,
                )
            else:
                target_errors = _validate_payload(
                    artifact_id=target.artifact_id,
                    schema_name=target.schema_name,
                    payload=payload,
                )
        except Exception as exc:
            target_errors = [f"{target.artifact_id}: {exc}"]
        reports.append(
            _target_report(
                artifact_id=target.artifact_id,
                schema_name=target.schema_name,
                path=target.path,
                errors=target_errors,
            )
        )
        errors.extend(target_errors)

    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    handoff_matrix_path = case_dir / "intermediate" / "handoff_matrix.json"
    input_paths.extend([agent_roles_path, handoff_matrix_path])
    try:
        agent_roles = read_json(agent_roles_path)
        handoff_matrix = read_json(handoff_matrix_path)
        agent_roles_payload = {
            "agents": agent_roles.get("agents") or [],
            "handoffs": handoff_matrix.get("handoffs") or [],
        }
        agent_role_errors = _validate_payload(
            artifact_id="agent_roles",
            schema_name="agent_roles.schema.json",
            payload=agent_roles_payload,
        )
    except Exception as exc:
        agent_role_errors = [f"agent_roles: {exc}"]
    reports.append(
        _target_report(
            artifact_id="agent_roles",
            schema_name="agent_roles.schema.json",
            path=case_dir / "intermediate",
            errors=agent_role_errors,
        )
    )
    errors.extend(agent_role_errors)

    project_paths: List[Path] = []
    try:
        project_payload, project_paths = _project_payload(case_dir=case_dir, backend_root=backend_root)
        project_errors = _validate_payload(
            artifact_id="interactive_agents_project",
            schema_name="interactive_agents_project.schema.json",
            payload=project_payload,
        )
        project_errors.extend(
            _validate_project_contract(
                case_dir=case_dir,
                backend_root=backend_root,
                project_payload=project_payload,
                discovery=discovery,
            )
        )
    except Exception as exc:
        project_errors = [*discovery.errors, f"interactive_agents_project: {exc}"]
    input_paths.extend([*project_paths, *discovery.related_paths])
    reports.append(
        _target_report(
            artifact_id="interactive_agents_project",
            schema_name="interactive_agents_project.schema.json",
            path=backend_root / "projects" / case_dir.name,
            errors=project_errors,
        )
    )
    errors.extend(project_errors)

    runtime_log_path = case_dir / "runtime_logs" / "events.jsonl"
    runtime_event_count = 0
    if runtime_log_path.exists():
        input_paths.append(runtime_log_path)
        runtime_errors: List[str] = []
        used_runtime_schemas: set[str] = set()
        runtime_errors_by_schema: Dict[str, List[str]] = {}
        with runtime_log_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                runtime_event_count += 1
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    runtime_errors.append(f"runtime_events line {line_number}: invalid JSON: {exc}")
                    continue
                runtime_schema = (
                    "runtime_event_v2.schema.json"
                    if str(event.get("schema_version") or "") == "2.0"
                    else "runtime_event.schema.json"
                )
                used_runtime_schemas.add(runtime_schema)
                event_errors = [
                    f"runtime_events line {line_number}: {error}"
                    for error in _validate_payload(
                        artifact_id="runtime_events",
                        schema_name=runtime_schema,
                        payload=event,
                    )
                ]
                runtime_errors.extend(event_errors)
                runtime_errors_by_schema.setdefault(runtime_schema, []).extend(event_errors)
        for runtime_schema in sorted(used_runtime_schemas or {"runtime_event.schema.json"}):
            reports.append(
                _target_report(
                    artifact_id=f"runtime_events_{runtime_schema}",
                    schema_name=runtime_schema,
                    path=runtime_log_path,
                    errors=runtime_errors_by_schema.get(runtime_schema, []),
                )
            )
        errors.extend(runtime_errors)
    else:
        warning_messages.append(f"Runtime-Log fehlt: {runtime_log_path}")

    runtime_validation_path = case_dir / "runtime_logs" / "runtime_validation.v2.jsonl"
    if runtime_validation_path.exists():
        input_paths.append(runtime_validation_path)
        runtime_validation_errors: List[str] = []
        with runtime_validation_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    runtime_validation_errors.append(
                        f"runtime_validation_v2 line {line_number}: invalid JSON: {exc}"
                    )
                    continue
                runtime_validation_errors.extend(
                    f"runtime_validation_v2 line {line_number}: {error}"
                    for error in _validate_payload(
                        artifact_id="runtime_validation_v2",
                        schema_name="runtime_validation_v2.schema.json",
                        payload=record,
                    )
                )
        reports.append(
            _target_report(
                artifact_id="runtime_validation_v2",
                schema_name="runtime_validation_v2.schema.json",
                path=runtime_validation_path,
                errors=runtime_validation_errors,
            )
        )
        errors.extend(runtime_validation_errors)

    schema_names = sorted({report["schema"] for report in reports})
    output = {
        "case_id": case_dir.name,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warning_messages,
        "metrics": {
            "artifact_count": len(reports),
            "valid_artifact_count": sum(1 for report in reports if report["status"] == "valid"),
            "invalid_artifact_count": sum(1 for report in reports if report["status"] != "valid"),
            "schema_count": len(schema_names),
            "runtime_event_count": runtime_event_count,
            "contract_mode": discovery.mode,
        },
        "artifacts": reports,
        "schemas": schema_names,
        "contract_mode": discovery.mode,
    }
    return output


def run_schema_validation_for_case(
    case_dir: Path,
    *,
    backend_root: Path = DEFAULT_BACKEND_ROOT,
) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    backend_root = Path(backend_root).resolve()
    validation = validate_case_schemas(case_dir=case_dir, backend_root=backend_root)
    validation_path = case_dir / "validation" / "schema_validation.json"
    write_json(validation_path, validation)

    discovery = _discover_contract(case_dir=case_dir, backend_root=backend_root)
    input_paths = [
        case_dir / "intermediate" / "scene_graph.normalized.json",
        case_dir / "intermediate" / "scene_semantics.json",
        case_dir / "intermediate" / "agent_roles.generated.json",
        case_dir / "intermediate" / "handoff_matrix.json",
        case_dir / "intermediate" / "knowledge.generated.json",
        backend_root / "projects" / case_dir.name / "project.json",
        backend_root / "projects" / case_dir.name / "agents.json",
        backend_root / "projects" / case_dir.name / "room_plan.json",
        case_dir / "runtime_logs" / "events.jsonl",
        case_dir / "runtime_logs" / "runtime_validation.v2.jsonl",
        *(target.path for target in discovery.instance_targets),
        *discovery.related_paths,
    ]
    input_paths = list(dict.fromkeys(input_paths))
    schema_paths = [_schema_path(name) for name in validation["schemas"]]
    update_manifest(
        case_dir,
        stage_id="schema_validation",
        status="success" if validation["status"] == "valid" else "failed",
        input_paths=input_paths + schema_paths,
        output_paths=[validation_path],
        errors=validation["errors"],
        warnings=validation["warnings"],
        metadata=validation["metrics"],
    )
    return {
        "case_id": case_dir.name,
        "status": "success" if validation["status"] == "valid" else "failed",
        "validation": validation,
        "validation_path": str(validation_path),
    }


def run_schema_validation_for_cases(
    case_dirs: Iterable[Path],
    *,
    backend_root: Path = DEFAULT_BACKEND_ROOT,
) -> List[Dict[str, Any]]:
    return [run_schema_validation_for_case(Path(case_dir), backend_root=backend_root) for case_dir in case_dirs]


def _case_dirs_from_root(root: Path) -> List[Path]:
    return sorted([path for path in root.iterdir() if path.is_dir()])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate RoomContract case-study artifacts against JSON Schemas.")
    parser.add_argument("--case-dir", type=Path, action="append", help="Case-study directory to validate.")
    parser.add_argument("--case-root", type=Path, help="Root containing multiple case-study directories.")
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    args = parser.parse_args(argv)

    case_dirs = args.case_dir or []
    if args.case_root:
        case_dirs.extend(_case_dirs_from_root(args.case_root))
    if not case_dirs:
        parser.error("Pass --case-dir or --case-root.")

    results = run_schema_validation_for_cases(case_dirs, backend_root=args.backend_root)
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
