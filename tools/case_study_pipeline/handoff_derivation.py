from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .agent_roles import validate_agent_roles
from .common import read_json, update_manifest, write_json


Pair = Tuple[str, str]


def _unique(seq: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for item in seq:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _agents_by_id(agent_roles: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(agent.get("id")): dict(agent)
        for agent in agent_roles.get("agents") or []
        if isinstance(agent, Mapping) and str(agent.get("id") or "").strip()
    }


def _functional_agents_by_source(instance: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(agent.get("source_agent_id")): dict(agent)
        for agent in instance.get("agents") or []
        if isinstance(agent, Mapping) and str(agent.get("source_agent_id") or "").strip()
    }


def _matrix_entries_by_pair(handoff_matrix: Mapping[str, Any]) -> Dict[Pair, Dict[str, Any]]:
    entries: Dict[Pair, Dict[str, Any]] = {}
    for entry in handoff_matrix.get("handoffs") or []:
        if not isinstance(entry, Mapping):
            continue
        source = str(entry.get("source_agent_id") or "").strip()
        target = str(entry.get("target_agent_id") or "").strip()
        if source and target and (source, target) not in entries:
            entries[(source, target)] = dict(entry)
    return entries


def _append_pair(pairs: List[Pair], source: str, target: str, agent_ids: Set[str]) -> None:
    if source and target and source in agent_ids and target in agent_ids and source != target and (source, target) not in pairs:
        pairs.append((source, target))


def _declared_pairs(agent_roles: Mapping[str, Any], instance: Mapping[str, Any], existing_matrix: Mapping[str, Any]) -> List[Pair]:
    agents = _agents_by_id(agent_roles)
    agent_ids = set(agents)
    pairs: List[Pair] = []
    for agent_id, agent in agents.items():
        for target in agent.get("handoff_targets") or []:
            _append_pair(pairs, agent_id, str(target or "").strip(), agent_ids)
    for source, functional_agent in _functional_agents_by_source(instance).items():
        for target in functional_agent.get("handoff_targets") or []:
            _append_pair(pairs, source, str(target or "").strip(), agent_ids)
    for source, target in _matrix_entries_by_pair(existing_matrix):
        _append_pair(pairs, source, target, agent_ids)
    # Spatial object selection can occur while the visitor is speaking with any
    # agent. Every agent therefore needs a direct modeled edge to every other
    # specialist; a merely transitive path cannot drive the single visible
    # proximity handoff/route used by the runtime.
    for source in agents:
        for target in agents:
            _append_pair(pairs, source, target, agent_ids)
    return pairs


def _fallback_pairs(agent_roles: Mapping[str, Any]) -> List[Pair]:
    agents = _agents_by_id(agent_roles)
    pairs: List[Pair] = []
    for source_id, source in agents.items():
        source_zones = set(source.get("responsible_zone_ids") or [])
        source_tags = set(source.get("knowledge_tags") or [])
        candidates: List[Tuple[int, str]] = []
        for target_id, target in agents.items():
            if target_id == source_id:
                continue
            target_zones = set(target.get("responsible_zone_ids") or [])
            target_tags = set(target.get("knowledge_tags") or [])
            target_objects = set(target.get("grounded_object_ids") or [])
            score = len(target_tags - source_tags) + len(target_zones - source_zones) * 2 + min(len(target_objects), 5)
            if target_zones and source_zones and target_zones.isdisjoint(source_zones):
                score += 2
            candidates.append((score, target_id))
        for _, target_id in sorted(candidates, key=lambda item: (-item[0], item[1]))[:2]:
            _append_pair(pairs, source_id, target_id, set(agents))
    return pairs


def _agent_label(agent: Mapping[str, Any], agent_id: str) -> str:
    return str(agent.get("display_name") or agent_id).strip() or agent_id


def _compact_terms(values: Iterable[Any], *, limit: int = 4) -> str:
    terms = _unique(str(value) for value in values if str(value or "").strip())
    if not terms:
        return "its specialized responsibility"
    if len(terms) > limit:
        return ", ".join(terms[:limit]) + ", ..."
    return ", ".join(terms)


def _default_condition(source: Mapping[str, Any], target: Mapping[str, Any], target_id: str) -> str:
    target_terms = _compact_terms(
        [
            *(target.get("expertise") or []),
            *(target.get("knowledge_tags") or []),
            *(target.get("responsible_zone_ids") or []),
        ],
        limit=5,
    )
    return (
        "Visitor question concerns "
        f"{target_terms}; the current agent should hand off to {_agent_label(target, target_id)}."
    )


def _default_reason(target: Mapping[str, Any], target_id: str, functional_target: Optional[Mapping[str, Any]]) -> str:
    capability_hint = ""
    if functional_target:
        capabilities = [str(item) for item in functional_target.get("providedCapabilityIds") or []]
        if any("HANDOFF-TO-RESPONSIBLE-AGENT" in item for item in capabilities):
            capability_hint = " and is represented in RoomContract as a handoff-capable responsible agent"
    target_terms = _compact_terms([*(target.get("expertise") or []), *(target.get("knowledge_tags") or [])], limit=5)
    return f"{_agent_label(target, target_id)} owns {target_terms}{capability_hint}."


def derive_handoff_artifacts(
    *,
    agent_roles: Dict[str, Any],
    roomcontract_instance: Dict[str, Any],
    existing_handoff_matrix: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    existing_handoff_matrix = existing_handoff_matrix or {"handoffs": []}
    agents = _agents_by_id(agent_roles)
    functional_agents = _functional_agents_by_source(roomcontract_instance)
    existing_entries = _matrix_entries_by_pair(existing_handoff_matrix)
    pair_order = _declared_pairs(agent_roles, roomcontract_instance, existing_handoff_matrix)
    if not pair_order:
        pair_order = _fallback_pairs(agent_roles)

    pair_set = set(pair_order)
    handoffs: List[Dict[str, Any]] = []
    for source_id, target_id in pair_order:
        source = agents[source_id]
        target = agents[target_id]
        existing = existing_entries.get((source_id, target_id), {})
        condition = str(existing.get("condition") or "").strip() or _default_condition(source, target, target_id)
        reason = str(existing.get("reason") or "").strip() or _default_reason(
            target,
            target_id,
            functional_agents.get(target_id),
        )
        handoffs.append(
            {
                "source_agent_id": source_id,
                "target_agent_id": target_id,
                "condition": condition,
                "reason": reason,
            }
        )

    updated_roles = dict(agent_roles)
    updated_agents: List[Dict[str, Any]] = []
    for agent in agent_roles.get("agents") or []:
        if not isinstance(agent, Mapping):
            continue
        updated_agent = dict(agent)
        source_id = str(updated_agent.get("id") or "").strip()
        updated_agent["handoff_targets"] = [target for source, target in pair_order if source == source_id]
        updated_agents.append(updated_agent)
    updated_roles["agents"] = updated_agents
    updated_roles["handoffs"] = handoffs

    updated_instance = dict(roomcontract_instance)
    updated_functional_agents: List[Dict[str, Any]] = []
    generated_id_by_source = {
        source: str(agent.get("id") or "")
        for source, agent in functional_agents.items()
    }
    for agent in roomcontract_instance.get("agents") or []:
        if not isinstance(agent, Mapping):
            continue
        updated_agent = dict(agent)
        source_id = str(updated_agent.get("source_agent_id") or "").strip()
        targets = [target for source, target in pair_order if source == source_id]
        updated_agent["handoff_targets"] = targets
        updated_agent["handoffTargetAgentIds"] = [
            generated_id_by_source[target]
            for target in targets
            if generated_id_by_source.get(target)
        ]
        updated_functional_agents.append(updated_agent)
    updated_instance["agents"] = updated_functional_agents

    return {
        "agent_roles": updated_roles,
        "roomcontract_instance": updated_instance,
        "handoff_matrix": {"handoffs": handoffs},
        "metrics": {
            "agent_count": len(agents),
            "handoff_pair_count": len(pair_order),
            "source_agent_with_handoff_count": len({source for source, _ in pair_order}),
            "fallback_used": not bool(_declared_pairs(agent_roles, roomcontract_instance, existing_handoff_matrix)),
            "unique_pair_count": len(pair_set),
        },
    }


def validate_handoff_derivation(agent_roles: Dict[str, Any], handoff_matrix: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    agents = _agents_by_id(agent_roles)
    agent_ids = set(agents)
    target_pairs = {
        (agent_id, str(target or "").strip())
        for agent_id, agent in agents.items()
        for target in agent.get("handoff_targets") or []
        if str(target or "").strip()
    }
    matrix_pairs = set(_matrix_entries_by_pair(handoff_matrix))
    expected_pairs = {
        (source, target)
        for source in agent_ids
        for target in agent_ids
        if source != target
    }
    for source, target in sorted(target_pairs | matrix_pairs):
        if source == target:
            errors.append(f"Self-handoff is not allowed: {source}->{target}.")
        if source not in agent_ids:
            errors.append(f"Handoff source does not exist: {source}->{target}.")
        if target not in agent_ids:
            errors.append(f"Handoff target does not exist: {source}->{target}.")
    for source, target in sorted(target_pairs - matrix_pairs):
        errors.append(f"Agent handoff target is missing in handoff_matrix: {source}->{target}.")
    for source, target in sorted(matrix_pairs - target_pairs):
        errors.append(f"Handoff matrix pair is missing in agent handoff_targets: {source}->{target}.")
    for source, target in sorted(expected_pairs - target_pairs):
        errors.append(f"Direct agent handoff is missing: {source}->{target}.")
    for source, target in sorted(expected_pairs - matrix_pairs):
        errors.append(f"Direct handoff matrix entry is missing: {source}->{target}.")
    for entry in handoff_matrix.get("handoffs") or []:
        if not isinstance(entry, Mapping):
            errors.append("Handoff entry is not an object.")
            continue
        if not str(entry.get("condition") or "").strip():
            errors.append(f"Handoff condition is empty: {entry.get('source_agent_id')}->{entry.get('target_agent_id')}.")
        if not str(entry.get("reason") or "").strip():
            errors.append(f"Handoff reason is empty: {entry.get('source_agent_id')}->{entry.get('target_agent_id')}.")
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": [],
        "metrics": {
            "agent_count": len(agent_ids),
            "agent_handoff_target_count": len(target_pairs),
            "matrix_handoff_count": len(matrix_pairs),
            "expected_direct_handoff_count": len(expected_pairs),
            "missing_direct_handoff_count": len(expected_pairs - matrix_pairs),
            "source_agent_with_handoff_count": len({source for source, _ in matrix_pairs}),
            "self_handoff_count": sum(1 for source, target in matrix_pairs if source == target),
        },
    }


def run_handoff_derivation_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    semantics_path = case_dir / "intermediate" / "scene_semantics.json"
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    roomcontract_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    handoff_path = case_dir / "intermediate" / "handoff_matrix.json"
    validation_path = case_dir / "validation" / "handoff_derivation_validation.json"

    agent_roles = read_json(agent_roles_path)
    roomcontract_instance = read_json(roomcontract_path)
    existing_handoff_matrix = read_json(handoff_path) if handoff_path.exists() else {"handoffs": []}
    derived = derive_handoff_artifacts(
        agent_roles=agent_roles,
        roomcontract_instance=roomcontract_instance,
        existing_handoff_matrix=existing_handoff_matrix,
    )
    role_validation = validate_agent_roles(
        derived["agent_roles"],
        scene_semantics=read_json(semantics_path),
        normalized_scene=read_json(normalized_path),
    )
    derivation_validation = validate_handoff_derivation(derived["agent_roles"], derived["handoff_matrix"])
    errors = [*role_validation.get("errors", []), *derivation_validation.get("errors", [])]
    warnings = [*role_validation.get("warnings", []), *derivation_validation.get("warnings", [])]
    validation = {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            **derived["metrics"],
            "role_validation_status": role_validation.get("status"),
            "derivation_validation_status": derivation_validation.get("status"),
        },
        "role_validation": role_validation,
        "derivation_validation": derivation_validation,
    }

    write_json(agent_roles_path, derived["agent_roles"])
    write_json(roomcontract_path, derived["roomcontract_instance"])
    write_json(handoff_path, derived["handoff_matrix"])
    write_json(validation_path, validation)
    update_manifest(
        case_dir,
        stage_id="handoff_derivation",
        status="success" if validation["status"] == "valid" else "failed",
        input_paths=[agent_roles_path, roomcontract_path, handoff_path],
        output_paths=[agent_roles_path, roomcontract_path, handoff_path, validation_path],
        errors=validation["errors"],
        warnings=validation["warnings"],
        metadata=validation["metrics"],
    )
    return {
        "case_id": case_dir.name,
        "status": "success" if validation["status"] == "valid" else "failed",
        "validation": validation,
        "handoff_matrix_path": str(handoff_path),
        "validation_path": str(validation_path),
    }
