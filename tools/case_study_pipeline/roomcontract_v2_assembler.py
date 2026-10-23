from __future__ import annotations

"""Native Dynamic Functional RDL V2 runtime-instance assembly.

This module deliberately lives next to, but does not modify, the v0.5 case-
study assembler.  Its source is the semantic projection returned by
``import_v05``.  The projection envelope and its compatibility ledger never
become part of the runtime document.
"""

import argparse
import copy
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


# The canonical V2 modules intentionally support direct execution from
# ``tools/``.  Add both import roots so this module works as a package import,
# as a standalone CLI, and under the repository's existing unittest layout.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = REPOSITORY_ROOT / "tools"
for _import_root in (REPOSITORY_ROOT, TOOLS_ROOT):
    if str(_import_root) not in sys.path:
        sys.path.insert(0, str(_import_root))

from tools.dynamic_functional_rdl_v2_compat import import_v05, structural_sha256
from tools.dynamic_functional_rdl_v2_model import MODEL
from tools.validate_dynamic_functional_rdl_v2 import validate_instance
from tools.case_study_pipeline.common import update_manifest


V2_INSTANCE_SCHEMA = "dynamic_functional_rdl_v2_instance"
V2_METAMODEL_VERSION = "2.0.0-model"
V2_SERIALIZATION_VERSION = "1.0"
V2_FIXTURE_PROFILE = "executable"
V2_FILENAME = "roomcontract.v2.instance.json"
V2_VALIDATION_FILENAME = "roomcontract.v2.assembly_report.json"
V2_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "dynamic_functional_rdl_v2_instance.schema.json"
WIRE_CONTRACT_VERSION = "2.0"
WIRE_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
INTERACTION_MODES = ("deictic", "non_deictic")
SPATIAL_ID_MAX_LENGTH = 256
SPATIAL_CANDIDATE_LIMIT = 16
SPATIAL_REASON_MAX_LENGTH = 512
SPATIAL_DISTANCE_LIMIT_METERS = 1_000_000
SPATIAL_COORDINATE_LIMIT = 1_000_000
SPATIAL_SELECTION_MODALITIES = (
    "desktop_ray",
    "mouse_ray",
    "keyboard_mouse",
    "xr_controller_ray",
    "controller_ray",
    "gaze",
    "touch",
    "direct",
    "programmatic",
)
V2_IMPLEMENTATION_INPUTS = [
    Path(__file__).resolve(),
    REPOSITORY_ROOT / "tools" / "dynamic_functional_rdl_v2_compat.py",
    REPOSITORY_ROOT / "tools" / "dynamic_functional_rdl_v2_model.py",
    REPOSITORY_ROOT / "tools" / "validate_dynamic_functional_rdl_v2.py",
    V2_SCHEMA_PATH,
]

ASSERTION_TYPES = {
    "StateAssertion",
    "EventAssertion",
    "OutputAssertion",
    "GroundingAssertion",
    "RelationAssertion",
}


class V2AssemblyError(ValueError):
    """Raised when a native executable V2 instance cannot be assembled."""


class _ObjectStore:
    def __init__(self) -> None:
        self.objects: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}

    def add(self, obj: Mapping[str, Any]) -> dict[str, Any]:
        record = {key: copy.deepcopy(value) for key, value in obj.items() if value is not None}
        object_id = str(record.get("id") or "")
        object_type = str(record.get("type") or "")
        if not object_id or not object_type:
            raise V2AssemblyError(f"Every native object needs id and type: {record!r}")
        if object_id in self.by_id:
            raise V2AssemblyError(f"Duplicate native V2 object id: {object_id}")
        self.by_id[object_id] = record
        self.objects.append(record)
        return record


def _id(record: Mapping[str, Any]) -> str:
    return str(record.get("shortName") or record.get("id") or "").strip()


def _refs(value: Any) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("id") or item.get("ref") or item.get("shortName")
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _text(value: Any) -> str:
    return str(value or "").strip()


def _token(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper() or "MODEL"


def _optional(record: dict[str, Any], name: str, value: Any) -> None:
    if value not in (None, "", []):
        record[name] = copy.deepcopy(value)


def _expression(store: _ObjectStore, assertion_id: str, expression_text: str) -> str:
    expression_id = f"EXPR-{assertion_id}"
    store.add(
        {
            "id": expression_id,
            "type": "EAExpression",
            "mixedStringContent": expression_text,
        }
    )
    return expression_id


def _assertion(
    store: _ObjectStore,
    *,
    assertion_id: str,
    assertion_type: str,
    subject_id: str,
    expression_text: str,
    severity: str,
) -> dict[str, Any]:
    if assertion_type not in ASSERTION_TYPES:
        raise V2AssemblyError(f"Unsupported assertion type: {assertion_type}")
    expression_id = _expression(store, assertion_id, expression_text)
    return store.add(
        {
            "id": assertion_id,
            "type": assertion_type,
            "subject": [subject_id],
            "expression": [expression_id],
            "expressionText": expression_text,
            "severity": severity,
        }
    )


def _probability(store: _ObjectStore, owner_id: str, role: str, value: Any) -> list[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return []
    probability_id = f"PV-{owner_id}-{role.upper()}"
    store.add({"id": probability_id, "type": "ProbabilityValue", "value": float(value)})
    return [probability_id]


def _resolve_agent_handoffs(entities: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    agent_records = [record for record in entities if _text(record.get("@type")) == "Agent"]
    entity_ids = {_id(record) for record in agent_records}
    by_source = {
        _text(record.get("sourceAgentId")): _id(record)
        for record in agent_records
        if _text(record.get("sourceAgentId"))
    }
    by_source_token = {_token(source): entity_id for source, entity_id in by_source.items()}
    resolved: dict[str, list[str]] = {}
    for record in agent_records:
        targets: list[str] = []
        for raw_target in _refs(record.get("handoffTargetRefs")):
            target = ""
            if raw_target in entity_ids:
                target = raw_target
            elif raw_target in by_source:
                target = by_source[raw_target]
            else:
                token_matches = [
                    entity_id
                    for source_token, entity_id in by_source_token.items()
                    if _token(raw_target).endswith(source_token)
                ]
                if len(token_matches) == 1:
                    target = token_matches[0]
            if target and target not in targets:
                targets.append(target)
        resolved[_id(record)] = targets
    return resolved


def _domain_capability_providers(
    entities: Sequence[Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Index concrete Agent providers in stable source order.

    A projected capability is a domain-facing capability when at least one
    modeled Agent declares it in ``providedCapabilityRefs``.  New user-facing
    v0.5 CapabilityUses carry an explicit ``preferredProviderRef`` and never
    depend on this ordering.  Stable source order remains only as a backwards-
    compatibility fallback for historical v0.5 fixtures.
    """

    providers: dict[str, list[str]] = {}
    for record in entities:
        if _text(record.get("@type")) != "Agent":
            continue
        provider_id = _id(record)
        if not provider_id:
            continue
        for capability_id in _refs(record.get("providedCapabilityRefs")):
            capability_providers = providers.setdefault(capability_id, [])
            if provider_id not in capability_providers:
                capability_providers.append(provider_id)
    return providers


def _domain_provider_semantic_errors(instance: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return executable-profile errors not expressible by the core metamodel.

    The canonical V2 invariant verifies that a provider advertises a
    Capability.  It cannot distinguish a concrete Domain Agent from an
    orchestration service, though.  This pipeline-level invariant closes that
    gap for capabilities explicitly advertised by one or more Agent objects.
    """

    objects = [
        item for item in instance.get("objects") or [] if isinstance(item, Mapping)
    ]
    by_id = {
        _text(item.get("id")): item for item in objects if _text(item.get("id"))
    }
    agent_ids = {
        object_id
        for object_id, item in by_id.items()
        if _text(item.get("type")) == "Agent"
    }
    agent_providers_by_capability: dict[str, set[str]] = {}
    for agent_id in agent_ids:
        for capability_id in _refs(by_id[agent_id].get("providedCapability")):
            agent_providers_by_capability.setdefault(capability_id, set()).add(agent_id)

    errors: list[dict[str, str]] = []
    for capability_use in (
        item for item in objects if _text(item.get("type")) == "CapabilityUse"
    ):
        use_id = _text(capability_use.get("id"))
        capability_ids = _refs(
            capability_use.get("typeRef") or capability_use.get("capability")
        )
        provider_ids = _refs(capability_use.get("provider"))
        if len(capability_ids) != 1 or len(provider_ids) != 1:
            continue
        capability_id = capability_ids[0]
        domain_provider_ids = agent_providers_by_capability.get(capability_id, set())
        if domain_provider_ids and provider_ids[0] not in domain_provider_ids:
            errors.append(
                {
                    "code": "RCA-DOMAIN-PROVIDER",
                    "severity": "error",
                    "path": f"objects.{use_id}.provider",
                    "message": (
                        f"CapabilityUse {use_id} references domain Capability "
                        f"{capability_id}, but provider {provider_ids[0]} is not one "
                        "of its modeled Agent providers."
                    ),
                }
            )
            continue
        if not domain_provider_ids:
            continue

        has_explicit_grounded_target = any(
            _text(by_id.get(parameter_id, {}).get("key")) == "modelGroundedTarget"
            for parameter_id in _refs(capability_use.get("parameter"))
        )
        if not has_explicit_grounded_target:
            # Historical v0.5 fixtures did not encode provider/target intent.
            # They remain importable, but only newly explicit interactions are
            # eligible for the stronger spatial responsibility invariant.
            continue
        target_ids = _refs(capability_use.get("target"))
        asset_targets = [
            target_id
            for target_id in target_ids
            if _text(by_id.get(target_id, {}).get("entityRole")) == "sceneObject"
        ]
        if len(asset_targets) != 1:
            errors.append(
                {
                    "code": "RCA-DOMAIN-TARGET",
                    "severity": "error",
                    "path": f"objects.{use_id}.target",
                    "message": (
                        f"CapabilityUse {use_id} must target exactly one sceneObject "
                        f"for provider {provider_ids[0]}."
                    ),
                }
            )
            continue

        asset = by_id[asset_targets[0]]
        source_object_id = _text(asset.get("sourceId"))
        expected_groups = set(_refs(asset.get("objectGroup"))) | {
            object_id
            for object_id, item in by_id.items()
            if _text(item.get("entityRole")) == "objectGroup"
            and source_object_id in _refs(item.get("sourceObjectId"))
        }
        expected_zones = {
            object_id
            for object_id, item in by_id.items()
            if _text(item.get("entityRole")) == "semanticZone"
            and source_object_id in _refs(item.get("sourceObjectId"))
        }
        candidate_owner_ids = {
            "asset": sorted(
                agent_id
                for agent_id in agent_ids
                if asset_targets[0]
                in _refs(by_id[agent_id].get("groundedAsset"))
            ),
            "group": sorted(
                agent_id
                for agent_id in agent_ids
                if expected_groups.intersection(
                    _refs(by_id[agent_id].get("groundedObjectGroup"))
                )
            ),
            "zone": sorted(
                agent_id
                for agent_id in agent_ids
                if expected_zones.intersection(
                    _refs(by_id[agent_id].get("responsibleZone"))
                )
            ),
        }
        selected_tier = next(
            (
                tier
                for tier in ("asset", "group", "zone")
                if candidate_owner_ids[tier]
            ),
            "unassigned",
        )
        selected_owner_ids = (
            candidate_owner_ids[selected_tier]
            if selected_tier != "unassigned"
            else []
        )
        if (
            len(selected_owner_ids) != 1
            or selected_owner_ids[0] != provider_ids[0]
        ):
            errors.append(
                {
                    "code": "RCA-DOMAIN-TARGET",
                    "severity": "error",
                    "path": f"objects.{use_id}.target",
                    "message": (
                        f"CapabilityUse {use_id} provider {provider_ids[0]} must "
                        f"equal the unique Asset>Group>Zone responsibility "
                        f"resolution for {asset_targets[0]}; selected tier "
                        f"{selected_tier} has candidates {selected_owner_ids}."
                    ),
                }
            )
            continue

        actual_groups = {
            target_id
            for target_id in target_ids
            if _text(by_id.get(target_id, {}).get("entityRole")) == "objectGroup"
        }
        if actual_groups != expected_groups:
            errors.append(
                {
                    "code": "RCA-DOMAIN-GROUP",
                    "severity": "error",
                    "path": f"objects.{use_id}.target",
                    "message": (
                        f"CapabilityUse {use_id} has object-group targets inconsistent "
                        f"with asset {asset_targets[0]} and provider {provider_ids[0]}."
                    ),
                }
            )
        actual_zones = {
            target_id
            for target_id in target_ids
            if _text(by_id.get(target_id, {}).get("entityRole")) == "semanticZone"
        }
        if actual_zones != expected_zones:
            errors.append(
                {
                    "code": "RCA-DOMAIN-ZONE",
                    "severity": "error",
                    "path": f"objects.{use_id}.target",
                    "message": (
                        f"CapabilityUse {use_id} has zone targets inconsistent with "
                        f"asset {asset_targets[0]} and provider {provider_ids[0]}."
                    ),
                }
            )
    return errors


def _application_action_kind(
    binding_source: Mapping[str, Any],
    action_source: Mapping[str, Any],
) -> str:
    """Classify the legacy locator once and serialize the result explicitly.

    Runtime and Unity consumers must never repeat this compatibility heuristic;
    they consume the ``applicationActionKind`` marker written into the native
    V2 action's modeled input SchemaReference.
    """

    locator = action_source.get("locator") or {}
    locator_kind = _text(locator.get("kind")).casefold()
    locator_value = _text(locator.get("value")).casefold().rstrip("/")
    if locator_kind != "endpoint":
        return "runtime"
    endpoint = locator_value.rsplit(" ", 1)[-1]
    if endpoint == "/setup":
        return "setup"
    if endpoint == "/chat":
        semantic_hint = " ".join(
            (
                _id(binding_source),
                " ".join(_refs(binding_source.get("capabilityRef"))),
                _id(action_source),
            )
        ).casefold()
        return "handoff" if "handoff" in semantic_hint else "chat"
    return "runtime"


def _model_binding_descriptor(
    *,
    runtime_binding_id: str,
    runtime_action_id: str,
    capability_ids: Sequence[str],
    capability_use_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "runtimeBindingId": runtime_binding_id,
        "runtimeActionId": runtime_action_id,
        "capabilityIds": list(capability_ids),
        "capabilityUseIds": list(capability_use_ids),
    }


def _bounded_id_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": SPATIAL_ID_MAX_LENGTH,
    }


def _spatial_context_wire_schema() -> dict[str, Any]:
    coordinate = {
        "type": "number",
        "minimum": -SPATIAL_COORDINATE_LIMIT,
        "maximum": SPATIAL_COORDINATE_LIMIT,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "model_sha256",
            "state",
            "hit_position",
            "distance_m",
            "selection_modality",
        ],
        "properties": {
            "model_sha256": {
                "type": "string",
                "pattern": "^[0-9A-Fa-f]{64}$",
            },
            "state": {"const": "resolved"},
            "entity_id": _bounded_id_schema(),
            "source_object_id": _bounded_id_schema(),
            "source_id": _bounded_id_schema(),
            "object_group_id": _bounded_id_schema(),
            "zone_id": _bounded_id_schema(),
            "hit_position": {
                "type": "object",
                "additionalProperties": False,
                "required": ["x", "y", "z"],
                "properties": {
                    "x": coordinate,
                    "y": coordinate,
                    "z": coordinate,
                },
            },
            "distance_m": {
                "type": "number",
                "minimum": 0,
                "maximum": SPATIAL_DISTANCE_LIMIT_METERS,
            },
            "selection_modality": {
                "type": "string",
                "enum": list(SPATIAL_SELECTION_MODALITIES),
            },
            "modality": {
                "type": "string",
                "enum": list(SPATIAL_SELECTION_MODALITIES),
            },
            "candidate_entity_ids": {
                "type": "array",
                "maxItems": SPATIAL_CANDIDATE_LIMIT,
                "uniqueItems": True,
                "items": _bounded_id_schema(),
            },
            "ambiguous": {"type": "boolean"},
            "ambiguity": {
                "oneOf": [
                    {"type": "boolean"},
                    {
                        "type": "object",
                        "additionalProperties": True,
                        "maxProperties": 8,
                    },
                ]
            },
            "ambiguity_reason": {
                "type": "string",
                "maxLength": SPATIAL_REASON_MAX_LENGTH,
            },
        },
        "anyOf": [
            {"required": ["entity_id"]},
            {"required": ["source_object_id"]},
            {"required": ["source_id"]},
        ],
    }


def _request_wire_schema(
    *,
    application_action_kind: str,
    model_binding: Mapping[str, Any],
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": WIRE_SCHEMA_DIALECT,
        "$id": (
            "urn:roomcontract:wire:"
            f"{application_action_kind}:request:{WIRE_CONTRACT_VERSION}"
        ),
        "title": f"Interactive Agents {application_action_kind} request",
        "type": "object",
        "additionalProperties": True,
        "applicationActionKind": application_action_kind,
        "wireContractVersion": WIRE_CONTRACT_VERSION,
        "modelBinding": dict(model_binding),
    }
    if application_action_kind not in {"chat", "handoff"}:
        return schema
    schema.update(
        {
            "required": [
                "session_id",
                "active_agent_id",
                "user_text",
                "interaction_mode",
            ],
            "properties": {
                "session_id": _bounded_id_schema(),
                "active_agent_id": _bounded_id_schema(),
                "user_text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 32_768,
                },
                "interaction_mode": {
                    "type": "string",
                    "enum": list(INTERACTION_MODES),
                },
                "spatial_context": _spatial_context_wire_schema(),
            },
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "interaction_mode": {"const": "deictic"}
                        },
                        "required": ["interaction_mode"],
                    },
                    "then": {"required": ["spatial_context"]},
                },
                {
                    "if": {
                        "properties": {
                            "interaction_mode": {"const": "non_deictic"}
                        },
                        "required": ["interaction_mode"],
                    },
                    "then": {"not": {"required": ["spatial_context"]}},
                },
            ],
        }
    )
    return schema


def _response_wire_schema(
    *,
    application_action_kind: str,
    model_binding: Mapping[str, Any],
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": WIRE_SCHEMA_DIALECT,
        "$id": (
            "urn:roomcontract:wire:"
            f"{application_action_kind}:response:{WIRE_CONTRACT_VERSION}"
        ),
        "title": f"Interactive Agents {application_action_kind} response",
        "type": "object",
        "additionalProperties": True,
        "applicationActionKind": application_action_kind,
        "wireContractVersion": WIRE_CONTRACT_VERSION,
        "modelBinding": dict(model_binding),
    }
    if application_action_kind not in {"chat", "handoff"}:
        return schema
    grounding_fields = [
        "grounded_entity_ids",
        "grounding_evidence",
        "routing_reason",
        "grounding",
        "routing",
    ]
    schema.update(
        {
            "required": [
                "session_id",
                "active_agent_id",
                "memory_mode",
                "handoff",
                "events",
                "interaction_mode",
                "model_binding",
            ],
            "properties": {
                "session_id": _bounded_id_schema(),
                "active_agent_id": _bounded_id_schema(),
                "memory_mode": {"type": "string"},
                "handoff": {"type": ["object", "null"]},
                "events": {"type": "array"},
                "interaction_mode": {
                    "type": "string",
                    "enum": list(INTERACTION_MODES),
                },
                "model_binding": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "runtime_binding_id",
                        "runtime_action_id",
                        "capability_id",
                        "capability_use_id",
                    ],
                    "properties": {
                        "runtime_binding_id": _bounded_id_schema(),
                        "runtime_action_id": _bounded_id_schema(),
                        "capability_id": _bounded_id_schema(),
                        "capability_use_id": _bounded_id_schema(),
                    },
                },
                "grounded_entity_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "uniqueItems": True,
                    "items": _bounded_id_schema(),
                },
                "grounding_evidence": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 128,
                    "items": {"type": "object"},
                },
                "routing_reason": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2_048,
                },
                "grounding": {"type": "object"},
                "routing": {"type": "object"},
            },
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "interaction_mode": {"const": "deictic"}
                        },
                        "required": ["interaction_mode"],
                    },
                    "then": {"required": grounding_fields},
                },
                {
                    "if": {
                        "properties": {
                            "interaction_mode": {"const": "non_deictic"}
                        },
                        "required": ["interaction_mode"],
                    },
                    "then": {
                        "not": {
                            "anyOf": [
                                {"required": [field_name]}
                                for field_name in grounding_fields
                            ]
                        }
                    },
                },
            ],
        }
    )
    return schema


def _build_native_instance(projection: Mapping[str, Any]) -> dict[str, Any]:
    semantic = projection.get("dynamicFunctionalModel")
    if not isinstance(semantic, Mapping):
        raise V2AssemblyError("import_v05 returned no semantic DynamicFunctionalModel projection")

    case_id = _text(projection.get("caseId"))
    prefix = _token(case_id)
    root_id = f"DFM-{prefix}"
    vv_id = f"VV-{prefix}"
    orchestrator_id = f"ENT-{prefix}-RUNTIME-ORCHESTRATOR"
    store = _ObjectStore()

    requirements_model = semantic.get("requirementsModel") or {}
    requirement_ids: list[str] = []
    for source in requirements_model.get("requirements") or []:
        requirement_id = _id(source)
        requirement_ids.append(requirement_id)
        record = {"id": requirement_id, "type": "Requirement"}
        _optional(record, "text", source.get("text"))
        store.add(record)

    use_case_ids: list[str] = []
    for source in requirements_model.get("useCases") or []:
        use_case_id = _id(source)
        use_case_ids.append(use_case_id)
        record = {
            "id": use_case_id,
            "type": "UseCase",
            "extensionPoint": [],
            "include": [],
            "extend": [],
        }
        _optional(record, "name", source.get("name"))
        store.add(record)

    requirements_model_id = _id(requirements_model) or f"RM-{prefix}"
    store.add(
        {
            "id": requirements_model_id,
            "type": "RequirementsModel",
            "requirement": requirement_ids,
            "useCase": use_case_ids,
        }
    )

    actor_ids: list[str] = []
    for source in semantic.get("actors") or []:
        actor_id = _id(source)
        actor_ids.append(actor_id)
        record = {"id": actor_id, "type": "Actor"}
        _optional(record, "name", source.get("name"))
        _optional(record, "text", source.get("text"))
        store.add(record)

    capability_sources = [item for item in semantic.get("capabilities") or [] if isinstance(item, Mapping)]
    capability_ids = [_id(item) for item in capability_sources]

    entity_sources = [item for item in semantic.get("entities") or [] if isinstance(item, Mapping)]
    handoff_targets = _resolve_agent_handoffs(entity_sources)
    domain_capability_providers = _domain_capability_providers(entity_sources)
    entity_ids: list[str] = []
    for source in entity_sources:
        entity_id = _id(source)
        entity_type = "Agent" if _text(source.get("@type")) == "Agent" else "Entity"
        entity_ids.append(entity_id)
        record: dict[str, Any] = {"id": entity_id, "type": entity_type}
        mappings = {
            "name": "name",
            "kind": "kind",
            "sourceId": "sourceId",
            "entityRole": "entityRole",
            "sourceObjectIds": "sourceObjectId",
            "purpose": "purpose",
            "sourceGroup": "sourceGroup",
            "objectType": "objectType",
            "objectGroupRef": "objectGroup",
            "sourceAgentId": "sourceAgentId",
            "displayName": "displayName",
            "persona": "persona",
            "expertise": "expertise",
            "knowledgeTags": "knowledgeTag",
            "voice": "voice",
            "voiceGender": "voiceGender",
            "voiceStyle": "voiceStyle",
            "ttsModel": "ttsModel",
            "playsActorRefs": "playsActor",
            "providedCapabilityRefs": "providedCapability",
            "responsibleZoneRefs": "responsibleZone",
            "groundedAssetRefs": "groundedAsset",
            "groundedObjectGroupRefs": "groundedObjectGroup",
        }
        for source_name, target_name in mappings.items():
            value = source.get(source_name)
            if target_name in {
                "sourceObjectId",
                "expertise",
                "knowledgeTag",
                "objectGroup",
                "playsActor",
                "providedCapability",
                "responsibleZone",
                "groundedAsset",
                "groundedObjectGroup",
            }:
                value = _refs(value)
            _optional(record, target_name, value)
        if entity_type == "Agent":
            record["kind"] = "agent"
            record["handoffTarget"] = handoff_targets.get(entity_id, [])
        store.add(record)

    entity_ids.append(orchestrator_id)
    store.add(
        {
            "id": orchestrator_id,
            "type": "Entity",
            "name": "Runtime Orchestrator",
            "sourceId": "runtime-orchestrator",
            "entityRole": "runtimeOrchestrator",
            "purpose": "Executable provider for pipeline and runtime-infrastructure capability uses.",
            "providedCapability": [
                capability_id
                for capability_id in capability_ids
                if capability_id not in domain_capability_providers
            ],
        }
    )

    event_ids: list[str] = []
    for source in semantic.get("scenarioEvents") or []:
        event_id = _id(source)
        event_ids.append(event_id)
        kind = _text(source.get("kind"))
        event_type = "ScenarioExternalEvent" if kind in {"user", "environment", "spatial"} else "ScenarioEvent"
        store.add(
            {
                "id": event_id,
                "type": event_type,
                "kind": kind,
                "expressionText": _text(source.get("mixedStringContent")),
                "mixedStringContent": _text(source.get("mixedStringContent")),
            }
        )

    condition_ids: list[str] = []
    for source in semantic.get("scenarioConditions") or []:
        condition_id = _id(source)
        condition_ids.append(condition_id)
        store.add(
            {
                "id": condition_id,
                "type": "ScenarioCondition",
                "kind": _text(source.get("kind")),
                "datatype": "EABoolean",
                "expressionText": _text(source.get("mixedStringContent")),
                "mixedStringContent": _text(source.get("mixedStringContent")),
            }
        )

    assertion_ids: list[str] = []
    assertion_subjects: dict[str, str] = {}
    for source in semantic.get("assertions") or []:
        assertion_id = _id(source)
        subject_refs = _refs(source.get("subjectRef"))
        subject_id = subject_refs[0] if subject_refs else orchestrator_id
        expression_source = source.get("expression") or {}
        expression_text = _text(expression_source.get("mixedStringContent") or source.get("expressionText"))
        _assertion(
            store,
            assertion_id=assertion_id,
            assertion_type="StateAssertion",
            subject_id=subject_id,
            expression_text=expression_text,
            severity="error",
        )
        assertion_ids.append(assertion_id)
        assertion_subjects[assertion_id] = subject_id

    capability_effects: dict[str, list[str]] = {}
    capability_targets: dict[str, list[str]] = {}
    for source in capability_sources:
        capability_id = _id(source)
        effect_ids: list[str] = []
        target_ids: list[str] = []
        for effect_source in source.get("effects") or []:
            effect_id = _id(effect_source)
            specified_by = _refs(effect_source.get("specifiedByRefs"))
            if not specified_by:
                raise V2AssemblyError(f"Capability effect {effect_id} has no projected Assertion")
            effect_ids.append(effect_id)
            for assertion_id in specified_by:
                subject_id = assertion_subjects.get(assertion_id)
                if subject_id and subject_id not in target_ids:
                    target_ids.append(subject_id)
            effect = {
                "id": effect_id,
                "type": "Effect",
                "specifiedBy": specified_by,
            }
            _optional(effect, "text", effect_source.get("text"))
            store.add(effect)
        capability_effects[capability_id] = effect_ids
        capability_targets[capability_id] = target_ids or [orchestrator_id]
        capability = {
            "id": capability_id,
            "type": "Capability",
            "precondition": _refs(source.get("preconditionRefs")),
            "effect": effect_ids,
        }
        _optional(capability, "name", source.get("name"))
        _optional(capability, "text", source.get("text"))
        store.add(capability)

    capability_use_sources = {
        _id(source): source
        for source in semantic.get("capabilityUses") or []
        if isinstance(source, Mapping)
    }
    capability_use_ids_by_capability: dict[str, list[str]] = {}
    for use_id, source in capability_use_sources.items():
        for capability_id in _refs(source.get("typeRef")):
            capability_use_ids_by_capability.setdefault(capability_id, []).append(
                use_id
            )

    runtime_binding_ids: list[str] = []
    runtime_action_ids: list[str] = []
    runtime_binding_platform: dict[str, str] = {}
    application_action_counts = {"setup": 0, "chat": 0, "handoff": 0}
    for source in semantic.get("runtimeBindings") or []:
        binding_id = _id(source)
        runtime_binding_ids.append(binding_id)
        runtime_binding_platform[binding_id] = _text(source.get("targetPlatform")) or "RuntimeOrchestrator"
        action_ids: list[str] = []
        for action_source in source.get("runtimeActions") or []:
            action_id = _id(action_source)
            action_ids.append(action_id)
            runtime_action_ids.append(action_id)
            application_action_kind = _application_action_kind(source, action_source)
            if application_action_kind in application_action_counts:
                application_action_counts[application_action_kind] += 1
            locator_source = action_source.get("locator") or {}
            locator_id = f"LOC-{action_id}"
            store.add(
                {
                    "id": locator_id,
                    "type": "RuntimeActionLocator",
                    "kind": _text(locator_source.get("kind")),
                    "value": _text(locator_source.get("value")),
                }
            )
            action: dict[str, Any] = {
                "id": action_id,
                "type": "RuntimeAction",
                "locator": [locator_id],
                "runtimeParameter": [],
            }
            binding_capability_ids = _refs(source.get("capabilityRef"))
            binding_capability_use_ids = [
                use_id
                for capability_id in binding_capability_ids
                for use_id in capability_use_ids_by_capability.get(
                    capability_id,
                    [],
                )
            ]
            model_binding = _model_binding_descriptor(
                runtime_binding_id=binding_id,
                runtime_action_id=action_id,
                capability_ids=binding_capability_ids,
                capability_use_ids=binding_capability_use_ids,
            )
            input_schema = _text(action_source.get("inputSchemaRef"))
            schema_id = f"SCHEMA-{action_id}-INPUT"
            store.add(
                {
                    "id": schema_id,
                    "type": "SchemaReference",
                    "uri": input_schema or "urn:roomcontract:schema:unspecified",
                    "text": json.dumps(
                        _request_wire_schema(
                            application_action_kind=application_action_kind,
                            model_binding=model_binding,
                        ),
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
            action["inputSchema"] = [schema_id]
            output_schema = _text(action_source.get("outputSchemaRef"))
            if output_schema:
                schema_id = f"SCHEMA-{action_id}-OUTPUT"
                store.add(
                    {
                        "id": schema_id,
                        "type": "SchemaReference",
                        "uri": output_schema,
                        "text": json.dumps(
                            _response_wire_schema(
                                application_action_kind=application_action_kind,
                                model_binding=model_binding,
                            ),
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                )
                action["outputSchema"] = [schema_id]
            store.add(action)
        if not action_ids:
            raise V2AssemblyError(f"RuntimeBinding {binding_id} has no RuntimeAction")
        store.add(
            {
                "id": binding_id,
                "type": "RuntimeBinding",
                "targetPlatform": runtime_binding_platform[binding_id],
                "capability": _refs(source.get("capabilityRef")),
                "runtimeAction": action_ids,
            }
        )

    invalid_application_counts = {
        kind: count for kind, count in application_action_counts.items() if count != 1
    }
    if invalid_application_counts:
        raise V2AssemblyError(
            "Executable V2 fixture requires exactly one setup, chat and handoff "
            f"application action; got {invalid_application_counts}"
        )

    scenario_step_sources = {
        _id(source): source
        for source in semantic.get("scenarioSteps") or []
        if isinstance(source, Mapping)
    }
    scenario_ids: list[str] = []
    capability_use_ids: list[str] = []
    for scenario_source in semantic.get("scenarios") or []:
        scenario_id = _id(scenario_source)
        scenario_ids.append(scenario_id)
        step_ids = _refs(scenario_source.get("stepRefs"))
        relation_ids: list[str] = []
        parallel_ids: list[str] = []
        for step_id in step_ids:
            step_source = scenario_step_sources.get(step_id)
            if step_source is None:
                raise V2AssemblyError(f"Scenario {scenario_id} references missing projected step {step_id}")
            use_ids = _refs(step_source.get("capabilityUseRefs"))
            step_provider_ids: list[str] = []
            for use_id in use_ids:
                if use_id in capability_use_ids:
                    raise V2AssemblyError(f"CapabilityUse {use_id} is composed by more than one ScenarioStep")
                source = capability_use_sources.get(use_id)
                if source is None:
                    raise V2AssemblyError(f"ScenarioStep {step_id} references missing CapabilityUse {use_id}")
                type_refs = _refs(source.get("typeRef"))
                if len(type_refs) != 1:
                    raise V2AssemblyError(f"CapabilityUse {use_id} needs exactly one Capability type")
                domain_providers = domain_capability_providers.get(type_refs[0], [])
                preferred_provider_refs = _refs(source.get("preferredProviderRef"))
                if len(preferred_provider_refs) > 1:
                    raise V2AssemblyError(
                        f"CapabilityUse {use_id} has more than one preferred provider"
                    )
                if preferred_provider_refs:
                    provider_id = preferred_provider_refs[0]
                    if provider_id not in domain_providers:
                        raise V2AssemblyError(
                            f"CapabilityUse {use_id} prefers {provider_id}, which does "
                            f"not provide Capability {type_refs[0]}"
                        )
                else:
                    provider_id = domain_providers[0] if domain_providers else orchestrator_id
                explicit_target_refs = _refs(source.get("targetRefs"))
                unknown_target_refs = [
                    target_id
                    for target_id in explicit_target_refs
                    if target_id not in entity_ids
                ]
                if unknown_target_refs:
                    raise V2AssemblyError(
                        f"CapabilityUse {use_id} references unknown explicit targets: "
                        + ", ".join(unknown_target_refs)
                    )
                parameter_refs: list[str] = []
                if explicit_target_refs:
                    explicit_target_parameter_id = (
                        f"PARAM-{use_id}-MODEL-GROUNDED-TARGET"
                    )
                    store.add(
                        {
                            "id": explicit_target_parameter_id,
                            "type": "KeyValueParameter",
                            "key": "modelGroundedTarget",
                        }
                    )
                    parameter_refs.append(explicit_target_parameter_id)
                parameters = source.get("parameters") or []
                if parameters not in ([], {}):
                    iterable: Iterable[Any] = parameters.items() if isinstance(parameters, Mapping) else parameters
                    for index, parameter in enumerate(iterable, start=1):
                        if isinstance(parameter, tuple) and len(parameter) == 2:
                            key, value = parameter
                        elif isinstance(parameter, Mapping):
                            key = parameter.get("key") or parameter.get("name") or f"parameter-{index}"
                            value = parameter.get("value")
                        else:
                            key, value = f"parameter-{index}", parameter
                        parameter_id = f"PARAM-{use_id}-{_token(key)}"
                        parameter_record: dict[str, Any] = {
                            "id": parameter_id,
                            "type": "KeyValueParameter",
                            "key": _text(key),
                        }
                        if value is not None:
                            value_id = f"VALUE-{parameter_id}"
                            store.add(
                                {
                                    "id": value_id,
                                    "type": "EAExpression",
                                    "mixedStringContent": json.dumps(value, ensure_ascii=False, sort_keys=True)
                                    if not isinstance(value, str)
                                    else value,
                                }
                            )
                            parameter_record["value"] = [value_id]
                        store.add(parameter_record)
                        parameter_refs.append(parameter_id)
                store.add(
                    {
                        "id": use_id,
                        "type": "CapabilityUse",
                        "typeRef": type_refs,
                        "provider": [provider_id],
                        "target": (
                            []
                            if not explicit_target_refs
                            and use_id.endswith(
                                (
                                    "-S11-ANSWER-ROOM-GROUNDED-QUESTION",
                                    "-S12-HANDOFF-TO-RESPONSIBLE-AGENT",
                                )
                            )
                            else (
                                explicit_target_refs
                                if explicit_target_refs
                                else capability_targets.get(
                                    type_refs[0], [orchestrator_id]
                                )
                            )
                        ),
                        "parameter": parameter_refs,
                    }
                )
                capability_use_ids.append(use_id)
                if provider_id not in step_provider_ids:
                    step_provider_ids.append(provider_id)
            step: dict[str, Any] = {
                "id": step_id,
                "type": "ScenarioStep",
                "kind": _text(step_source.get("kind")),
                "actorRole": _refs(step_source.get("actorRoleRefs")),
                "performedBy": step_provider_ids,
                "triggeredBy": _refs(step_source.get("eventRefs")),
                "resultingAssertion": _refs(step_source.get("resultingAssertionRefs")),
                "capabilityUse": use_ids,
            }
            _optional(step, "text", step_source.get("text"))
            condition_refs = _refs(step_source.get("conditionRef"))
            if condition_refs:
                step["guard"] = condition_refs
            occurrence = _probability(store, step_id, "occurrence", step_source.get("occurrenceProbability"))
            if occurrence:
                step["occurrenceProbability"] = occurrence
            store.add(step)

        for relation_source in scenario_source.get("stepRelations") or []:
            relation_id = _id(relation_source)
            relation_ids.append(relation_id)
            kind = _text(relation_source.get("kind"))
            relation: dict[str, Any] = {
                "id": relation_id,
                "type": "StepRelation",
                "kind": kind,
                "sourceStep": _refs(relation_source.get("sourceStepRef")),
                "targetStep": _refs(relation_source.get("targetStepRef")),
                # Validator aliases; canonical model roles remain sourceStep/targetStep.
                "source": _refs(relation_source.get("sourceStepRef")),
                "target": _refs(relation_source.get("targetStepRef")),
            }
            guard = _refs(relation_source.get("guardRef"))
            if guard:
                relation["guard"] = guard
            if kind in {"alternative", "exception"}:
                probability = _probability(store, relation_id, "branch", relation_source.get("probability"))
                if probability:
                    relation["probability"] = probability
            store.add(relation)

        for group_source in scenario_source.get("parallelGroups") or []:
            group_id = _id(group_source)
            parallel_ids.append(group_id)
            group = {
                "id": group_id,
                "type": "ParallelGroup",
                "memberStep": _refs(group_source.get("memberStepRefs")),
            }
            _optional(group, "name", group_source.get("name"))
            store.add(group)

        scenario: dict[str, Any] = {
            "id": scenario_id,
            "type": "Scenario",
            "kind": _text(scenario_source.get("kind")),
            "precondition": _refs(scenario_source.get("preconditionRefs")),
            "postcondition": _refs(scenario_source.get("postconditionRefs")),
            "step": step_ids,
            "stepRelation": relation_ids,
            "parallelGroup": parallel_ids,
        }
        _optional(scenario, "text", scenario_source.get("text"))
        variant = _refs(scenario_source.get("variantOfRef"))
        if variant:
            scenario["variantOf"] = variant
        store.add(scenario)

    # Four additional assertion kinds make the complete V2 assertion surface
    # executable without changing the projected StateAssertion semantics.
    if not assertion_ids:
        fallback_id = f"AST-{prefix}-DERIVED-STATE"
        _assertion(
            store,
            assertion_id=fallback_id,
            assertion_type="StateAssertion",
            subject_id=orchestrator_id,
            expression_text="The native V2 runtime model is assembled.",
            severity="info",
        )
        assertion_ids.append(fallback_id)
        assertion_subjects[fallback_id] = orchestrator_id

    derived_assertions = [
        (
            f"AST-{prefix}-DERIVED-EVENT",
            "EventAssertion",
            event_ids[0] if event_ids else orchestrator_id,
            "The projected runtime trigger is observable.",
            "warning",
        ),
        (
            f"AST-{prefix}-DERIVED-OUTPUT",
            "OutputAssertion",
            runtime_action_ids[0] if runtime_action_ids else orchestrator_id,
            "The bound runtime action produces an observable output.",
            "error",
        ),
        (
            f"AST-{prefix}-DERIVED-GROUNDING",
            "GroundingAssertion",
            next((item for item in entity_ids if item != orchestrator_id), orchestrator_id),
            "The runtime participant remains grounded in an identifiable model entity.",
            "warning",
        ),
        (
            f"AST-{prefix}-DERIVED-RELATION",
            "RelationAssertion",
            capability_use_ids[0] if capability_use_ids else orchestrator_id,
            "The capability occurrence is linked to its explicit provider and targets.",
            "critical",
        ),
    ]
    for assertion_id, assertion_type, subject_id, expression_text, severity in derived_assertions:
        _assertion(
            store,
            assertion_id=assertion_id,
            assertion_type=assertion_type,
            subject_id=subject_id,
            expression_text=expression_text,
            severity=severity,
        )
        assertion_ids.append(assertion_id)
        assertion_subjects[assertion_id] = subject_id

    owned_relationship_ids: list[str] = []
    semantic_relationships = [
        item for item in semantic.get("ownedRelationships") or [] if isinstance(item, Mapping)
    ]
    for source in semantic_relationships:
        relationship_type = _text(source.get("@type"))
        relationship_id = _id(source)
        if relationship_type == "ActorParticipation":
            store.add(
                {
                    "id": relationship_id,
                    "type": relationship_type,
                    "actor": _refs(source.get("actorRef")),
                    "useCase": _refs(source.get("useCaseRef")),
                }
            )
            owned_relationship_ids.append(relationship_id)
        elif relationship_type == "UseCaseScenarioSpecification":
            store.add(
                {
                    "id": relationship_id,
                    "type": relationship_type,
                    "useCase": _refs(source.get("useCaseRef")),
                    "scenario": _refs(source.get("scenarioRef")),
                }
            )
            owned_relationship_ids.append(relationship_id)
        elif relationship_type == "Satisfy":
            store.add(
                {
                    "id": relationship_id,
                    "type": relationship_type,
                    "satisfiedRequirement": _refs(source.get("satisfiedRequirementRefs")),
                    "satisfiedUseCase": _refs(source.get("satisfiedUseCaseRefs")),
                    "satisfiedBy": _refs(source.get("satisfiedByRefs")),
                }
            )
            owned_relationship_ids.append(relationship_id)

    verification = semantic.get("verificationValidation") or {}
    target_ids: list[str] = []
    for source in verification.get("vvTargets") or []:
        target_id = _id(source)
        binding_refs = _refs(source.get("runtimeBindingRefs"))
        target_ids.append(target_id)
        store.add(
            {
                "id": target_id,
                "type": "RuntimeValidationTarget",
                "platform": _text(source.get("platform")) or "RuntimeOrchestrator",
                "environmentRef": f"case:{case_id}",
                "element": _refs(source.get("elementRefs")) or binding_refs,
                "runtimeBinding": binding_refs,
            }
        )

    validation_case_ids: list[str] = []
    for source in verification.get("vvCases") or []:
        validation_case_id = _id(source)
        validation_case_ids.append(validation_case_id)
        subject_refs = _refs(source.get("vvSubjectRefs")) or [orchestrator_id]
        case_target_refs = _refs(source.get("vvTargetRefs"))
        if not case_target_refs:
            target_id = f"{validation_case_id}-TARGET-RUNTIME-ORCHESTRATOR"
            store.add(
                {
                    "id": target_id,
                    "type": "RuntimeValidationTarget",
                    "platform": "RuntimeOrchestrator",
                    "environmentRef": f"case:{case_id}",
                    "element": [orchestrator_id],
                    "runtimeBinding": [],
                }
            )
            target_ids.append(target_id)
            case_target_refs = [target_id]

        procedure_sources = [
            item for item in source.get("vvProcedures") or [] if isinstance(item, Mapping)
        ]
        if not procedure_sources:
            procedure_sources = [
                {
                    "shortName": f"{validation_case_id}-PROCEDURE",
                    "vvStimuli": [],
                    "vvIntendedOutcomes": [],
                }
            ]
        procedure_ids: list[str] = []
        log_ids: list[str] = []
        for procedure_source in procedure_sources:
            procedure_id = _id(procedure_source)
            procedure_ids.append(procedure_id)
            stimulus_ids: list[str] = []
            for stimulus_source in procedure_source.get("vvStimuli") or []:
                stimulus_id = _id(stimulus_source)
                stimulus_ids.append(stimulus_id)
                source_refs = _refs(stimulus_source.get("sourceRef"))
                stimulus: dict[str, Any] = {"id": stimulus_id, "type": "RuntimeStimulus"}
                if source_refs and source_refs[0] in event_ids:
                    stimulus["scenarioEvent"] = source_refs
                elif source_refs and source_refs[0] in runtime_action_ids:
                    stimulus["runtimeAction"] = source_refs
                else:
                    stimulus["scenarioEvent"] = [event_ids[0]] if event_ids else []
                store.add(stimulus)

            intended_ids: list[str] = []
            intended_assertions: dict[str, list[str]] = {}
            for outcome_source in procedure_source.get("vvIntendedOutcomes") or []:
                outcome_id = _id(outcome_source)
                intended_ids.append(outcome_id)
                assertions = _refs(
                    outcome_source.get("assertionRef") or outcome_source.get("assertionRefs")
                )
                intended_assertions[outcome_id] = assertions
                store.add(
                    {
                        "id": outcome_id,
                        "type": "StateAssertionOutcome",
                        "assertion": assertions,
                    }
                )
            store.add(
                {
                    "id": procedure_id,
                    "type": "RuntimeValidationProcedure",
                    "vvStimuli": stimulus_ids,
                    "vvIntendedOutcome": intended_ids,
                }
            )

            log_id = f"{procedure_id}-LOG-PENDING"
            log_ids.append(log_id)
            actual_ids: list[str] = []
            for index, outcome_id in enumerate(intended_ids, start=1):
                actual_id = f"{log_id}-ACTUAL-{index}"
                actual_ids.append(actual_id)
                result_ids: list[str] = []
                for result_index, assertion_id in enumerate(intended_assertions[outcome_id], start=1):
                    result_id = f"{actual_id}-RESULT-{result_index}"
                    result_ids.append(result_id)
                    store.add(
                        {
                            "id": result_id,
                            "type": "AssertionResult",
                            "assertion": [assertion_id],
                            "verdict": "inconclusive",
                            "evidenceRef": f"pending://{case_id}/{validation_case_id}/{assertion_id}",
                        }
                    )
                store.add(
                    {
                        "id": actual_id,
                        "type": "RuntimeActualOutcome",
                        "intendedOutcome": [outcome_id],
                        "result": result_ids,
                    }
                )
            store.add(
                {
                    "id": log_id,
                    "type": "RuntimeValidationLog",
                    "date": "1970-01-01T00:00:00Z",
                    "performedVVProcedure": [procedure_id],
                    "vvActualOutcome": actual_ids,
                    # Current canonical validator consumes this alias when
                    # checking the log owner; both arrays are identical.
                    "actualOutcome": actual_ids,
                }
            )

        store.add(
            {
                "id": validation_case_id,
                "type": "ValidationCase",
                "vvSubject": subject_refs,
                "vvTarget": case_target_refs,
                "vvProcedure": procedure_ids,
                "vvLog": log_ids,
            }
        )

    verify_ids: list[str] = []
    for source in verification.get("verifyRelationships") or []:
        verify_id = _id(source)
        verify_ids.append(verify_id)
        requirements = _refs(source.get("verifiedRequirementRef"))
        cases = _refs(source.get("verifiedByCaseRef"))
        procedures = _refs(source.get("verifiedByProcedureRef"))
        store.add(
            {
                "id": verify_id,
                "type": "Verify",
                "verifiedRequirement": requirements,
                "verifiedByCase": cases,
                "verifiedByProcedure": procedures,
                # Aliases required by the current canonical instance checker.
                "requirement": requirements,
                "vvCase": cases,
            }
        )

    for source in semantic_relationships:
        if _text(source.get("@type")) != "ValidationCaseUseCaseBinding":
            continue
        relationship_id = _id(source)
        store.add(
            {
                "id": relationship_id,
                "type": "ValidationCaseUseCaseBinding",
                "validationCase": _refs(source.get("validationCaseRef")),
                "useCase": _refs(source.get("useCaseRef")),
            }
        )
        owned_relationship_ids.append(relationship_id)

    store.add(
        {
            "id": vv_id,
            "type": "VerificationValidation",
            "vvTarget": target_ids,
            "vvCase": validation_case_ids,
            "verify": verify_ids,
        }
    )

    root = {
        "id": root_id,
        "type": "DynamicFunctionalModel",
        "requirementsModel": [requirements_model_id],
        "verificationValidation": [vv_id],
        "actor": actor_ids,
        "scenario": scenario_ids,
        "scenarioEvent": event_ids,
        "scenarioCondition": condition_ids,
        "assertion": assertion_ids,
        "entity": entity_ids,
        "capability": capability_ids,
        "runtimeBinding": runtime_binding_ids,
        "ownedRelationship": owned_relationship_ids,
    }

    return {
        "schema": V2_INSTANCE_SCHEMA,
        "id": root_id,
        "metamodelVersion": V2_METAMODEL_VERSION,
        "serializationVersion": V2_SERIALIZATION_VERSION,
        "caseId": case_id,
        "profile": V2_FIXTURE_PROFILE,
        "fixture_profile": V2_FIXTURE_PROFILE,
        "sourceContract": {
            "schema": _text((semantic.get("compatibilitySource") or {}).get("schema")),
            "metamodelVersion": _text((semantic.get("compatibilitySource") or {}).get("version")),
            "semanticProjectionSha256": structural_sha256(semantic),
        },
        "objects": [root, *store.objects],
    }


def assemble_roomcontract_v2_instance(v05_document: Mapping[str, Any]) -> dict[str, Any]:
    """Project a valid v0.5 document into the native executable V2 format."""

    projection = import_v05(v05_document)
    instance = _build_native_instance(projection)
    semantic_errors = _domain_provider_semantic_errors(instance)
    if semantic_errors:
        details = "; ".join(item["message"] for item in semantic_errors[:12])
        raise V2AssemblyError(f"Domain-provider validation failed: {details}")
    report = validate_instance(MODEL, instance, subject=f"native V2 runtime instance {instance['caseId']}")
    if not report.ok:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues[:12])
        raise V2AssemblyError(f"Canonical V2 validation failed: {details}")
    return instance


def validate_roomcontract_v2_instance(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical evidence wrapped in the pipeline validation contract."""

    canonical = validate_instance(
        MODEL,
        instance,
        subject=f"native V2 runtime instance {instance.get('caseId')}",
    ).to_dict()
    issues = [
        *list(canonical.get("issues") or []),
        *_domain_provider_semantic_errors(instance),
    ]
    errors = [issue for issue in issues if str(issue.get("severity") or "error") == "error"]
    warnings = [issue for issue in issues if str(issue.get("severity") or "") == "warning"]
    object_count = len(instance.get("objects") or [])
    return {
        **canonical,
        "status": "valid" if canonical.get("ok") and not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "object_count": object_count,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "error_count": len(errors),
        "warning_count": len(warnings),
        "ok": bool(canonical.get("ok")) and not errors,
        "issues": issues,
    }


# Short aliases form the stable public integration surface.  Keep the longer
# name for callers that prefer the domain-specific spelling.
def assemble_v2_instance(v05_document: Mapping[str, Any]) -> dict[str, Any]:
    return assemble_roomcontract_v2_instance(v05_document)


def write_v2_artifacts(
    instance: Mapping[str, Any],
    output_dir: Path,
    *,
    source_v05_path: Path | None = None,
) -> dict[str, Path]:
    """Write a native instance and its pipeline/canonical validation report."""

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    instance_path = output_dir / V2_FILENAME
    validation_path = output_dir / V2_VALIDATION_FILENAME
    payload = copy.deepcopy(dict(instance))
    report = validate_roomcontract_v2_instance(payload)
    if source_v05_path is not None:
        # Filesystem provenance belongs to the execution report, not to the
        # portable deterministic model document.
        report["source_v05_path"] = Path(source_v05_path).name
    instance_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"instance": instance_path, "validation": validation_path}


def run_v2_assembly(input_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Assemble one v0.5 file and write versioned V2 artifacts beside it."""

    input_path = Path(input_path).resolve()
    target_dir = Path(output_dir).resolve() if output_dir is not None else input_path.parent
    source = json.loads(input_path.read_text(encoding="utf-8-sig"))
    instance = assemble_v2_instance(source)
    paths = write_v2_artifacts(instance, target_dir, source_v05_path=input_path)
    report = json.loads(paths["validation"].read_text(encoding="utf-8"))
    return {
        "case_id": instance["caseId"],
        "status": "success" if report["status"] == "valid" else "needs_manual_review",
        "roomcontract_v2_path": str(paths["instance"]),
        "validation_path": str(paths["validation"]),
        "validation": report,
    }


def run_roomcontract_v2_assembly_for_case(case_dir: Path) -> dict[str, Any]:
    """Write versioned V2 artifacts without replacing the v0.5 instance."""

    case_dir = Path(case_dir).resolve()
    input_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    output_path = case_dir / "roomcontract" / V2_FILENAME
    validation_path = case_dir / "roomcontract" / V2_VALIDATION_FILENAME
    try:
        result = run_v2_assembly(input_path, case_dir / "roomcontract")
    except Exception as exc:
        update_manifest(
            case_dir,
            stage_id="roomcontract_v2_assembly",
            status="failed",
            input_paths=[input_path, *V2_IMPLEMENTATION_INPUTS],
            output_paths=[output_path, validation_path],
            errors=[str(exc)],
            metadata={"deterministic": True, "metamodel_version": V2_METAMODEL_VERSION},
        )
        raise

    report = result["validation"]
    update_manifest(
        case_dir,
        stage_id="roomcontract_v2_assembly",
        status="success" if report["status"] == "valid" else "failed",
        input_paths=[input_path, *V2_IMPLEMENTATION_INPUTS],
        output_paths=[output_path, validation_path],
        errors=[str(item) for item in report.get("errors") or []],
        warnings=[str(item) for item in report.get("warnings") or []],
        metadata={
            "deterministic": True,
            "metamodel_version": V2_METAMODEL_VERSION,
            "metrics": report.get("metrics") or {},
        },
    )
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a native Dynamic Functional RDL V2 runtime instance.")
    parser.add_argument("input", type=Path, help="v0.5 roomcontract.instance.generated.json")
    parser.add_argument("output", type=Path, help="Native V2 JSON output path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    instance = assemble_roomcontract_v2_instance(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(instance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
