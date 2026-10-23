from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .common import read_json, slugify, update_manifest, write_json, write_text
from .llm_client import ResponsesClient, load_llm_settings, response_metadata, sanitize_error_text


PROMPT_VERSION = "knowledge_synthesis_v1"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{PROMPT_VERSION}.md"
REPAIR_PROMPT_VERSION = "repair_missing_knowledge_entries_v1"
REPAIR_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{REPAIR_PROMPT_VERSION}.md"
STRUCTURAL_TYPES = {"floor", "ceiling", "wall", "walls"}
STRUCTURAL_GROUPS = {"structural", "floor", "walls", "wall", "lights", "overhead_lights"}


def _excerpt(text: Any, limit: int = 260) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _unique(seq: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in seq:
        item = str(item or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _agent_list(agent_roles: Dict[str, Any]) -> List[Dict[str, Any]]:
    agents = agent_roles.get("agents")
    if isinstance(agents, list):
        return [agent for agent in agents if isinstance(agent, dict)]
    return []


def _all_required_tags(agent_roles: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    for agent in _agent_list(agent_roles):
        tags.extend(str(tag) for tag in (agent.get("knowledge_tags") or []) if str(tag).strip())
    return _unique(tags)


def _all_agent_ids(agent_roles: Dict[str, Any]) -> List[str]:
    return _unique(agent.get("id") for agent in _agent_list(agent_roles))


def _object_lookup(normalized_scene: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup = {}
    for obj in normalized_scene.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        object_id = str(obj.get("object_id") or "").strip()
        if object_id:
            lookup[object_id] = obj
    return lookup


def _position_summary(obj: Dict[str, Any]) -> Dict[str, float]:
    position = obj.get("position") or {}
    return {
        "x": float(position.get("x") or 0.0),
        "z": float(position.get("z") or 0.0),
    }


def _is_structural_object(obj: Dict[str, Any]) -> bool:
    object_type = str(obj.get("object_type") or "").strip().lower()
    group = str(obj.get("group") or "").strip().lower()
    return object_type in STRUCTURAL_TYPES or group in STRUCTURAL_GROUPS


def _object_group_context(normalized_scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for obj in normalized_scene.get("objects") or []:
        if not isinstance(obj, dict) or _is_structural_object(obj):
            continue
        group = str(obj.get("group") or "ungrouped").strip() or "ungrouped"
        groups.setdefault(group, []).append(obj)

    result: List[Dict[str, Any]] = []
    for group in sorted(groups):
        objects = groups[group]
        representatives = objects[:6]
        result.append(
            {
                "group": group,
                "object_count": len(objects),
                "representative_objects": [
                    {
                        "object_id": str(obj.get("object_id") or ""),
                        "object_type": obj.get("object_type"),
                        "position_xz": _position_summary(obj),
                        "specification_excerpt": _excerpt(obj.get("specification"), 180),
                    }
                    for obj in representatives
                    if str(obj.get("object_id") or "").strip()
                ],
            }
        )
    return result


def _required_room_groups(normalized_scene: Dict[str, Any]) -> Set[str]:
    return {str(group["group"]) for group in _object_group_context(normalized_scene)}


def build_knowledge_payload(
    normalized_scene: Dict[str, Any],
    scene_semantics: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    object_lookup = _object_lookup(normalized_scene)
    grounded_ids: Set[str] = set()
    tag_requirements = []
    for agent in _agent_list(agent_roles):
        agent_id = str(agent.get("id") or "")
        agent_tags = _unique(agent.get("knowledge_tags") or [])
        object_ids = _unique(agent.get("grounded_object_ids") or [])
        grounded_ids.update(object_ids)
        for tag in agent_tags:
            tag_requirements.append(
                {
                    "tag": tag,
                    "agent_id": agent_id,
                    "agent_display_name": agent.get("display_name"),
                    "agent_persona": _excerpt(agent.get("persona"), 220),
                    "expertise": agent.get("expertise") or [],
                    "grounded_object_ids": object_ids,
                }
            )

    important_ids = [
        str(entry.get("object_id"))
        for entry in scene_semantics.get("important_objects") or []
        if isinstance(entry, dict) and str(entry.get("object_id") or "").strip()
    ]
    selected_ids = _unique(list(grounded_ids) + important_ids)
    object_context = []
    for object_id in selected_ids:
        obj = object_lookup.get(object_id)
        if not obj:
            continue
        object_context.append(
            {
                "object_id": object_id,
                "object_type": obj.get("object_type"),
                "group": obj.get("group"),
                "specification_excerpt": _excerpt(obj.get("specification")),
            }
        )

    return {
        "scene_name": normalized_scene.get("scene_name"),
        "domain": scene_semantics.get("domain"),
        "room_purpose": scene_semantics.get("room_purpose"),
        "room_question_requirement": (
            "Knowledge entries must allow an agent to answer questions such as "
            "'Welche Objekte gibt es hier?', 'Welche Bereiche/Zonen gibt es?' and "
            "'Wofuer sind diese Objekte im Raum relevant?' using object groups, zones, purpose and approximate positions."
        ),
        "visitor_goals": scene_semantics.get("visitor_goals"),
        "semantic_zones": scene_semantics.get("semantic_zones"),
        "interaction_topics": scene_semantics.get("interaction_topics"),
        "object_group_context": _object_group_context(normalized_scene),
        "required_room_groups": sorted(_required_room_groups(normalized_scene)),
        "agents": _agent_list(agent_roles),
        "tag_requirements": tag_requirements,
        "required_tags": _all_required_tags(agent_roles),
        "allowed_agent_ids": _all_agent_ids(agent_roles),
        "allowed_object_ids": list(object_lookup.keys()),
        "object_context": object_context,
    }


def knowledge_schema(required_tags: List[str], allowed_agent_ids: List[str], allowed_object_ids: List[str]) -> Dict[str, Any]:
    tags = required_tags or ["common"]
    agents = allowed_agent_ids or ["agent"]
    objects = allowed_object_ids or ["object"]
    return {
        "type": "object",
        "properties": {
            "knowledge_entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "enum": tags},
                        "name": {"type": "string"},
                        "source_object_ids": {"type": "array", "items": {"type": "string", "enum": objects}},
                        "text": {"type": "string"},
                        "intended_agents": {"type": "array", "items": {"type": "string", "enum": agents}},
                    },
                    "required": ["tag", "name", "source_object_ids", "text", "intended_agents"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["knowledge_entries"],
        "additionalProperties": False,
    }


def _agents_by_tag(agent_roles: Dict[str, Any]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for agent in _agent_list(agent_roles):
        agent_id = str(agent.get("id") or "")
        for tag in agent.get("knowledge_tags") or []:
            tag = str(tag)
            result.setdefault(tag, []).append(agent_id)
    return {tag: _unique(agent_ids) for tag, agent_ids in result.items()}


def _objects_by_tag(agent_roles: Dict[str, Any]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for agent in _agent_list(agent_roles):
        objects = _unique(agent.get("grounded_object_ids") or [])
        for tag in agent.get("knowledge_tags") or []:
            tag = str(tag)
            result.setdefault(tag, []).extend(objects[:4])
    return {tag: _unique(object_ids) for tag, object_ids in result.items()}


def normalize_knowledge_output(
    raw_output: Dict[str, Any],
    *,
    normalized_scene: Dict[str, Any],
    scene_semantics: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    required_tags = set(_all_required_tags(agent_roles))
    allowed_agents = set(_all_agent_ids(agent_roles))
    allowed_objects = set(_object_lookup(normalized_scene).keys())
    agents_by_tag = _agents_by_tag(agent_roles)
    objects_by_tag = _objects_by_tag(agent_roles)
    entries: List[Dict[str, Any]] = []

    for index, entry in enumerate(raw_output.get("knowledge_entries") or []):
        if not isinstance(entry, dict):
            continue
        tag = slugify(str(entry.get("tag") or ""), fallback="")
        if tag not in required_tags:
            continue
        name = slugify(str(entry.get("name") or f"{tag}_overview"), fallback=f"{tag}_overview")
        source_object_ids = [obj for obj in _unique(entry.get("source_object_ids") or []) if obj in allowed_objects]
        if not source_object_ids:
            source_object_ids = objects_by_tag.get(tag, [])[:3]
        intended_agents = [agent for agent in _unique(entry.get("intended_agents") or []) if agent in allowed_agents]
        if not intended_agents:
            intended_agents = agents_by_tag.get(tag, [])
        text = " ".join(str(entry.get("text") or "").split())
        if text:
            entries.append(
                {
                    "tag": tag,
                    "name": name,
                    "source_object_ids": source_object_ids,
                    "text": text,
                    "intended_agents": intended_agents,
                }
            )

    existing_tags = {entry["tag"] for entry in entries}
    object_lookup = _object_lookup(normalized_scene)
    for tag in sorted(required_tags - existing_tags):
        object_ids = objects_by_tag.get(tag, [])[:3]
        snippets = []
        for object_id in object_ids:
            obj = object_lookup.get(object_id, {})
            snippets.append(f"{object_id} ({obj.get('object_type', 'object')})")
        object_text = ", ".join(snippets) if snippets else "the overall room context"
        room_groups = ", ".join(sorted(_required_room_groups(normalized_scene))[:12])
        zone_names = ", ".join(
            str(zone.get("name") or zone.get("zone_id"))
            for zone in (scene_semantics.get("semantic_zones") or [])[:6]
            if isinstance(zone, dict)
        )
        entries.append(
            {
                "tag": tag,
                "name": f"{tag}_overview",
                "source_object_ids": object_ids,
                "text": (
                    f"This entry summarizes the {scene_semantics.get('domain', 'scene')} context for {tag}. "
                    f"It is grounded in {object_text} and should be used to answer visitor questions about "
                    f"{scene_semantics.get('room_purpose', 'the room purpose')}. "
                    f"Relevant room object groups include {room_groups or 'the available non-structural objects'}; "
                    f"semantic zones include {zone_names or 'the available activity areas'}."
                ),
                "intended_agents": agents_by_tag.get(tag, []),
            }
        )

    return {"knowledge_entries": entries}


def _contains_secret_or_path(text: str) -> bool:
    if re.search(r"sk-[A-Za-z0-9_-]+", text):
        return True
    if re.search(r"[A-Za-z]:\\", text):
        return True
    if "openai_api_key" in text.lower() or "bearer " in text.lower():
        return True
    return False


def validate_knowledge(
    knowledge: Dict[str, Any],
    *,
    normalized_scene: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    entries = knowledge.get("knowledge_entries") or []
    required_tags = set(_all_required_tags(agent_roles))
    allowed_agents = set(_all_agent_ids(agent_roles))
    object_lookup = _object_lookup(normalized_scene)
    allowed_objects = set(object_lookup.keys())
    required_room_groups = _required_room_groups(normalized_scene)
    covered_tags: Set[str] = set()
    referenced_objects: Set[str] = set()
    referenced_room_groups: Set[str] = set()
    tags_with_agents: Set[str] = set()

    if not isinstance(entries, list) or not entries:
        errors.append("knowledge_entries must contain at least one entry.")
        entries = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"knowledge_entries[{index}] is not an object.")
            continue
        tag = str(entry.get("tag") or "")
        if tag not in required_tags:
            errors.append(f"knowledge_entries[{index}] has unknown tag: {tag}.")
        covered_tags.add(tag)
        name = str(entry.get("name") or "")
        if slugify(name, fallback="") != name:
            errors.append(f"knowledge_entries[{index}].name is not slug-compatible: {name}.")
        text = str(entry.get("text") or "").strip()
        if not text:
            errors.append(f"knowledge_entries[{index}].text is empty.")
        elif _contains_secret_or_path(text):
            errors.append(f"knowledge_entries[{index}].text contains a secret-like token or local path.")
        source_object_ids = entry.get("source_object_ids") or []
        invalid_objects = sorted({str(obj) for obj in source_object_ids if str(obj) not in allowed_objects})
        if invalid_objects:
            errors.append(f"knowledge_entries[{index}] references unknown object_ids: {', '.join(invalid_objects)}.")
        referenced_objects.update(str(obj) for obj in source_object_ids if str(obj) in allowed_objects)
        for obj in source_object_ids:
            obj_payload = object_lookup.get(str(obj))
            if obj_payload and not _is_structural_object(obj_payload):
                referenced_room_groups.add(str(obj_payload.get("group") or "ungrouped"))
        intended_agents = entry.get("intended_agents") or []
        invalid_agents = sorted({str(agent) for agent in intended_agents if str(agent) not in allowed_agents})
        if invalid_agents:
            errors.append(f"knowledge_entries[{index}] references unknown agents: {', '.join(invalid_agents)}.")
        if intended_agents:
            tags_with_agents.add(tag)

    missing_tags = sorted(required_tags - covered_tags)
    if missing_tags:
        errors.append("Missing knowledge entries for tags: " + ", ".join(missing_tags))
    tags_without_agents = sorted((covered_tags & required_tags) - tags_with_agents)
    if tags_without_agents:
        errors.append("Knowledge entries lack intended_agents for tags: " + ", ".join(tags_without_agents))
    missing_room_groups = sorted(required_room_groups - referenced_room_groups)
    if missing_room_groups:
        errors.append("Knowledge entries do not cover important room object groups: " + ", ".join(missing_room_groups))

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "knowledge_entry_count": len(entries),
            "required_tag_count": len(required_tags),
            "covered_tag_count": len(covered_tags & required_tags),
            "referenced_object_count": len(referenced_objects),
            "required_room_group_count": len(required_room_groups),
            "covered_room_group_count": len(referenced_room_groups & required_room_groups),
            "room_group_coverage": (
                round(len(referenced_room_groups & required_room_groups) / len(required_room_groups), 6)
                if required_room_groups
                else 1.0
            ),
        },
    }


def materialize_knowledge_files(case_dir: Path, knowledge: Dict[str, Any]) -> List[Path]:
    written: List[Path] = []
    kb_root = case_dir / "interactive_agents_project" / "kb"
    for entry in knowledge.get("knowledge_entries") or []:
        tag = slugify(str(entry.get("tag") or ""), fallback="common")
        name = slugify(str(entry.get("name") or f"{tag}_entry"), fallback=f"{tag}_entry")
        path = kb_root / tag / f"{name}.txt"
        write_text(path, str(entry.get("text") or "").strip() + "\n")
        written.append(path)
    return written


def _build_messages(
    *,
    prompt_text: str,
    repair_prompt_text: str,
    payload: Dict[str, Any],
    previous_output: Optional[Dict[str, Any]] = None,
    validation_errors: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    user_payload: Dict[str, Any] = {
        "task": "Generate compact room-grounded knowledge entries for all required knowledge tags.",
        "scene": payload,
    }
    if previous_output is not None:
        user_payload["previous_invalid_output"] = previous_output
        user_payload["validation_errors"] = validation_errors or []
        user_payload["repair_instruction"] = repair_prompt_text
    return [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def run_knowledge_synthesis_for_case(
    case_dir: Path,
    *,
    model_override: Optional[str] = None,
    max_repair_attempts: int = 2,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    semantics_path = case_dir / "intermediate" / "scene_semantics.json"
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    knowledge_path = case_dir / "intermediate" / "knowledge.generated.json"
    validation_path = case_dir / "validation" / "knowledge_synthesis_validation.json"

    normalized_scene = read_json(normalized_path)
    scene_semantics = read_json(semantics_path)
    agent_roles = read_json(agent_roles_path)
    payload = build_knowledge_payload(normalized_scene, scene_semantics, agent_roles)
    schema = knowledge_schema(payload["required_tags"], payload["allowed_agent_ids"], payload["allowed_object_ids"])
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    repair_prompt_text = REPAIR_PROMPT_PATH.read_text(encoding="utf-8")

    validation: Dict[str, Any] = {
        "status": "invalid",
        "errors": ["KnowledgeSynthesis did not run."],
        "warnings": [],
        "metrics": {},
    }
    previous_output: Optional[Dict[str, Any]] = None
    last_response_meta: Dict[str, Any] = {}
    attempts_used = 0
    infrastructure_failed = False
    written_files: List[Path] = []

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
                payload=payload,
                previous_output=previous_output,
                validation_errors=validation.get("errors") if previous_output is not None else None,
            )
            raw_output, response_payload, _ = client.create_structured_json(
                input_messages=messages,
                schema=schema,
                schema_name="knowledge_synthesis",
                temperature=0.2,
                max_output_tokens=3200,
            )
            last_response_meta = response_metadata(response_payload)
            normalized_output = normalize_knowledge_output(
                raw_output,
                normalized_scene=normalized_scene,
                scene_semantics=scene_semantics,
                agent_roles=agent_roles,
            )
            validation = validate_knowledge(
                normalized_output,
                normalized_scene=normalized_scene,
                agent_roles=agent_roles,
            )
            write_json(knowledge_path, normalized_output)
            written_files = materialize_knowledge_files(case_dir, normalized_output)
            write_json(validation_path, validation)
            previous_output = normalized_output
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
        stage_id="knowledge_synthesis",
        status=status,
        input_paths=[normalized_path, semantics_path, agent_roles_path, PROMPT_PATH, REPAIR_PROMPT_PATH],
        output_paths=[knowledge_path, validation_path, *written_files],
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
        "knowledge_path": str(knowledge_path),
        "kb_root": str(case_dir / "interactive_agents_project" / "kb"),
        "validation_path": str(validation_path),
        "model": llm_metadata.get("model"),
        "attempts_used": attempts_used,
    }
