from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from ..common import read_json, update_manifest, write_json
from ..project_materializer import DEFAULT_BACKEND_ROOT


STRUCTURAL_GROUP_NAMES = {
    "ceiling",
    "ceilings",
    "floor",
    "floor_markings",
    "light",
    "lights",
    "lighting",
    "overhead_lights",
    "structural",
    "wall",
    "walls",
}


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 6)


def _coverage_metric(
    *,
    metric_id: str,
    description: str,
    numerator: int,
    denominator: int,
    covered_ids: Iterable[str],
    uncovered_ids: Iterable[str],
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "metric_id": metric_id,
        "description": description,
        "numerator": numerator,
        "denominator": denominator,
        "coverage": _ratio(numerator, denominator),
        "covered_ids": sorted({item for item in covered_ids if item}),
        "uncovered_ids": sorted({item for item in uncovered_ids if item}),
        "details": details or {},
    }


def _requirements(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        item
        for item in (instance.get("requirementsModel") or {}).get("requirements") or []
        if isinstance(item, dict)
    ]


def _use_cases(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        item
        for item in (instance.get("requirementsModel") or {}).get("useCases") or []
        if isinstance(item, dict)
    ]


def _scenario_steps(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for use_case in _use_cases(instance):
        for scenario in use_case.get("scenarios") or []:
            if not isinstance(scenario, dict):
                continue
            for step in scenario.get("steps") or []:
                if isinstance(step, dict):
                    steps.append(step)
    return steps


def _runtime_actions(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for binding in instance.get("runtimeBindings") or []:
        if not isinstance(binding, dict):
            continue
        for action in binding.get("runtimeActions") or []:
            if isinstance(action, dict):
                item = dict(action)
                item["_runtime_binding_id"] = binding.get("id")
                item["_capability_id"] = binding.get("capability_id")
                actions.append(item)
    return actions


def _runtime_event_action_ids(path: Path) -> Set[str]:
    action_ids: Set[str] = set()
    if not path.exists():
        return action_ids
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            action_id = str(event.get("runtime_action_id") or "").strip()
            if action_id:
                action_ids.add(action_id)
    return action_ids


def _requirement_to_validation(instance: Dict[str, Any]) -> Dict[str, Any]:
    requirements = {str(item.get("id")) for item in _requirements(instance) if item.get("id")}
    validation_cases = [item for item in instance.get("validationCases") or [] if isinstance(item, dict)]
    covered: Set[str] = set()
    by_requirement: Dict[str, List[str]] = {req_id: [] for req_id in requirements}
    for validation_case in validation_cases:
        validation_id = str(validation_case.get("id") or "")
        for req_id in validation_case.get("verifies_requirement_ids") or []:
            req_id = str(req_id)
            if req_id in requirements:
                covered.add(req_id)
                by_requirement.setdefault(req_id, []).append(validation_id)
    return _coverage_metric(
        metric_id="requirement_to_validation_coverage",
        description="Share of Requirements referenced by at least one ValidationCase.",
        numerator=len(covered),
        denominator=len(requirements),
        covered_ids=covered,
        uncovered_ids=requirements - covered,
        details={"validation_cases_by_requirement": by_requirement},
    )


def _scenario_step_to_capability(instance: Dict[str, Any]) -> Dict[str, Any]:
    steps = _scenario_steps(instance)
    capability_uses = {
        str(item.get("id")): item
        for item in instance.get("capabilityUses") or []
        if isinstance(item, dict) and item.get("id")
    }
    covered: Set[str] = set()
    uncovered: Set[str] = set()
    invalid_refs: Dict[str, List[str]] = {}
    uncovered_kinds: Dict[str, str] = {}
    for step in steps:
        step_id = str(step.get("id") or "")
        refs = [str(item) for item in step.get("capabilityUseIds") or [] if item]
        valid_refs = [ref for ref in refs if ref in capability_uses]
        invalid = [ref for ref in refs if ref not in capability_uses]
        if valid_refs:
            covered.add(step_id)
        else:
            uncovered.add(step_id)
            uncovered_kinds[step_id] = str(step.get("kind") or "")
        if invalid:
            invalid_refs[step_id] = invalid
    return _coverage_metric(
        metric_id="scenario_step_to_capability_coverage",
        description="Share of ScenarioSteps operationalized by at least one existing CapabilityUse.",
        numerator=len(covered),
        denominator=len(steps),
        covered_ids=covered,
        uncovered_ids=uncovered,
        details={"invalid_capability_use_refs": invalid_refs, "uncovered_step_kinds": uncovered_kinds},
    )


def _capability_to_runtime_binding(instance: Dict[str, Any]) -> Dict[str, Any]:
    capabilities = {
        str(item.get("id"))
        for item in instance.get("capabilities") or []
        if isinstance(item, dict) and item.get("id")
    }
    covered = {
        str(item.get("capability_id"))
        for item in instance.get("runtimeBindings") or []
        if isinstance(item, dict) and item.get("capability_id") in capabilities
    }
    return _coverage_metric(
        metric_id="capability_to_runtime_binding_coverage",
        description="Share of Capabilities with at least one RuntimeBinding.",
        numerator=len(covered),
        denominator=len(capabilities),
        covered_ids=covered,
        uncovered_ids=capabilities - covered,
    )


def _runtime_action_to_log(instance: Dict[str, Any], runtime_log_path: Path) -> Dict[str, Any]:
    actions = _runtime_actions(instance)
    action_ids = {str(item.get("id")) for item in actions if item.get("id")}
    logged_action_ids = _runtime_event_action_ids(runtime_log_path)
    covered = action_ids & logged_action_ids
    return _coverage_metric(
        metric_id="runtime_action_to_log_coverage",
        description="Share of RuntimeActions observed in runtime_logs/events.jsonl.",
        numerator=len(covered),
        denominator=len(action_ids),
        covered_ids=covered,
        uncovered_ids=action_ids - covered,
        details={
            "runtime_log_path": str(runtime_log_path),
            "logged_runtime_action_ids": sorted(logged_action_ids),
        },
    )


def _agent_to_knowledge_tag(agent_roles: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
    knowledge_tags = {
        str(item.get("tag"))
        for item in knowledge.get("knowledge_entries") or []
        if isinstance(item, dict) and item.get("tag")
    }
    agents = [item for item in agent_roles.get("agents") or [] if isinstance(item, dict)]
    covered_agents: Set[str] = set()
    uncovered_agents: Set[str] = set()
    missing_tags_by_agent: Dict[str, List[str]] = {}
    for agent in agents:
        agent_id = str(agent.get("id") or "")
        tags = {str(item) for item in agent.get("knowledge_tags") or [] if item}
        missing = sorted(tags - knowledge_tags)
        if tags and not missing:
            covered_agents.add(agent_id)
        else:
            uncovered_agents.add(agent_id)
            missing_tags_by_agent[agent_id] = missing if missing else ["<no knowledge_tags>"]
    return _coverage_metric(
        metric_id="agent_to_knowledge_tag_coverage",
        description="Share of Agents whose knowledge_tags are fully backed by generated knowledge entries.",
        numerator=len(covered_agents),
        denominator=len(agents),
        covered_ids=covered_agents,
        uncovered_ids=uncovered_agents,
        details={
            "available_knowledge_tags": sorted(knowledge_tags),
            "missing_tags_by_agent": missing_tags_by_agent,
        },
    )


def _object_group_to_agent_role(normalized_scene: Dict[str, Any], agent_roles: Dict[str, Any]) -> Dict[str, Any]:
    objects = [item for item in normalized_scene.get("objects") or [] if isinstance(item, dict)]
    object_to_group = {
        str(item.get("object_id")): str(item.get("group") or "")
        for item in objects
        if item.get("object_id") and item.get("group")
    }
    all_groups = {group for group in object_to_group.values() if group}
    semantic_groups = {
        group
        for group in all_groups
        if group.strip().lower() not in STRUCTURAL_GROUP_NAMES
    }
    grounded_object_ids = {
        str(object_id)
        for agent in agent_roles.get("agents") or []
        if isinstance(agent, dict)
        for object_id in agent.get("grounded_object_ids") or []
        if object_id
    }
    covered_groups = {
        object_to_group[object_id]
        for object_id in grounded_object_ids
        if object_id in object_to_group and object_to_group[object_id] in semantic_groups
    }
    grounded_objects_by_group: Dict[str, List[str]] = {group: [] for group in semantic_groups}
    for object_id in grounded_object_ids:
        group = object_to_group.get(object_id)
        if group in semantic_groups:
            grounded_objects_by_group.setdefault(group, []).append(object_id)
    return _coverage_metric(
        metric_id="object_group_to_agent_role_grounding",
        description="Share of semantic RDL object groups grounded by at least one AgentRole grounded_object_id.",
        numerator=len(covered_groups),
        denominator=len(semantic_groups),
        covered_ids=covered_groups,
        uncovered_ids=semantic_groups - covered_groups,
        details={
            "all_object_groups": sorted(all_groups),
            "excluded_structural_groups": sorted(all_groups - semantic_groups),
            "grounded_objects_by_group": {key: sorted(value) for key, value in grounded_objects_by_group.items()},
        },
    )


def compute_traceability_metrics(
    *,
    instance: Dict[str, Any],
    normalized_scene: Dict[str, Any],
    agent_roles: Dict[str, Any],
    knowledge: Dict[str, Any],
    runtime_log_path: Path,
) -> Dict[str, Any]:
    metrics = [
        _requirement_to_validation(instance),
        _scenario_step_to_capability(instance),
        _capability_to_runtime_binding(instance),
        _runtime_action_to_log(instance, runtime_log_path),
        _agent_to_knowledge_tag(agent_roles, knowledge),
        _object_group_to_agent_role(normalized_scene, agent_roles),
    ]
    warnings: List[str] = []
    for metric in metrics:
        if metric["coverage"] < 1.0:
            warnings.append(
                f"{metric['metric_id']} coverage is {metric['coverage']} "
                f"({metric['numerator']}/{metric['denominator']})."
            )
    return {
        "status": "valid",
        "errors": [],
        "warnings": warnings,
        "metrics": {
            "metric_count": len(metrics),
            "full_coverage_metric_count": sum(1 for metric in metrics if metric["coverage"] >= 1.0),
            "partial_coverage_metric_count": sum(1 for metric in metrics if metric["coverage"] < 1.0),
            "average_coverage": round(sum(metric["coverage"] for metric in metrics) / len(metrics), 6),
        },
        "traceability_metrics": metrics,
    }


def run_traceability_metrics_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    instance_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    knowledge_path = case_dir / "intermediate" / "knowledge.generated.json"
    runtime_log_path = case_dir / "runtime_logs" / "events.jsonl"
    validation_path = case_dir / "validation" / "traceability_metrics.json"

    validation = compute_traceability_metrics(
        instance=read_json(instance_path),
        normalized_scene=read_json(normalized_path),
        agent_roles=read_json(agent_roles_path),
        knowledge=read_json(knowledge_path),
        runtime_log_path=runtime_log_path,
    )
    write_json(validation_path, validation)
    update_manifest(
        case_dir,
        stage_id="traceability_metrics",
        status="success",
        input_paths=[instance_path, normalized_path, agent_roles_path, knowledge_path, runtime_log_path],
        output_paths=[validation_path],
        errors=validation["errors"],
        warnings=validation["warnings"],
        metadata=validation["metrics"],
    )
    return {
        "case_id": case_dir.name,
        "status": "success",
        "validation": validation,
        "validation_path": str(validation_path),
    }


def run_traceability_metrics_for_cases(case_dirs: Iterable[Path]) -> List[Dict[str, Any]]:
    return [run_traceability_metrics_for_case(case_dir) for case_dir in case_dirs]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compute RoomContract case-study traceability metrics.")
    parser.add_argument("--case-dir", type=Path, action="append")
    parser.add_argument("--case-root", type=Path)
    args = parser.parse_args(argv)
    case_dirs = args.case_dir or []
    if args.case_root:
        case_dirs.extend(sorted(path for path in args.case_root.iterdir() if path.is_dir()))
    if not case_dirs:
        parser.error("Pass --case-dir or --case-root.")
    results = run_traceability_metrics_for_cases(case_dirs)
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
