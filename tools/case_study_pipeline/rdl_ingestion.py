from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .common import (
    copy_file,
    ensure_dirs,
    read_json,
    sha256_file,
    slugify,
    update_manifest,
    write_json,
    write_text,
)


STRUCTURAL_TYPES = {"floor", "ceiling", "wall", "walls"}
STRUCTURAL_GROUPS = {"structural", "floor", "walls", "wall"}
CONFIG_DIR = Path(__file__).resolve().parent / "config"


def _load_case_aliases() -> Dict[str, str]:
    path = CONFIG_DIR / "case_aliases.json"
    if not path.exists():
        return {}
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if str(key).strip() and str(value).strip()}


CASE_ID_ALIASES = _load_case_aliases()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _vec3(data: Any, default_y: float = 0.0) -> Dict[str, float]:
    if not isinstance(data, dict):
        data = {}
    return {
        "x": _num(data.get("x"), 0.0),
        "y": _num(data.get("y"), default_y),
        "z": _num(data.get("z"), 0.0),
    }


def _dimensions(data: Any) -> Dict[str, float]:
    if not isinstance(data, dict):
        data = {}
    width = data.get("width", data.get("x", 0.0))
    height = data.get("height", data.get("y", 0.0))
    depth = data.get("depth", data.get("z", 0.0))
    return {
        "width": _num(width, 0.0),
        "height": _num(height, 0.0),
        "depth": _num(depth, 0.0),
    }


def detect_schema(payload: Dict[str, Any]) -> str:
    scene = payload.get("scene")
    if isinstance(scene, dict) and isinstance(scene.get("objects"), list):
        return "rdl_scene"
    if isinstance(payload.get("zones"), list) or isinstance(payload.get("spawn_points"), list):
        return "room_plan"
    return "unknown"


def room_bounds_from_dimensions(dimensions: Dict[str, Any]) -> Optional[Dict[str, float]]:
    width = _num(dimensions.get("width"), 0.0)
    depth = _num(dimensions.get("depth"), 0.0)
    if width <= 0 or depth <= 0:
        return None
    return {
        "min_x": round(-width / 2.0, 4),
        "max_x": round(width / 2.0, 4),
        "min_z": round(-depth / 2.0, 4),
        "max_z": round(depth / 2.0, 4),
    }


def room_bounds_from_objects(objects: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not objects:
        return None
    min_x = min((o["position"]["x"] - o["dimensions"]["width"] / 2.0) for o in objects)
    max_x = max((o["position"]["x"] + o["dimensions"]["width"] / 2.0) for o in objects)
    min_z = min((o["position"]["z"] - o["dimensions"]["depth"] / 2.0) for o in objects)
    max_z = max((o["position"]["z"] + o["dimensions"]["depth"] / 2.0) for o in objects)
    margin = 0.5
    return {
        "min_x": round(min_x - margin, 4),
        "max_x": round(max_x + margin, 4),
        "min_z": round(min_z - margin, 4),
        "max_z": round(max_z + margin, 4),
    }


def _unique_id(raw_id: str, used: set[str], fallback_prefix: str, index: int) -> Tuple[str, bool]:
    generated = False
    candidate = slugify(raw_id, fallback="")
    if not candidate:
        candidate = f"{fallback_prefix}_{index + 1:03d}"
        generated = True
    original = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{original}_{suffix}"
        suffix += 1
        generated = True
    used.add(candidate)
    return candidate, generated


def _normalize_rdl_objects(scene: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    used: set[str] = set()
    warnings: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for index, raw in enumerate(scene.get("objects") or []):
        if not isinstance(raw, dict):
            warnings.append(f"Skipped non-object entry at scene.objects[{index}].")
            continue
        object_type = str(raw.get("objectType") or raw.get("type") or raw.get("name") or "object").strip()
        raw_id = str(raw.get("objectId") or raw.get("id") or "").strip()
        object_id, generated = _unique_id(raw_id, used, slugify(object_type, "object"), index)
        if generated:
            warnings.append(f"Generated or disambiguated object id '{object_id}' for object index {index}.")
        normalized.append(
            {
                "object_id": object_id,
                "source_id": raw_id or None,
                "object_type": object_type,
                "group": str(raw.get("group") or "").strip() or "ungrouped",
                "position": _vec3(raw.get("position")),
                "rotation": _vec3(raw.get("rotation")),
                "dimensions": _dimensions(raw.get("dimensions")),
                "specification": str(raw.get("specification") or "").strip(),
                "children_count": len(raw.get("children") or []) if isinstance(raw.get("children"), list) else 0,
            }
        )
    return normalized, warnings


def _normalize_room_plan_objects(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    raw_objects: List[Dict[str, Any]] = []
    for key in ("objects", "furniture", "props", "fixtures", "obstacles"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_objects.extend([v for v in value if isinstance(v, dict)])

    used: set[str] = set()
    warnings: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_objects):
        object_type = str(raw.get("objectType") or raw.get("type") or raw.get("name") or "object").strip()
        raw_id = str(raw.get("objectId") or raw.get("id") or "").strip()
        object_id, generated = _unique_id(raw_id, used, slugify(object_type, "object"), index)
        if generated:
            warnings.append(f"Generated or disambiguated object id '{object_id}' for room object index {index}.")
        normalized.append(
            {
                "object_id": object_id,
                "source_id": raw_id or None,
                "object_type": object_type,
                "group": str(raw.get("group") or raw.get("zone_id") or "").strip() or "ungrouped",
                "position": _vec3(raw.get("position") or raw.get("pos")),
                "rotation": _vec3(raw.get("rotation")),
                "dimensions": _dimensions(raw.get("dimensions") or raw.get("size") or raw.get("scale")),
                "specification": str(raw.get("specification") or raw.get("description") or "").strip(),
                "children_count": 0,
            }
        )
    return normalized, warnings


def normalize_scene(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    schema_kind = detect_schema(payload)
    warnings: List[str] = []
    errors: List[str] = []

    if schema_kind == "rdl_scene":
        scene = payload.get("scene") or {}
        environment = scene.get("environment") or {}
        dimensions = _dimensions(environment.get("dimensions"))
        objects, object_warnings = _normalize_rdl_objects(scene)
        warnings.extend(object_warnings)
        scene_name = str(scene.get("sceneName") or scene.get("name") or "Unnamed RDL Scene").strip()
        environment_type = str(environment.get("type") or "").strip() or None
        object_groups_raw = scene.get("objectGroups") if isinstance(scene.get("objectGroups"), dict) else {}
    elif schema_kind == "room_plan":
        dimensions = {"width": 0.0, "height": 0.0, "depth": 0.0}
        objects, object_warnings = _normalize_room_plan_objects(payload)
        warnings.extend(object_warnings)
        scene_name = str(payload.get("sceneName") or payload.get("name") or "RoomPlan Scene").strip()
        environment_type = str(payload.get("environment_type") or "").strip() or None
        object_groups_raw = {}
    else:
        errors.append("Unknown scene schema. Expected RDL scene.objects or RoomPlan zones/spawn_points.")
        objects = []
        dimensions = {"width": 0.0, "height": 0.0, "depth": 0.0}
        scene_name = "Unknown Scene"
        environment_type = None
        object_groups_raw = {}

    if not objects and schema_kind == "rdl_scene":
        errors.append("No objects extracted from RDL scene.")

    room_bounds = room_bounds_from_dimensions(dimensions) or room_bounds_from_objects(objects)
    if room_bounds is None:
        warnings.append("Room bounds missing and could not be inferred from objects.")

    normalized = {
        "schema_kind": schema_kind,
        "scene_name": scene_name,
        "environment_type": environment_type,
        "dimensions": dimensions,
        "room_bounds": room_bounds,
        "objects": objects,
        "object_groups_declared": object_groups_raw,
        "zones": payload.get("zones") if isinstance(payload.get("zones"), list) else [],
        "spawn_points": payload.get("spawn_points") if isinstance(payload.get("spawn_points"), list) else [],
        "source_stats": {
            "object_count": len(objects),
            "group_count": len({o["group"] for o in objects}),
        },
    }
    validation = validate_normalized_scene(normalized, initial_errors=errors, initial_warnings=warnings)
    return normalized, validation


def is_structural_object(obj: Dict[str, Any]) -> bool:
    return str(obj.get("object_type") or "").lower() in STRUCTURAL_TYPES or str(obj.get("group") or "").lower() in STRUCTURAL_GROUPS


def summarize_object_groups(normalized: Dict[str, Any]) -> Dict[str, Any]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for obj in normalized.get("objects") or []:
        grouped[str(obj.get("group") or "ungrouped")].append(obj)

    summaries = []
    for group, objects in sorted(grouped.items(), key=lambda item: item[0]):
        type_counts = Counter(str(o.get("object_type") or "object") for o in objects)
        xs = [o["position"]["x"] for o in objects]
        zs = [o["position"]["z"] for o in objects]
        examples = []
        for obj in objects[:3]:
            examples.append(
                {
                    "object_id": obj["object_id"],
                    "object_type": obj["object_type"],
                    "specification_excerpt": (obj.get("specification") or "")[:240],
                }
            )
        summaries.append(
            {
                "group": group,
                "object_count": len(objects),
                "object_types": dict(type_counts),
                "is_structural": all(is_structural_object(o) for o in objects),
                "centroid_xz": {
                    "x": round(sum(xs) / len(xs), 4) if xs else 0.0,
                    "z": round(sum(zs) / len(zs), 4) if zs else 0.0,
                },
                "example_objects": examples,
            }
        )

    return {
        "case_scene_name": normalized.get("scene_name"),
        "schema_kind": normalized.get("schema_kind"),
        "groups": summaries,
    }


def validate_normalized_scene(
    normalized: Dict[str, Any],
    *,
    initial_errors: Optional[List[str]] = None,
    initial_warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    errors = list(initial_errors or [])
    warnings = list(initial_warnings or [])
    schema_kind = normalized.get("schema_kind")
    if schema_kind not in {"rdl_scene", "room_plan"}:
        errors.append(f"schema_kind is invalid: {schema_kind!r}.")

    objects = normalized.get("objects") or []
    if schema_kind == "rdl_scene" and not objects:
        errors.append("RDL scenes must contain at least one normalized object.")

    ids = [str(o.get("object_id") or "") for o in objects]
    if any(not i for i in ids):
        errors.append("At least one normalized object has an empty object_id.")
    duplicates = [i for i, count in Counter(ids).items() if count > 1]
    if duplicates:
        errors.append("Duplicate object IDs: " + ", ".join(sorted(duplicates)))

    room_bounds = normalized.get("room_bounds")
    if room_bounds is None:
        warnings.append("room_bounds is null.")
    else:
        for key in ("min_x", "max_x", "min_z", "max_z"):
            if key not in room_bounds:
                errors.append(f"room_bounds.{key} is missing.")
        if room_bounds.get("min_x", 0) >= room_bounds.get("max_x", 0):
            errors.append("room_bounds min_x must be smaller than max_x.")
        if room_bounds.get("min_z", 0) >= room_bounds.get("max_z", 0):
            errors.append("room_bounds min_z must be smaller than max_z.")

    non_structural_groups = set()
    for obj in objects:
        if not is_structural_object(obj):
            non_structural_groups.add(str(obj.get("group") or "ungrouped"))
    if schema_kind == "rdl_scene" and not non_structural_groups:
        warnings.append("No non-structural object groups found.")

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "object_count": len(objects),
            "non_structural_group_count": len(non_structural_groups),
        },
    }


def default_case_id(input_path: Path) -> str:
    stem = input_path.stem
    return slugify(CASE_ID_ALIASES.get(stem, stem), fallback="case")


def unique_case_ids(paths: Iterable[Path]) -> Dict[Path, str]:
    used: set[str] = set()
    result: Dict[Path, str] = {}
    for path in paths:
        base = default_case_id(path)
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        used.add(candidate)
        result[path] = candidate
    return result


def initialize_case(input_path: Path, out_root: Path, case_id: str) -> Dict[str, Path]:
    case_dir = out_root / case_id
    ensure_dirs(case_dir)
    source_copy = case_dir / "input" / "source_rdl.json"
    copy_file(input_path, source_copy)
    source_hash = sha256_file(source_copy)
    hash_path = case_dir / "input" / "source_rdl.sha256"
    write_text(hash_path, source_hash + "\n")
    update_manifest(
        case_dir,
        stage_id="case_initialization",
        status="success",
        input_paths=[input_path],
        output_paths=[source_copy, hash_path],
        metadata={"case_id": case_id, "source_sha256": source_hash},
    )
    return {"case_dir": case_dir, "source_copy": source_copy, "hash_path": hash_path}


def run_ingestion_for_case(case_dir: Path) -> Dict[str, Any]:
    source = case_dir / "input" / "source_rdl.json"
    payload = read_json(source)
    normalized, validation = normalize_scene(payload)
    group_summary = summarize_object_groups(normalized)

    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    group_summary_path = case_dir / "intermediate" / "object_group_summary.json"
    validation_path = case_dir / "validation" / "rdl_ingestion_validation.json"
    write_json(normalized_path, normalized)
    write_json(group_summary_path, group_summary)
    write_json(validation_path, validation)

    status = "success" if validation["status"] == "valid" else "failed"
    update_manifest(
        case_dir,
        stage_id="rdl_ingestion",
        status=status,
        input_paths=[source],
        output_paths=[normalized_path, group_summary_path, validation_path],
        errors=validation.get("errors"),
        warnings=validation.get("warnings"),
        metadata=validation.get("metrics"),
    )
    return {
        "case_id": case_dir.name,
        "status": status,
        "validation": validation,
        "normalized_path": str(normalized_path),
        "group_summary_path": str(group_summary_path),
    }


def run_pipeline(inputs: List[Path], out_root: Path) -> List[Dict[str, Any]]:
    out_root.mkdir(parents=True, exist_ok=True)
    mapping = unique_case_ids(inputs)
    results = []
    for input_path, case_id in mapping.items():
        initialized = initialize_case(input_path, out_root, case_id)
        result = run_ingestion_for_case(initialized["case_dir"])
        results.append(result)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize RoomContract case studies and run RDL ingestion.")
    parser.add_argument("inputs", nargs="+", type=Path, help="RDL or RoomPlan JSON files.")
    parser.add_argument("--out-root", type=Path, default=Path("output/case_studies"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = [p.resolve() for p in args.inputs]
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        for path in missing:
            print(f"Missing input: {path}")
        return 2

    results = run_pipeline(inputs, args.out_root.resolve())
    for result in results:
        errors = len(result["validation"].get("errors") or [])
        warnings = len(result["validation"].get("warnings") or [])
        print(f"{result['case_id']}: {result['status']} ({errors} errors, {warnings} warnings)")
    return 0 if all(r["status"] == "success" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
