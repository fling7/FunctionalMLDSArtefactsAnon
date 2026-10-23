from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..common import read_json, update_manifest, write_json


Pair = Tuple[str, str]


DEFAULT_HANDOFF_CHAIN_LIMIT = 1
PREFERRED_HANDOFF_TEST_RESULT_PATHS = (
    Path("validation/handoff_test_results.json"),
    Path("runtime_logs/handoff_test_results.json"),
)
FALLBACK_CHAT_TEST_RESULT_PATHS = (
    Path("validation/chat_test_results.json"),
    Path("runtime_logs/chat_test_results.json"),
)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 6)


def _agent_ids(agent_roles: Mapping[str, Any]) -> Set[str]:
    return {
        str(agent.get("id") or "").strip()
        for agent in agent_roles.get("agents") or []
        if isinstance(agent, Mapping) and str(agent.get("id") or "").strip()
    }


def _agent_target_refs(agent_roles: Mapping[str, Any]) -> List[Pair]:
    refs: List[Pair] = []
    for agent in agent_roles.get("agents") or []:
        if not isinstance(agent, Mapping):
            continue
        source = str(agent.get("id") or "").strip()
        if not source:
            continue
        for target in agent.get("handoff_targets") or []:
            target_id = str(target or "").strip()
            if target_id:
                refs.append((source, target_id))
    return refs


def _handoff_pairs(handoff_matrix: Mapping[str, Any]) -> List[Pair]:
    pairs: List[Pair] = []
    for handoff in handoff_matrix.get("handoffs") or []:
        if not isinstance(handoff, Mapping):
            continue
        source = str(handoff.get("source_agent_id") or "").strip()
        target = str(handoff.get("target_agent_id") or "").strip()
        if source or target:
            pairs.append((source, target))
    return pairs


def _handoff_entries_by_pair(handoff_matrix: Mapping[str, Any]) -> Dict[Pair, Dict[str, Any]]:
    entries: Dict[Pair, Dict[str, Any]] = {}
    for handoff in handoff_matrix.get("handoffs") or []:
        if not isinstance(handoff, Mapping):
            continue
        source = str(handoff.get("source_agent_id") or "").strip()
        target = str(handoff.get("target_agent_id") or "").strip()
        if source and target and (source, target) not in entries:
            entries[(source, target)] = dict(handoff)
    return entries


def _valid_pair(pair: Pair, agent_ids: Set[str]) -> bool:
    source, target = pair
    return bool(source and target and source in agent_ids and target in agent_ids and source != target)


def _duplicate_count(pairs: Sequence[Pair]) -> int:
    return len(pairs) - len(set(pairs))


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _metadata_pair(event: Mapping[str, Any]) -> Optional[Pair]:
    metadata = event.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        return None
    source = str(metadata.get("from") or "").strip()
    target = str(metadata.get("to") or "").strip()
    if source or target:
        return (source, target)
    return None


def _sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _runtime_events_for_active_model(
    runtime_events: Sequence[Dict[str, Any]],
    *,
    active_model_sha256: Optional[str],
) -> Tuple[List[Dict[str, Any]], int]:
    """Select execution evidence belonging to the currently validated model.

    V2 events carry the exact model SHA.  Once a V2 model exists, legacy events
    and V2 events from older generations remain useful historical evidence, but
    must not invalidate a newly generated model.  Legacy-only cases retain the
    original behavior because their events cannot be scoped by model SHA.
    """

    normalized_sha = str(active_model_sha256 or "").strip().upper()
    if not normalized_sha:
        return list(runtime_events), 0
    current = [
        event
        for event in runtime_events
        if str(event.get("schema_version") or "").strip() == "2.0"
        and str(event.get("model_sha256") or "").strip().upper() == normalized_sha
    ]
    return current, len(runtime_events) - len(current)


def _read_chain_limit(config_path: Optional[Path]) -> int:
    if not config_path or not config_path.exists():
        return DEFAULT_HANDOFF_CHAIN_LIMIT
    try:
        value = json.loads(config_path.read_text(encoding="utf-8-sig")).get("max_handoffs")
        return max(0, int(value))
    except Exception:
        return DEFAULT_HANDOFF_CHAIN_LIMIT


def _items_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "tests", "items", "chat_tests", "handoff_tests"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _nested_get(item: Mapping[str, Any], section: str, key: str) -> Any:
    nested = item.get(section)
    if isinstance(nested, Mapping):
        return nested.get(key)
    return None


def _optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _optional_agent_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if text.lower() in {"", "none", "null"}:
        return None
    return text


def _load_test_results(case_dir: Path) -> Tuple[List[Dict[str, Any]], List[Path]]:
    loaded_by_id: Dict[str, Dict[str, Any]] = {}
    anonymous_items: List[Dict[str, Any]] = []
    paths: List[Path] = []
    for relative in (*PREFERRED_HANDOFF_TEST_RESULT_PATHS, *FALLBACK_CHAT_TEST_RESULT_PATHS):
        path = case_dir / relative
        if not path.exists():
            continue
        payload = read_json(path)
        items = _items_from_payload(payload)
        if not items:
            continue
        paths.append(path)
        for index, item in enumerate(items):
            question_id = str(item.get("question_id") or "").strip()
            if question_id:
                loaded_by_id.setdefault(question_id, item)
            else:
                anonymous_items.append({"_source_index": index, **item})
    return [*loaded_by_id.values(), *anonymous_items], paths


def _evaluate_decision_tests(test_results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    evaluated = 0
    correct = 0
    invalid_observations = 0
    per_test: List[Dict[str, Any]] = []

    for index, item in enumerate(test_results):
        expected_target = _optional_agent_id(
            item.get("expected_handoff_to")
            or item.get("expected_target_agent_id")
            or _nested_get(item, "expected", "handoff_to")
            or _nested_get(item, "expected", "target_agent_id")
        )
        observed_target = _optional_agent_id(
            item.get("observed_handoff_to")
            or item.get("actual_handoff_to")
            or item.get("handoff_to")
            or _nested_get(item, "observed", "handoff_to")
            or _nested_get(item, "actual", "handoff_to")
        )
        expected_flag = _optional_bool(item.get("expected_handoff"))
        observed_flag = _optional_bool(item.get("observed_handoff") or item.get("actual_handoff"))
        if expected_flag is None:
            expected_flag = expected_target is not None
        if observed_flag is None:
            observed_flag = observed_target is not None

        if "expected_handoff" not in item and expected_target is None and _nested_get(item, "expected", "handoff_to") is None:
            continue

        evaluated += 1
        if expected_flag:
            is_correct = observed_target == expected_target and observed_flag
        else:
            is_correct = not observed_flag and observed_target is None
        if is_correct:
            correct += 1
        if observed_flag and observed_target is None:
            invalid_observations += 1
        per_test.append(
            {
                "index": index,
                "expected_handoff": expected_flag,
                "expected_handoff_to": expected_target,
                "observed_handoff": observed_flag,
                "observed_handoff_to": observed_target,
                "correct": is_correct,
            }
        )

    return {
        "decision_test_count": evaluated,
        "correct_handoff_decision_count": correct,
        "handoff_decision_accuracy": _round(correct / evaluated) if evaluated else None,
        "invalid_observed_decision_count": invalid_observations,
        "per_test": per_test,
    }


def compute_handoff_metrics(
    *,
    agent_roles: Dict[str, Any],
    handoff_matrix: Dict[str, Any],
    runtime_events: Sequence[Dict[str, Any]],
    test_results: Sequence[Dict[str, Any]],
    handoff_chain_limit: int = DEFAULT_HANDOFF_CHAIN_LIMIT,
    active_model_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    agents = _agent_ids(agent_roles)
    agent_refs = _agent_target_refs(agent_roles)
    matrix_pairs = _handoff_pairs(handoff_matrix)
    matrix_entries = _handoff_entries_by_pair(handoff_matrix)
    all_declared_pairs = agent_refs + matrix_pairs

    invalid_agent_refs = [pair for pair in agent_refs if not _valid_pair(pair, agents)]
    invalid_matrix_pairs = [pair for pair in matrix_pairs if not _valid_pair(pair, agents)]
    self_refs = [pair for pair in all_declared_pairs if pair[0] and pair[0] == pair[1]]
    agent_ref_set = set(agent_refs)
    matrix_pair_set = set(matrix_pairs)
    missing_matrix_pairs = sorted(agent_ref_set - matrix_pair_set)
    extra_matrix_pairs = sorted(matrix_pair_set - agent_ref_set)

    for pair in invalid_agent_refs:
        errors.append(f"Agent handoff target is invalid: {pair[0]}->{pair[1]}.")
    for pair in invalid_matrix_pairs:
        errors.append(f"Handoff matrix pair is invalid: {pair[0]}->{pair[1]}.")
    for pair in missing_matrix_pairs:
        errors.append(f"Agent handoff target is not represented in handoff_matrix: {pair[0]}->{pair[1]}.")
    for pair in extra_matrix_pairs:
        errors.append(f"Handoff matrix pair is not represented in agent handoff_targets: {pair[0]}->{pair[1]}.")

    for pair, entry in matrix_entries.items():
        if not str(entry.get("condition") or "").strip():
            errors.append(f"Handoff condition is empty: {pair[0]}->{pair[1]}.")
        if not str(entry.get("reason") or "").strip():
            errors.append(f"Handoff reason is empty: {pair[0]}->{pair[1]}.")

    current_runtime_events, historical_runtime_event_count = _runtime_events_for_active_model(
        runtime_events,
        active_model_sha256=active_model_sha256,
    )
    observed_handoff_events = [
        event
        for event in current_runtime_events
        if event.get("event_type")
        in {"backend_handoff_completed", "unity_handoff_received", "unity_handoff_arrived"}
    ]
    observed_pairs = [_metadata_pair(event) for event in observed_handoff_events]
    observed_pairs = [pair for pair in observed_pairs if pair is not None]
    invalid_observed_pairs = [pair for pair in observed_pairs if pair not in matrix_pair_set or not _valid_pair(pair, agents)]
    invalid_handoff_runtime_action_events = [
        str(event.get("event_id") or "<unknown>")
        for event in observed_handoff_events
        if event.get("event_type") == "backend_handoff_completed"
        and not str(event.get("runtime_action_id") or "").endswith("-BACKEND-CHAT-HANDOFF")
    ]
    invalid_handoff_runtime_binding_events = [
        str(event.get("event_id") or "<unknown>")
        for event in observed_handoff_events
        if event.get("event_type") == "backend_handoff_completed"
        and "HANDOFF-TO-RESPONSIBLE-AGENT" not in str(event.get("runtime_binding_id") or "")
    ]

    handoffs_by_session: Dict[str, int] = {}
    for event in observed_handoff_events:
        session_id = str(event.get("session_id") or "unknown")
        handoffs_by_session[session_id] = handoffs_by_session.get(session_id, 0) + 1
    # Runtime logs do not currently carry a request id. This is therefore a conservative per-session upper bound.
    observed_max_handoffs_per_logged_session = max(handoffs_by_session.values(), default=0)

    decision = _evaluate_decision_tests(test_results)
    if decision["decision_test_count"] == 0:
        warnings.append("No handoff decision test results found yet; handoff_decision_accuracy is not evaluated.")

    declared_total = len(all_declared_pairs)
    valid_declared_total = sum(1 for pair in all_declared_pairs if _valid_pair(pair, agents))
    metrics = {
        "agent_count": len(agents),
        "declared_agent_handoff_target_count": len(agent_refs),
        "declared_matrix_handoff_count": len(matrix_pairs),
        "unique_handoff_pair_count": len(matrix_pair_set),
        "valid_agent_handoff_target_ratio": _round((len(agent_refs) - len(invalid_agent_refs)) / len(agent_refs)) if agent_refs else 1.0,
        "valid_handoff_matrix_ratio": _round((len(matrix_pairs) - len(invalid_matrix_pairs)) / len(matrix_pairs)) if matrix_pairs else 1.0,
        "valid_handoff_target_ratio": _round(valid_declared_total / declared_total) if declared_total else 1.0,
        "self_handoff_count": len(self_refs),
        "duplicate_agent_handoff_target_count": _duplicate_count(agent_refs),
        "duplicate_matrix_handoff_count": _duplicate_count(matrix_pairs),
        "missing_matrix_pair_count": len(missing_matrix_pairs),
        "extra_matrix_pair_count": len(extra_matrix_pairs),
        "handoff_chain_limit": handoff_chain_limit,
        "runtime_event_count": len(runtime_events),
        "current_model_runtime_event_count": len(current_runtime_events),
        "historical_runtime_event_count": historical_runtime_event_count,
        "active_model_sha256": str(active_model_sha256 or "").strip().upper() or None,
        "observed_handoff_event_count": len(observed_handoff_events),
        "observed_valid_handoff_event_count": len(observed_pairs) - len(invalid_observed_pairs),
        "observed_invalid_handoff_event_count": len(invalid_observed_pairs),
        "observed_invalid_handoff_runtime_action_event_count": len(invalid_handoff_runtime_action_events),
        "observed_invalid_handoff_runtime_binding_event_count": len(invalid_handoff_runtime_binding_events),
        "observed_max_handoffs_per_logged_session": observed_max_handoffs_per_logged_session,
        "runtime_chain_limit_evaluation": "per_request_not_evaluable_without_request_id",
        "decision_test_count": decision["decision_test_count"],
        "correct_handoff_decision_count": decision["correct_handoff_decision_count"],
        "handoff_decision_accuracy": decision["handoff_decision_accuracy"],
        "invalid_observed_decision_count": decision["invalid_observed_decision_count"],
    }
    if metrics["observed_invalid_handoff_event_count"]:
        errors.append("Observed runtime handoff event contains an invalid or undeclared handoff pair.")
    if invalid_handoff_runtime_action_events:
        errors.append(
            "Backend handoff events are not traceable to BACKEND-CHAT-HANDOFF RuntimeAction: "
            + ", ".join(invalid_handoff_runtime_action_events[:10])
        )
    if invalid_handoff_runtime_binding_events:
        errors.append(
            "Backend handoff events are not traceable to HANDOFF-TO-RESPONSIBLE-AGENT RuntimeBinding: "
            + ", ".join(invalid_handoff_runtime_binding_events[:10])
        )

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "invalid_agent_handoff_targets": [{"source": s, "target": t} for s, t in invalid_agent_refs],
        "invalid_matrix_handoffs": [{"source": s, "target": t} for s, t in invalid_matrix_pairs],
        "missing_matrix_pairs": [{"source": s, "target": t} for s, t in missing_matrix_pairs],
        "extra_matrix_pairs": [{"source": s, "target": t} for s, t in extra_matrix_pairs],
        "observed_invalid_handoff_pairs": [{"source": s, "target": t} for s, t in invalid_observed_pairs],
        "observed_invalid_handoff_runtime_action_events": invalid_handoff_runtime_action_events,
        "observed_invalid_handoff_runtime_binding_events": invalid_handoff_runtime_binding_events,
        "handoff_decision_tests": decision["per_test"],
    }


def run_handoff_metrics_for_case(case_dir: Path, *, config_path: Optional[Path] = None) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    handoff_path = case_dir / "intermediate" / "handoff_matrix.json"
    runtime_log_path = case_dir / "runtime_logs" / "events.jsonl"
    v2_model_path = case_dir / "roomcontract" / "roomcontract.v2.instance.json"
    validation_path = case_dir / "validation" / "handoff_metrics.json"
    test_results, test_paths = _load_test_results(case_dir)

    validation = compute_handoff_metrics(
        agent_roles=read_json(agent_roles_path),
        handoff_matrix=read_json(handoff_path),
        runtime_events=_load_jsonl(runtime_log_path),
        test_results=test_results,
        handoff_chain_limit=_read_chain_limit(config_path),
        active_model_sha256=_sha256_file(v2_model_path),
    )
    write_json(validation_path, validation)
    update_manifest(
        case_dir,
        stage_id="handoff_metrics",
        status="success" if validation["status"] == "valid" else "failed",
        input_paths=[agent_roles_path, handoff_path, runtime_log_path, v2_model_path, *test_paths],
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


def run_handoff_metrics_for_cases(
    case_dirs: Iterable[Path],
    *,
    config_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    return [run_handoff_metrics_for_case(case_dir, config_path=config_path) for case_dir in case_dirs]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compute Interactive Agents handoff metrics.")
    parser.add_argument("--case-dir", type=Path, action="append")
    parser.add_argument("--case-root", type=Path)
    parser.add_argument("--config-path", type=Path)
    args = parser.parse_args(argv)
    case_dirs = args.case_dir or []
    if args.case_root:
        case_dirs.extend(sorted(path for path in args.case_root.iterdir() if path.is_dir()))
    if not case_dirs:
        parser.error("Pass --case-dir or --case-root.")
    results = run_handoff_metrics_for_cases(case_dirs, config_path=args.config_path)
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
