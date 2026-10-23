from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .common import read_json, slugify, update_manifest, write_json
from .llm_client import ResponsesClient, load_llm_settings, response_metadata, sanitize_error_text
from .rdl_ingestion import is_structural_object


PROMPT_VERSION = "scene_semantics_v1"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{PROMPT_VERSION}.md"
REPAIR_PROMPT_VERSION = "repair_invalid_object_refs_v1"
REPAIR_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{REPAIR_PROMPT_VERSION}.md"


def _excerpt(text: Any, limit: int = 160) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _collect_object_ids(normalized_scene: Dict[str, Any]) -> List[str]:
    ids = []
    for obj in normalized_scene.get("objects") or []:
        object_id = obj.get("object_id")
        if isinstance(object_id, str) and object_id:
            ids.append(object_id)
    return ids


def _compact_objects(normalized_scene: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    compact: List[Dict[str, Any]] = []
    structural_ids: List[str] = []
    for obj in normalized_scene.get("objects") or []:
        object_id = str(obj.get("object_id") or "")
        if not object_id:
            continue
        if is_structural_object(obj):
            structural_ids.append(object_id)
            continue
        pos = obj.get("position") or {}
        compact.append(
            {
                "object_id": object_id,
                "object_type": obj.get("object_type"),
                "group": obj.get("group"),
                "position_xz": {
                    "x": round(float(pos.get("x", 0.0)), 3),
                    "z": round(float(pos.get("z", 0.0)), 3),
                },
                "specification_excerpt": _excerpt(obj.get("specification")),
            }
        )
    return compact, structural_ids


def build_scene_semantics_payload(
    normalized_scene: Dict[str, Any],
    object_group_summary: Dict[str, Any],
) -> Dict[str, Any]:
    compact_objects, structural_ids = _compact_objects(normalized_scene)
    compact_groups = []
    for group in object_group_summary.get("groups") or []:
        examples = []
        for example in group.get("example_objects") or []:
            examples.append(
                {
                    "object_id": example.get("object_id"),
                    "object_type": example.get("object_type"),
                    "specification_excerpt": _excerpt(example.get("specification_excerpt"), 120),
                }
            )
        compact_groups.append(
            {
                "group": group.get("group"),
                "object_count": group.get("object_count"),
                "object_types": group.get("object_types"),
                "is_structural": group.get("is_structural"),
                "centroid_xz": group.get("centroid_xz"),
                "example_objects": examples,
            }
        )

    return {
        "schema_kind": normalized_scene.get("schema_kind"),
        "scene_name": normalized_scene.get("scene_name"),
        "environment_type": normalized_scene.get("environment_type"),
        "room_bounds": normalized_scene.get("room_bounds"),
        "dimensions": normalized_scene.get("dimensions"),
        "allowed_object_ids": _collect_object_ids(normalized_scene),
        "structural_object_ids": structural_ids,
        "non_structural_objects": compact_objects,
        "object_groups": compact_groups,
    }


def _object_id_array_schema(allowed_object_ids: List[str]) -> Dict[str, Any]:
    return {"type": "array", "items": {"type": "string", "enum": allowed_object_ids}}


def scene_semantics_schema(allowed_object_ids: List[str]) -> Dict[str, Any]:
    object_id_array = _object_id_array_schema(allowed_object_ids)
    return {
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "room_purpose": {"type": "string"},
            "visitor_goals": {"type": "array", "items": {"type": "string"}},
            "semantic_zones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "zone_id": {"type": "string"},
                        "name": {"type": "string"},
                        "purpose": {"type": "string"},
                        "object_ids": object_id_array,
                        "centroid_xz": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "z"],
                            "additionalProperties": False,
                        },
                        "visitor_goals_supported": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "zone_id",
                        "name",
                        "purpose",
                        "object_ids",
                        "centroid_xz",
                        "visitor_goals_supported",
                    ],
                    "additionalProperties": False,
                },
            },
            "important_objects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "object_id": {"type": "string", "enum": allowed_object_ids},
                        "reason": {"type": "string"},
                    },
                    "required": ["object_id", "reason"],
                    "additionalProperties": False,
                },
            },
            "interaction_topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "related_object_ids": object_id_array,
                    },
                    "required": ["topic_id", "title", "description", "related_object_ids"],
                    "additionalProperties": False,
                },
            },
            "agent_role_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role_id": {"type": "string"},
                        "display_name": {"type": "string"},
                        "mission": {"type": "string"},
                        "expertise": {"type": "array", "items": {"type": "string"}},
                        "responsible_zone_ids": {"type": "array", "items": {"type": "string"}},
                        "grounded_object_ids": object_id_array,
                    },
                    "required": [
                        "role_id",
                        "display_name",
                        "mission",
                        "expertise",
                        "responsible_zone_ids",
                        "grounded_object_ids",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "domain",
            "room_purpose",
            "visitor_goals",
            "semantic_zones",
            "important_objects",
            "interaction_topics",
            "agent_role_candidates",
        ],
        "additionalProperties": False,
    }


def _invalid_refs(refs: Iterable[str], allowed: Set[str]) -> List[str]:
    return sorted({str(ref) for ref in refs if str(ref) not in allowed})


def validate_scene_semantics(
    semantics: Dict[str, Any],
    normalized_scene: Dict[str, Any],
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    allowed_object_ids = set(_collect_object_ids(normalized_scene))

    if not str(semantics.get("domain") or "").strip():
        errors.append("domain is empty.")
    if not str(semantics.get("room_purpose") or "").strip():
        errors.append("room_purpose is empty.")

    visitor_goals = semantics.get("visitor_goals") or []
    if not isinstance(visitor_goals, list) or len([g for g in visitor_goals if str(g).strip()]) < 2:
        errors.append("At least two visitor_goals are required.")

    zones = semantics.get("semantic_zones") or []
    if not isinstance(zones, list) or len(zones) < 2:
        errors.append("At least two semantic_zones are required.")
    zone_ids: Set[str] = set()
    covered_object_ids: Set[str] = set()
    for index, zone in enumerate(zones if isinstance(zones, list) else []):
        zone_id = str(zone.get("zone_id") or "").strip() if isinstance(zone, dict) else ""
        if not zone_id:
            errors.append(f"semantic_zones[{index}].zone_id is empty.")
        elif zone_id in zone_ids:
            errors.append(f"Duplicate semantic zone id: {zone_id}.")
        zone_ids.add(zone_id)
        object_ids = zone.get("object_ids") if isinstance(zone, dict) else []
        if not isinstance(object_ids, list) or not object_ids:
            errors.append(f"semantic_zones[{index}] must reference at least one object_id.")
            object_ids = []
        invalid = _invalid_refs(object_ids, allowed_object_ids)
        if invalid:
            errors.append(f"semantic_zones[{index}] references unknown object_ids: {', '.join(invalid)}.")
        covered_object_ids.update(str(obj_id) for obj_id in object_ids if str(obj_id) in allowed_object_ids)

    important_objects = semantics.get("important_objects") or []
    for index, entry in enumerate(important_objects if isinstance(important_objects, list) else []):
        object_id = entry.get("object_id") if isinstance(entry, dict) else None
        if object_id not in allowed_object_ids:
            errors.append(f"important_objects[{index}] references unknown object_id: {object_id}.")

    topics = semantics.get("interaction_topics") or []
    if not isinstance(topics, list) or not topics:
        warnings.append("No interaction_topics were produced.")
    for index, topic in enumerate(topics if isinstance(topics, list) else []):
        refs = topic.get("related_object_ids") if isinstance(topic, dict) else []
        if not isinstance(refs, list):
            errors.append(f"interaction_topics[{index}].related_object_ids must be a list.")
            refs = []
        invalid = _invalid_refs(refs, allowed_object_ids)
        if invalid:
            errors.append(f"interaction_topics[{index}] references unknown object_ids: {', '.join(invalid)}.")

    role_candidates = semantics.get("agent_role_candidates") or []
    if not isinstance(role_candidates, list) or len(role_candidates) < 2:
        errors.append("At least two agent_role_candidates are required.")
    role_ids: Set[str] = set()
    for index, role in enumerate(role_candidates if isinstance(role_candidates, list) else []):
        role_id = str(role.get("role_id") or "").strip() if isinstance(role, dict) else ""
        if not role_id:
            errors.append(f"agent_role_candidates[{index}].role_id is empty.")
        elif slugify(role_id, fallback="") != role_id:
            warnings.append(f"agent_role_candidates[{index}].role_id is not slug-normalized: {role_id}.")
        elif role_id in role_ids:
            errors.append(f"Duplicate agent role id: {role_id}.")
        role_ids.add(role_id)

        expertise = role.get("expertise") if isinstance(role, dict) else []
        if not isinstance(expertise, list) or not expertise:
            errors.append(f"agent_role_candidates[{index}] needs at least one expertise item.")

        responsible_zone_ids = role.get("responsible_zone_ids") if isinstance(role, dict) else []
        if not isinstance(responsible_zone_ids, list):
            errors.append(f"agent_role_candidates[{index}].responsible_zone_ids must be a list.")
            responsible_zone_ids = []
        unknown_zones = sorted({str(z) for z in responsible_zone_ids if str(z) not in zone_ids})
        if unknown_zones:
            errors.append(
                f"agent_role_candidates[{index}] references unknown zone_ids: {', '.join(unknown_zones)}."
            )

        grounded_object_ids = role.get("grounded_object_ids") if isinstance(role, dict) else []
        if not isinstance(grounded_object_ids, list) or not grounded_object_ids:
            errors.append(f"agent_role_candidates[{index}] needs at least one grounded_object_id.")
            grounded_object_ids = []
        invalid = _invalid_refs(grounded_object_ids, allowed_object_ids)
        if invalid:
            errors.append(
                f"agent_role_candidates[{index}] references unknown object_ids: {', '.join(invalid)}."
            )

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "visitor_goal_count": len(visitor_goals) if isinstance(visitor_goals, list) else 0,
            "semantic_zone_count": len(zones) if isinstance(zones, list) else 0,
            "important_object_count": len(important_objects) if isinstance(important_objects, list) else 0,
            "interaction_topic_count": len(topics) if isinstance(topics, list) else 0,
            "agent_role_candidate_count": len(role_candidates) if isinstance(role_candidates, list) else 0,
            "covered_object_count": len(covered_object_ids),
        },
    }


def _build_messages(
    *,
    prompt_text: str,
    repair_prompt_text: str,
    scene_payload: Dict[str, Any],
    previous_output: Optional[Dict[str, Any]] = None,
    validation_errors: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    user_payload: Dict[str, Any] = {
        "task": "Analyze this normalized scene and produce scene semantics.",
        "scene": scene_payload,
    }
    if previous_output is not None:
        user_payload["previous_invalid_output"] = previous_output
        user_payload["validation_errors"] = validation_errors or []
        user_payload["repair_instruction"] = repair_prompt_text

    return [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def run_scene_semantics_for_case(
    case_dir: Path,
    *,
    model_override: Optional[str] = None,
    max_repair_attempts: int = 3,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    group_summary_path = case_dir / "intermediate" / "object_group_summary.json"
    semantics_path = case_dir / "intermediate" / "scene_semantics.json"
    validation_path = case_dir / "validation" / "scene_semantics_validation.json"

    normalized_scene = read_json(normalized_path)
    group_summary = read_json(group_summary_path)
    scene_payload = build_scene_semantics_payload(normalized_scene, group_summary)
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    repair_prompt_text = REPAIR_PROMPT_PATH.read_text(encoding="utf-8")
    schema = scene_semantics_schema(scene_payload["allowed_object_ids"])
    previous_output: Optional[Dict[str, Any]] = None
    validation: Dict[str, Any] = {
        "status": "invalid",
        "errors": ["Scene semantics did not run."],
        "warnings": [],
        "metrics": {},
    }
    last_response_meta: Dict[str, Any] = {}
    attempts_used = 0
    infrastructure_failed = False

    try:
        settings = load_llm_settings(
            config_path=config_path or Path.cwd() / "app/backend_root/agent_backend/config.json",
            model_override=model_override,
            prefer_low_token_model=True,
        )
        client = ResponsesClient(settings)

        for attempt in range(1, max(1, max_repair_attempts) + 1):
            attempts_used = attempt
            messages = _build_messages(
                prompt_text=prompt_text,
                repair_prompt_text=repair_prompt_text,
                scene_payload=scene_payload,
                previous_output=previous_output,
                validation_errors=validation.get("errors") if previous_output is not None else None,
            )
            semantics, response_payload, _ = client.create_structured_json(
                input_messages=messages,
                schema=schema,
                schema_name="scene_semantics",
                temperature=0.2,
                max_output_tokens=1800,
            )
            last_response_meta = response_metadata(response_payload)
            validation = validate_scene_semantics(semantics, normalized_scene)
            write_json(semantics_path, semantics)
            write_json(validation_path, validation)
            previous_output = semantics
            if validation["status"] == "valid":
                break
        llm_metadata = settings.redacted_metadata()
    except Exception as exc:
        validation = {
            "status": "invalid",
            "errors": [sanitize_error_text(exc)],
            "warnings": [],
            "metrics": {},
        }
        write_json(validation_path, validation)
        llm_metadata = {"api_key_present": True, "model": model_override or "configured-default"}
        infrastructure_failed = True

    if validation["status"] == "valid":
        status = "success"
    elif infrastructure_failed:
        status = "failed"
    else:
        status = "needs_manual_review"
    update_manifest(
        case_dir,
        stage_id="scene_semantics",
        status=status,
        input_paths=[normalized_path, group_summary_path, PROMPT_PATH, REPAIR_PROMPT_PATH],
        output_paths=[semantics_path, validation_path],
        errors=validation.get("errors"),
        warnings=validation.get("warnings"),
        metadata={
            "prompt_version": PROMPT_VERSION,
            "repair_prompt_version": REPAIR_PROMPT_VERSION,
            "attempts_used": attempts_used,
            "llm": llm_metadata,
            "response": last_response_meta,
            "metrics": validation.get("metrics", {}),
        },
    )

    return {
        "case_id": case_dir.name,
        "status": status,
        "validation": validation,
        "semantics_path": str(semantics_path),
        "validation_path": str(validation_path),
        "model": llm_metadata.get("model"),
        "attempts_used": attempts_used,
    }
