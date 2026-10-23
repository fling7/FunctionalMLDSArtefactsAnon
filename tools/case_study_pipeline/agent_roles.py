from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .common import read_json, slugify, update_manifest, write_json
from .llm_client import ResponsesClient, load_llm_settings, response_metadata, sanitize_error_text
from .scene_semantics import _compact_objects


PROMPT_VERSION = "agent_roles_v1"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{PROMPT_VERSION}.md"
REPAIR_PROMPT_VERSION = "repair_invalid_handoff_targets_v1"
REPAIR_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{REPAIR_PROMPT_VERSION}.md"
ALLOWED_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
VOICE_GENDER_BY_VOICE = {
    "coral": "weiblich",
    "nova": "weiblich",
    "shimmer": "weiblich",
    "sage": "weiblich",
    "alloy": "maennlich",
    "ash": "maennlich",
    "ballad": "maennlich",
    "echo": "maennlich",
    "fable": "maennlich",
    "onyx": "maennlich",
    "verse": "maennlich",
}


def _unique(seq: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in seq:
        item = str(item or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def voice_gender_for_voice(voice: str) -> str:
    voice = str(voice or "").strip().lower()
    return VOICE_GENDER_BY_VOICE.get(voice, "weiblich" if voice in {"coral", "nova", "shimmer", "sage"} else "maennlich")


def _zone_object_map(scene_semantics: Dict[str, Any]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for zone in scene_semantics.get("semantic_zones") or []:
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("zone_id") or "").strip()
        object_ids = [str(obj_id) for obj_id in (zone.get("object_ids") or []) if str(obj_id).strip()]
        if zone_id:
            result[zone_id] = object_ids
    return result


def _collect_zone_ids(scene_semantics: Dict[str, Any]) -> List[str]:
    return [
        str(zone.get("zone_id"))
        for zone in scene_semantics.get("semantic_zones") or []
        if isinstance(zone, dict) and str(zone.get("zone_id") or "").strip()
    ]


def _collect_object_ids(normalized_scene: Dict[str, Any]) -> List[str]:
    return [
        str(obj.get("object_id"))
        for obj in normalized_scene.get("objects") or []
        if isinstance(obj, dict) and str(obj.get("object_id") or "").strip()
    ]


def build_agent_roles_payload(
    normalized_scene: Dict[str, Any],
    object_group_summary: Dict[str, Any],
    scene_semantics: Dict[str, Any],
) -> Dict[str, Any]:
    compact_objects, structural_object_ids = _compact_objects(normalized_scene)
    compact_groups = []
    for group in object_group_summary.get("groups") or []:
        if not isinstance(group, dict) or group.get("is_structural"):
            continue
        compact_groups.append(
            {
                "group": group.get("group"),
                "object_count": group.get("object_count"),
                "object_types": group.get("object_types"),
                "centroid_xz": group.get("centroid_xz"),
            }
        )
    return {
        "scene_name": normalized_scene.get("scene_name"),
        "domain": scene_semantics.get("domain"),
        "room_purpose": scene_semantics.get("room_purpose"),
        "visitor_goals": scene_semantics.get("visitor_goals"),
        "semantic_zones": scene_semantics.get("semantic_zones"),
        "interaction_topics": scene_semantics.get("interaction_topics"),
        "agent_role_candidates": scene_semantics.get("agent_role_candidates"),
        "object_groups": compact_groups,
        "non_structural_objects": compact_objects,
        "allowed_zone_ids": _collect_zone_ids(scene_semantics),
        "allowed_object_ids": _collect_object_ids(normalized_scene),
        "structural_object_ids": structural_object_ids,
        "allowed_voices": ALLOWED_VOICES,
        "required_tts_model": DEFAULT_TTS_MODEL,
    }


def _string_array_schema_with_enum(values: List[str]) -> Dict[str, Any]:
    return {"type": "array", "items": {"type": "string", "enum": values}}


def agent_roles_schema(allowed_zone_ids: List[str], allowed_object_ids: List[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "agents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "display_name": {"type": "string"},
                        "persona": {"type": "string"},
                        "expertise": {"type": "array", "items": {"type": "string"}},
                        "knowledge_tags": {"type": "array", "items": {"type": "string"}},
                        "responsible_zone_ids": _string_array_schema_with_enum(allowed_zone_ids),
                        "grounded_object_ids": _string_array_schema_with_enum(allowed_object_ids),
                        "handoff_targets": {"type": "array", "items": {"type": "string"}},
                        "voice": {"type": "string", "enum": ALLOWED_VOICES},
                        "voice_gender": {"type": "string"},
                        "voice_style": {"type": "string"},
                        "tts_model": {"type": "string"},
                    },
                    "required": [
                        "id",
                        "display_name",
                        "persona",
                        "expertise",
                        "knowledge_tags",
                        "responsible_zone_ids",
                        "grounded_object_ids",
                        "handoff_targets",
                        "voice",
                        "voice_gender",
                        "voice_style",
                        "tts_model",
                    ],
                    "additionalProperties": False,
                },
            },
            "handoffs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_agent_id": {"type": "string"},
                        "target_agent_id": {"type": "string"},
                        "condition": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["source_agent_id", "target_agent_id", "condition", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["agents", "handoffs"],
        "additionalProperties": False,
    }


def normalize_agent_roles_output(
    raw_output: Dict[str, Any],
    scene_semantics: Dict[str, Any],
) -> Dict[str, Any]:
    zone_to_objects = _zone_object_map(scene_semantics)
    old_to_new: Dict[str, str] = {}
    used_ids: Set[str] = set()
    agents: List[Dict[str, Any]] = []

    for index, agent in enumerate(raw_output.get("agents") or []):
        if not isinstance(agent, dict):
            continue
        raw_id = str(agent.get("id") or agent.get("display_name") or f"agent_{index + 1}")
        base_id = slugify(raw_id, fallback=f"agent_{index + 1}")
        agent_id = base_id
        suffix = 2
        while agent_id in used_ids:
            agent_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(agent_id)
        old_to_new[raw_id] = agent_id
        old_to_new[base_id] = agent_id

        responsible_zone_ids = _unique(agent.get("responsible_zone_ids") or [])
        grounded_object_ids = _unique(agent.get("grounded_object_ids") or [])
        if not grounded_object_ids:
            for zone_id in responsible_zone_ids:
                grounded_object_ids.extend(zone_to_objects.get(zone_id, [])[:2])
            grounded_object_ids = _unique(grounded_object_ids)

        knowledge_tags = [slugify(tag, fallback="common") for tag in (agent.get("knowledge_tags") or [])]
        if not knowledge_tags:
            knowledge_tags = [slugify(zone_id, fallback=agent_id) for zone_id in responsible_zone_ids[:2]]
        if not knowledge_tags:
            knowledge_tags = [agent_id]

        tts_model = str(agent.get("tts_model") or "").strip()
        if not tts_model or tts_model.lower() == "standard":
            tts_model = DEFAULT_TTS_MODEL

        voice = str(agent.get("voice") or "").strip().lower()
        if voice not in ALLOWED_VOICES:
            voice = ALLOWED_VOICES[index % len(ALLOWED_VOICES)]
        voice_gender = str(agent.get("voice_gender") or "").strip()
        if not voice_gender:
            voice_gender = voice_gender_for_voice(voice)

        agents.append(
            {
                "id": agent_id,
                "display_name": str(agent.get("display_name") or agent_id).strip() or agent_id,
                "persona": str(agent.get("persona") or "").strip(),
                "expertise": _unique(agent.get("expertise") or []),
                "knowledge_tags": _unique(knowledge_tags),
                "responsible_zone_ids": responsible_zone_ids,
                "grounded_object_ids": grounded_object_ids,
                "handoff_targets": _unique(agent.get("handoff_targets") or []),
                "voice": voice,
                "voice_gender": voice_gender,
                "voice_style": str(agent.get("voice_style") or "neutral").strip() or "neutral",
                "tts_model": tts_model,
            }
        )

    known_ids = {agent["id"] for agent in agents}
    for agent in agents:
        remapped_targets = []
        for target in agent["handoff_targets"]:
            target_id = old_to_new.get(str(target), slugify(str(target), fallback=""))
            if target_id and target_id in known_ids and target_id != agent["id"]:
                remapped_targets.append(target_id)
        agent["handoff_targets"] = _unique(remapped_targets)

    handoffs: List[Dict[str, Any]] = []
    seen_pairs: Set[Tuple[str, str]] = set()
    for handoff in raw_output.get("handoffs") or []:
        if not isinstance(handoff, dict):
            continue
        source = old_to_new.get(str(handoff.get("source_agent_id")), slugify(str(handoff.get("source_agent_id") or ""), fallback=""))
        target = old_to_new.get(str(handoff.get("target_agent_id")), slugify(str(handoff.get("target_agent_id") or ""), fallback=""))
        if not source or not target or source == target or source not in known_ids or target not in known_ids:
            continue
        pair = (source, target)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        handoffs.append(
            {
                "source_agent_id": source,
                "target_agent_id": target,
                "condition": str(handoff.get("condition") or "Visitor question belongs to the target agent expertise.").strip(),
                "reason": str(handoff.get("reason") or "The target agent has the more specific responsibility.").strip(),
            }
        )

    for agent in agents:
        for target in agent["handoff_targets"]:
            pair = (agent["id"], target)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                handoffs.append(
                    {
                        "source_agent_id": agent["id"],
                        "target_agent_id": target,
                        "condition": "Visitor question belongs to the target agent expertise.",
                        "reason": "Target agent is responsible for the referenced zone or topic.",
                    }
                )

    return {"agents": agents, "handoffs": handoffs}


def validate_agent_roles(
    agent_roles: Dict[str, Any],
    *,
    scene_semantics: Dict[str, Any],
    normalized_scene: Dict[str, Any],
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    allowed_zone_ids = set(_collect_zone_ids(scene_semantics))
    allowed_object_ids = set(_collect_object_ids(normalized_scene))
    agents = agent_roles.get("agents") or []
    handoffs = agent_roles.get("handoffs") or []

    if not isinstance(agents, list) or not (2 <= len(agents) <= 8):
        errors.append("AgentRoleSynthesis requires 2 to 8 agents.")
        agents = []

    agent_ids: Set[str] = set()
    all_knowledge_tags: Set[str] = set()
    grounded_objects: Set[str] = set()
    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            errors.append(f"agents[{index}] is not an object.")
            continue
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id:
            errors.append(f"agents[{index}].id is empty.")
        elif slugify(agent_id, fallback="") != agent_id:
            errors.append(f"agents[{index}].id is not slug-compatible: {agent_id}.")
        elif agent_id in agent_ids:
            errors.append(f"Duplicate agent id: {agent_id}.")
        agent_ids.add(agent_id)

        if not str(agent.get("persona") or "").strip():
            errors.append(f"agents[{index}].persona is empty.")
        expertise = agent.get("expertise") or []
        if not isinstance(expertise, list) or not expertise:
            errors.append(f"agents[{index}] needs at least one expertise item.")

        knowledge_tags = agent.get("knowledge_tags") or []
        if not isinstance(knowledge_tags, list) or not knowledge_tags:
            errors.append(f"agents[{index}] needs at least one knowledge_tag.")
            knowledge_tags = []
        for tag in knowledge_tags:
            tag = str(tag)
            if slugify(tag, fallback="") != tag:
                errors.append(f"agents[{index}] has non-slug knowledge_tag: {tag}.")
            all_knowledge_tags.add(tag)

        zones = agent.get("responsible_zone_ids") or []
        objects = agent.get("grounded_object_ids") or []
        if not zones and not objects:
            errors.append(f"agents[{index}] must reference at least one zone or object.")
        invalid_zones = sorted({str(zone) for zone in zones if str(zone) not in allowed_zone_ids})
        invalid_objects = sorted({str(obj) for obj in objects if str(obj) not in allowed_object_ids})
        if invalid_zones:
            errors.append(f"agents[{index}] references unknown zone_ids: {', '.join(invalid_zones)}.")
        if invalid_objects:
            errors.append(f"agents[{index}] references unknown object_ids: {', '.join(invalid_objects)}.")
        grounded_objects.update(str(obj) for obj in objects if str(obj) in allowed_object_ids)

        tts_model = str(agent.get("tts_model") or "").strip().lower()
        if not tts_model or tts_model == "standard":
            errors.append(f"agents[{index}].tts_model must be concrete, not standard.")
        if str(agent.get("voice") or "").strip().lower() not in ALLOWED_VOICES:
            errors.append(f"agents[{index}].voice is not in the allowed voice set.")
        if not str(agent.get("voice_gender") or "").strip():
            errors.append(f"agents[{index}].voice_gender is empty.")

    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            continue
        source = str(agent.get("id") or "")
        targets = agent.get("handoff_targets") or []
        if not isinstance(targets, list):
            errors.append(f"agents[{index}].handoff_targets must be a list.")
            continue
        for target in targets:
            target = str(target)
            if target == source:
                errors.append(f"agents[{index}] contains a self-handoff target.")
            elif target not in agent_ids:
                errors.append(f"agents[{index}] references unknown handoff target: {target}.")

    handoff_pairs: Set[Tuple[str, str]] = set()
    for index, handoff in enumerate(handoffs if isinstance(handoffs, list) else []):
        source = str(handoff.get("source_agent_id") or "") if isinstance(handoff, dict) else ""
        target = str(handoff.get("target_agent_id") or "") if isinstance(handoff, dict) else ""
        if source not in agent_ids:
            errors.append(f"handoffs[{index}] has unknown source_agent_id: {source}.")
        if target not in agent_ids:
            errors.append(f"handoffs[{index}] has unknown target_agent_id: {target}.")
        if source and source == target:
            errors.append(f"handoffs[{index}] is a self-handoff.")
        if (source, target) in handoff_pairs:
            warnings.append(f"Duplicate handoff pair ignored by consumers: {source}->{target}.")
        handoff_pairs.add((source, target))
        if not str(handoff.get("condition") or "").strip():
            errors.append(f"handoffs[{index}].condition is empty.")
        if not str(handoff.get("reason") or "").strip():
            errors.append(f"handoffs[{index}].reason is empty.")

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "agent_count": len(agents),
            "knowledge_tag_count": len(all_knowledge_tags),
            "handoff_count": len(handoffs) if isinstance(handoffs, list) else 0,
            "grounded_object_count": len(grounded_objects),
        },
    }


def _build_messages(
    *,
    prompt_text: str,
    repair_prompt_text: str,
    payload: Dict[str, Any],
    previous_output: Optional[Dict[str, Any]] = None,
    validation_errors: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    user_payload: Dict[str, Any] = {
        "task": "Generate backend-compatible Interactive Agents roles and handoff matrix.",
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


def run_agent_roles_for_case(
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
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    handoff_path = case_dir / "intermediate" / "handoff_matrix.json"
    validation_path = case_dir / "validation" / "agent_roles_validation.json"

    normalized_scene = read_json(normalized_path)
    group_summary = read_json(group_summary_path)
    scene_semantics = read_json(semantics_path)
    payload = build_agent_roles_payload(normalized_scene, group_summary, scene_semantics)
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    repair_prompt_text = REPAIR_PROMPT_PATH.read_text(encoding="utf-8")
    schema = agent_roles_schema(payload["allowed_zone_ids"], payload["allowed_object_ids"])

    validation: Dict[str, Any] = {
        "status": "invalid",
        "errors": ["AgentRoleSynthesis did not run."],
        "warnings": [],
        "metrics": {},
    }
    attempts_used = 0
    previous_output: Optional[Dict[str, Any]] = None
    last_response_meta: Dict[str, Any] = {}
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
                payload=payload,
                previous_output=previous_output,
                validation_errors=validation.get("errors") if previous_output is not None else None,
            )
            raw_output, response_payload, _ = client.create_structured_json(
                input_messages=messages,
                schema=schema,
                schema_name="agent_roles",
                temperature=0.2,
                max_output_tokens=2200,
            )
            last_response_meta = response_metadata(response_payload)
            normalized_output = normalize_agent_roles_output(raw_output, scene_semantics)
            validation = validate_agent_roles(
                normalized_output,
                scene_semantics=scene_semantics,
                normalized_scene=normalized_scene,
            )
            # Keep the normalized handoff declarations with the role artifact as
            # well as in the dedicated matrix.  The downstream deterministic
            # handoff stage may validate or enrich these declarations, but should
            # not have to mutate an earlier LLM-stage output merely to add data
            # that was already returned by that stage.  This keeps later
            # knowledge-stage fingerprints stable across offline reruns.
            write_json(
                agent_roles_path,
                {
                    "agents": normalized_output["agents"],
                    "handoffs": normalized_output["handoffs"],
                },
            )
            write_json(handoff_path, {"handoffs": normalized_output["handoffs"]})
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
        stage_id="agent_roles",
        status=status,
        input_paths=[normalized_path, group_summary_path, semantics_path, PROMPT_PATH, REPAIR_PROMPT_PATH],
        output_paths=[agent_roles_path, handoff_path, validation_path],
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
        "agent_roles_path": str(agent_roles_path),
        "handoff_matrix_path": str(handoff_path),
        "validation_path": str(validation_path),
        "model": llm_metadata.get("model"),
        "attempts_used": attempts_used,
    }
