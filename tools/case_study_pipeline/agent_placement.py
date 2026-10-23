from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from .common import read_json, update_manifest, write_json
from .rdl_ingestion import is_structural_object


# The placement is a floor-level deployment projection for a standing Unity
# avatar. Objects only act as obstacles when they intersect this horizontal
# slice. OBJECT_PADDING represents the avatar footprint and safety clearance.
FLOOR_SLICE_Y = 0.5
PLACEMENT_ARTIFACT_SCHEMA = "roomcontract_agent_placements"
PLACEMENT_ARTIFACT_SCHEMA_VERSION = "2.0"
PLACEMENT_ALGORITHM_VERSION = "2.0.0"
PLACEMENT_ORIGINS = frozenset({"deterministic", "wizard_manual"})
PLACEMENT_FLOOR_TOLERANCE = 1e-4
MIN_AGENT_DISTANCE = 1.0
OBJECT_PADDING = 0.45
WALL_MARGIN = 0.45

MIN_OBJECT_DIMENSION = 0.2
POSITION_DECIMALS = 3
SEARCH_RADIAL_STEP = 0.25
SEARCH_ARC_STEP = 0.2
FORWARD_NORMALIZATION_TOLERANCE = 1e-3
FLOAT_EPSILON = 1e-9

Point = Tuple[float, float]
LegacyBounds = Tuple[float, float, float, float]


class AgentPlacementError(ValueError):
    """Raised when the deterministic placement constraints are infeasible."""


def placement_artifact_sha256(payload: Mapping[str, Any]) -> str:
    """Return a formatting-independent SHA-256 for one placement artifact.

    The hash is over canonical parsed JSON, not over pretty-print whitespace.
    ``allow_nan=False`` deliberately rejects values that JSON permits only as a
    non-standard extension.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("Placement artifact must be a JSON object.")
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Placement artifact is not canonical JSON: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _ObstacleFootprint:
    """A floor-sliced, yaw-rotated rectangle with a legacy AABB view.

    Iteration intentionally yields the former four-value bounds tuple. This
    keeps private-but-imported callers such as ``placement_metrics`` working,
    while ``_inside_obstacle`` can use the exact oriented footprint.
    """

    min_x: float
    max_x: float
    min_z: float
    max_z: float
    center_x: float
    center_z: float
    half_width: float
    half_depth: float
    cos_yaw: float
    sin_yaw: float
    intersects_floor_slice: bool

    def __iter__(self) -> Iterator[float]:
        yield self.min_x
        yield self.max_x
        yield self.min_z
        yield self.max_z


Obstacle = _ObstacleFootprint | LegacyBounds


def _finite_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _json_number(value: Any) -> bool:
    """Return true only for finite JSON number values, excluding booleans."""

    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _finite_point(payload: Any, *, key_x: str = "x", key_z: str = "z") -> Optional[Point]:
    if not isinstance(payload, dict):
        return None
    x = _finite_float(payload.get(key_x))
    z = _finite_float(payload.get(key_z))
    if x is None or z is None:
        return None
    return (x, z)


def _distance_xz(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _normalize_vec_xz(dx: float, dz: float) -> Dict[str, float]:
    if not math.isfinite(dx) or not math.isfinite(dz):
        return {"x": 0.0, "y": 0.0, "z": 1.0}
    length = math.hypot(dx, dz)
    if length < FLOAT_EPSILON:
        return {"x": 0.0, "y": 0.0, "z": 1.0}
    # Do not round the components independently: doing so makes a supposedly
    # normalized vector measurably shorter or longer than one.
    return {"x": dx / length, "y": 0.0, "z": dz / length}


def _canonical_room_bounds(raw_bounds: Any) -> Dict[str, float]:
    if not isinstance(raw_bounds, dict):
        raise AgentPlacementError("room_bounds are missing or are not an object.")
    values: Dict[str, float] = {}
    for key in ("min_x", "max_x", "min_z", "max_z"):
        raw_value = raw_bounds.get(key)
        if not _json_number(raw_value):
            raise AgentPlacementError(f"room_bounds.{key} must be a finite number.")
        values[key] = float(raw_value)
    if values["min_x"] >= values["max_x"] or values["min_z"] >= values["max_z"]:
        raise AgentPlacementError("room_bounds minimum values must be smaller than maximum values.")
    if values["max_x"] - values["min_x"] < 2.0 * WALL_MARGIN - FLOAT_EPSILON:
        raise AgentPlacementError("room_bounds leave no usable width after applying the wall margin.")
    if values["max_z"] - values["min_z"] < 2.0 * WALL_MARGIN - FLOAT_EPSILON:
        raise AgentPlacementError("room_bounds leave no usable depth after applying the wall margin.")
    return values


def _room_center(bounds: Dict[str, float]) -> Point:
    return ((bounds["min_x"] + bounds["max_x"]) / 2.0, (bounds["min_z"] + bounds["max_z"]) / 2.0)


def _object_bounds(obj: Dict[str, Any]) -> _ObstacleFootprint:
    """Return the object's exact floor-sliced oriented footprint.

    The four iterable values are the rotated AABB for legacy callers. Collision
    checks use the additional OBB fields, including the RDL/Unity yaw.
    """

    pos = obj.get("position") or {}
    dims = obj.get("dimensions") or {}
    rotation = obj.get("rotation") or {}
    x = _finite_float(pos.get("x"), 0.0) or 0.0
    y = _finite_float(pos.get("y"), 0.0) or 0.0
    z = _finite_float(pos.get("z"), 0.0) or 0.0
    width = max(_finite_float(dims.get("width"), 0.0) or 0.0, MIN_OBJECT_DIMENSION)
    depth = max(_finite_float(dims.get("depth"), 0.0) or 0.0, MIN_OBJECT_DIMENSION)
    height = max(_finite_float(dims.get("height"), 0.0) or 0.0, 0.0)
    yaw_degrees = _finite_float(rotation.get("y"), 0.0) or 0.0
    yaw = math.radians(yaw_degrees)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    half_width = width / 2.0
    half_depth = depth / 2.0

    # Axis-aligned envelope of the oriented rectangle, retained for callers
    # that display or report bounds rather than perform collision checks.
    envelope_x = abs(cos_yaw) * half_width + abs(sin_yaw) * half_depth
    envelope_z = abs(sin_yaw) * half_width + abs(cos_yaw) * half_depth
    lower_y = y - height / 2.0
    upper_y = y + height / 2.0
    # Room-plan inputs may omit object height and are normalized to 0. Such an
    # unknown vertical extent must remain a conservative floor obstacle rather
    # than silently disappearing from collision detection.
    intersects_floor_slice = height <= FLOAT_EPSILON or (
        lower_y - FLOAT_EPSILON <= FLOOR_SLICE_Y <= upper_y + FLOAT_EPSILON
    )
    return _ObstacleFootprint(
        min_x=x - envelope_x,
        max_x=x + envelope_x,
        min_z=z - envelope_z,
        max_z=z + envelope_z,
        center_x=x,
        center_z=z,
        half_width=half_width,
        half_depth=half_depth,
        cos_yaw=cos_yaw,
        sin_yaw=sin_yaw,
        intersects_floor_slice=intersects_floor_slice,
    )


def _inside_bounds(x: float, z: float, bounds: Dict[str, float]) -> bool:
    if not math.isfinite(x) or not math.isfinite(z):
        return False
    try:
        return (
            bounds["min_x"] + WALL_MARGIN - FLOAT_EPSILON
            <= x
            <= bounds["max_x"] - WALL_MARGIN + FLOAT_EPSILON
            and bounds["min_z"] + WALL_MARGIN - FLOAT_EPSILON
            <= z
            <= bounds["max_z"] - WALL_MARGIN + FLOAT_EPSILON
        )
    except (KeyError, TypeError):
        return False


def _inside_obstacle(x: float, z: float, obstacles: Sequence[Obstacle]) -> bool:
    if not math.isfinite(x) or not math.isfinite(z):
        return True
    for obstacle in obstacles:
        if isinstance(obstacle, _ObstacleFootprint):
            if not obstacle.intersects_floor_slice:
                continue
            # RDL rotation is projected like Unity's left-handed Y rotation.
            # Transform the world point into the object's local XZ plane.
            dx = x - obstacle.center_x
            dz = z - obstacle.center_z
            local_x = obstacle.cos_yaw * dx - obstacle.sin_yaw * dz
            local_z = obstacle.sin_yaw * dx + obstacle.cos_yaw * dz
            if (
                abs(local_x) <= obstacle.half_width + OBJECT_PADDING + FLOAT_EPSILON
                and abs(local_z) <= obstacle.half_depth + OBJECT_PADDING + FLOAT_EPSILON
            ):
                return True
            continue

        # Accept the historical four-value AABB form for callers/tests that
        # constructed obstacles directly.
        try:
            min_x, max_x, min_z, max_z = obstacle
        except (TypeError, ValueError):
            continue
        if (
            min_x - OBJECT_PADDING - FLOAT_EPSILON
            <= x
            <= max_x + OBJECT_PADDING + FLOAT_EPSILON
            and min_z - OBJECT_PADDING - FLOAT_EPSILON
            <= z
            <= max_z + OBJECT_PADDING + FLOAT_EPSILON
        ):
            return True
    return False


def _too_close_to_agents(x: float, z: float, placed: Sequence[Dict[str, Any]]) -> bool:
    for placement in placed:
        pos = _finite_point(placement.get("position") or {})
        if pos is None:
            continue
        if _distance_xz((x, z), pos) + FLOAT_EPSILON < MIN_AGENT_DISTANCE:
            return True
    return False


def _is_valid_position(
    x: float,
    z: float,
    *,
    bounds: Dict[str, float],
    obstacles: Sequence[Obstacle],
    placed: Sequence[Dict[str, Any]],
) -> bool:
    return _inside_bounds(x, z, bounds) and not _inside_obstacle(x, z, obstacles) and not _too_close_to_agents(x, z, placed)


def _clamp_to_room(x: float, z: float, bounds: Dict[str, float]) -> Point:
    return (
        max(bounds["min_x"] + WALL_MARGIN, min(bounds["max_x"] - WALL_MARGIN, x)),
        max(bounds["min_z"] + WALL_MARGIN, min(bounds["max_z"] - WALL_MARGIN, z)),
    )


def _quantized_point(x: float, z: float) -> Point:
    return (round(x, POSITION_DECIMALS), round(z, POSITION_DECIMALS))


def _spiral_search(
    target: Point,
    *,
    bounds: Dict[str, float],
    obstacles: Sequence[Obstacle],
    placed: Sequence[Dict[str, Any]],
) -> Point:
    """Find the nearest deterministic valid point or raise an explicit error."""

    start = _quantized_point(*_clamp_to_room(target[0], target[1], bounds))
    if _is_valid_position(*start, bounds=bounds, obstacles=obstacles, placed=placed):
        return start

    seen: Set[Point] = {start}
    usable_corners = (
        (bounds["min_x"] + WALL_MARGIN, bounds["min_z"] + WALL_MARGIN),
        (bounds["min_x"] + WALL_MARGIN, bounds["max_z"] - WALL_MARGIN),
        (bounds["max_x"] - WALL_MARGIN, bounds["min_z"] + WALL_MARGIN),
        (bounds["max_x"] - WALL_MARGIN, bounds["max_z"] - WALL_MARGIN),
    )
    max_radius = max(_distance_xz(start, corner) for corner in usable_corners)
    radius = SEARCH_RADIAL_STEP
    while radius <= max_radius + SEARCH_RADIAL_STEP:
        sample_count = max(24, int(math.ceil((2.0 * math.pi * radius) / SEARCH_ARC_STEP)))
        for index in range(sample_count):
            angle = (2.0 * math.pi * index) / sample_count
            candidate = _quantized_point(
                start[0] + math.cos(angle) * radius,
                start[1] + math.sin(angle) * radius,
            )
            if candidate in seen:
                continue
            seen.add(candidate)
            if _is_valid_position(*candidate, bounds=bounds, obstacles=obstacles, placed=placed):
                return candidate
        radius += SEARCH_RADIAL_STEP

    raise AgentPlacementError(
        "No valid floor position exists for the requested target "
        f"({target[0]:.3f}, {target[1]:.3f}) within the room constraints."
    )


def _object_lookup(normalized_scene: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for obj in normalized_scene.get("objects") or []:
        if isinstance(obj, dict) and obj.get("object_id"):
            result[str(obj["object_id"])] = obj
    return result


def _object_center(obj: Dict[str, Any]) -> Optional[Point]:
    return _finite_point(obj.get("position") or {})


def _point_medoid(candidates: Sequence[Tuple[str, Point]]) -> Optional[Point]:
    """Choose an existing point minimizing total distance, with stable ties."""

    ordered = sorted(candidates, key=lambda item: (item[0], item[1][0], item[1][1]))
    if not ordered:
        return None
    ranked: List[Tuple[float, str, float, float, Point]] = []
    points = [point for _, point in ordered]
    for key, point in ordered:
        total_distance = sum(_distance_xz(point, other) for other in points)
        ranked.append((round(total_distance, 12), key, point[0], point[1], point))
    return min(ranked)[-1]


def _zone_centroids(
    scene_semantics: Dict[str, Any],
    object_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Point]:
    """Resolve deterministic zone representatives.

    When object geometry is available, the representative is the medoid of the
    zone's referenced objects. The LLM-provided centroid remains a fallback for
    zones without resolvable members.
    """

    result: Dict[str, Point] = {}
    for zone in scene_semantics.get("semantic_zones") or []:
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("zone_id") or "")
        if not zone_id:
            continue
        candidates: List[Tuple[str, Point]] = []
        if object_lookup is not None:
            for object_id_value in zone.get("object_ids") or []:
                object_id = str(object_id_value)
                obj = object_lookup.get(object_id)
                point = _object_center(obj) if obj else None
                if point is not None:
                    candidates.append((object_id, point))
        representative = _point_medoid(candidates)
        if representative is None:
            representative = _finite_point(zone.get("centroid_xz") or {})
        if representative is not None:
            result[zone_id] = representative
    return result


def _agent_target(
    agent: Dict[str, Any],
    *,
    object_lookup: Dict[str, Dict[str, Any]],
    zone_centroids: Dict[str, Point],
    room_center: Point,
) -> Point:
    """Select one primary zone target, or a grounded-object medoid.

    ``responsible_zone_ids`` is an ordered responsibility declaration, so the
    first resolvable zone is the deterministic primary target. We intentionally
    do not average remote zones into a point that belongs to none of them.
    """

    for zone_id_value in agent.get("responsible_zone_ids") or []:
        zone_id = str(zone_id_value)
        if zone_id in zone_centroids:
            return zone_centroids[zone_id]

    candidates: List[Tuple[str, Point]] = []
    for object_id_value in agent.get("grounded_object_ids") or []:
        object_id = str(object_id_value)
        obj = object_lookup.get(object_id)
        point = _object_center(obj) if obj else None
        if point is not None:
            candidates.append((object_id, point))
    return _point_medoid(candidates) or room_center


def generate_agent_placements(
    *,
    normalized_scene: Dict[str, Any],
    scene_semantics: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    raw_bounds = normalized_scene.get("room_bounds") or {
        "min_x": -5.0,
        "max_x": 5.0,
        "min_z": -5.0,
        "max_z": 5.0,
    }
    bounds = _canonical_room_bounds(raw_bounds)
    center = _room_center(bounds)
    object_lookup = _object_lookup(normalized_scene)
    zone_centroids = _zone_centroids(scene_semantics, object_lookup)
    obstacles: List[Obstacle] = [
        _object_bounds(obj)
        for obj in normalized_scene.get("objects") or []
        if isinstance(obj, dict) and not is_structural_object(obj)
    ]

    # The collision outcome must not depend on LLM/list ordering. Place by a
    # stable agent ID, then restore the source order in the returned artifact.
    indexed_agents = [
        (index, agent)
        for index, agent in enumerate(agent_roles.get("agents") or [])
        if isinstance(agent, dict)
    ]
    processing_order = sorted(indexed_agents, key=lambda item: (str(item[1].get("id") or ""), item[0]))
    placed: List[Dict[str, Any]] = []
    placement_by_index: Dict[int, Dict[str, Any]] = {}
    for source_index, agent in processing_order:
        agent_id = agent.get("id")
        target = _agent_target(agent, object_lookup=object_lookup, zone_centroids=zone_centroids, room_center=center)
        # Approach the represented object/zone from the room interior.
        direction_to_center = _normalize_vec_xz(center[0] - target[0], center[1] - target[1])
        preferred = (target[0] + direction_to_center["x"] * 1.25, target[1] + direction_to_center["z"] * 1.25)
        try:
            x, z = _spiral_search(preferred, bounds=bounds, obstacles=obstacles, placed=placed)
        except AgentPlacementError as exc:
            raise AgentPlacementError(f"Unable to place agent {agent_id!r}: {exc}") from exc
        forward = _normalize_vec_xz(target[0] - x, target[1] - z)
        placement = {
            "id": agent_id,
            "display_name": agent.get("display_name") or agent_id,
            "position": {"x": x, "y": 0.0, "z": z},
            "forward": forward,
            "target_xz": {"x": round(target[0], POSITION_DECIMALS), "z": round(target[1], POSITION_DECIMALS)},
            "responsible_zone_ids": agent.get("responsible_zone_ids") or [],
            "grounded_object_ids": agent.get("grounded_object_ids") or [],
        }
        placed.append(placement)
        placement_by_index[source_index] = placement

    ordered_placements = [placement_by_index[index] for index, _ in indexed_agents]
    return {
        "schema": PLACEMENT_ARTIFACT_SCHEMA,
        "schema_version": PLACEMENT_ARTIFACT_SCHEMA_VERSION,
        "placement_algorithm_version": PLACEMENT_ALGORITHM_VERSION,
        "origin": "deterministic",
        "room_bounds": bounds,
        "agent_placements": ordered_placements,
    }


def _minimum_agent_distance(placements: List[Dict[str, Any]]) -> Optional[float]:
    valid_positions = [
        point
        for placement in placements
        if (point := _finite_point((placement.get("position") or {}) if isinstance(placement, dict) else {})) is not None
    ]
    if len(valid_positions) < 2:
        return None
    distances = [
        _distance_xz(left, right)
        for index, left in enumerate(valid_positions)
        for right in valid_positions[index + 1 :]
    ]
    return min(distances) if distances else None


def _forward_error(forward: Any) -> Optional[str]:
    if not isinstance(forward, dict):
        return "must be an object with finite x, y and z components"
    raw_components = [forward.get(key) for key in ("x", "y", "z")]
    if any(not _json_number(component) for component in raw_components):
        return "must contain finite JSON-number x, y and z components"
    x, y, z = (float(component) for component in raw_components)
    if abs(y) > PLACEMENT_FLOOR_TOLERANCE:
        return "must lie in the floor (XZ) plane"
    length = math.sqrt(x * x + y * y + z * z)
    if abs(length - 1.0) > FORWARD_NORMALIZATION_TOLERANCE:
        return f"must be normalized (length is {length:.6f})"
    return None


def validate_agent_placements(
    placements_payload: Dict[str, Any],
    *,
    normalized_scene: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    if placements_payload.get("schema") != PLACEMENT_ARTIFACT_SCHEMA:
        errors.append(f"schema must be exactly {PLACEMENT_ARTIFACT_SCHEMA!r}.")
    if placements_payload.get("schema_version") != PLACEMENT_ARTIFACT_SCHEMA_VERSION:
        errors.append(f"schema_version must be exactly {PLACEMENT_ARTIFACT_SCHEMA_VERSION!r}.")
    if placements_payload.get("placement_algorithm_version") != PLACEMENT_ALGORITHM_VERSION:
        errors.append(f"placement_algorithm_version must be exactly {PLACEMENT_ALGORITHM_VERSION!r}.")
    origin = placements_payload.get("origin")
    if origin not in PLACEMENT_ORIGINS:
        errors.append("origin must be one of: " + ", ".join(sorted(PLACEMENT_ORIGINS)) + ".")
    raw_bounds = placements_payload.get("room_bounds") or normalized_scene.get("room_bounds")
    try:
        bounds = _canonical_room_bounds(raw_bounds)
    except AgentPlacementError as exc:
        errors.append(str(exc))
        bounds = {"min_x": -5.0, "max_x": 5.0, "min_z": -5.0, "max_z": 5.0}

    obstacles: List[Obstacle] = [
        _object_bounds(obj)
        for obj in normalized_scene.get("objects") or []
        if isinstance(obj, dict) and not is_structural_object(obj)
    ]
    raw_placements = placements_payload.get("agent_placements") or []
    placements = [item for item in raw_placements if isinstance(item, dict)]
    if len(placements) != len(raw_placements):
        errors.append("agent_placements contains a non-object entry.")

    expected_agent_ids = {
        str(agent.get("id"))
        for agent in agent_roles.get("agents") or []
        if isinstance(agent, dict) and agent.get("id") is not None
    }
    actual_agent_ids: Set[str] = set()
    seen_agent_ids: Counter[str] = Counter()
    obstacle_overlaps = 0
    out_of_bounds = 0

    if len(placements) != len(expected_agent_ids):
        errors.append(f"Expected {len(expected_agent_ids)} placements, got {len(placements)}.")

    for index, placement in enumerate(placements):
        agent_id = str(placement.get("id") or "")
        actual_agent_ids.add(agent_id)
        seen_agent_ids[agent_id] += 1
        if agent_id not in expected_agent_ids:
            errors.append(f"agent_placements[{index}] references unknown agent id: {agent_id}.")

        pos_payload = placement.get("position") or {}
        raw_position = [
            pos_payload.get(key) if isinstance(pos_payload, dict) else None
            for key in ("x", "y", "z")
        ]
        if any(not _json_number(component) for component in raw_position):
            errors.append(
                f"agent_placements[{index}] has a non-finite, non-numeric or incomplete position."
            )
        else:
            x, y, z = (float(component) for component in raw_position)
            if abs(y) > PLACEMENT_FLOOR_TOLERANCE:
                errors.append(f"agent_placements[{index}] must be placed on the floor plane (y = 0).")
            if not _inside_bounds(x, z, bounds):
                out_of_bounds += 1
                errors.append(f"agent_placements[{index}] is outside room bounds.")
            if _inside_obstacle(x, z, obstacles):
                obstacle_overlaps += 1
                errors.append(f"agent_placements[{index}] overlaps an obstacle footprint.")

        forward_error = _forward_error(placement.get("forward"))
        if forward_error:
            errors.append(f"agent_placements[{index}] has an invalid forward vector: {forward_error}.")

    duplicate_agent_ids = sorted(agent_id for agent_id, count in seen_agent_ids.items() if count > 1)
    if duplicate_agent_ids:
        errors.append("Duplicate placements for agents: " + ", ".join(duplicate_agent_ids))

    missing_agents = sorted(expected_agent_ids - actual_agent_ids)
    if missing_agents:
        errors.append("Missing placements for agents: " + ", ".join(missing_agents))

    min_distance = _minimum_agent_distance(placements)
    if min_distance is not None and min_distance + FLOAT_EPSILON < MIN_AGENT_DISTANCE:
        errors.append(f"Minimum agent distance is too small: {min_distance:.3f}.")

    artifact_hash: Optional[str] = None
    if not errors:
        try:
            artifact_hash = placement_artifact_sha256(placements_payload)
        except ValueError as exc:
            errors.append(str(exc))

    return {
        "placement_algorithm_version": PLACEMENT_ALGORITHM_VERSION,
        "placement_artifact_sha256": artifact_hash,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "agent_count": len(expected_agent_ids),
            "placement_count": len(placements),
            "out_of_bounds_count": out_of_bounds,
            "obstacle_overlap_count": obstacle_overlaps,
            "minimum_agent_distance": round(min_distance, 4) if min_distance is not None else None,
        },
    }


def run_agent_placement_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    semantics_path = case_dir / "intermediate" / "scene_semantics.json"
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    placements_path = case_dir / "intermediate" / "agent_placements.json"
    validation_path = case_dir / "validation" / "agent_placement_validation.json"

    normalized_scene = read_json(normalized_path)
    scene_semantics = read_json(semantics_path)
    agent_roles = read_json(agent_roles_path)
    placements = generate_agent_placements(
        normalized_scene=normalized_scene,
        scene_semantics=scene_semantics,
        agent_roles=agent_roles,
    )
    validation = validate_agent_placements(
        placements,
        normalized_scene=normalized_scene,
        agent_roles=agent_roles,
    )
    write_json(placements_path, placements)
    write_json(validation_path, validation)
    status = "success" if validation["status"] == "valid" else "needs_manual_review"
    update_manifest(
        case_dir,
        stage_id="agent_placement",
        status=status,
        input_paths=[normalized_path, semantics_path, agent_roles_path],
        output_paths=[placements_path, validation_path],
        errors=validation.get("errors"),
        warnings=validation.get("warnings"),
        metadata=validation.get("metrics"),
    )
    return {
        "case_id": case_dir.name,
        "status": status,
        "validation": validation,
        "placements_path": str(placements_path),
        "validation_path": str(validation_path),
    }
