from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from .agent_roles import voice_gender_for_voice
from .common import read_json, slugify, update_manifest, write_json


PROMPT_VERSION = "roomcontract_assembly_v1"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{PROMPT_VERSION}.md"
ALLOWED_ENTITY_KINDS = {"agent", "asset", "zone", "signal", "stateObject"}
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
STRUCTURAL_OBJECT_TYPES = {"floor", "ceiling", "wall", "walls"}


def _case_prefix(case_id: str) -> str:
    return slugify(case_id, fallback="case").upper().replace("-", "_")


def _unique(seq: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in seq:
        item = str(item or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _object_lookup(normalized_scene: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(obj.get("object_id")): obj
        for obj in normalized_scene.get("objects") or []
        if isinstance(obj, dict) and str(obj.get("object_id") or "").strip()
    }


def _zone_entity_id(zone_id: str) -> str:
    return f"ENT-ZONE-{slugify(zone_id, fallback='zone').upper()}"


def _asset_entity_id(object_id: str) -> str:
    return f"ENT-ASSET-{slugify(object_id, fallback='object').upper()}"


def _object_group_entity_id(group_id: str) -> str:
    return f"ENT-GROUP-{slugify(group_id, fallback='group').upper()}"


def _agent_entity_id(agent_id: str) -> str:
    return f"ENT-AGENT-{slugify(agent_id, fallback='agent').upper()}"


def _is_structural_object(obj: Dict[str, Any]) -> bool:
    group = str(obj.get("group") or "").strip().lower()
    object_type = str(obj.get("object_type") or "").strip().lower()
    return group in STRUCTURAL_GROUP_NAMES or object_type in STRUCTURAL_OBJECT_TYPES


def _object_groups(normalized_scene: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for obj in normalized_scene.get("objects") or []:
        if not isinstance(obj, dict) or _is_structural_object(obj):
            continue
        group = str(obj.get("group") or "ungrouped").strip() or "ungrouped"
        groups.setdefault(group, []).append(obj)
    return groups


def _state_assertions(prefix: str) -> List[Dict[str, Any]]:
    rows = [
        ("NORMALIZED-SCENE-VALID", "Normalized RDL scene is valid and object IDs are unique."),
        ("SCENE-SEMANTICS-VALID", "Scene semantics are grounded in existing object IDs."),
        ("AGENT-ROLES-VALID", "Generated agents have valid zones, objects, knowledge tags and handoff targets."),
        ("KNOWLEDGE-VALID", "Every agent knowledge tag has at least one materialized knowledge entry."),
        ("PLACEMENT-VALID", "Every generated agent has a valid room position and forward vector."),
        ("ROOMCONTRACT-VALID", "RoomContract instance satisfies all core invariants."),
        ("PROJECT-MATERIALIZED", "Interactive Agents project files are present and backend-readable."),
        ("SETUP-VALID", "Interactive Agents backend setup returns a valid session with all agents."),
        ("ANSWER-GROUNDED", "A visitor question is answered using room-grounded agent knowledge."),
        ("HANDOFF-VALID", "A specialist handoff targets an existing responsible agent when needed."),
    ]
    return [
        {
            "id": f"SA-{prefix}-{suffix}",
            "subject_id": f"ENT-STATE-{prefix}",
            "expression": expression,
        }
        for suffix, expression in rows
    ]


def _events(prefix: str) -> List[Dict[str, Any]]:
    return [
        {"id": f"EV-{prefix}-RDL-PROVIDED", "kind": "environment", "expression": "source_rdl.json available"},
        {"id": f"EV-{prefix}-VISITOR-QUESTION", "kind": "user", "expression": "visitor asks a room-related question"},
        {"id": f"EV-{prefix}-HANDOFF-NEEDED", "kind": "user", "expression": "visitor question belongs to another agent expertise"},
    ]


def _conditions(prefix: str) -> List[Dict[str, Any]]:
    return [
        {"id": f"COND-{prefix}-VALID-INPUT", "kind": "precondition", "expression": "RDL input parses successfully"},
        {"id": f"COND-{prefix}-AGENTS-AVAILABLE", "kind": "guard", "expression": "at least two valid agents exist"},
        {"id": f"COND-{prefix}-HANDOFF-TARGET-AVAILABLE", "kind": "guard", "expression": "handoff target exists and is not the source agent"},
    ]


def _requirements(prefix: str) -> List[Dict[str, Any]]:
    return [
        {"id": f"REQ-{prefix}-001", "text": "The pipeline shall ingest an RDL scene and preserve stable object identities."},
        {"id": f"REQ-{prefix}-002", "text": "The pipeline shall derive room semantics grounded in existing RDL objects."},
        {"id": f"REQ-{prefix}-003", "text": "The pipeline shall synthesize backend-compatible spatial agent roles."},
        {"id": f"REQ-{prefix}-004", "text": "Every generated agent knowledge tag shall be covered by materialized knowledge."},
        {"id": f"REQ-{prefix}-005", "text": "Every generated agent shall be placed inside the room without obstacle overlap."},
        {"id": f"REQ-{prefix}-006", "text": "The generated behavior shall be traceable from requirements to runtime actions and validation cases."},
    ]


def _capabilities(prefix: str) -> List[Dict[str, Any]]:
    specs = [
        ("ANALYZE-RDL-SCENE", "Analyze RDL scene structure and normalize room objects.", ["NORMALIZED-SCENE-VALID", "SCENE-SEMANTICS-VALID"]),
        ("DERIVE-SPATIAL-AGENT-ROLES", "Derive agent roles grounded in semantic zones and objects.", ["AGENT-ROLES-VALID"]),
        ("GENERATE-ROOM-KNOWLEDGE", "Generate local knowledge entries for all agent knowledge tags.", ["KNOWLEDGE-VALID"]),
        ("PLACE-AGENTS-IN-SCENE", "Place agents in valid positions near their responsible zones.", ["PLACEMENT-VALID"]),
        ("ASSEMBLE-FUNCTIONAL-RDL", "Assemble a valid RoomContract instance for the case study.", ["ROOMCONTRACT-VALID"]),
        ("MATERIALIZE-INTERACTIVE-AGENTS-PROJECT", "Write backend-compatible Interactive Agents project files.", ["PROJECT-MATERIALIZED"]),
        ("SETUP-INTERACTIVE-SESSION", "Initialize the runtime session for the generated project.", ["SETUP-VALID"]),
        ("ANSWER-ROOM-GROUNDED-QUESTION", "Answer visitor questions using room-grounded agent knowledge.", ["ANSWER-GROUNDED"]),
        ("HANDOFF-TO-RESPONSIBLE-AGENT", "Forward a question to an existing responsible specialist agent.", ["HANDOFF-VALID"]),
    ]
    capabilities = []
    for capability_suffix, text, state_suffixes in specs:
        cap_id = f"CAP-{prefix}-{capability_suffix}"
        capabilities.append(
            {
                "id": cap_id,
                "name": capability_suffix.replace("-", " ").title(),
                "text": text,
                "precondition_ids": [],
                "effects": [
                    {
                        "id": f"EFF-{prefix}-{capability_suffix}-{index + 1:02d}",
                        "text": f"Effect of {capability_suffix}: {state_suffix.replace('-', ' ').lower()}.",
                        "evidencedBy": [f"SA-{prefix}-{state_suffix}"],
                    }
                    for index, state_suffix in enumerate(state_suffixes)
                ],
            }
        )
    return capabilities


def _runtime_bindings(prefix: str) -> List[Dict[str, Any]]:
    def action(action_id: str, *, endpoint: str | None = None, tool: str | None = None, input_schema: str = "json", output_schema: str = "json") -> Dict[str, Any]:
        return {
            "id": f"RA-{prefix}-{action_id}",
            "endpoint": endpoint,
            "tool": tool,
            "topic": None,
            "inputSchema": input_schema,
            "outputSchema": output_schema,
        }

    specs = [
        (
            "ANALYZE-RDL-SCENE",
            "CaseStudyPipeline",
            [
                action("RUN-RDL-INGESTION", tool="tools.case_study_pipeline.rdl_ingestion.run_ingestion_for_case"),
                action("RUN-SCENE-SEMANTICS", tool="tools.case_study_pipeline.scene_semantics.run_scene_semantics_for_case"),
                action("ARROW-ANALYZE", endpoint="POST /projects/arrow/analyze"),
            ],
        ),
        (
            "DERIVE-SPATIAL-AGENT-ROLES",
            "CaseStudyPipeline",
            [action("RUN-AGENT-ROLES", tool="tools.case_study_pipeline.agent_roles.run_agent_roles_for_case")],
        ),
        (
            "GENERATE-ROOM-KNOWLEDGE",
            "CaseStudyPipeline",
            [action("RUN-KNOWLEDGE-SYNTHESIS", tool="tools.case_study_pipeline.knowledge_synthesis.run_knowledge_synthesis_for_case")],
        ),
        (
            "PLACE-AGENTS-IN-SCENE",
            "CaseStudyPipeline",
            [action("RUN-AGENT-PLACEMENT", tool="tools.case_study_pipeline.agent_placement.run_agent_placement_for_case")],
        ),
        (
            "ASSEMBLE-FUNCTIONAL-RDL",
            "CaseStudyPipeline",
            [action("RUN-ROOMCONTRACT-ASSEMBLER", tool="tools.case_study_pipeline.roomcontract_assembler.run_roomcontract_assembly_for_case")],
        ),
        (
            "MATERIALIZE-INTERACTIVE-AGENTS-PROJECT",
            "agent_backendBackend",
            [
                action("ARROW-COMMIT", endpoint="POST /projects/arrow/commit"),
                action("WRITE-PROJECT-FILES", tool="tools.case_study_pipeline.project_materializer.run_project_materializer_for_case"),
            ],
        ),
        ("SETUP-INTERACTIVE-SESSION", "agent_backendBackend", [action("BACKEND-SETUP", endpoint="POST /setup")]),
        ("ANSWER-ROOM-GROUNDED-QUESTION", "agent_backendBackend", [action("BACKEND-CHAT", endpoint="POST /chat")]),
        ("HANDOFF-TO-RESPONSIBLE-AGENT", "agent_backendBackend", [action("BACKEND-CHAT-HANDOFF", endpoint="POST /chat")]),
    ]

    bindings = []
    for capability_suffix, platform, actions in specs:
        bindings.append(
            {
                "id": f"RB-{prefix}-{capability_suffix}",
                "capability_id": f"CAP-{prefix}-{capability_suffix}",
                "targetPlatform": platform,
                "runtimeActions": actions,
            }
        )
    return bindings


def _scenario_and_capability_uses(
    prefix: str,
    uc_id: str,
    *,
    agent_provider_entity_ids: Iterable[str],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Build the authoring pipeline scenario.

    User-facing room interactions are deliberately modeled separately by
    :func:`_interaction_use_cases`.  Keeping the pipeline trace independent
    preserves its stable S01--S09 identifiers while allowing every grounded
    scene object to carry its own provider and target chain.
    """

    steps_spec = [
        ("S01", "actorIntent", "ACT-CASE-STUDY-ENGINEER", "Provide an RDL file as case-study input.", [], ["RDL-PROVIDED"], "VALID-INPUT", []),
        ("S02", "systemResponse", None, "Load and normalize the RDL scene.", ["ANALYZE-RDL-SCENE"], [], None, ["NORMALIZED-SCENE-VALID"]),
        ("S03", "systemResponse", None, "Derive semantic zones, visitor goals and interaction topics.", ["ANALYZE-RDL-SCENE"], [], None, ["SCENE-SEMANTICS-VALID"]),
        ("S04", "systemResponse", None, "Generate spatially grounded agent roles and handoff rules.", ["DERIVE-SPATIAL-AGENT-ROLES"], [], None, ["AGENT-ROLES-VALID"]),
        ("S05", "systemResponse", None, "Generate materialized knowledge entries for all agent knowledge tags.", ["GENERATE-ROOM-KNOWLEDGE"], [], None, ["KNOWLEDGE-VALID"]),
        ("S06", "systemResponse", None, "Place generated agents inside the room near their responsibilities.", ["PLACE-AGENTS-IN-SCENE"], [], None, ["PLACEMENT-VALID"]),
        ("S07", "systemResponse", None, "Assemble and validate the RoomContract trace instance.", ["ASSEMBLE-FUNCTIONAL-RDL"], [], None, ["ROOMCONTRACT-VALID"]),
        ("S08", "systemResponse", None, "Materialize the Interactive Agents project files.", ["MATERIALIZE-INTERACTIVE-AGENTS-PROJECT"], [], None, ["PROJECT-MATERIALIZED"]),
        ("S09", "systemResponse", None, "Set up an Interactive Agents runtime session.", ["SETUP-INTERACTIVE-SESSION"], [], "AGENTS-AVAILABLE", ["SETUP-VALID"]),
        # Keep one targetless chat/handoff chain per agent for ordinary text and
        # voice. Object-specific deictic chains are modeled separately below.
        # The provider-specific chains prevent a general request made to one
        # agent from borrowing another agent's runtime evidence.
        ("S10", "actorIntent", "ACT-VISITOR", "Ask a general room-related question to an agent.", [], ["VISITOR-QUESTION"], None, []),
        ("S11", "systemResponse", None, "Answer a general visitor question without a selected scene object.", ["ANSWER-ROOM-GROUNDED-QUESTION"], [], None, ["ANSWER-GROUNDED"]),
        ("S12", "systemResponse", None, "Optionally hand off a general question to a responsible specialist agent.", ["HANDOFF-TO-RESPONSIBLE-AGENT"], ["HANDOFF-NEEDED"], "HANDOFF-TARGET-AVAILABLE", ["HANDOFF-VALID"]),
    ]
    provider_entity_ids = _unique(agent_provider_entity_ids)
    if not provider_entity_ids:
        raise ValueError("At least one agent provider is required for user-facing communication.")
    capability_uses: List[Dict[str, Any]] = []
    steps = []
    for index, (step_suffix, kind, actor_id, text, capabilities, event_suffixes, condition_suffix, state_suffixes) in enumerate(steps_spec, start=1):
        step_id = f"STEP-{prefix}-{step_suffix}"
        use_ids = []
        for capability_suffix in capabilities:
            provider_ids = (
                provider_entity_ids
                if capability_suffix
                in {
                    "ANSWER-ROOM-GROUNDED-QUESTION",
                    "HANDOFF-TO-RESPONSIBLE-AGENT",
                }
                else [""]
            )
            for provider_entity_id in provider_ids:
                provider_token = ""
                if provider_entity_id:
                    raw_provider_token = provider_entity_id
                    if raw_provider_token.startswith("ENT-AGENT-"):
                        raw_provider_token = raw_provider_token[len("ENT-AGENT-") :]
                    provider_token = (
                        slugify(raw_provider_token, fallback="agent")
                        .upper()
                    )
                cu_id = "-".join(
                    part
                    for part in (
                        "CU",
                        prefix,
                        provider_token,
                        step_suffix,
                        capability_suffix,
                    )
                    if part
                )
                use_ids.append(cu_id)
                capability_use = {
                    "id": cu_id,
                    "step_id": step_id,
                    "capability_id": f"CAP-{prefix}-{capability_suffix}",
                    "parameters": [],
                }
                if provider_entity_id:
                    capability_use["preferred_provider_entity_id"] = provider_entity_id
                capability_uses.append(capability_use)
        steps.append(
            {
                "id": step_id,
                "stepNumber": index,
                "kind": kind,
                "performedBy": actor_id,
                "text": text,
                "occurrenceProbability": 1.0,
                "triggeredBy": [f"EV-{prefix}-{suffix}" for suffix in event_suffixes],
                "guard": f"COND-{prefix}-{condition_suffix}" if condition_suffix else None,
                "resultingState": [f"SA-{prefix}-{suffix}" for suffix in state_suffixes],
                "capabilityUseIds": use_ids,
            }
        )

    relations = [
        {
            "id": f"REL-{prefix}-{i:02d}-{i + 1:02d}",
            "kind": "sequence",
            "source_step_id": steps[i - 1]["id"],
            "target_step_id": steps[i]["id"],
            "guard": None,
            "probability": 1.0,
        }
        for i in range(1, len(steps))
    ]
    scenario = {
        "id": f"SC-{prefix}-MAIN",
        "kind": "main",
        "description": "Authoring pipeline for generating and validating a spatially grounded multi-agent room guide.",
        "precondition_ids": [f"COND-{prefix}-VALID-INPUT"],
        "postcondition_ids": [f"SA-{prefix}-SETUP-VALID"],
        "steps": steps,
        "stepRelations": relations,
        "parallelGroups": [],
    }
    return scenario, capability_uses


def _interaction_targets(
    *,
    normalized_scene: Dict[str, Any],
    scene_semantics: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Resolve one fail-closed interaction owner for every grounded asset.

    Only object IDs explicitly grounded by an agent are routable here.  The
    owner is therefore resolved at the highest-priority asset tier; group and
    zone references are retained as transparent target context.  Competing
    asset owners are an ambiguity and must not silently fall through to a
    lower-priority group or zone owner.
    """

    object_lookup = _object_lookup(normalized_scene)
    agents = [
        agent
        for agent in (agent_roles.get("agents") or [])
        if isinstance(agent, dict) and str(agent.get("id") or "").strip()
    ]
    owners_by_object: Dict[str, List[Dict[str, Any]]] = {}
    for agent in agents:
        for object_id in _unique(agent.get("grounded_object_ids") or []):
            if object_id not in object_lookup:
                raise ValueError(
                    f"Agent {agent.get('id')} grounds missing scene object {object_id}."
                )
            owners_by_object.setdefault(object_id, []).append(agent)

    zones_by_object: Dict[str, List[str]] = {}
    for zone in scene_semantics.get("semantic_zones") or []:
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("zone_id") or "").strip()
        if not zone_id:
            continue
        for object_id in _unique(zone.get("object_ids") or []):
            zones_by_object.setdefault(object_id, []).append(zone_id)

    ordered_object_ids = [
        str(obj.get("object_id"))
        for obj in normalized_scene.get("objects") or []
        if isinstance(obj, dict) and str(obj.get("object_id") or "") in owners_by_object
    ]
    interaction_targets: List[Dict[str, Any]] = []
    used_tokens: Dict[str, str] = {}
    for object_id in ordered_object_ids:
        owners = owners_by_object[object_id]
        if len(owners) != 1:
            owner_ids = ", ".join(str(owner.get("id")) for owner in owners)
            raise ValueError(
                f"Grounded scene object {object_id} has ambiguous asset owners: {owner_ids}."
            )
        owner = owners[0]
        owner_id = str(owner.get("id"))
        obj = object_lookup[object_id]
        token = slugify(object_id, fallback="object").upper().replace("-", "_")
        previous = used_tokens.setdefault(token, object_id)
        if previous != object_id:
            raise ValueError(
                f"Scene object IDs {previous} and {object_id} collapse to interaction token {token}."
            )

        responsible_zone_ids = set(_unique(owner.get("responsible_zone_ids") or []))
        object_zone_ids = _unique(zones_by_object.get(object_id) or [])
        target_zone_ids = [
            zone_id for zone_id in object_zone_ids if zone_id in responsible_zone_ids
        ]
        if object_zone_ids and not target_zone_ids:
            raise ValueError(
                f"Asset owner {owner_id} has no responsible zone containing {object_id}."
            )

        group_id = str(obj.get("group") or "ungrouped").strip() or "ungrouped"
        target_entity_ids = [_asset_entity_id(object_id)]
        if not _is_structural_object(obj):
            target_entity_ids.append(_object_group_entity_id(group_id))
        target_entity_ids.extend(_zone_entity_id(zone_id) for zone_id in target_zone_ids)
        interaction_targets.append(
            {
                "object_id": object_id,
                "object_token": token,
                "object_name": str(obj.get("object_type") or object_id),
                "provider_entity_id": _agent_entity_id(owner_id),
                "provider_name": str(owner.get("display_name") or owner_id),
                "target_entity_ids": target_entity_ids,
                "responsibility_tier": "asset",
            }
        )

    if not interaction_targets:
        raise ValueError("No explicitly grounded scene object is available for interaction modeling.")
    return interaction_targets


def _interaction_use_cases(
    *,
    prefix: str,
    interaction_targets: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Create one concrete user-facing scenario for each routable asset."""

    use_cases: List[Dict[str, Any]] = []
    capability_uses: List[Dict[str, Any]] = []
    for target in interaction_targets:
        object_token = target["object_token"]
        object_name = target["object_name"]
        object_id = target["object_id"]
        provider_name = target["provider_name"]
        provider_entity_id = target["provider_entity_id"]
        target_entity_ids = list(target["target_entity_ids"])
        use_case_id = f"UC-{prefix}-INTERACT-{object_token}"
        scenario_id = f"SC-{prefix}-INTERACT-{object_token}-MAIN"

        ask_step_id = f"STEP-{prefix}-INTERACT-{object_token}-ASK"
        answer_step_id = f"STEP-{prefix}-INTERACT-{object_token}-ANSWER"
        handoff_step_id = f"STEP-{prefix}-INTERACT-{object_token}-HANDOFF"
        answer_use_id = (
            f"CU-{prefix}-INTERACT-{object_token}-ANSWER-ROOM-GROUNDED-QUESTION"
        )
        handoff_use_id = (
            f"CU-{prefix}-INTERACT-{object_token}-HANDOFF-TO-RESPONSIBLE-AGENT"
        )

        answer_capability_id = f"CAP-{prefix}-ANSWER-ROOM-GROUNDED-QUESTION"
        handoff_capability_id = f"CAP-{prefix}-HANDOFF-TO-RESPONSIBLE-AGENT"
        capability_uses.extend(
            [
                {
                    "id": answer_use_id,
                    "step_id": answer_step_id,
                    "capability_id": answer_capability_id,
                    "preferred_provider_entity_id": provider_entity_id,
                    "target_entity_ids": target_entity_ids,
                    "parameters": [],
                },
                {
                    "id": handoff_use_id,
                    "step_id": handoff_step_id,
                    "capability_id": handoff_capability_id,
                    "preferred_provider_entity_id": provider_entity_id,
                    "target_entity_ids": target_entity_ids,
                    "parameters": [],
                },
            ]
        )
        steps = [
            {
                "id": ask_step_id,
                "stepNumber": 1,
                "kind": "actorIntent",
                "performedBy": "ACT-VISITOR",
                "text": f"Select {object_name} ({object_id}) and ask for a description.",
                "occurrenceProbability": 1.0,
                "triggeredBy": [f"EV-{prefix}-VISITOR-QUESTION"],
                "guard": None,
                "resultingState": [],
                "capabilityUseIds": [],
            },
            {
                "id": answer_step_id,
                "stepNumber": 2,
                "kind": "systemResponse",
                "performedBy": "ACT-ROOM-GUIDE",
                "text": (
                    f"{provider_name} describes {object_name} using knowledge grounded "
                    f"in source object {object_id}."
                ),
                "occurrenceProbability": 1.0,
                "triggeredBy": [],
                "guard": None,
                "resultingState": [f"SA-{prefix}-ANSWER-GROUNDED"],
                "capabilityUseIds": [answer_use_id],
            },
            {
                "id": handoff_step_id,
                "stepNumber": 3,
                "kind": "systemResponse",
                "performedBy": "ACT-ROOM-GUIDE",
                "text": (
                    f"Constrain any follow-up handoff about {object_name} to the "
                    f"modeled responsibility of {provider_name}."
                ),
                "occurrenceProbability": 1.0,
                "triggeredBy": [f"EV-{prefix}-HANDOFF-NEEDED"],
                "guard": f"COND-{prefix}-HANDOFF-TARGET-AVAILABLE",
                "resultingState": [f"SA-{prefix}-HANDOFF-VALID"],
                "capabilityUseIds": [handoff_use_id],
            },
        ]
        relations = [
            {
                "id": f"REL-{prefix}-INTERACT-{object_token}-{relation_index:02d}",
                "kind": "sequence",
                "source_step_id": steps[relation_index - 1]["id"],
                "target_step_id": steps[relation_index]["id"],
                "guard": None,
                "probability": 1.0,
            }
            for relation_index in range(1, len(steps))
        ]
        scenario = {
            "id": scenario_id,
            "kind": "main",
            "description": (
                f"Visitor asks about source object {object_id}; the model binds the "
                f"interaction to {provider_name} and its asset, group, and zone context."
            ),
            "precondition_ids": [f"COND-{prefix}-AGENTS-AVAILABLE"],
            "postcondition_ids": [
                f"SA-{prefix}-ANSWER-GROUNDED",
                f"SA-{prefix}-HANDOFF-VALID",
            ],
            "steps": steps,
            "stepRelations": relations,
            "parallelGroups": [],
        }
        use_cases.append(
            {
                "id": use_case_id,
                "name": f"Describe grounded scene object {object_id}",
                "actor_ids": ["ACT-VISITOR", "ACT-ROOM-GUIDE"],
                "extensionPoints": [],
                "includes": [],
                "extends": [],
                "scenarios": [scenario],
            }
        )
    return use_cases, capability_uses


def _entities(
    *,
    prefix: str,
    normalized_scene: Dict[str, Any],
    scene_semantics: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> List[Dict[str, Any]]:
    object_lookup = _object_lookup(normalized_scene)
    referenced_objects: Set[str] = set()
    for agent in agent_roles.get("agents") or []:
        referenced_objects.update(
            str(obj) for obj in (agent.get("grounded_object_ids") or [])
        )
    entities: List[Dict[str, Any]] = []
    for zone in scene_semantics.get("semantic_zones") or []:
        zone_id = str(zone.get("zone_id") or "")
        if zone_id:
            entities.append(
                {
                    "id": _zone_entity_id(zone_id),
                    "name": zone.get("name") or zone_id,
                    "kind": "zone",
                    "source_id": zone_id,
                    "entityRole": "semanticZone",
                    "source_object_ids": _unique(zone.get("object_ids") or []),
                    "purpose": zone.get("purpose"),
                }
            )
    for group_id, group_objects in sorted(_object_groups(normalized_scene).items()):
        grounded_group_objects = [
            obj
            for obj in group_objects
            if str(obj.get("object_id") or "") in referenced_objects
        ]
        if not grounded_group_objects:
            # An object group is part of the executable interaction contract only
            # when at least one modeled agent grounds an asset in that group.
            # Keeping unowned scene-only groups would manufacture a responsibility
            # relation that neither the generated roles nor the runtime can honor.
            continue
        entities.append(
            {
                "id": _object_group_entity_id(group_id),
                "name": f"Object group: {group_id}",
                "kind": "asset",
                "source_id": f"group:{group_id}",
                "entityRole": "objectGroup",
                "source_group": group_id,
                "source_object_ids": _unique(
                    obj.get("object_id") for obj in grounded_group_objects
                ),
            }
        )
    for object_id in sorted(referenced_objects):
        obj = object_lookup.get(object_id)
        if obj:
            group_id = str(obj.get("group") or "ungrouped").strip() or "ungrouped"
            entity = {
                "id": _asset_entity_id(object_id),
                "name": obj.get("object_type") or object_id,
                "kind": "asset",
                "source_id": object_id,
                "entityRole": "sceneObject",
                "source_group": group_id,
                "object_type": obj.get("object_type"),
            }
            if not _is_structural_object(obj):
                entity["object_group_entity_id"] = _object_group_entity_id(group_id)
            entities.append(entity)
    for agent in agent_roles.get("agents") or []:
        agent_id = str(agent.get("id") or "")
        if agent_id:
            entities.append(
                {
                    "id": _agent_entity_id(agent_id),
                    "name": agent.get("display_name") or agent_id,
                    "kind": "agent",
                    "source_id": agent_id,
                    "entityRole": "interactiveAgent",
                }
            )
    entities.append({"id": f"ENT-STATE-{prefix}", "name": "Case study validation state", "kind": "stateObject", "source_id": "validation_state"})
    return entities


def _responsibility_trace(agent: Dict[str, Any], object_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    zone_ids = _unique(agent.get("responsible_zone_ids") or [])
    object_ids = _unique(agent.get("grounded_object_ids") or [])
    group_ids = _unique(
        str(object_lookup.get(object_id, {}).get("group") or "ungrouped").strip() or "ungrouped"
        for object_id in object_ids
        if object_lookup.get(object_id) and not _is_structural_object(object_lookup[object_id])
    )
    return {
        "responsible_zone_ids": zone_ids,
        "responsibleZoneEntityIds": [_zone_entity_id(zone_id) for zone_id in zone_ids],
        "grounded_object_ids": object_ids,
        "groundedAssetEntityIds": [_asset_entity_id(object_id) for object_id in object_ids],
        "grounded_object_groups": group_ids,
        "groundedObjectGroupEntityIds": [_object_group_entity_id(group_id) for group_id in group_ids],
    }


def assemble_roomcontract_instance(
    *,
    case_id: str,
    normalized_scene: Dict[str, Any],
    scene_semantics: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    prefix = _case_prefix(case_id)
    object_lookup = _object_lookup(normalized_scene)
    requirements = _requirements(prefix)
    uc_id = f"UC-{prefix}-01"
    interaction_targets = _interaction_targets(
        normalized_scene=normalized_scene,
        scene_semantics=scene_semantics,
        agent_roles=agent_roles,
    )
    pipeline_scenario, capability_uses = _scenario_and_capability_uses(
        prefix,
        uc_id,
        agent_provider_entity_ids=[
            _agent_entity_id(str(agent.get("id") or ""))
            for agent in agent_roles.get("agents") or []
            if str(agent.get("id") or "").strip()
        ],
    )
    interaction_use_cases, interaction_capability_uses = _interaction_use_cases(
        prefix=prefix,
        interaction_targets=interaction_targets,
    )
    capability_uses.extend(interaction_capability_uses)
    actors = [
        {"id": "ACT-CASE-STUDY-ENGINEER", "name": "Case Study Engineer", "description": "Provides RDL input and runs the validation pipeline."},
        {"id": "ACT-VISITOR", "name": "Visitor", "description": "Asks room-related questions in the generated immersive environment."},
        {"id": "ACT-ROOM-GUIDE", "name": "Room Guide", "description": "Role played by generated interactive agents."},
    ]
    agents = []
    for agent in agent_roles.get("agents") or []:
        agent_id = str(agent.get("id") or "")
        responsibility_trace = _responsibility_trace(agent, object_lookup)
        voice = str(agent.get("voice") or "alloy").strip() or "alloy"
        handoff_targets = _unique(agent.get("handoff_targets") or [])
        agents.append(
            {
                "id": f"AG-{prefix}-{slugify(agent_id, fallback='agent').upper()}",
                "source_agent_id": agent_id,
                "entity_id": _agent_entity_id(agent_id),
                "playsActor": ["ACT-ROOM-GUIDE"],
                "providedCapabilityIds": [
                    f"CAP-{prefix}-ANSWER-ROOM-GROUNDED-QUESTION",
                    f"CAP-{prefix}-HANDOFF-TO-RESPONSIBLE-AGENT",
                ],
                "handoff_targets": handoff_targets,
                "handoffTargetAgentIds": [
                    f"AG-{prefix}-{slugify(target_id, fallback='agent').upper()}"
                    for target_id in handoff_targets
                ],
                "display_name": agent.get("display_name") or agent_id,
                "persona": agent.get("persona") or "",
                "expertise": agent.get("expertise") or [],
                "knowledge_tags": agent.get("knowledge_tags") or [],
                "voice": voice,
                "voice_gender": agent.get("voice_gender") or voice_gender_for_voice(voice),
                "voice_style": agent.get("voice_style") or "neutral",
                "tts_model": agent.get("tts_model") or "gpt-4o-mini-tts",
                **responsibility_trace,
            }
        )
    pipeline_use_case = {
        "id": uc_id,
        "name": "Generate spatially grounded multi-agent guide",
        "actor_ids": ["ACT-CASE-STUDY-ENGINEER", "ACT-ROOM-GUIDE"],
        "extensionPoints": [],
        "includes": [],
        "extends": [],
        "scenarios": [pipeline_scenario],
    }
    use_cases = [pipeline_use_case, *interaction_use_cases]
    representative_use_case_id = interaction_use_cases[0]["id"]
    capabilities = _capabilities(prefix)
    validation_cases = [
        {
            "id": f"VC-{prefix}-RDL-INGESTION",
            "level": "concrete",
            "validates_use_case_ids": [uc_id],
            "verifies_requirement_ids": [f"REQ-{prefix}-001"],
            "stimulus_ids": [f"EV-{prefix}-RDL-PROVIDED"],
            "runtime_binding_ids": [f"RB-{prefix}-ANALYZE-RDL-SCENE"],
            "expectedOutcome": [f"SA-{prefix}-NORMALIZED-SCENE-VALID"],
        },
        {
            "id": f"VC-{prefix}-MODEL-INVARIANTS",
            "level": "concrete",
            "validates_use_case_ids": [uc_id],
            "verifies_requirement_ids": [f"REQ-{prefix}-006"],
            "stimulus_ids": [],
            "runtime_binding_ids": [f"RB-{prefix}-ASSEMBLE-FUNCTIONAL-RDL"],
            "expectedOutcome": [f"SA-{prefix}-ROOMCONTRACT-VALID"],
        },
        {
            "id": f"VC-{prefix}-PROJECT-MATERIALIZATION",
            "level": "concrete",
            "validates_use_case_ids": [uc_id],
            "verifies_requirement_ids": [f"REQ-{prefix}-004", f"REQ-{prefix}-005"],
            "stimulus_ids": [],
            "runtime_binding_ids": [f"RB-{prefix}-MATERIALIZE-INTERACTIVE-AGENTS-PROJECT"],
            "expectedOutcome": [f"SA-{prefix}-PROJECT-MATERIALIZED"],
        },
        {
            "id": f"VC-{prefix}-SETUP",
            "level": "concrete",
            "validates_use_case_ids": [uc_id],
            "verifies_requirement_ids": [f"REQ-{prefix}-003", f"REQ-{prefix}-005"],
            "stimulus_ids": [],
            "runtime_binding_ids": [f"RB-{prefix}-SETUP-INTERACTIVE-SESSION"],
            "expectedOutcome": [f"SA-{prefix}-SETUP-VALID"],
        },
        {
            "id": f"VC-{prefix}-CHAT-GROUNDING",
            "level": "concrete",
            "validates_use_case_ids": [representative_use_case_id],
            "verifies_requirement_ids": [f"REQ-{prefix}-002", f"REQ-{prefix}-004", f"REQ-{prefix}-006"],
            "stimulus_ids": [f"EV-{prefix}-VISITOR-QUESTION"],
            "runtime_binding_ids": [f"RB-{prefix}-ANSWER-ROOM-GROUNDED-QUESTION"],
            "expectedOutcome": [f"SA-{prefix}-ANSWER-GROUNDED"],
        },
        {
            "id": f"VC-{prefix}-HANDOFF",
            "level": "concrete",
            "validates_use_case_ids": [representative_use_case_id],
            "verifies_requirement_ids": [f"REQ-{prefix}-003", f"REQ-{prefix}-006"],
            "stimulus_ids": [f"EV-{prefix}-HANDOFF-NEEDED"],
            "runtime_binding_ids": [f"RB-{prefix}-HANDOFF-TO-RESPONSIBLE-AGENT"],
            "expectedOutcome": [f"SA-{prefix}-HANDOFF-VALID"],
        },
    ]
    for target, interaction_use_case in zip(
        interaction_targets[1:],
        interaction_use_cases[1:],
    ):
        validation_cases.append(
            {
                "id": f"VC-{prefix}-INTERACT-{target['object_token']}",
                "level": "concrete",
                "validates_use_case_ids": [interaction_use_case["id"]],
                "verifies_requirement_ids": [
                    f"REQ-{prefix}-002",
                    f"REQ-{prefix}-003",
                    f"REQ-{prefix}-004",
                    f"REQ-{prefix}-006",
                ],
                "stimulus_ids": [
                    f"EV-{prefix}-VISITOR-QUESTION",
                    f"EV-{prefix}-HANDOFF-NEEDED",
                ],
                "runtime_binding_ids": [
                    f"RB-{prefix}-ANSWER-ROOM-GROUNDED-QUESTION",
                    f"RB-{prefix}-HANDOFF-TO-RESPONSIBLE-AGENT",
                ],
                "expectedOutcome": [
                    f"SA-{prefix}-ANSWER-GROUNDED",
                    f"SA-{prefix}-HANDOFF-VALID",
                ],
            }
        )
    satisfy = [
        {
            "id": f"SAT-{req['id']}",
            "satisfiedRequirement": [req["id"]],
            "satisfiedUseCase": [],
            "satisfiedBy": [
                uc_id,
                *[use_case["id"] for use_case in interaction_use_cases],
                f"VC-{prefix}-MODEL-INVARIANTS",
            ],
        }
        for req in requirements
    ]
    return {
        "schema": "roomcontract_case_study",
        "metamodelVersion": "v0.5",
        "caseId": case_id,
        "requirementsModel": {
            "id": f"RM-{prefix}",
            "requirements": requirements,
            "useCases": use_cases,
        },
        "actors": actors,
        "entities": _entities(prefix=prefix, normalized_scene=normalized_scene, scene_semantics=scene_semantics, agent_roles=agent_roles),
        "agents": agents,
        "events": _events(prefix),
        "conditions": _conditions(prefix),
        "stateAssertions": _state_assertions(prefix),
        "capabilityUses": capability_uses,
        "capabilities": capabilities,
        "runtimeBindings": _runtime_bindings(prefix),
        "validationCases": validation_cases,
        "satisfyRelationships": satisfy,
    }


def validate_roomcontract_instance(instance: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    actors = {a.get("id") for a in instance.get("actors", []) if isinstance(a, dict)}
    entities = {e.get("id"): e for e in instance.get("entities", []) if isinstance(e, dict)}
    events = {e.get("id") for e in instance.get("events", []) if isinstance(e, dict)}
    conditions = {c.get("id") for c in instance.get("conditions", []) if isinstance(c, dict)}
    state_assertions = {s.get("id") for s in instance.get("stateAssertions", []) if isinstance(s, dict)}
    capabilities = {c.get("id"): c for c in instance.get("capabilities", []) if isinstance(c, dict)}
    capability_uses = {cu.get("id"): cu for cu in instance.get("capabilityUses", []) if isinstance(cu, dict)}
    runtime_bindings = {rb.get("id"): rb for rb in instance.get("runtimeBindings", []) if isinstance(rb, dict)}
    validation_cases = instance.get("validationCases") or []
    use_cases = (instance.get("requirementsModel") or {}).get("useCases") or []
    use_case_ids = {
        use_case.get("id")
        for use_case in use_cases
        if isinstance(use_case, dict) and use_case.get("id")
    }
    requirements = {r.get("id") for r in (instance.get("requirementsModel") or {}).get("requirements", []) if isinstance(r, dict)}
    agent_by_entity_id = {
        agent.get("entity_id"): agent
        for agent in instance.get("agents", [])
        if isinstance(agent, dict) and agent.get("entity_id")
    }
    step_owners_by_capability_use: Dict[str, List[str]] = {}

    for entity_id, entity in entities.items():
        kind = entity.get("kind")
        if kind is not None and kind not in ALLOWED_ENTITY_KINDS:
            errors.append(f"Entity {entity_id} has invalid kind: {kind}.")
        group_entity_id = entity.get("object_group_entity_id")
        if group_entity_id and group_entity_id not in entities:
            errors.append(f"SceneObject Entity {entity_id} references missing object group entity {group_entity_id}.")

    for state_assertion in instance.get("stateAssertions", []) or []:
        subject_id = state_assertion.get("subject_id")
        if subject_id not in entities:
            errors.append(f"StateAssertion {state_assertion.get('id')} references missing subject {subject_id}.")

    agent_ids = {agent.get("id") for agent in instance.get("agents", []) if isinstance(agent, dict)}
    if agent_ids & actors:
        errors.append("Agent IDs must not be reused as Actor IDs.")
    covered_object_group_entities: Set[str] = set()
    for agent in instance.get("agents", []) or []:
        for field in ("source_agent_id", "display_name", "persona", "voice", "voice_gender", "voice_style", "tts_model"):
            if not str(agent.get(field) or "").strip():
                errors.append(f"Agent {agent.get('id')} has empty required field {field}.")
        for field in ("expertise", "knowledge_tags", "providedCapabilityIds"):
            if not isinstance(agent.get(field), list) or not agent.get(field):
                errors.append(f"Agent {agent.get('id')} must contain non-empty {field}.")
        if str(agent.get("tts_model") or "").strip().lower() == "standard":
            errors.append(f"Agent {agent.get('id')} uses non-concrete tts_model=standard.")
        entity_id = agent.get("entity_id")
        if entity_id not in entities:
            errors.append(f"Agent {agent.get('id')} references missing entity {entity_id}.")
        elif entities[entity_id].get("kind") != "agent":
            errors.append(f"Agent {agent.get('id')} entity is not kind=agent.")
        for actor_id in agent.get("playsActor") or []:
            if actor_id not in actors:
                errors.append(f"Agent {agent.get('id')} plays unknown actor {actor_id}.")
        expected_zone_entities = {_zone_entity_id(zone_id) for zone_id in agent.get("responsible_zone_ids") or []}
        actual_zone_entities = {str(entity_id) for entity_id in agent.get("responsibleZoneEntityIds") or []}
        if expected_zone_entities != actual_zone_entities:
            errors.append(f"Agent {agent.get('id')} has inconsistent responsible zone entity trace.")
        for zone_entity_id in actual_zone_entities:
            if zone_entity_id not in entities:
                errors.append(f"Agent {agent.get('id')} references missing zone entity {zone_entity_id}.")
            elif entities[zone_entity_id].get("kind") != "zone":
                errors.append(f"Agent {agent.get('id')} references non-zone entity {zone_entity_id} as responsibility.")

        expected_asset_entities = {_asset_entity_id(object_id) for object_id in agent.get("grounded_object_ids") or []}
        actual_asset_entities = {str(entity_id) for entity_id in agent.get("groundedAssetEntityIds") or []}
        if expected_asset_entities != actual_asset_entities:
            errors.append(f"Agent {agent.get('id')} has inconsistent grounded asset entity trace.")
        for asset_entity_id in actual_asset_entities:
            if asset_entity_id not in entities:
                errors.append(f"Agent {agent.get('id')} references missing asset entity {asset_entity_id}.")
            elif entities[asset_entity_id].get("kind") != "asset":
                errors.append(f"Agent {agent.get('id')} references non-asset entity {asset_entity_id} as grounded object.")

        expected_group_entities = {
            _object_group_entity_id(group_id)
            for group_id in agent.get("grounded_object_groups") or []
            if _object_group_entity_id(group_id) in entities
        }
        actual_group_entities = {str(entity_id) for entity_id in agent.get("groundedObjectGroupEntityIds") or []}
        if expected_group_entities != actual_group_entities:
            errors.append(f"Agent {agent.get('id')} has inconsistent object group entity trace.")
        for group_entity_id in actual_group_entities:
            if group_entity_id not in entities:
                errors.append(f"Agent {agent.get('id')} references missing object group entity {group_entity_id}.")
            elif entities[group_entity_id].get("entityRole") != "objectGroup":
                errors.append(f"Agent {agent.get('id')} references non-objectGroup entity {group_entity_id}.")
        covered_object_group_entities.update(actual_group_entities)

    object_group_entities = {
        entity_id
        for entity_id, entity in entities.items()
        if entity.get("entityRole") == "objectGroup"
    }
    missing_object_group_entities = sorted(object_group_entities - covered_object_group_entities)
    if missing_object_group_entities:
        errors.append(
            "Object group entities are not grounded by any RoomContract agent: "
            + ", ".join(missing_object_group_entities)
        )

    for use_case in use_cases:
        scenarios = use_case.get("scenarios") or []
        main_count = sum(1 for scenario in scenarios if scenario.get("kind") == "main")
        if main_count != 1:
            errors.append(f"UseCase {use_case.get('id')} must have exactly one main Scenario, got {main_count}.")
        for scenario in scenarios:
            for condition_id in (scenario.get("precondition_ids") or []) + (scenario.get("postcondition_ids") or []):
                if condition_id.startswith("COND-") and condition_id not in conditions:
                    errors.append(f"Scenario {scenario.get('id')} references unknown Condition {condition_id}.")
                if condition_id.startswith("SA-") and condition_id not in state_assertions:
                    errors.append(f"Scenario {scenario.get('id')} references unknown StateAssertion {condition_id}.")
            steps = scenario.get("steps") or []
            if not steps:
                errors.append(f"Scenario {scenario.get('id')} has no steps.")
            step_ids = {step.get("id") for step in steps}
            for step in steps:
                if "runtimeActionIds" in step or "runtime_actions" in step:
                    errors.append(f"ScenarioStep {step.get('id')} directly references RuntimeAction.")
                if step.get("kind") == "actorIntent" and not step.get("performedBy"):
                    errors.append(f"ActorIntent step {step.get('id')} has no performedBy Actor.")
                if step.get("performedBy") and step.get("performedBy") not in actors:
                    errors.append(f"ScenarioStep {step.get('id')} references unknown Actor {step.get('performedBy')}.")
                for event_id in step.get("triggeredBy") or []:
                    if event_id not in events:
                        errors.append(f"ScenarioStep {step.get('id')} references unknown Event {event_id}.")
                if step.get("guard") and step.get("guard") not in conditions:
                    errors.append(f"ScenarioStep {step.get('id')} references unknown Condition {step.get('guard')}.")
                for cu_id in step.get("capabilityUseIds") or []:
                    if cu_id not in capability_uses:
                        errors.append(f"ScenarioStep {step.get('id')} references unknown CapabilityUse {cu_id}.")
                    else:
                        step_owners_by_capability_use.setdefault(cu_id, []).append(
                            str(step.get("id") or "")
                        )
                for state_id in step.get("resultingState") or []:
                    if state_id not in state_assertions:
                        errors.append(f"ScenarioStep {step.get('id')} references unknown StateAssertion {state_id}.")
            for relation in scenario.get("stepRelations") or []:
                if relation.get("source_step_id") not in step_ids or relation.get("target_step_id") not in step_ids:
                    errors.append(f"StepRelation {relation.get('id')} references a step outside its Scenario.")
            for group in scenario.get("parallelGroups") or []:
                members = group.get("memberStepIds") or []
                if len(members) < 2:
                    errors.append(f"ParallelGroup {group.get('id')} has fewer than two members.")
                if any(member not in step_ids for member in members):
                    errors.append(f"ParallelGroup {group.get('id')} references a step outside its Scenario.")

    for cu_id, capability_use in capability_uses.items():
        capability_id = capability_use.get("capability_id")
        if not capability_id or capability_id not in capabilities:
            errors.append(f"CapabilityUse {cu_id} must reference exactly one existing Capability.")
        owning_steps = step_owners_by_capability_use.get(str(cu_id), [])
        if len(owning_steps) != 1:
            errors.append(
                f"CapabilityUse {cu_id} must be composed by exactly one ScenarioStep."
            )
        elif capability_use.get("step_id") != owning_steps[0]:
            errors.append(
                f"CapabilityUse {cu_id} step_id does not match its composing ScenarioStep."
            )

        is_user_facing = str(capability_id or "").endswith(
            (
                "-ANSWER-ROOM-GROUNDED-QUESTION",
                "-HANDOFF-TO-RESPONSIBLE-AGENT",
            )
        )
        if not is_user_facing:
            continue

        provider_entity_id = str(
            capability_use.get("preferred_provider_entity_id") or ""
        ).strip()
        target_entity_ids = _unique(capability_use.get("target_entity_ids") or [])
        if not provider_entity_id:
            errors.append(
                f"User-facing CapabilityUse {cu_id} has no preferred provider."
            )
            continue
        provider = agent_by_entity_id.get(provider_entity_id)
        if provider is None:
            errors.append(
                f"User-facing CapabilityUse {cu_id} references unknown Agent entity "
                f"{provider_entity_id}."
            )
            continue
        if capability_id not in (provider.get("providedCapabilityIds") or []):
            errors.append(
                f"Preferred provider {provider_entity_id} does not provide "
                f"Capability {capability_id}."
            )
        if not target_entity_ids:
            generic_targetless_id = str(cu_id).endswith(
                (
                    "-S11-ANSWER-ROOM-GROUNDED-QUESTION",
                    "-S12-HANDOFF-TO-RESPONSIBLE-AGENT",
                )
            )
            if generic_targetless_id:
                continue
            errors.append(f"User-facing CapabilityUse {cu_id} has no explicit target.")
            continue
        unknown_targets = [
            target_id for target_id in target_entity_ids if target_id not in entities
        ]
        if unknown_targets:
            errors.append(
                f"User-facing CapabilityUse {cu_id} references unknown targets: "
                + ", ".join(unknown_targets)
            )
            continue

        provider_assets = set(provider.get("groundedAssetEntityIds") or [])
        provider_groups = set(provider.get("groundedObjectGroupEntityIds") or [])
        provider_zones = set(provider.get("responsibleZoneEntityIds") or [])
        asset_targets = [
            target_id
            for target_id in target_entity_ids
            if entities[target_id].get("entityRole") == "sceneObject"
        ]
        if len(asset_targets) != 1 or asset_targets[0] not in provider_assets:
            errors.append(
                f"User-facing CapabilityUse {cu_id} must target exactly one asset "
                f"grounded by provider {provider_entity_id}."
            )
            continue
        asset = entities[asset_targets[0]]
        expected_groups = {
            str(asset.get("object_group_entity_id"))
        } if asset.get("object_group_entity_id") else set()
        actual_groups = {
            target_id
            for target_id in target_entity_ids
            if entities[target_id].get("entityRole") == "objectGroup"
        }
        if actual_groups != expected_groups or not actual_groups.issubset(provider_groups):
            errors.append(
                f"User-facing CapabilityUse {cu_id} has a group target inconsistent "
                f"with asset {asset_targets[0]} and provider {provider_entity_id}."
            )
        source_object_id = str(asset.get("source_id") or "")
        expected_zones = {
            target_id
            for target_id in provider_zones
            if source_object_id in (entities.get(target_id, {}).get("source_object_ids") or [])
        }
        actual_zones = {
            target_id
            for target_id in target_entity_ids
            if entities[target_id].get("entityRole") == "semanticZone"
        }
        if actual_zones != expected_zones:
            errors.append(
                f"User-facing CapabilityUse {cu_id} has zone targets inconsistent "
                f"with asset {asset_targets[0]} and provider {provider_entity_id}."
            )

    for capability_id, capability in capabilities.items():
        for forbidden in ("endpoint", "tool", "topic", "runtimeActionIds"):
            if forbidden in capability:
                errors.append(f"Capability {capability_id} contains forbidden technical field {forbidden}.")
        effects = capability.get("effects") or []
        if not effects:
            errors.append(f"Capability {capability_id} has no Effect.")
        for effect in effects:
            for state_id in effect.get("evidencedBy") or []:
                if state_id not in state_assertions:
                    errors.append(f"Effect {effect.get('id')} references unknown StateAssertion {state_id}.")

    for rb_id, binding in runtime_bindings.items():
        capability_id = binding.get("capability_id")
        if capability_id not in capabilities:
            errors.append(f"RuntimeBinding {rb_id} references unknown Capability {capability_id}.")
        actions = binding.get("runtimeActions") or []
        if not actions:
            errors.append(f"RuntimeBinding {rb_id} must contain at least one RuntimeAction.")
        for action in actions:
            if not (action.get("endpoint") or action.get("tool") or action.get("topic")):
                errors.append(f"RuntimeAction {action.get('id')} must define endpoint, tool or topic.")

    answer_capability_ids = [
        capability_id
        for capability_id in capabilities
        if str(capability_id).endswith("-ANSWER-ROOM-GROUNDED-QUESTION")
    ]
    handoff_capability_ids = [
        capability_id
        for capability_id in capabilities
        if str(capability_id).endswith("-HANDOFF-TO-RESPONSIBLE-AGENT")
    ]
    if not answer_capability_ids:
        errors.append("RoomContract instance has no ANSWER-ROOM-GROUNDED-QUESTION Capability.")
    if not handoff_capability_ids:
        errors.append("RoomContract instance has no HANDOFF-TO-RESPONSIBLE-AGENT Capability.")
    handoff_bindings = [
        binding
        for binding in runtime_bindings.values()
        if binding.get("capability_id") in handoff_capability_ids
    ]
    if not handoff_bindings:
        errors.append("HANDOFF-TO-RESPONSIBLE-AGENT Capability has no RuntimeBinding.")
    handoff_actions = [
        action
        for binding in handoff_bindings
        for action in binding.get("runtimeActions") or []
        if str(action.get("id") or "").endswith("-BACKEND-CHAT-HANDOFF")
    ]
    if not handoff_actions:
        errors.append("Handoff RuntimeBinding has no BACKEND-CHAT-HANDOFF RuntimeAction.")
    for action in handoff_actions:
        if action.get("endpoint") != "POST /chat":
            errors.append(f"Handoff RuntimeAction {action.get('id')} must use endpoint POST /chat.")

    for validation_case in validation_cases:
        expected = validation_case.get("expectedOutcome") or []
        if not expected:
            errors.append(f"ValidationCase {validation_case.get('id')} has no expectedOutcome.")
        for use_case_id in validation_case.get("validates_use_case_ids") or []:
            if use_case_id not in use_case_ids:
                errors.append(
                    f"ValidationCase {validation_case.get('id')} references unknown "
                    f"UseCase {use_case_id}."
                )
        for state_id in expected:
            if state_id not in state_assertions:
                errors.append(f"ValidationCase {validation_case.get('id')} references unknown StateAssertion {state_id}.")
        for rb_id in validation_case.get("runtime_binding_ids") or []:
            if rb_id not in runtime_bindings:
                errors.append(f"ValidationCase {validation_case.get('id')} references unknown RuntimeBinding {rb_id}.")

    for satisfy in instance.get("satisfyRelationships") or []:
        reqs = satisfy.get("satisfiedRequirement") or []
        ucs = satisfy.get("satisfiedUseCase") or []
        if bool(reqs) == bool(ucs):
            errors.append(f"Satisfy {satisfy.get('id')} violates requirement/useCase XOR.")
        for req_id in reqs:
            if req_id not in requirements:
                errors.append(f"Satisfy {satisfy.get('id')} references unknown Requirement {req_id}.")
        if not satisfy.get("satisfiedBy"):
            errors.append(f"Satisfy {satisfy.get('id')} has empty satisfiedBy.")

    capability_use_coverage = len({cu.get("capability_id") for cu in capability_uses.values() if cu.get("capability_id") in capabilities})
    runtime_capability_coverage = len({rb.get("capability_id") for rb in runtime_bindings.values() if rb.get("capability_id") in capabilities})
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "requirement_count": len(requirements),
            "use_case_count": len(use_cases),
            "interaction_use_case_count": sum(
                1
                for use_case in use_cases
                if "-INTERACT-" in str(use_case.get("id") or "")
            ),
            "entity_count": len(entities),
            "semantic_zone_entity_count": sum(1 for entity in entities.values() if entity.get("entityRole") == "semanticZone"),
            "object_group_entity_count": sum(1 for entity in entities.values() if entity.get("entityRole") == "objectGroup"),
            "scene_object_entity_count": sum(1 for entity in entities.values() if entity.get("entityRole") == "sceneObject"),
            "room_answer_capability_count": len(answer_capability_ids),
            "handoff_capability_count": len(handoff_capability_ids),
            "handoff_runtime_binding_count": len(handoff_bindings),
            "handoff_runtime_action_count": len(handoff_actions),
            "capability_count": len(capabilities),
            "capability_use_count": len(capability_uses),
            "explicit_user_provider_count": sum(
                1
                for capability_use in capability_uses.values()
                if capability_use.get("preferred_provider_entity_id")
            ),
            "runtime_binding_count": len(runtime_bindings),
            "validation_case_count": len(validation_cases),
            "capability_use_coverage": capability_use_coverage,
            "runtime_capability_coverage": runtime_capability_coverage,
        },
    }


def run_roomcontract_assembly_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
    semantics_path = case_dir / "intermediate" / "scene_semantics.json"
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    placements_path = case_dir / "intermediate" / "agent_placements.json"
    instance_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    validation_path = case_dir / "validation" / "roomcontract_invariant_validation.json"

    instance = assemble_roomcontract_instance(
        case_id=case_dir.name,
        normalized_scene=read_json(normalized_path),
        scene_semantics=read_json(semantics_path),
        agent_roles=read_json(agent_roles_path),
    )
    validation = validate_roomcontract_instance(instance)
    write_json(instance_path, instance)
    write_json(validation_path, validation)
    status = "success" if validation["status"] == "valid" else "needs_manual_review"
    update_manifest(
        case_dir,
        stage_id="roomcontract_assembly",
        status=status,
        input_paths=[
            normalized_path,
            semantics_path,
            agent_roles_path,
            placements_path,
            PROMPT_PATH,
            Path(__file__).resolve(),
        ],
        output_paths=[instance_path, validation_path],
        errors=validation.get("errors"),
        warnings=validation.get("warnings"),
        metadata={"prompt_version": PROMPT_VERSION, "deterministic": True, "metrics": validation.get("metrics", {})},
    )
    return {
        "case_id": case_dir.name,
        "status": status,
        "validation": validation,
        "roomcontract_path": str(instance_path),
        "validation_path": str(validation_path),
    }
