from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .publication import project_lock, append_evidence_pair

from .roomcontract_v2_runtime import (
    V2_MODEL_VERSION,
    RoomContractContractError,
    load_project_contract,
    runtime_actions_for_kind,
    select_runtime_action,
)


RUNTIME_LOG_SCHEMA = "roomcontract_runtime_event"
RUNTIME_LOG_SCHEMA_VERSION = "1.0"
RUNTIME_LOG_SCHEMA_VERSION_V2 = "2.0"
RUNTIME_VALIDATION_SCHEMA = "dynamic_functional_rdl_v2_runtime_validation"

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*[^,\s}]+"),
)

_LOG_LOCKS: Dict[str, threading.RLock] = {}
_LOG_LOCKS_GUARD = threading.Lock()


def contract_runtime_fingerprint(contract: Mapping[str, Any]) -> str:
    """Return a stable identity for the executable part of a loaded contract.

    The native model hash, complete trace/runtime context, and contract-relevant
    project paths are included.  Descriptive metadata is excluded so harmless title
    edits do not invalidate a running session.
    """

    snapshot = {
        "kind": contract.get("kind"),
        "model_version": contract.get("model_version"),
        "profile": contract.get("profile"),
        "model_sha256": contract.get("model_sha256"),
        "instance_path": contract.get("instance_path"),
        "trace_path": contract.get("trace_path"),
        "trace": contract.get("trace"),
        "runtime_context": contract.get("runtime_context"),
        "project_contract_paths": {
            key: (contract.get("project") or {}).get(key)
            for key in (
                "roomcontract_model_path",
                "roomcontract_v2_path",
                "roomcontract_trace_map_path",
                "roomcontract_trace_path",
            )
        },
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


_ROUTING_VERIFIER = None


def contract_commit_fingerprint(contract: Mapping[str, Any], variant: str = "full", *,
                                project_dir: Optional[Path] = None) -> str:
    """Explicit experimental scope; full preserves the packet fingerprint."""
    if variant == "full":
        return contract_runtime_fingerprint(contract)
    if variant == "none":
        return ""
    if variant == "digest_only":
        return str(contract.get("model_sha256") or "")
    if variant not in {"slice", "slice_prompt"}:
        raise ValueError("Unknown commit fingerprint scope")
    global _ROUTING_VERIFIER
    if _ROUTING_VERIFIER is None:
        import importlib.util
        verifier_path = next((parent / "tools" / "routing_verifier.py" for parent in Path(__file__).resolve().parents
                              if (parent / "tools" / "routing_verifier.py").is_file()), None)
        if verifier_path is None:
            raise RoomContractContractError("Routing-slice verifier is unavailable.")
        spec = importlib.util.spec_from_file_location("_roomcontract_commit_routing_verifier", verifier_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _ROUTING_VERIFIER = module
    report = _ROUTING_VERIFIER.verify_routing(contract.get("instance") or {}, contract.get("trace") or {},
                                             model_sha256=str(contract.get("model_sha256") or ""))
    snapshot = {"routing_table": report["routing_table"],
                "declared_actions": sorted((contract.get("runtime_context") or {}).get("runtime_actions") or [], key=_canonical_json)}
    if variant == "slice_prompt":
        root = Path(project_dir) if project_dir is not None else Path(str(contract.get("instance_path") or "")).parent
        projections = contract.get("publication_projections") or {}
        agents_doc = projections.get("agents.json") or json.loads((root / "agents.json").read_text(encoding="utf-8"))
        prompt_fields = ("id", "display_name", "name", "persona", "expertise", "knowledge_tags", "system_prompt", "description")
        snapshot["prompt_agents"] = sorted([{k: a.get(k) for k in prompt_fields} for a in agents_doc.get("agents", [])], key=_canonical_json)
        kb = root / "kb"
        snapshot["knowledge_documents"] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in sorted(kb.rglob("*")) if p.is_file()} if kb.exists() else {}
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest().upper()


def log_backend_event(
    *,
    project_manager: Any,
    project_id: Optional[str],
    action_kind: str,
    event_type: str,
    session_id: Optional[str],
    agent_id: Optional[str],
    input_summary: Any,
    output_summary: Any,
    duration_ms: Optional[float] = None,
    status: str = "success",
    metadata: Optional[Mapping[str, Any]] = None,
    expected_contract_fingerprint: Optional[str] = None,
    expected_action: Optional[Mapping[str, Any]] = None,
    publication_protocol: str = "packet",
    expected_publication_generation: Optional[int] = None,
    commit_variant: str = "full",
    pinned_contract: Optional[Mapping[str, Any]] = None,
    skip_declared_action_check: bool = False,
) -> Optional[Dict[str, Any]]:
    events = log_backend_events(
        project_manager=project_manager,
        project_id=project_id,
        entries=[
            {
                "action_kind": action_kind,
                "event_type": event_type,
                "session_id": session_id,
                "agent_id": agent_id,
                "input_summary": input_summary,
                "output_summary": output_summary,
                "duration_ms": duration_ms,
                "status": status,
                "metadata": metadata or {},
                "expected_action": expected_action,
            }
        ],
        expected_contract_fingerprint=expected_contract_fingerprint,
        publication_protocol=publication_protocol,
        expected_publication_generation=expected_publication_generation,
        commit_variant=commit_variant, pinned_contract=pinned_contract,
        skip_declared_action_check=skip_declared_action_check,
    )
    return events[0] if events else None


def log_backend_events(
    *, project_manager: Any, project_id: Optional[str],
    entries: Sequence[Mapping[str, Any]],
    expected_contract_fingerprint: Optional[str] = None,
    publication_protocol: str = "packet",
    expected_publication_generation: Optional[int] = None,
    fault_hook: Any = None,
    commit_variant: str = "full",
    pinned_contract: Optional[Mapping[str, Any]] = None,
    skip_declared_action_check: bool = False,
) -> List[Dict[str, Any]]:
    """Cooperative mode encloses validation, comparison and append in one lock."""
    if commit_variant not in {"full", "none", "digest_only", "slice", "slice_prompt"}:
        raise ValueError("Unknown commit variant")
    if publication_protocol not in {"packet", "cooperative"}:
        raise ValueError("Unknown publication protocol")
    kwargs = dict(project_manager=project_manager, project_id=project_id, entries=entries,
                  expected_contract_fingerprint=expected_contract_fingerprint,
                  publication_protocol=publication_protocol,
                  expected_publication_generation=expected_publication_generation,
                  fault_hook=fault_hook, commit_variant=commit_variant, pinned_contract=pinned_contract,
                  skip_declared_action_check=skip_declared_action_check)
    project_dir = _project_dir(project_manager, project_id) if project_id else None
    if publication_protocol == "cooperative" and project_dir is not None:
        with project_lock(project_dir):
            return _log_backend_events_unlocked(**kwargs)
    return _log_backend_events_unlocked(**kwargs)


def _log_backend_events_unlocked(
    *,
    project_manager: Any,
    project_id: Optional[str],
    entries: Sequence[Mapping[str, Any]],
    expected_contract_fingerprint: Optional[str] = None,
    publication_protocol: str = "packet",
    expected_publication_generation: Optional[int] = None,
    fault_hook: Any = None,
    commit_variant: str = "full",
    pinned_contract: Optional[Mapping[str, Any]] = None,
    skip_declared_action_check: bool = False,
) -> List[Dict[str, Any]]:
    """Validate and append one or more runtime events as one local transaction.

    For a V2 contract, every entry is resolved to one exact action mapping before
    any byte is written.  Event and validation JSONL files are then appended under
    one process lock; on a local write/fsync failure both files are truncated back
    to their original sizes.
    """

    if not project_id:
        return []
    contract_kind: Optional[str] = None
    try:
        project_dir = _project_dir(project_manager, project_id)
        if project_dir is None:
            return []
        contract_kind = _declared_contract_kind(project_dir)
        if publication_protocol == "cooperative":
            # The callback calls the legacy loader only inside the consistent read.
            from .publication import load_consistent_contract
            contract = load_consistent_contract(project_dir, load_project_contract)
            if expected_publication_generation is None or contract["publication_generation"] != expected_publication_generation:
                raise RoomContractContractError("Published generation differs from the session pin.", code="E_CONTRACT_DRIFT")
        elif commit_variant in {"none", "digest_only"} and pinned_contract is not None:
            contract = dict(pinned_contract)
            if commit_variant == "digest_only":
                from .roomcontract_v2_runtime import _sha256
                scheme = str((contract.get("project") or {}).get("roomcontract_digest_scheme") or "sha256-raw-v1")
                contract["model_sha256"] = _sha256(Path(contract["instance_path"]), scheme=scheme)
        else:
            contract = load_project_contract(project_dir)
        contract_kind = str(contract.get("kind") or "")
        if (
            contract_kind == "v2"
            and commit_variant != "none"
            and expected_contract_fingerprint
            and contract_commit_fingerprint(contract, commit_variant, project_dir=project_dir) != expected_contract_fingerprint
        ):
            raise RoomContractContractError("RoomContract V2 project drift detected: the current runtime contract "
                "does not match the contract pinned by the session.", code="E_CONTRACT_DRIFT")
        runtime_context = contract.get("runtime_context") or {}
        log_path = (project_dir / "runtime_logs" / "events.jsonl") if publication_protocol == "cooperative" else _runtime_log_path(project_dir)
        events: List[Dict[str, Any]] = []
        validations: List[Dict[str, Any]] = []
        for index, entry in enumerate(entries):
            action_kind = str(entry.get("action_kind") or "").strip().lower()
            expected_action = entry.get("expected_action")
            experimental_unbound = bool(skip_declared_action_check and isinstance(expected_action, Mapping)
                                        and expected_action.get("_experimental_undeclared"))
            if experimental_unbound:
                trace_ref = dict(expected_action)
            elif contract_kind == "v2" and expected_action is not None and commit_variant in {"none", "digest_only"}:
                trace_ref = dict(expected_action)
            elif contract_kind == "v2" and expected_action is not None:
                exact_matches = [
                    candidate
                    for candidate in runtime_actions_for_kind(
                        runtime_context,
                        action_kind,
                    )
                    if _canonical_json(candidate)
                    == _canonical_json(expected_action)
                ]
                if len(exact_matches) != 1:
                    raise RoomContractContractError(f"RoomContract V2 action drift detected for {action_kind!r}: "
                        "the concrete runtime action no longer matches the session preflight.", code="E_CONTRACT_DRIFT")
                trace_ref = exact_matches[0]
            else:
                try:
                    trace_ref = select_runtime_action(
                        runtime_context,
                        action_kind,
                    )
                except RoomContractContractError:
                    if contract_kind == "v2":
                        raise
                    trace_ref = _empty_trace_ref()
            event = _build_event(
                case_id=str((contract.get("trace") or {}).get("case_id") or project_id),
                event_type=str(entry.get("event_type") or "").strip(),
                session_id=_optional_str(entry.get("session_id")),
                agent_id=_optional_str(entry.get("agent_id")),
                input_summary=entry.get("input_summary"),
                output_summary=entry.get("output_summary"),
                duration_ms=entry.get("duration_ms"),
                status=str(entry.get("status") or "success"),
                metadata=entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {},
                model_version=str(contract.get("model_version") or "v0.5"),
                model_sha256=str(contract.get("model_sha256") or ""),
                scenario_step_id=trace_ref.get("scenario_step_id"),
                capability_use_id=trace_ref.get("capability_use_id"),
                capability_id=trace_ref.get("capability_id"),
                provider_entity_id=trace_ref.get("provider_entity_id"),
                target_ids=trace_ref.get("target_ids") or [],
                runtime_binding_id=trace_ref.get("runtime_binding_id"),
                runtime_action_id=trace_ref.get("runtime_action_id"),
                assertion_ids=trace_ref.get("assertion_ids") or [],
                validation_case_ids=trace_ref.get("validation_case_ids") or [],
                runtime_validation_target_ids=trace_ref.get("runtime_validation_target_ids") or [],
            )
            if experimental_unbound:
                event["metadata"]["declaration_check"] = "disabled_reach_only"
            if publication_protocol == "cooperative":
                event["publication_generation"] = contract["publication_generation"]
            events.append(event)
            if contract_kind == "v2" and experimental_unbound:
                validations.append({"schema": "roomcontract_experimental_unbound_validation", "schema_version": "1.0",
                                    "event_id": event["event_id"], "verdict": "inconclusive",
                                    "reason": "declaration check disabled; no model assertion is claimed",
                                    "runtimeValidationLog": {"id": event["event_id"] + "-LOG"}})
            elif contract_kind == "v2":
                validations.append(
                    _build_validation_record(
                        event=event,
                        assertion_ids=trace_ref.get("assertion_ids") or [],
                        validation_case_ids=trace_ref.get("validation_case_ids") or [],
                        runtime_validation_target_ids=trace_ref.get("runtime_validation_target_ids") or [],
                        observed_value=entry.get("output_summary"),
                        status=str(entry.get("status") or "success"),
                    )
                )
        if not events:
            return []
        validation_path = log_path.parent / "runtime_validation.v2.jsonl" if validations else None
        if fault_hook is not None:
            fault_hook("after_contract_check")
        _append_jsonl_transaction(log_path, events, validation_path, validations,
                                  cooperative_project=project_dir if publication_protocol == "cooperative" else None,
                                  fault_hook=fault_hook)
        return events
    except Exception as exc:
        if contract_kind == "v2" or expected_contract_fingerprint:
            raise
        print(f"[RuntimeTrace] Warnung: Event konnte nicht geschrieben werden: {exc}", flush=True)
        return []


def _declared_contract_kind(project_dir: Path) -> str:
    meta = _read_json_if_exists(project_dir / "project.json")
    version = str(
        meta.get("roomcontract_model_version")
        or meta.get("metamodelVersion")
        or ""
    ).strip()
    return "v2" if version == V2_MODEL_VERSION else ""


def _empty_trace_ref() -> Dict[str, Any]:
    return {
        "scenario_step_id": None,
        "capability_use_id": None,
        "capability_id": None,
        "provider_entity_id": None,
        "target_ids": [],
        "runtime_binding_id": None,
        "runtime_action_id": None,
        "assertion_ids": [],
        "validation_case_ids": [],
        "runtime_validation_target_ids": [],
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _log_lock(path: Path) -> threading.RLock:
    key = str(path.resolve()).lower()
    with _LOG_LOCKS_GUARD:
        return _LOG_LOCKS.setdefault(key, threading.RLock())


def _append_jsonl_transaction(
    event_path: Path,
    events: Sequence[Mapping[str, Any]],
    validation_path: Optional[Path],
    validations: Sequence[Mapping[str, Any]],
    *, cooperative_project: Optional[Path] = None, fault_hook: Any = None,
) -> None:
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_payload = b"".join(
        (json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for item in events
    )
    validation_payload = b"".join(
        (json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for item in validations
    )
    if cooperative_project is not None:
        append_evidence_pair(cooperative_project, event_path, event_payload,
                             validation_path, validation_payload, fault_hook=fault_hook)
        return
    with _log_lock(event_path):
        event_handle = None
        validation_handle = None
        event_start = 0
        validation_start = 0
        try:
            event_handle = event_path.open("a+b")
            event_handle.seek(0, os.SEEK_END)
            event_start = event_handle.tell()
            if validation_path is not None:
                validation_path.parent.mkdir(parents=True, exist_ok=True)
                validation_handle = validation_path.open("a+b")
                validation_handle.seek(0, os.SEEK_END)
                validation_start = validation_handle.tell()
            event_handle.write(event_payload)
            event_handle.flush()
            os.fsync(event_handle.fileno())
            if validation_handle is not None:
                validation_handle.write(validation_payload)
                validation_handle.flush()
                os.fsync(validation_handle.fileno())
            if fault_hook is not None:
                fault_hook("after_packet_append")
        except Exception:
            if event_handle is not None:
                event_handle.seek(event_start)
                event_handle.truncate()
                event_handle.flush()
                os.fsync(event_handle.fileno())
            if validation_handle is not None:
                validation_handle.seek(validation_start)
                validation_handle.truncate()
                validation_handle.flush()
                os.fsync(validation_handle.fileno())
            raise
        finally:
            if validation_handle is not None:
                validation_handle.close()
            if event_handle is not None:
                event_handle.close()


def _project_dir(project_manager: Any, project_id: str) -> Optional[Path]:
    resolver = getattr(project_manager, "_project_dir", None)
    if callable(resolver):
        return Path(resolver(project_id))
    root = getattr(project_manager, "root", None)
    if root is None:
        return None
    return Path(root) / project_id


def _runtime_log_path(project_dir: Path) -> Path:
    meta = _read_json_if_exists(project_dir / "project.json")
    trace_path_raw = str(meta.get("roomcontract_trace_path") or "").strip()
    if trace_path_raw:
        trace_path = Path(trace_path_raw)
        if trace_path.parent.name == "roomcontract":
            return trace_path.parent.parent / "runtime_logs" / "events.jsonl"
    return project_dir / "runtime_logs" / "events.jsonl"


def _read_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _trace_ref(trace_map: Mapping[str, Any], action_kind: str) -> Dict[str, Optional[str]]:
    actions = [item for item in trace_map.get("runtime_actions", []) if isinstance(item, Mapping)]
    action_kind = action_kind.strip().lower()

    def matches(item: Mapping[str, Any]) -> bool:
        action_id = str(item.get("runtime_action_id") or "")
        capability_id = str(item.get("capability_id") or "")
        endpoint = str(item.get("endpoint") or "")
        if action_kind == "setup":
            return endpoint == "POST /setup"
        if action_kind == "handoff":
            return endpoint == "POST /chat" and ("HANDOFF" in action_id or "HANDOFF" in capability_id)
        if action_kind == "chat":
            return (
                endpoint == "POST /chat"
                and "HANDOFF" not in action_id
                and "HANDOFF" not in capability_id
            )
        return False

    for item in actions:
        if matches(item):
            return {
                "capability_id": _optional_str(item.get("capability_id")),
                "runtime_binding_id": _optional_str(item.get("runtime_binding_id")),
                "runtime_action_id": _optional_str(item.get("runtime_action_id")),
            }
    return {"capability_id": None, "runtime_binding_id": None, "runtime_action_id": None}


def _scenario_step_id(trace_map: Mapping[str, Any], capability_id: Optional[str]) -> Optional[str]:
    if not capability_id:
        return None
    case_id = str(trace_map.get("case_id") or "").upper()
    prefix = f"CAP-{case_id}-"
    suffix = capability_id[len(prefix) :] if capability_id.startswith(prefix) else capability_id
    for step in trace_map.get("scenario_steps", []):
        if not isinstance(step, Mapping):
            continue
        for capability_use_id in step.get("capability_use_ids") or []:
            if str(capability_use_id).endswith(suffix):
                return _optional_str(step.get("scenario_step_id"))
    return None


def _build_event(
    *,
    case_id: str,
    event_type: str,
    session_id: Optional[str],
    agent_id: Optional[str],
    model_version: str,
    model_sha256: str,
    scenario_step_id: Optional[str],
    capability_use_id: Optional[str],
    capability_id: Optional[str],
    provider_entity_id: Optional[str],
    target_ids: Any,
    runtime_binding_id: Optional[str],
    runtime_action_id: Optional[str],
    assertion_ids: Any,
    validation_case_ids: Any,
    runtime_validation_target_ids: Any,
    input_summary: Any,
    output_summary: Any,
    duration_ms: Optional[float],
    status: str,
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    event = {
        "schema": RUNTIME_LOG_SCHEMA,
        "schema_version": RUNTIME_LOG_SCHEMA_VERSION_V2 if model_version == V2_MODEL_VERSION else RUNTIME_LOG_SCHEMA_VERSION,
        "event_id": f"EVT-{uuid.uuid4().hex}",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "case_id": case_id,
        "session_id": session_id,
        "event_type": event_type,
        "agent_id": agent_id,
        "scenario_step_id": scenario_step_id,
        "capability_id": capability_id,
        "runtime_binding_id": runtime_binding_id,
        "runtime_action_id": runtime_action_id,
        "input_summary": _summary(input_summary),
        "output_summary": _summary(output_summary),
        "duration_ms": duration_ms,
        "status": status,
        "error_summary": None,
        "metadata": _metadata(metadata),
    }
    if model_version == V2_MODEL_VERSION:
        event.update(
            {
                "model_version": model_version,
                "model_sha256": model_sha256,
                "capability_use_id": capability_use_id,
                "provider_entity_id": provider_entity_id,
                "target_ids": list(target_ids or []),
                "assertion_ids": list(assertion_ids or []),
                "validation_case_ids": list(validation_case_ids or []),
                "runtime_validation_target_ids": list(runtime_validation_target_ids or []),
            }
        )
    return event


def _build_validation_record(
    *,
    event: Mapping[str, Any],
    assertion_ids: Any,
    validation_case_ids: Any,
    runtime_validation_target_ids: Any,
    observed_value: Any,
    status: str,
) -> Dict[str, Any]:
    event_id = str(event.get("event_id") or f"EVT-{uuid.uuid4().hex}")
    timestamp = str(event.get("timestamp") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    # A successful transport/action is not evidence that the domain assertion passed.
    # Until a concrete probe evaluates the EAExpression, the semantically correct result
    # is inconclusive. Explicit execution errors and failures remain distinguishable.
    verdict = "error" if status == "error" else ("fail" if status in {"failed", "failure"} else "inconclusive")
    results = []
    for index, assertion_id in enumerate(assertion_ids or [], start=1):
        results.append(
            {
                "id": f"{event_id}-RESULT-{index}",
                "type": "AssertionResult",
                "assertion": [str(assertion_id)],
                "verdict": verdict,
                "observedValue": {
                    "type": "EAExpression",
                    "mixedStringContent": _summary(observed_value, max_chars=2000),
                },
                "evidenceRef": f"runtime-event://{event_id}",
                "timestamp": timestamp,
            }
        )
    if not results:
        raise RoomContractContractError(
            f"V2 runtime action {event.get('runtime_action_id')!r} has no Assertion specification."
        )
    actual_outcome_id = f"{event_id}-ACTUAL"
    return {
        "schema": RUNTIME_VALIDATION_SCHEMA,
        "schema_version": "2.0",
        "model_version": V2_MODEL_VERSION,
        "model_sha256": event.get("model_sha256"),
        "case_id": event.get("case_id"),
        "session_id": event.get("session_id"),
        "validation_case_ids": list(validation_case_ids or []),
        "runtime_validation_target_ids": list(runtime_validation_target_ids or []),
        "runtimeValidationLog": {
            "id": f"{event_id}-LOG",
            "type": "RuntimeValidationLog",
            "actualOutcome": [actual_outcome_id],
        },
        "runtimeActualOutcome": {
            "id": actual_outcome_id,
            "type": "RuntimeActualOutcome",
            "result": results,
        },
    }


def _summary(value: Any, max_chars: int = 2000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 15].rstrip() + " [TRUNCATED]"
    return text


def _metadata(values: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in values.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            out[str(key)] = value
        else:
            out[str(key)] = _summary(value, max_chars=500)
    return out


def _optional_str(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None
