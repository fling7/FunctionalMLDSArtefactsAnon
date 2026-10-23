#!/usr/bin/env python3
"""Lossless v0.5 compatibility projection for Dynamic Functional RDL V2.

The existing ``roomcontract.instance.generated.json`` contract is a runtime
contract.  It is deliberately *not* changed by V2.  This module imports that
contract into a V2 projection envelope and keeps a separate
``V05ProjectionLedger`` with all information that must not be inferred:

* field presence versus missing fields, explicit nulls and empty containers;
* object-key and array order, identifiers and original enum lexemes;
* raw step numbers, validation-case ``level`` values and all three legacy
  runtime-action locator slots;
* the distinct ``AG-*``, ``ENT-AGENT-*`` and source-agent identities; and
* the first use case / first main scenario relied on by the current backend.

Export is intentionally fail-closed.  A projection is exported only when the
semantic projection, exact v0.5 payload and ledger still agree.  V2-only data
therefore raises :class:`RepresentabilityError` instead of being discarded.
Re-import an intentionally edited v0.5 document to create a fresh ledger.

The CLI writes executable compatibility evidence below
``output/metamodel_v2/evidence`` without modifying any v0.5 or runtime file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dynamic_functional_rdl_v2_model import MODEL


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V05_FILENAME = "roomcontract.instance.generated.json"
V05_SCHEMA = "roomcontract_case_study"
V05_METAMODEL_VERSION = "v0.5"
V2_PROJECTION_SCHEMA = "dynamic_functional_rdl_v2_projection"
V2_PROJECTION_VERSION = "v2.0"
LEDGER_SCHEMA = "V05ProjectionLedger"
LEDGER_VERSION = "1.0"

EXPECTED_CASE_IDS = {
    "bestfit_career_fair",
    "classroom_dinosaur",
    "steinpilz_brand_room",
    "cheese_factory_tradefair_booth_36f00adc",
    "classroom_with_reading_area_and_dinosaur_26649c3f",
    "rdlsteinpilz_e2e_1783611970",
    "rdlsteinpilz_probe",
    "rdlsteinpilz_uidiag_abs_repair_1783611709",
}

V05_TOP_LEVEL_FIELDS = (
    "schema",
    "metamodelVersion",
    "caseId",
    "requirementsModel",
    "actors",
    "entities",
    "agents",
    "events",
    "conditions",
    "stateAssertions",
    "capabilityUses",
    "capabilities",
    "runtimeBindings",
    "validationCases",
    "satisfyRelationships",
)

ENVELOPE_FIELDS = {
    "schema",
    "metamodelVersion",
    "caseId",
    "dynamicFunctionalModel",
    "v05Projection",
    "v05ProjectionLedger",
    "v2Extensions",
}


class RepresentabilityError(ValueError):
    """Raised when a value cannot be exported to v0.5 without information loss."""


def _json_bytes(value: Any) -> bytes:
    """Return deterministic bytes while retaining insertion order of objects."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def structural_sha256(value: Any) -> str:
    """Hash JSON structure, including object-key and array order."""

    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _pointer_escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _walk_concrete(value: Any, pointer: str = "") -> Iterable[tuple[str, Any]]:
    yield pointer or "/", value
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{_pointer_escape(str(key))}"
            yield from _walk_concrete(child, child_pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_concrete(child, f"{pointer}/{index}")


def collect_normalized_paths(value: Any) -> tuple[set[str], set[str]]:
    """Collect normalized container and leaf paths (arrays use ``[]``)."""

    structures: set[str] = set()
    leaves: set[str] = set()

    def walk(child: Any, path: str) -> None:
        if isinstance(child, dict):
            structures.add(path)
            for key, nested in child.items():
                walk(nested, f"{path}.{key}")
        elif isinstance(child, list):
            structures.add(path)
            for nested in child:
                walk(nested, f"{path}[]")
        else:
            leaves.add(path)

    walk(value, "$")
    return structures, leaves


def discover_v05_instances(root: Path | str = REPOSITORY_ROOT) -> list[Path]:
    """Find the eight live generated v0.5 fixtures, never archived copies."""

    root = Path(root).resolve()
    output_root = root / "output"
    if not output_root.is_dir():
        return []
    return sorted(
        (path for path in output_root.rglob(V05_FILENAME) if "metamodel_v2" not in path.parts),
        key=lambda path: path.as_posix().casefold(),
    )


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RepresentabilityError(message)


def validate_v05_document(document: Mapping[str, Any]) -> None:
    """Validate compatibility-critical v0.5 constraints.

    The repository's JSON Schema is intentionally shallow below the root.  The
    checks here cover the additional constraints required by a lossless V2
    projection, not a replacement for the existing runtime validators.
    """

    _require(isinstance(document, dict), "v0.5 document must be a JSON object")
    actual_fields = tuple(document.keys())
    _require(
        set(actual_fields) == set(V05_TOP_LEVEL_FIELDS),
        "v0.5 top-level field set changed; V2-only fields are not representable",
    )
    _require(document.get("schema") == V05_SCHEMA, f"unsupported schema: {document.get('schema')!r}")
    _require(
        document.get("metamodelVersion") == V05_METAMODEL_VERSION,
        f"unsupported metamodelVersion: {document.get('metamodelVersion')!r}",
    )
    _require(isinstance(document.get("caseId"), str) and bool(document["caseId"]), "caseId must be non-empty")

    requirements_model = document.get("requirementsModel")
    _require(isinstance(requirements_model, dict), "requirementsModel must be an object")
    use_cases = requirements_model.get("useCases")
    _require(isinstance(use_cases, list) and bool(use_cases), "requirementsModel.useCases[0] is required")
    for use_case_index, use_case in enumerate(use_cases):
        _require(isinstance(use_case, dict), f"useCases[{use_case_index}] must be an object")
        scenarios = use_case.get("scenarios")
        _require(isinstance(scenarios, list) and bool(scenarios), f"useCases[{use_case_index}].scenarios[0] is required")
        _require(
            isinstance(scenarios[0], dict) and scenarios[0].get("kind") == "main",
            f"useCases[{use_case_index}].scenarios[0] must remain the main scenario",
        )

    entity_ids = {
        entity.get("id")
        for entity in document.get("entities", [])
        if isinstance(entity, dict) and isinstance(entity.get("id"), str)
    }
    agent_ids: set[str] = set()
    for index, agent in enumerate(document.get("agents", [])):
        _require(isinstance(agent, dict), f"agents[{index}] must be an object")
        for key in ("id", "source_agent_id", "entity_id"):
            _require(isinstance(agent.get(key), str) and bool(agent[key]), f"agents[{index}].{key} must be non-empty")
        _require(agent["id"] not in agent_ids, f"duplicate agent id: {agent['id']}")
        agent_ids.add(agent["id"])
        _require(
            agent["entity_id"] in entity_ids,
            f"agent alias {agent['id']} references missing entity_id {agent['entity_id']}",
        )

    for binding_index, binding in enumerate(document.get("runtimeBindings", [])):
        _require(isinstance(binding, dict), f"runtimeBindings[{binding_index}] must be an object")
        for action_index, action in enumerate(binding.get("runtimeActions", [])):
            _require(isinstance(action, dict), f"runtime action {binding_index}/{action_index} must be an object")
            active: list[str] = []
            for slot in ("endpoint", "tool", "topic"):
                if slot in action and action[slot] is not None:
                    _require(
                        isinstance(action[slot], str) and bool(action[slot]),
                        f"runtime action {action.get('id', action_index)} has an empty {slot} locator",
                    )
                    active.append(slot)
            _require(
                len(active) == 1,
                f"runtime action {action.get('id', action_index)} must have exactly one active locator; got {active}",
            )

    for index, validation_case in enumerate(document.get("validationCases", [])):
        _require(isinstance(validation_case, dict), f"validationCases[{index}] must be an object")
        _require(
            "level" in validation_case
            and isinstance(validation_case["level"], str)
            and bool(validation_case["level"]),
            f"validationCases[{index}].level is a required compatibility discriminator",
        )


def _id_list(items: Any) -> list[Any]:
    if not isinstance(items, list):
        return []
    return [item.get("id") for item in items if isinstance(item, dict)]


def _ref_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return copy.deepcopy(value) if isinstance(value, list) else [copy.deepcopy(value)]


def _build_semantic_projection(document: Mapping[str, Any]) -> dict[str, Any]:
    """Build a readable V2/EAST-ADL-oriented semantic index.

    The exact payload remains separate.  This index makes the intended V2
    concepts explicit while using references rather than silently normalizing
    any legacy field.
    """

    requirements_model = document["requirementsModel"]
    use_cases = requirements_model.get("useCases", [])
    scenarios = [
        scenario
        for use_case in use_cases
        if isinstance(use_case, dict)
        for scenario in use_case.get("scenarios", [])
        if isinstance(scenario, dict)
    ]
    steps = [
        step
        for scenario in scenarios
        for step in scenario.get("steps", [])
        if isinstance(step, dict)
    ]
    agent_by_entity_id = {
        str(agent.get("entity_id")): agent
        for agent in document.get("agents", [])
        if isinstance(agent, dict) and agent.get("entity_id")
    }

    semantic_entities: list[dict[str, Any]] = []
    for entity in document.get("entities", []):
        agent = agent_by_entity_id.get(str(entity.get("id")))
        record: dict[str, Any] = {
            "@type": "Agent" if agent is not None else "Entity",
            "shortName": entity.get("id"),
            "name": entity.get("name"),
            "kind": entity.get("kind"),
            "sourceId": entity.get("source_id"),
            "entityRole": entity.get("entityRole"),
            "sourceObjectIds": copy.deepcopy(entity.get("source_object_ids", [])),
            "purpose": entity.get("purpose"),
            "sourceGroup": entity.get("source_group"),
            "objectType": entity.get("object_type"),
            "objectGroupRef": entity.get("object_group_entity_id"),
        }
        if agent is not None:
            record.update(
                {
                    "sourceAgentId": agent.get("source_agent_id"),
                    "displayName": agent.get("display_name"),
                    "persona": agent.get("persona"),
                    "expertise": copy.deepcopy(agent.get("expertise", [])),
                    "knowledgeTags": copy.deepcopy(agent.get("knowledge_tags", [])),
                    "voice": agent.get("voice"),
                    "voiceGender": agent.get("voice_gender"),
                    "voiceStyle": agent.get("voice_style"),
                    "ttsModel": agent.get("tts_model"),
                    "playsActorRefs": copy.deepcopy(agent.get("playsActor", [])),
                    "providedCapabilityRefs": copy.deepcopy(agent.get("providedCapabilityIds", [])),
                    "responsibleZoneRefs": copy.deepcopy(agent.get("responsibleZoneEntityIds", [])),
                    "groundedAssetRefs": copy.deepcopy(agent.get("groundedAssetEntityIds", [])),
                    "groundedObjectGroupRefs": copy.deepcopy(agent.get("groundedObjectGroupEntityIds", [])),
                    "handoffTargetRefs": copy.deepcopy(agent.get("handoffTargetAgentIds", [])),
                }
            )
        semantic_entities.append(record)

    runtime_bindings: list[dict[str, Any]] = []
    for binding in document.get("runtimeBindings", []):
        actions: list[dict[str, Any]] = []
        for action in binding.get("runtimeActions", []):
            active_slot = next(
                slot
                for slot in ("endpoint", "tool", "topic")
                if slot in action and action[slot] is not None
            )
            actions.append(
                {
                    "@type": "RuntimeAction",
                    "shortName": action.get("id"),
                    "locator": {
                        "@type": "RuntimeActionLocator",
                        "kind": active_slot,
                        "value": action[active_slot],
                    },
                    "inputSchemaRef": action.get("inputSchema"),
                    "outputSchemaRef": action.get("outputSchema"),
                }
            )
        runtime_bindings.append(
            {
                "@type": "RuntimeBinding",
                "shortName": binding.get("id"),
                "capabilityRef": binding.get("capability_id"),
                "targetPlatform": binding.get("targetPlatform"),
                "runtimeActions": actions,
            }
        )
    runtime_binding_by_id = {
        str(binding.get("shortName")): binding
        for binding in runtime_bindings
        if binding.get("shortName")
    }

    owned_relationships: list[dict[str, Any]] = []
    scenario_records: list[dict[str, Any]] = []
    for use_case in use_cases:
        use_case_id = use_case.get("id")
        owned_relationships.extend(
            {
                "@type": "ActorParticipation",
                "shortName": f"{use_case_id}-ACTOR-{index + 1}",
                "actorRef": actor_id,
                "useCaseRef": use_case_id,
            }
            for index, actor_id in enumerate(use_case.get("actor_ids", []))
        )
        use_case_scenarios = [item for item in use_case.get("scenarios", []) if isinstance(item, dict)]
        main_id = next((item.get("id") for item in use_case_scenarios if item.get("kind") == "main"), None)
        for scenario in use_case_scenarios:
            scenario_id = scenario.get("id")
            owned_relationships.append(
                {
                    "@type": "UseCaseScenarioSpecification",
                    "shortName": f"{use_case_id}-SPEC-{scenario_id}",
                    "useCaseRef": use_case_id,
                    "scenarioRef": scenario_id,
                }
            )
            scenario_records.append(
                {
                    "@type": "Scenario",
                    "shortName": scenario_id,
                    "text": scenario.get("description"),
                    "kind": scenario.get("kind"),
                    "variantOfRef": main_id if scenario.get("kind") in {"alternative", "exception"} else None,
                    "preconditionRefs": copy.deepcopy(scenario.get("precondition_ids", [])),
                    "postconditionRefs": copy.deepcopy(scenario.get("postcondition_ids", [])),
                    "stepRefs": _id_list(scenario.get("steps", [])),
                    "stepRelations": [
                        {
                            "@type": "StepRelation",
                            "shortName": relation.get("id"),
                            "kind": relation.get("kind"),
                            "sourceStepRef": relation.get("source_step_id"),
                            "targetStepRef": relation.get("target_step_id"),
                            "guardRef": relation.get("guard"),
                            **(
                                {"probability": relation.get("probability")}
                                if relation.get("kind") in {"alternative", "exception"}
                                else {"compatibilityProbability": relation.get("probability")}
                            ),
                        }
                        for relation in scenario.get("stepRelations", [])
                        if isinstance(relation, dict)
                    ],
                    "parallelGroups": [
                        {
                            "@type": "ParallelGroup",
                            "shortName": group.get("id"),
                            "name": group.get("label"),
                            "memberStepRefs": copy.deepcopy(group.get("memberStepIds", [])),
                        }
                        for group in scenario.get("parallelGroups", [])
                        if isinstance(group, dict)
                    ],
                }
            )

    validation_cases: list[dict[str, Any]] = []
    validation_targets: list[dict[str, Any]] = []
    verify_relationships: list[dict[str, Any]] = []
    use_case_validation_bindings: list[dict[str, Any]] = []
    for validation_case in document.get("validationCases", []):
        case_id = validation_case.get("id")
        procedure_id = f"{case_id}-PROCEDURE"
        target_refs: list[str] = []
        for index, runtime_binding_id in enumerate(validation_case.get("runtime_binding_ids", [])):
            target_id = f"{case_id}-TARGET-{index + 1}"
            runtime_binding = runtime_binding_by_id.get(str(runtime_binding_id), {})
            validation_targets.append(
                {
                    "@type": "RuntimeValidationTarget",
                    "shortName": target_id,
                    "platform": runtime_binding.get("targetPlatform"),
                    "runtimeBindingRefs": [runtime_binding_id],
                    "elementRefs": [runtime_binding_id],
                }
            )
            target_refs.append(target_id)
        stimuli = [
            {
                "@type": "RuntimeStimulus",
                "shortName": f"{case_id}-STIMULUS-{index + 1}",
                "sourceRef": stimulus_id,
            }
            for index, stimulus_id in enumerate(validation_case.get("stimulus_ids", []))
        ]
        intended_outcomes = [
            {
                "@type": "StateAssertionOutcome",
                "shortName": f"{case_id}-OUTCOME-{index + 1}",
                "assertionRef": assertion_id,
            }
            for index, assertion_id in enumerate(validation_case.get("expectedOutcome", []))
        ]
        validation_cases.append(
            {
                "@type": "ValidationCase",
                "shortName": case_id,
                "vvSubjectRefs": copy.deepcopy(validation_case.get("runtime_binding_ids", [])),
                "vvTargetRefs": target_refs,
                "vvProcedures": [
                    {
                        "@type": "RuntimeValidationProcedure",
                        "shortName": procedure_id,
                        "vvStimuli": stimuli,
                        "vvIntendedOutcomes": intended_outcomes,
                    }
                ],
            }
        )
        verify_relationships.extend(
            {
                "@type": "Verify",
                "shortName": f"{case_id}-VERIFY-{index + 1}",
                "verifiedRequirementRef": requirement_id,
                "verifiedByCaseRef": case_id,
                "verifiedByProcedureRef": procedure_id,
            }
            for index, requirement_id in enumerate(validation_case.get("verifies_requirement_ids", []))
        )
        use_case_validation_bindings.extend(
            {
                "@type": "ValidationCaseUseCaseBinding",
                "shortName": f"{case_id}-USECASE-{index + 1}",
                "validationCaseRef": case_id,
                "useCaseRef": use_case_id,
            }
            for index, use_case_id in enumerate(validation_case.get("validates_use_case_ids", []))
        )

    satisfy_relationships = [
        {
            "@type": "Satisfy",
            "shortName": item.get("id"),
            "satisfiedRequirementRefs": _ref_list(item.get("satisfiedRequirement")),
            "satisfiedUseCaseRefs": _ref_list(item.get("satisfiedUseCase")),
            "satisfiedByRefs": _ref_list(item.get("satisfiedBy")),
        }
        for item in document.get("satisfyRelationships", [])
        if isinstance(item, dict)
    ]
    owned_relationships.extend(satisfy_relationships)
    owned_relationships.extend(verify_relationships)
    owned_relationships.extend(use_case_validation_bindings)

    return {
        "@type": "DynamicFunctionalModel",
        "shortName": document["caseId"],
        "compatibilitySource": {"schema": document["schema"], "version": document["metamodelVersion"]},
        "requirementsModel": {
            "@type": "RequirementsModel",
            "shortName": requirements_model.get("id"),
            "requirements": [
                {"@type": "Requirement", "shortName": item.get("id"), "text": item.get("text")}
                for item in requirements_model.get("requirements", [])
            ],
            "useCases": [
                {
                    "@type": "UseCase",
                    "shortName": item.get("id"),
                    "name": item.get("name"),
                    "actorParticipationRefs": [
                        f"{item.get('id')}-ACTOR-{index + 1}"
                        for index, _ in enumerate(item.get("actor_ids", []))
                    ],
                    "scenarioSpecificationRefs": [
                        f"{item.get('id')}-SPEC-{scenario.get('id')}"
                        for scenario in item.get("scenarios", [])
                        if isinstance(scenario, dict)
                    ],
                }
                for item in use_cases
            ],
        },
        "scenarios": scenario_records,
        "scenarioSteps": [
            {
                "@type": "ScenarioStep",
                "shortName": item.get("id"),
                "text": item.get("text"),
                "kind": item.get("kind"),
                "actorRoleRefs": _ref_list(item.get("performedBy")),
                "eventRefs": copy.deepcopy(item.get("triggeredBy", [])),
                "conditionRef": item.get("guard"),
                "resultingAssertionRefs": copy.deepcopy(item.get("resultingState", [])),
                "capabilityUseRefs": copy.deepcopy(item.get("capabilityUseIds", [])),
                "occurrenceProbability": item.get("occurrenceProbability"),
            }
            for item in steps
        ],
        "actors": [
            {"@type": "Actor", "shortName": item.get("id"), "name": item.get("name"), "text": item.get("description")}
            for item in document.get("actors", [])
        ],
        "entities": semantic_entities,
        "scenarioEvents": [
            {"@type": "ScenarioEvent", "shortName": item.get("id"), "kind": item.get("kind"), "mixedStringContent": item.get("expression")}
            for item in document.get("events", [])
        ],
        "scenarioConditions": [
            {"@type": "ScenarioCondition", "shortName": item.get("id"), "kind": item.get("kind"), "mixedStringContent": item.get("expression"), "type": "EABoolean"}
            for item in document.get("conditions", [])
        ],
        "assertions": [
            {
                "@type": "StateAssertion",
                "shortName": item.get("id"),
                "subjectRef": item.get("subject_id"),
                "expression": {"@type": "EAExpression", "mixedStringContent": item.get("expression")},
                "expressionText": item.get("expression"),
            }
            for item in document.get("stateAssertions", [])
        ],
        "capabilities": [
            {
                "@type": "Capability",
                "shortName": item.get("id"),
                "name": item.get("name"),
                "text": item.get("text"),
                "preconditionRefs": copy.deepcopy(item.get("precondition_ids", [])),
                "effects": [
                    {
                        "@type": "Effect",
                        "shortName": effect.get("id"),
                        "text": effect.get("text"),
                        "specifiedByRefs": copy.deepcopy(effect.get("evidencedBy", [])),
                    }
                    for effect in item.get("effects", [])
                    if isinstance(effect, dict)
                ],
            }
            for item in document.get("capabilities", [])
        ],
        "capabilityUses": [
            {
                "@type": "CapabilityUse",
                "shortName": item.get("id"),
                "typeRef": item.get("capability_id"),
                "preferredProviderRef": item.get("preferred_provider_entity_id"),
                "targetRefs": copy.deepcopy(item.get("target_entity_ids", [])),
                "parameters": copy.deepcopy(item.get("parameters", {})),
            }
            for item in document.get("capabilityUses", [])
        ],
        "runtimeBindings": runtime_bindings,
        "verificationValidation": {
            "@type": "VerificationValidation",
            "vvCases": validation_cases,
            "vvTargets": validation_targets,
            "verifyRelationships": verify_relationships,
        },
        "ownedRelationships": owned_relationships,
    }


def _array_token(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("id"), str):
        return f"id:{value['id']}"
    return f"sha256:{structural_sha256(value)}"


def build_v05_projection_ledger(
    document: Mapping[str, Any], semantic_projection: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build the separate, auditable losslessness ledger."""

    validate_v05_document(document)
    semantic_projection = semantic_projection or _build_semantic_projection(document)

    presence: list[str] = []
    nulls: list[str] = []
    empty_containers: list[str] = []
    object_key_order: dict[str, list[str]] = {}
    array_order: dict[str, list[str]] = {}
    enum_lexemes: dict[str, Any] = {}
    step_numbers: dict[str, Any] = {}

    for pointer, value in _walk_concrete(document):
        presence.append(pointer)
        if value is None:
            nulls.append(pointer)
        if isinstance(value, (dict, list)) and not value:
            empty_containers.append(pointer)
        if isinstance(value, dict):
            object_key_order[pointer] = list(value.keys())
        elif isinstance(value, list):
            array_order[pointer] = [_array_token(item) for item in value]

        final_token = pointer.rsplit("/", 1)[-1] if "/" in pointer else ""
        if final_token in {"kind", "level"} and not isinstance(value, (dict, list)):
            enum_lexemes[pointer] = value
        if final_token == "stepNumber" and not isinstance(value, (dict, list)):
            step_numbers[pointer] = value

    runtime_action_locators: list[dict[str, Any]] = []
    for binding_index, binding in enumerate(document.get("runtimeBindings", [])):
        for action_index, action in enumerate(binding.get("runtimeActions", [])):
            slots = {
                slot: {"present": slot in action, "value": copy.deepcopy(action.get(slot))}
                for slot in ("endpoint", "tool", "topic")
            }
            active = [slot for slot, entry in slots.items() if entry["present"] and entry["value"] is not None]
            runtime_action_locators.append(
                {
                    "pointer": f"/runtimeBindings/{binding_index}/runtimeActions/{action_index}",
                    "runtimeBindingId": binding.get("id"),
                    "runtimeActionId": action.get("id"),
                    "slots": slots,
                    "activeSlot": active[0],
                }
            )

    agent_aliases = [
        {
            "pointer": f"/agents/{index}",
            "agentId": agent.get("id"),
            "sourceAgentId": agent.get("source_agent_id"),
            "entityId": agent.get("entity_id"),
            "legacyReferencePairs": {
                "responsibleZone": {
                    "source": copy.deepcopy(agent.get("responsible_zone_ids")),
                    "entity": copy.deepcopy(agent.get("responsibleZoneEntityIds")),
                },
                "groundedAsset": {
                    "source": copy.deepcopy(agent.get("grounded_object_ids")),
                    "entity": copy.deepcopy(agent.get("groundedAssetEntityIds")),
                },
                "groundedObjectGroup": {
                    "source": copy.deepcopy(agent.get("grounded_object_groups")),
                    "entity": copy.deepcopy(agent.get("groundedObjectGroupEntityIds")),
                },
                "handoffTarget": {
                    "source": copy.deepcopy(agent.get("handoff_targets")),
                    "agent": copy.deepcopy(agent.get("handoffTargetAgentIds")),
                },
            },
        }
        for index, agent in enumerate(document.get("agents", []))
    ]

    main_scenario_positions: list[dict[str, Any]] = []
    for use_case_index, use_case in enumerate(document["requirementsModel"]["useCases"]):
        main_scenario_positions.append(
            {
                "useCaseIndex": use_case_index,
                "useCaseId": use_case.get("id"),
                "scenarioOrder": _id_list(use_case.get("scenarios", [])),
                "scenarioKindLexemes": [item.get("kind") for item in use_case.get("scenarios", [])],
                "mainIndex": 0,
            }
        )

    structures, leaves = collect_normalized_paths(document)
    ledger: dict[str, Any] = {
        "@type": LEDGER_SCHEMA,
        "ledgerVersion": LEDGER_VERSION,
        "envelopeIdentifiers": {
            "schema": document["schema"],
            "metamodelVersion": document["metamodelVersion"],
            "caseId": document["caseId"],
        },
        "sourceStructuralSha256": structural_sha256(document),
        "semanticProjectionSha256": structural_sha256(semantic_projection),
        "presencePointers": presence,
        "nullPointers": nulls,
        "emptyContainerPointers": empty_containers,
        "objectKeyOrder": object_key_order,
        "arrayOrder": array_order,
        "enumLexemes": enum_lexemes,
        "stepNumbers": step_numbers,
        "runtimeActionLocatorSlots": runtime_action_locators,
        "agentAliases": agent_aliases,
        "mainScenarioPositions": main_scenario_positions,
        "normalizedStructurePaths": sorted(structures),
        "normalizedLeafPaths": sorted(leaves),
    }
    ledger["ledgerIntegritySha256"] = structural_sha256(ledger)
    return ledger


def import_v05(document: Mapping[str, Any]) -> dict[str, Any]:
    """Import a v0.5 JSON object into a lossless V2 projection envelope."""

    validate_v05_document(document)
    exact_projection = copy.deepcopy(document)
    semantic_projection = _build_semantic_projection(exact_projection)
    ledger = build_v05_projection_ledger(exact_projection, semantic_projection)
    return {
        "schema": V2_PROJECTION_SCHEMA,
        "metamodelVersion": V2_PROJECTION_VERSION,
        "caseId": exact_projection["caseId"],
        "dynamicFunctionalModel": semantic_projection,
        "v05Projection": exact_projection,
        "v05ProjectionLedger": ledger,
        "v2Extensions": {},
    }


def _assert_projection_integrity(envelope: Mapping[str, Any]) -> None:
    _require(isinstance(envelope, dict), "projection envelope must be an object")
    extra = set(envelope) - ENVELOPE_FIELDS
    missing = ENVELOPE_FIELDS - set(envelope)
    _require(not extra, f"V2-only envelope fields are not representable in v0.5: {sorted(extra)}")
    _require(not missing, f"projection envelope is incomplete: {sorted(missing)}")
    _require(envelope.get("schema") == V2_PROJECTION_SCHEMA, "projection schema changed")
    _require(envelope.get("metamodelVersion") == V2_PROJECTION_VERSION, "projection version changed")
    _require(envelope.get("v2Extensions") == {}, "non-empty v2Extensions cannot be represented in v0.5")

    source = envelope.get("v05Projection")
    semantic = envelope.get("dynamicFunctionalModel")
    ledger = envelope.get("v05ProjectionLedger")
    _require(isinstance(source, dict), "v05Projection must be an object")
    _require(isinstance(semantic, dict), "dynamicFunctionalModel must be an object")
    _require(isinstance(ledger, dict), "v05ProjectionLedger must be an object")
    _require(envelope.get("caseId") == source.get("caseId"), "projection caseId diverged from v0.5")

    validate_v05_document(source)
    expected_semantic = _build_semantic_projection(source)
    _require(
        semantic == expected_semantic and structural_sha256(semantic) == structural_sha256(expected_semantic),
        "dynamicFunctionalModel contains changed or V2-only data; lossless v0.5 export refused",
    )
    expected_ledger = build_v05_projection_ledger(source, expected_semantic)
    _require(
        ledger == expected_ledger,
        "V05ProjectionLedger does not match the exact payload; export refused",
    )


def export_v05(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Export an unchanged imported projection, failing on any lossy V2 data."""

    _assert_projection_integrity(envelope)
    return copy.deepcopy(envelope["v05Projection"])


# Each leaf path observed across the eight real fixtures has an explicit target.
# Compatibility-only discriminators deliberately remain in the ledger instead
# of being falsely inferred from an EAST-ADL abstract metaclass.
LEAF_TARGETS: dict[str, str] = {
    "$.schema": "V05ProjectionLedger.envelopeIdentifiers.schema",
    "$.metamodelVersion": "V05ProjectionLedger.envelopeIdentifiers.metamodelVersion",
    "$.caseId": "DynamicFunctionalModel.shortName",
    "$.requirementsModel.id": "RequirementsModel.shortName",
    "$.requirementsModel.requirements[].id": "Requirement.shortName",
    "$.requirementsModel.requirements[].text": "Requirement.text",
    "$.requirementsModel.useCases[].id": "UseCase.shortName",
    "$.requirementsModel.useCases[].name": "UseCase.name",
    "$.requirementsModel.useCases[].actor_ids[]": "ActorParticipation.actor",
    "$.requirementsModel.useCases[].scenarios[].id": "Scenario.shortName",
    "$.requirementsModel.useCases[].scenarios[].kind": "V05ProjectionLedger.enumLexemes.scenarioKind",
    "$.requirementsModel.useCases[].scenarios[].description": "Scenario.text",
    "$.requirementsModel.useCases[].scenarios[].precondition_ids[]": "Scenario.precondition",
    "$.requirementsModel.useCases[].scenarios[].postcondition_ids[]": "Scenario.postcondition",
    "$.requirementsModel.useCases[].scenarios[].steps[].id": "ScenarioStep.shortName",
    "$.requirementsModel.useCases[].scenarios[].steps[].stepNumber": "V05ProjectionLedger.stepNumbers",
    "$.requirementsModel.useCases[].scenarios[].steps[].kind": "ScenarioStep.kind",
    "$.requirementsModel.useCases[].scenarios[].steps[].performedBy": "ScenarioStep.actorRole",
    "$.requirementsModel.useCases[].scenarios[].steps[].text": "ScenarioStep.text",
    "$.requirementsModel.useCases[].scenarios[].steps[].occurrenceProbability": "ScenarioStep.occurrenceProbability:Probability",
    "$.requirementsModel.useCases[].scenarios[].steps[].triggeredBy[]": "ScenarioStep.triggeredBy:ScenarioEvent",
    "$.requirementsModel.useCases[].scenarios[].steps[].guard": "ScenarioStep.guard:ScenarioCondition",
    "$.requirementsModel.useCases[].scenarios[].steps[].resultingState[]": "ScenarioStep.resultingAssertion:StateAssertion",
    "$.requirementsModel.useCases[].scenarios[].steps[].capabilityUseIds[]": "ScenarioStep.capabilityUse:CapabilityUse",
    "$.requirementsModel.useCases[].scenarios[].stepRelations[].id": "StepRelation.shortName",
    "$.requirementsModel.useCases[].scenarios[].stepRelations[].kind": "StepRelation.kind",
    "$.requirementsModel.useCases[].scenarios[].stepRelations[].source_step_id": "StepRelation.sourceStep",
    "$.requirementsModel.useCases[].scenarios[].stepRelations[].target_step_id": "StepRelation.targetStep",
    "$.requirementsModel.useCases[].scenarios[].stepRelations[].guard": "StepRelation.guard:ScenarioCondition",
    "$.requirementsModel.useCases[].scenarios[].stepRelations[].probability": "StepRelation.probability:Probability (alternative/exception only; otherwise preserved in V05ProjectionLedger)",
    "$.actors[].id": "Actor.shortName",
    "$.actors[].name": "Actor.name",
    "$.actors[].description": "Actor.text",
    "$.entities[].id": "Entity.shortName",
    "$.entities[].name": "Entity.name",
    "$.entities[].kind": "Entity.kind",
    "$.entities[].source_id": "Entity.sourceId",
    "$.entities[].entityRole": "Entity.entityRole",
    "$.entities[].source_object_ids[]": "Entity.sourceObjectId",
    "$.entities[].purpose": "Entity.purpose",
    "$.entities[].source_group": "Entity.sourceGroup",
    "$.entities[].object_type": "Entity.objectType",
    "$.entities[].object_group_entity_id": "Entity.objectGroup",
    "$.agents[].id": "V05ProjectionLedger.agentAliases.agentId",
    "$.agents[].source_agent_id": "Agent.sourceAgentId",
    "$.agents[].entity_id": "Agent.shortName",
    "$.agents[].playsActor[]": "Entity.playsActor",
    "$.agents[].providedCapabilityIds[]": "Agent.providedCapability",
    "$.agents[].display_name": "Agent.displayName",
    "$.agents[].persona": "Agent.persona",
    "$.agents[].expertise[]": "Agent.expertise",
    "$.agents[].knowledge_tags[]": "Agent.knowledgeTag",
    "$.agents[].voice": "Agent.voice",
    "$.agents[].voice_gender": "Agent.voiceGender",
    "$.agents[].voice_style": "Agent.voiceStyle",
    "$.agents[].tts_model": "Agent.ttsModel",
    "$.agents[].responsible_zone_ids[]": "V05ProjectionLedger.agentAliases.responsibleZone.source",
    "$.agents[].responsibleZoneEntityIds[]": "Agent.responsibleZone",
    "$.agents[].grounded_object_ids[]": "V05ProjectionLedger.agentAliases.groundedAsset.source",
    "$.agents[].groundedAssetEntityIds[]": "Agent.groundedAsset",
    "$.agents[].grounded_object_groups[]": "V05ProjectionLedger.agentAliases.groundedObjectGroup.source",
    "$.agents[].groundedObjectGroupEntityIds[]": "Agent.groundedObjectGroup",
    "$.agents[].handoff_targets[]": "V05ProjectionLedger.agentAliases.handoffTarget.source",
    "$.agents[].handoffTargetAgentIds[]": "Agent.handoffTarget",
    "$.events[].id": "ScenarioEvent.shortName",
    "$.events[].kind": "ScenarioEvent.kind",
    "$.events[].expression": "EAExpression.mixedStringContent",
    "$.conditions[].id": "ScenarioCondition.shortName",
    "$.conditions[].kind": "ScenarioCondition.kind",
    "$.conditions[].expression": "EAExpression.mixedStringContent:EABoolean",
    "$.stateAssertions[].id": "StateAssertion.shortName",
    "$.stateAssertions[].subject_id": "Assertion.subject",
    "$.stateAssertions[].expression": "Assertion.expression:EAExpression (expressionText is derived)",
    "$.capabilityUses[].id": "CapabilityUse.shortName",
    "$.capabilityUses[].step_id": "ScenarioStep.capabilityUse",
    "$.capabilityUses[].capability_id": "CapabilityUse.type:Capability",
    "$.capabilityUses[].preferred_provider_entity_id": "CapabilityUse.provider",
    "$.capabilityUses[].target_entity_ids[]": "CapabilityUse.target",
    "$.capabilities[].id": "Capability.shortName",
    "$.capabilities[].name": "Capability.name",
    "$.capabilities[].text": "Capability.text",
    "$.capabilities[].effects[].id": "Effect.shortName",
    "$.capabilities[].effects[].text": "Effect.text",
    "$.capabilities[].effects[].evidencedBy[]": "Effect.specifiedBy:StateAssertion",
    "$.runtimeBindings[].id": "RuntimeBinding.shortName",
    "$.runtimeBindings[].capability_id": "RuntimeBinding.capability",
    "$.runtimeBindings[].targetPlatform": "RuntimeBinding.targetPlatform",
    "$.runtimeBindings[].runtimeActions[].id": "RuntimeAction.shortName",
    "$.runtimeBindings[].runtimeActions[].endpoint": "V05ProjectionLedger.runtimeActionLocatorSlots.endpoint",
    "$.runtimeBindings[].runtimeActions[].tool": "V05ProjectionLedger.runtimeActionLocatorSlots.tool",
    "$.runtimeBindings[].runtimeActions[].topic": "V05ProjectionLedger.runtimeActionLocatorSlots.topic",
    "$.runtimeBindings[].runtimeActions[].inputSchema": "RuntimeAction.inputSchema:SchemaReference",
    "$.runtimeBindings[].runtimeActions[].outputSchema": "RuntimeAction.outputSchema:SchemaReference",
    "$.validationCases[].id": "ValidationCase.shortName",
    "$.validationCases[].level": "V05ProjectionLedger.enumLexemes.validationLevel",
    "$.validationCases[].validates_use_case_ids[]": "ValidationCaseUseCaseBinding.useCase",
    "$.validationCases[].verifies_requirement_ids[]": "Verify.verifiedRequirement",
    "$.validationCases[].stimulus_ids[]": "VVProcedure.vvStimuli",
    "$.validationCases[].runtime_binding_ids[]": "ValidationCase.vvSubject",
    "$.validationCases[].expectedOutcome[]": "VVProcedure.vvIntendedOutcome",
    "$.satisfyRelationships[].id": "Satisfy.shortName",
    "$.satisfyRelationships[].satisfiedRequirement[]": "Satisfy.satisfiedRequirement",
    "$.satisfyRelationships[].satisfiedBy[]": "Satisfy.satisfiedBy",
}


STRUCTURE_TARGETS: dict[str, str] = {
    "$": "DynamicFunctionalModel",
    "$.requirementsModel": "RequirementsModel",
    "$.requirementsModel.requirements": "RequirementsModel.requirement[*]",
    "$.requirementsModel.requirements[]": "Requirement",
    "$.requirementsModel.useCases": "RequirementsModel.useCase[*]",
    "$.requirementsModel.useCases[]": "UseCase",
    "$.requirementsModel.useCases[].actor_ids": "ActorParticipation[*]",
    "$.requirementsModel.useCases[].extensionPoints": "UseCase.extensionPoint[*]",
    "$.requirementsModel.useCases[].includes": "UseCase.include[*]",
    "$.requirementsModel.useCases[].extends": "UseCase.extend[*]",
    "$.requirementsModel.useCases[].scenarios": "UseCaseScenarioSpecification[*]",
    "$.requirementsModel.useCases[].scenarios[]": "Scenario",
    "$.requirementsModel.useCases[].scenarios[].precondition_ids": "Scenario.precondition[*]",
    "$.requirementsModel.useCases[].scenarios[].postcondition_ids": "Scenario.postcondition[*]",
    "$.requirementsModel.useCases[].scenarios[].steps": "Scenario.step[*]",
    "$.requirementsModel.useCases[].scenarios[].steps[]": "ScenarioStep",
    "$.requirementsModel.useCases[].scenarios[].steps[].triggeredBy": "ScenarioStep.triggeredBy[*]",
    "$.requirementsModel.useCases[].scenarios[].steps[].resultingState": "ScenarioStep.resultingAssertion[*] (StateAssertion subset)",
    "$.requirementsModel.useCases[].scenarios[].steps[].capabilityUseIds": "ScenarioStep.capabilityUse[*]",
    "$.requirementsModel.useCases[].scenarios[].stepRelations": "Scenario.stepRelation[*]",
    "$.requirementsModel.useCases[].scenarios[].stepRelations[]": "StepRelation",
    "$.requirementsModel.useCases[].scenarios[].parallelGroups": "Scenario.parallelGroup[*]",
    "$.actors": "DynamicFunctionalModel.actor[*]",
    "$.actors[]": "Actor",
    "$.entities": "DynamicFunctionalModel.entity[*]",
    "$.entities[]": "Entity",
    "$.entities[].source_object_ids": "Entity.sourceObjectId[*]",
    "$.agents": "DynamicFunctionalModel.entity[*] (Agent specialization; alias order in ledger)",
    "$.agents[]": "Agent",
    "$.agents[].playsActor": "Entity.playsActor[*]",
    "$.agents[].providedCapabilityIds": "Agent.providedCapability[*]",
    "$.agents[].expertise": "Agent.expertise[*]",
    "$.agents[].knowledge_tags": "Agent.knowledgeTag[*]",
    "$.agents[].responsible_zone_ids": "V05ProjectionLedger.agentAliases.responsibleZone.source[*]",
    "$.agents[].responsibleZoneEntityIds": "Agent.responsibleZone[*]",
    "$.agents[].grounded_object_ids": "V05ProjectionLedger.agentAliases.groundedAsset.source[*]",
    "$.agents[].groundedAssetEntityIds": "Agent.groundedAsset[*]",
    "$.agents[].grounded_object_groups": "V05ProjectionLedger.agentAliases.groundedObjectGroup.source[*]",
    "$.agents[].groundedObjectGroupEntityIds": "Agent.groundedObjectGroup[*]",
    "$.agents[].handoff_targets": "V05ProjectionLedger.agentAliases.handoffTarget.source[*]",
    "$.agents[].handoffTargetAgentIds": "Agent.handoffTarget[*]",
    "$.events": "DynamicFunctionalModel.scenarioEvent[*]",
    "$.events[]": "ScenarioEvent",
    "$.conditions": "DynamicFunctionalModel.scenarioCondition[*]",
    "$.conditions[]": "ScenarioCondition",
    "$.stateAssertions": "DynamicFunctionalModel.assertion[*] (StateAssertion subset)",
    "$.stateAssertions[]": "StateAssertion",
    "$.capabilityUses": "ScenarioStep.capabilityUse[*] (legacy top-level order in ledger)",
    "$.capabilityUses[]": "CapabilityUse",
    "$.capabilityUses[].target_entity_ids": "CapabilityUse.target[*]",
    "$.capabilityUses[].parameters": "CapabilityUse.parameter[*]",
    "$.capabilities": "DynamicFunctionalModel.capability[*]",
    "$.capabilities[]": "Capability",
    "$.capabilities[].precondition_ids": "Capability.precondition[*]",
    "$.capabilities[].effects": "Capability.effect[*]",
    "$.capabilities[].effects[]": "Effect",
    "$.capabilities[].effects[].evidencedBy": "Effect.specifiedBy[*] (legacy field name preserved only in v0.5)",
    "$.runtimeBindings": "DynamicFunctionalModel.runtimeBinding[*]",
    "$.runtimeBindings[]": "RuntimeBinding",
    "$.runtimeBindings[].runtimeActions": "RuntimeBinding.runtimeAction[*]",
    "$.runtimeBindings[].runtimeActions[]": "RuntimeAction",
    "$.validationCases": "VerificationValidation.vvCase[*]",
    "$.validationCases[]": "ValidationCase",
    "$.validationCases[].validates_use_case_ids": "ValidationCaseUseCaseBinding[*]",
    "$.validationCases[].verifies_requirement_ids": "Verify[*]",
    "$.validationCases[].stimulus_ids": "VVProcedure.vvStimuli[*]",
    "$.validationCases[].runtime_binding_ids": "ValidationCase.vvSubject[*]",
    "$.validationCases[].expectedOutcome": "VVProcedure.vvIntendedOutcome[*]",
    "$.satisfyRelationships": "Context.ownedRelationship[*] (RequirementsModel context)",
    "$.satisfyRelationships[]": "Satisfy",
    "$.satisfyRelationships[].satisfiedRequirement": "Satisfy.satisfiedRequirement[*]",
    "$.satisfyRelationships[].satisfiedUseCase": "Satisfy.satisfiedUseCase[*]",
    "$.satisfyRelationships[].satisfiedBy": "Satisfy.satisfiedBy[*]",
}


def _canonical_target_members() -> tuple[dict[str, str], dict[str, set[str]]]:
    """Index canonical V2 classes and every inherited attribute/role.

    Association target roles are properties of the source class and source
    roles are properties of the target class.  Resolving both directions
    catches stale prose targets in the compatibility table instead of merely
    proving that all v0.5 paths have *some* string assigned to them.
    """

    classes = MODEL["classes"]
    by_name = {definition["name"]: qualified for qualified, definition in classes.items()}
    direct_members: dict[str, set[str]] = {
        qualified: {attribute["name"] for attribute in definition["attributes"]}
        for qualified, definition in classes.items()
    }
    for association_definition in MODEL["associations"]:
        direct_members[association_definition["source"]].add(
            association_definition["target_role"]
        )
        direct_members[association_definition["target"]].add(
            association_definition["source_role"]
        )

    resolved: dict[str, set[str]] = {}

    def inherited_members(qualified: str, active: set[str] | None = None) -> set[str]:
        if qualified in resolved:
            return resolved[qualified]
        active = set() if active is None else active
        if qualified in active:
            raise RepresentabilityError(f"inheritance cycle while resolving {qualified}")
        active.add(qualified)
        members = set(direct_members[qualified])
        for base in classes[qualified]["bases"]:
            members.update(inherited_members(base, active))
        active.remove(qualified)
        resolved[qualified] = members
        return members

    for qualified in classes:
        inherited_members(qualified)
    return by_name, {classes[qualified]["name"]: members for qualified, members in resolved.items()}


def resolve_v2_target(target: str) -> dict[str, Any]:
    """Resolve a mapping target against the canonical metamodel.

    Ledger paths are intentionally outside EAST-ADL and resolve against the
    compatibility contract.  Type annotations (``:Probability``), collection
    markers and explanatory parentheticals do not change the owning member.
    ``EAExpression.mixedStringContent`` is the textual surface supplied by the
    normative ``atpMixedString`` stereotype.
    """

    original = target
    normalized = target.split(" (", 1)[0].strip()
    normalized = normalized.replace("[*]", "")
    if normalized.startswith("V05ProjectionLedger"):
        return {
            "target": original,
            "normalizedTarget": normalized,
            "resolved": True,
            "resolution": "compatibility-ledger",
        }

    class_names, members = _canonical_target_members()
    if "." not in normalized:
        resolved = normalized in class_names
        return {
            "target": original,
            "normalizedTarget": normalized,
            "resolved": resolved,
            "resolution": "canonical-class" if resolved else "unresolved-class",
        }

    owner, member_and_type = normalized.split(".", 1)
    member = member_and_type.split(":", 1)[0]
    stereotype_surface = (
        owner == "EAExpression"
        and member == "mixedStringContent"
        and owner in class_names
        and "atpMixedString"
        in MODEL["classes"][class_names[owner]].get("stereotypes", [])
    )
    resolved = owner in members and (member in members[owner] or stereotype_surface)
    return {
        "target": original,
        "normalizedTarget": f"{owner}.{member}",
        "resolved": resolved,
        "resolution": (
            "atpMixedString-surface"
            if stereotype_surface
            else ("canonical-member" if resolved else "unresolved-member")
        ),
    }


def build_semantic_mapping(documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Map every normalized path seen in the real v0.5 surface to V2."""

    structures: set[str] = set()
    leaves: set[str] = set()
    for document in documents:
        current_structures, current_leaves = collect_normalized_paths(document)
        structures.update(current_structures)
        leaves.update(current_leaves)

    missing_structures = structures - STRUCTURE_TARGETS.keys()
    missing_leaves = leaves - LEAF_TARGETS.keys()
    extra_structures = STRUCTURE_TARGETS.keys() - structures
    extra_leaves = LEAF_TARGETS.keys() - leaves
    entries: list[dict[str, Any]] = []
    for path in sorted(structures | leaves):
        kind = "structure" if path in structures else "leaf"
        target = STRUCTURE_TARGETS.get(path) if kind == "structure" else LEAF_TARGETS.get(path)
        ledger_only = bool(target and target.startswith("V05ProjectionLedger"))
        target_resolution = resolve_v2_target(target) if target else {
            "target": "UNMAPPED",
            "normalizedTarget": "UNMAPPED",
            "resolved": False,
            "resolution": "unmapped",
        }
        entries.append(
            {
                "v05Path": path,
                "pathKind": kind,
                "v2Target": target or "UNMAPPED",
                "targetResolution": target_resolution,
                "preservation": "compatibility-ledger" if ledger_only else ("container-and-order" if kind == "structure" else "semantic-projection+ledger"),
                "rule": (
                    f"Preserve exact compatibility lexeme/presence in {target}; do not infer an EAST-ADL value."
                    if ledger_only
                    else (
                        f"Preserve the object/array boundary and order while projecting it as {target}."
                        if kind == "structure"
                        else f"Project the value as {target}; retain exact presence, null and lexeme in V05ProjectionLedger."
                    )
                ),
            }
        )

    return {
        "mappingVersion": "1.0",
        "sourceContract": f"{V05_SCHEMA}/{V05_METAMODEL_VERSION}",
        "targetContract": V2_PROJECTION_VERSION,
        "entryCount": len(entries),
        "structurePathCount": len(structures),
        "leafPathCount": len(leaves),
        "coverage": {
            "covered": (
                not missing_structures
                and not missing_leaves
                and all(entry["targetResolution"]["resolved"] for entry in entries)
            ),
            "coveredPathCount": sum(entry["v2Target"] != "UNMAPPED" for entry in entries),
            "resolvedTargetCount": sum(
                entry["targetResolution"]["resolved"] for entry in entries
            ),
            "unresolvedTargets": [
                {
                    "v05Path": entry["v05Path"],
                    **entry["targetResolution"],
                }
                for entry in entries
                if not entry["targetResolution"]["resolved"]
            ],
            "missingStructurePaths": sorted(missing_structures),
            "missingLeafPaths": sorted(missing_leaves),
            "declaredButUnobservedStructurePaths": sorted(extra_structures),
            "declaredButUnobservedLeafPaths": sorted(extra_leaves),
        },
        "entries": entries,
    }


def _recursive_order_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return [(key, _recursive_order_signature(child)) for key, child in value.items()]
    if isinstance(value, list):
        return [_recursive_order_signature(child) for child in value]
    return type(value).__name__


def run_compatibility_audit(root: Path | str = REPOSITORY_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    paths = discover_v05_instances(root)
    documents = [load_json(path) for path in paths]
    mapping = build_semantic_mapping(documents)
    cases: list[dict[str, Any]] = []
    for path, document in zip(paths, documents):
        envelope = import_v05(document)
        exported = export_v05(envelope)
        structural_equal = exported == document
        order_equal = _recursive_order_signature(exported) == _recursive_order_signature(document)
        ledger = envelope["v05ProjectionLedger"]
        cases.append(
            {
                "caseId": document["caseId"],
                "source": path.relative_to(root).as_posix(),
                "roundTripStructuralEqual": structural_equal,
                "objectAndArrayOrderEqual": order_equal,
                "sourceStructuralSha256": ledger["sourceStructuralSha256"],
                "presencePointerCount": len(ledger["presencePointers"]),
                "nullPointerCount": len(ledger["nullPointers"]),
                "emptyContainerPointerCount": len(ledger["emptyContainerPointers"]),
                "runtimeActionLocatorCount": len(ledger["runtimeActionLocatorSlots"]),
                "agentAliasCount": len(ledger["agentAliases"]),
                "validationLevelCount": sum(
                    pointer.endswith("/level") for pointer in ledger["enumLexemes"]
                ),
                "mainFirst": all(item["mainIndex"] == 0 for item in ledger["mainScenarioPositions"]),
            }
        )

    found_case_ids = {document.get("caseId") for document in documents}
    passed = (
        len(paths) == len(EXPECTED_CASE_IDS)
        and found_case_ids == EXPECTED_CASE_IDS
        and mapping["coverage"]["covered"]
        and all(case["roundTripStructuralEqual"] and case["objectAndArrayOrderEqual"] for case in cases)
    )
    return {
        "audit": "Dynamic Functional RDL V2 v0.5 compatibility",
        "passed": passed,
        "fixtureCount": len(paths),
        "expectedFixtureCount": len(EXPECTED_CASE_IDS),
        "foundCaseIds": sorted(found_case_ids),
        "missingCaseIds": sorted(EXPECTED_CASE_IDS - found_case_ids),
        "unexpectedCaseIds": sorted(found_case_ids - EXPECTED_CASE_IDS),
        "mappingSummary": {
            "entryCount": mapping["entryCount"],
            "structurePathCount": mapping["structurePathCount"],
            "leafPathCount": mapping["leafPathCount"],
            "coverage": mapping["coverage"],
        },
        "cases": cases,
        "mapping": mapping,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_evidence(audit: Mapping[str, Any], output_dir: Path | str) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = audit["mapping"]
    report = {key: copy.deepcopy(value) for key, value in audit.items() if key != "mapping"}

    mapping_json = output_dir / "v05_compatibility_mapping.json"
    coverage_json = output_dir / "v05_field_coverage.json"
    report_json = output_dir / "v05_roundtrip_report.json"
    mapping_md = output_dir / "v05_compatibility_mapping.md"
    report_md = output_dir / "v05_roundtrip_report.md"

    _write_json(mapping_json, mapping)
    _write_json(coverage_json, mapping["coverage"] | {
        "entryCount": mapping["entryCount"],
        "structurePathCount": mapping["structurePathCount"],
        "leafPathCount": mapping["leafPathCount"],
    })
    _write_json(report_json, report)

    mapping_lines = [
        "# v0.5 ↔ V2 compatibility mapping",
        "",
        f"Coverage: **{'PASS' if mapping['coverage']['covered'] else 'FAIL'}** — "
        f"{mapping['entryCount']} normalized paths "
        f"({mapping['structurePathCount']} structures, {mapping['leafPathCount']} leaves).",
        "",
        "| v0.5 path | Kind | V2 target | Preservation |",
        "|---|---|---|---|",
    ]
    for entry in mapping["entries"]:
        mapping_lines.append(
            "| {v05Path} | {pathKind} | {v2Target} | {preservation} |".format(**entry)
        )
    mapping_md.write_text("\n".join(mapping_lines) + "\n", encoding="utf-8")

    report_lines = [
        "# v0.5 lossless round-trip evidence",
        "",
        f"Overall: **{'PASS' if audit['passed'] else 'FAIL'}**",
        "",
        f"Fixtures: {audit['fixtureCount']}/{audit['expectedFixtureCount']}",
        "",
        "| Case | Structural equality | Object/array order | Locators | Agent aliases | Legacy levels | Main first |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for case in audit["cases"]:
        report_lines.append(
            f"| {case['caseId']} | {case['roundTripStructuralEqual']} | "
            f"{case['objectAndArrayOrderEqual']} | {case['runtimeActionLocatorCount']} | "
            f"{case['agentAliasCount']} | {case['validationLevelCount']} | {case['mainFirst']} |"
        )
    report_lines.extend(
        [
            "",
            "Export is fail-closed: non-empty `v2Extensions`, altered semantic projections, "
            "altered ledgers, invalid locator multiplicities and non-main first scenarios "
            "raise `RepresentabilityError`.",
        ]
    )
    report_md.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return [mapping_json, mapping_md, coverage_json, report_json, report_md]


def write_projection_fixtures(root: Path | str, output_dir: Path | str) -> list[Path]:
    """Persist the real V2 projections and their exact v0.5 reverse views.

    These files are acceptance evidence only.  Runtime consumers continue to
    read the original v0.5 artifacts at their existing paths.
    """

    root = Path(root).resolve()
    projection_dir = Path(output_dir) / "v05_projections"
    projection_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for source_path in discover_v05_instances(root):
        source = load_json(source_path)
        projection = import_v05(source)
        reverse_view = export_v05(projection)
        case_id = str(source["caseId"])
        projection_path = projection_dir / f"{case_id}.v2.projection.json"
        reverse_path = projection_dir / f"{case_id}.v05.roundtrip.json"
        _write_json(projection_path, projection)
        _write_json(reverse_path, reverse_view)
        written.extend((projection_path, reverse_path))
    return written


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT, help="repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "output" / "metamodel_v2" / "evidence",
        help="evidence output directory",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    audit = run_compatibility_audit(args.root)
    written = write_evidence(audit, args.output)
    written.extend(write_projection_fixtures(args.root, args.output))
    print(
        json.dumps(
            {
                "passed": audit["passed"],
                "fixtures": audit["fixtureCount"],
                "mappingPaths": audit["mappingSummary"]["entryCount"],
                "written": [str(path) for path in written],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
