from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..agent_placement import MIN_AGENT_DISTANCE, _inside_bounds, _inside_obstacle, _minimum_agent_distance, _object_bounds
from ..common import read_json, update_manifest, write_json
from ..rdl_ingestion import is_structural_object


Point = Tuple[float, float]


def _distance_xz(left: Point, right: Point) -> float:
    return math.sqrt((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 6)


def _position_xz(payload: Dict[str, Any], key: str = "position") -> Point:
    value = payload.get(key) or {}
    return (float(value.get("x", 0.0)), float(value.get("z", 0.0)))


def _target_xz(placement: Dict[str, Any]) -> Optional[Point]:
    target = placement.get("target_xz") or {}
    if "x" not in target or "z" not in target:
        return None
    return (float(target.get("x", 0.0)), float(target.get("z", 0.0)))


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _max(values: Sequence[float]) -> Optional[float]:
    return max(values) if values else None


def _object_lookup(normalized_scene: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(obj.get("object_id")): obj
        for obj in normalized_scene.get("objects") or []
        if isinstance(obj, dict) and obj.get("object_id")
    }


def _object_center(obj: Dict[str, Any]) -> Point:
    position = obj.get("position") or {}
    return (float(position.get("x", 0.0)), float(position.get("z", 0.0)))


def _zone_centroids(scene_semantics: Dict[str, Any]) -> Dict[str, Point]:
    zones: Dict[str, Point] = {}
    for zone in scene_semantics.get("semantic_zones") or []:
        if not isinstance(zone, dict) or not zone.get("zone_id"):
            continue
        centroid = zone.get("centroid_xz") or {}
        zones[str(zone["zone_id"])] = (float(centroid.get("x", 0.0)), float(centroid.get("z", 0.0)))
    return zones


def _group_centroids_for_agent(agent: Dict[str, Any], object_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Point]:
    grouped: Dict[str, List[Point]] = {}
    for object_id in agent.get("grounded_object_ids") or []:
        obj = object_lookup.get(str(object_id))
        if not obj:
            continue
        group = str(obj.get("group") or "")
        if not group:
            continue
        grouped.setdefault(group, []).append(_object_center(obj))
    centroids: Dict[str, Point] = {}
    for group, points in grouped.items():
        centroids[group] = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    return centroids


def _distance_summary(position: Point, targets: Iterable[Point]) -> Dict[str, Any]:
    distances = [_distance_xz(position, target) for target in targets]
    return {
        "count": len(distances),
        "nearest": _round(min(distances) if distances else None),
        "average": _round(_mean(distances)),
        "maximum": _round(_max(distances)),
    }


def _valid_forward(forward: Dict[str, Any]) -> bool:
    return abs(float(forward.get("x", 0.0))) + abs(float(forward.get("z", 0.0))) >= 0.1


def _agent_role_by_id(agent_roles: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(agent.get("id")): agent
        for agent in agent_roles.get("agents") or []
        if isinstance(agent, dict) and agent.get("id")
    }


def compute_placement_metrics(
    *,
    placements_payload: Dict[str, Any],
    normalized_scene: Dict[str, Any],
    scene_semantics: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    bounds = placements_payload.get("room_bounds") or normalized_scene.get("room_bounds") or {
        "min_x": -5.0,
        "max_x": 5.0,
        "min_z": -5.0,
        "max_z": 5.0,
    }
    obstacles = [
        _object_bounds(obj)
        for obj in normalized_scene.get("objects") or []
        if isinstance(obj, dict) and not is_structural_object(obj)
    ]
    placements = [item for item in placements_payload.get("agent_placements") or [] if isinstance(item, dict)]
    role_by_id = _agent_role_by_id(agent_roles)
    object_lookup = _object_lookup(normalized_scene)
    zone_centroids = _zone_centroids(scene_semantics)

    errors: List[str] = []
    warnings: List[str] = []
    per_agent: List[Dict[str, Any]] = []
    valid_position_count = 0
    out_of_bounds_count = 0
    obstacle_overlap_count = 0
    target_distances: List[float] = []
    nearest_group_distances: List[float] = []
    nearest_zone_distances: List[float] = []

    for placement in placements:
        agent_id = str(placement.get("id") or "")
        role = role_by_id.get(agent_id, {})
        position = _position_xz(placement)
        forward = placement.get("forward") or {}
        inside_bounds = _inside_bounds(position[0], position[1], bounds)
        overlaps_obstacle = _inside_obstacle(position[0], position[1], obstacles)
        has_valid_forward = _valid_forward(forward)
        is_valid_position = bool(agent_id in role_by_id and inside_bounds and not overlaps_obstacle and has_valid_forward)

        if is_valid_position:
            valid_position_count += 1
        if not inside_bounds:
            out_of_bounds_count += 1
            errors.append(f"Agent {agent_id} is outside room bounds.")
        if overlaps_obstacle:
            obstacle_overlap_count += 1
            errors.append(f"Agent {agent_id} overlaps an obstacle footprint.")
        if not has_valid_forward:
            errors.append(f"Agent {agent_id} has an invalid forward vector.")
        if agent_id not in role_by_id:
            errors.append(f"Placement references unknown agent: {agent_id}.")

        target = _target_xz(placement)
        target_distance = _distance_xz(position, target) if target is not None else None
        if target_distance is not None:
            target_distances.append(target_distance)

        group_centroids = _group_centroids_for_agent(role, object_lookup)
        group_summary = _distance_summary(position, group_centroids.values())
        if group_summary["nearest"] is not None:
            nearest_group_distances.append(float(group_summary["nearest"]))

        zone_targets = [
            zone_centroids[zone_id]
            for zone_id in role.get("responsible_zone_ids") or []
            if zone_id in zone_centroids
        ]
        zone_summary = _distance_summary(position, zone_targets)
        if zone_summary["nearest"] is not None:
            nearest_zone_distances.append(float(zone_summary["nearest"]))

        if not group_centroids:
            warnings.append(f"Agent {agent_id} has no resolvable grounded object-group centroid.")
        if role.get("responsible_zone_ids") and not zone_targets:
            warnings.append(f"Agent {agent_id} has responsible_zone_ids but no matching semantic-zone centroid.")

        per_agent.append(
            {
                "agent_id": agent_id,
                "valid_position": is_valid_position,
                "position": {"x": _round(position[0]), "z": _round(position[1])},
                "inside_room_bounds": inside_bounds,
                "overlaps_obstacle": overlaps_obstacle,
                "valid_forward": has_valid_forward,
                "distance_to_target_xz": _round(target_distance),
                "responsible_group_count": len(group_centroids),
                "distance_to_responsible_object_groups": group_summary,
                "responsible_zone_count": len(zone_targets),
                "distance_to_responsible_zones": zone_summary,
            }
        )

    expected_agent_ids = set(role_by_id)
    placed_agent_ids = {str(placement.get("id") or "") for placement in placements}
    missing_agents = sorted(expected_agent_ids - placed_agent_ids)
    for agent_id in missing_agents:
        errors.append(f"Missing placement for agent {agent_id}.")

    min_distance = _minimum_agent_distance(placements)
    if min_distance is not None and min_distance < MIN_AGENT_DISTANCE:
        errors.append(f"Minimum agent distance is too small: {min_distance:.3f}.")

    agent_count = len(expected_agent_ids)
    valid_position_ratio = valid_position_count / agent_count if agent_count else 1.0
    metrics = {
        "agent_count": agent_count,
        "placement_count": len(placements),
        "valid_position_count": valid_position_count,
        "valid_position_ratio": round(valid_position_ratio, 6),
        "out_of_bounds_count": out_of_bounds_count,
        "obstacle_overlap_count": obstacle_overlap_count,
        "minimum_agent_distance": _round(min_distance),
        "minimum_agent_distance_threshold": MIN_AGENT_DISTANCE,
        "average_distance_to_target_xz": _round(_mean(target_distances)),
        "max_distance_to_target_xz": _round(_max(target_distances)),
        "average_nearest_responsible_group_distance": _round(_mean(nearest_group_distances)),
        "max_nearest_responsible_group_distance": _round(_max(nearest_group_distances)),
        "average_nearest_responsible_zone_distance": _round(_mean(nearest_zone_distances)),
        "max_nearest_responsible_zone_distance": _round(_max(nearest_zone_distances)),
    }
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "per_agent": per_agent,
    }


def run_placement_metrics_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    semantics_path = case_dir / "intermediate" / "scene_semantics.json"
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    placements_path = case_dir / "intermediate" / "agent_placements.json"
    validation_path = case_dir / "validation" / "placement_metrics.json"

    validation = compute_placement_metrics(
        placements_payload=read_json(placements_path),
        normalized_scene=read_json(normalized_path),
        scene_semantics=read_json(semantics_path),
        agent_roles=read_json(agent_roles_path),
    )
    write_json(validation_path, validation)
    update_manifest(
        case_dir,
        stage_id="placement_metrics",
        status="success" if validation["status"] == "valid" else "failed",
        input_paths=[normalized_path, semantics_path, agent_roles_path, placements_path],
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


def run_placement_metrics_for_cases(case_dirs: Iterable[Path]) -> List[Dict[str, Any]]:
    return [run_placement_metrics_for_case(case_dir) for case_dir in case_dirs]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compute Interactive Agents placement metrics.")
    parser.add_argument("--case-dir", type=Path, action="append")
    parser.add_argument("--case-root", type=Path)
    args = parser.parse_args(argv)
    case_dirs = args.case_dir or []
    if args.case_root:
        case_dirs.extend(sorted(path for path in args.case_root.iterdir() if path.is_dir()))
    if not case_dirs:
        parser.error("Pass --case-dir or --case-root.")
    results = run_placement_metrics_for_cases(case_dirs)
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
