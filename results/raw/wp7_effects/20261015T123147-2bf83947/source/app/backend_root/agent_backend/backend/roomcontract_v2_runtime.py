from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


V05_MODEL_VERSION = "v0.5"
V2_INSTANCE_SCHEMA = "dynamic_functional_rdl_v2_instance"
V2_MODEL_VERSION = "2.0.0-model"
V2_TRACE_SCHEMA = "roomcontract_trace_map_v2"
V2_TRACE_VERSION = "2.0"
RUNTIME_CONTEXT_SCHEMA = "roomcontract_runtime_context_v2"
WIRE_CONTRACT_VERSION = "2.0"
WIRE_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
INTERACTION_MODES = ("deictic", "non_deictic")
SPATIAL_ID_MAX_LENGTH = 256
SPATIAL_CANDIDATE_LIMIT = 16
SPATIAL_REASON_MAX_LENGTH = 512
SPATIAL_DISTANCE_LIMIT_METERS = 1_000_000
SPATIAL_COORDINATE_LIMIT = 1_000_000
SPATIAL_SELECTION_MODALITIES = frozenset(
    {
        "desktop_ray",
        "mouse_ray",
        "keyboard_mouse",
        "xr_controller_ray",
        "controller_ray",
        "gaze",
        "touch",
        "direct",
        "programmatic",
    }
)
PLACEMENT_ARTIFACT_SCHEMA = "roomcontract_agent_placements"
PLACEMENT_ARTIFACT_SCHEMA_VERSION = "2.0"
PLACEMENT_ALGORITHM_VERSION = "2.0.0"
PLACEMENT_ORIGINS = frozenset({"deterministic", "wizard_manual"})
PLACEMENT_DEPLOYMENT_FIELDS = (
    "placement_schema",
    "placement_schema_version",
    "placement_algorithm_version",
    "placement_origin",
    "placement_artifact_sha256",
    "placement_projection_sha256",
)


class RoomContractContractError(ValueError):
    """Raised when a materialized RoomContract project is inconsistent."""

    def __init__(self, message: str, *, code: str = "E_PUBLICATION_INCONSISTENT"):
        super().__init__(message)
        self.code = code


def load_project_contract(project_dir: Path, *, publication_protocol: str = "packet") -> Dict[str, Any]:
    if publication_protocol == "packet":
        return _load_project_contract_unchecked(project_dir)
    if publication_protocol != "cooperative":
        raise RoomContractContractError("Unknown publication protocol.")
    from .publication import load_consistent_contract
    return load_consistent_contract(project_dir, _load_project_contract_unchecked)


def _load_project_contract_unchecked(project_dir: Path) -> Dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    meta = _read_json(project_dir / "project.json")
    generation_mode = str(meta.get("generation_mode") or "").strip().lower()
    if generation_mode and generation_mode != "roomcontract":
        return {
            "kind": "none",
            "project": meta,
            "model_version": "",
            "profile": "none",
            "runtime_context": None,
        }

    version = _resolve_contract_version(project_dir, meta)

    if version == V2_MODEL_VERSION:
        return _load_v2_contract(project_dir, meta)
    if version in {V05_MODEL_VERSION, "0.5", ""}:
        return _load_v05_contract(project_dir, meta)
    raise RoomContractContractError(
        f"Unsupported RoomContract model version {version!r}; expected {V2_MODEL_VERSION!r} or {V05_MODEL_VERSION!r}."
    )


def load_v2_document(project_dir: Path) -> Dict[str, Any]:
    contract = load_project_contract(project_dir)
    if contract.get("kind") != "v2":
        raise RoomContractContractError("Project does not expose a native V2 RoomContract instance.")
    return dict(contract["instance"])


def runtime_actions_for_kind(
    runtime_context: Mapping[str, Any],
    action_kind: str,
) -> List[Dict[str, Any]]:
    action_kind = str(action_kind or "").strip().lower()
    return [
        dict(item)
        for item in runtime_context.get("runtime_actions", [])
        if isinstance(item, Mapping) and str(item.get("action_kind") or "").lower() == action_kind
    ]


def select_runtime_action(
    runtime_context: Mapping[str, Any],
    action_kind: str,
    *,
    scenario_id: Optional[str] = None,
    provider_entity_id: Optional[str] = None,
    target_id: Optional[str] = None,
    require_targetless: bool = False,
) -> Dict[str, Any]:
    action_kind = str(action_kind or "").strip().lower()
    matches = runtime_actions_for_kind(runtime_context, action_kind)
    filters: List[str] = []
    if scenario_id is not None:
        expected_scenario = str(scenario_id or "").strip()
        matches = [
            item
            for item in matches
            if str(item.get("scenario_id") or "").strip() == expected_scenario
        ]
        filters.append(f"scenario_id={expected_scenario!r}")
    if require_targetless:
        matches = [
            item for item in matches if not _refs(item.get("target_ids"))
        ]
        filters.append("target_ids=[]")
    if provider_entity_id is not None:
        expected_provider = str(provider_entity_id or "").strip()
        provider_matches = [
            item
            for item in matches
            if str(item.get("provider_entity_id") or "").strip()
            == expected_provider
        ]
        # A targetless chain models general communication and remains valid
        # when the currently active agent owns only target-bound chains.
        # Deictic/provider-specific selection stays strict.
        if provider_matches or not require_targetless:
            matches = provider_matches
        filters.append(f"provider_entity_id={expected_provider!r}")
    if target_id is not None:
        expected_target = str(target_id or "").strip()
        matches = [
            item
            for item in matches
            if expected_target in _refs(item.get("target_ids"))
        ]
        filters.append(f"target_id={expected_target!r}")
    if not matches:
        qualifier = f" ({', '.join(filters)})" if filters else ""
        raise RoomContractContractError(f"Runtime context has no exact action mapping for "
            f"{action_kind!r}{qualifier}.", code="E_NO_DECLARED_ACTION")
    if len(matches) > 1:
        qualifier = f" after {', '.join(filters)}" if filters else ""
        raise RoomContractContractError(f"Runtime context has {len(matches)} ambiguous action mappings for "
            f"{action_kind!r}{qualifier}.", code="E_ACTION_AMBIGUOUS")
    return matches[0]


def _load_v2_contract(project_dir: Path, meta: Mapping[str, Any]) -> Dict[str, Any]:
    instance_path = _resolve_project_file(
        project_dir,
        meta.get("roomcontract_model_path") or meta.get("roomcontract_v2_path"),
        "roomcontract.v2.instance.json",
    )
    trace_path = _resolve_project_file(
        project_dir,
        meta.get("roomcontract_trace_map_path"),
        "trace_map.v2.json",
    )
    instance = _read_json(instance_path)
    trace = _read_json(trace_path)
    _validate_optional_placement_deployment(project_dir, meta, trace)
    digest_scheme = str(meta.get("roomcontract_digest_scheme") or "sha256-raw-v1")
    trace_scheme = str(trace.get("digest_scheme") or "sha256-raw-v1")
    if digest_scheme != trace_scheme:
        raise RoomContractContractError("Project and trace digest schemes disagree.")
    model_sha256 = _sha256(instance_path, scheme=digest_scheme)
    declared_hash = str(meta.get("roomcontract_model_sha256") or "").strip().upper()
    if declared_hash and declared_hash != model_sha256:
        raise RoomContractContractError(
            f"RoomContract model hash mismatch: project.json={declared_hash}, actual={model_sha256}."
        )

    by_id = _validate_v2_instance(instance)
    _validate_v2_project_metadata(project_dir, meta, instance)
    _validate_v2_trace(trace, by_id, model_sha256, instance)
    context = _build_v2_runtime_context(instance, trace, model_sha256)
    return {
        "kind": "v2",
        "project": dict(meta),
        "model_version": V2_MODEL_VERSION,
        "profile": str(instance.get("fixture_profile") or instance.get("profile") or "executable"),
        "model_sha256": model_sha256,
        "instance_path": str(instance_path),
        "trace_path": str(trace_path),
        "instance": instance,
        "trace": trace,
        "runtime_context": context,
    }


def _load_v05_contract(project_dir: Path, meta: Mapping[str, Any]) -> Dict[str, Any]:
    trace_path = _resolve_project_file(project_dir, None, "trace_map.json", required=False)
    trace = _read_json(trace_path) if trace_path.exists() else {}
    if trace and trace.get("schema") != "roomcontract_trace_map":
        raise RoomContractContractError(
            "Legacy v0.5 projects require a roomcontract_trace_map trace; "
            f"found {trace.get('schema')!r}."
        )
    _validate_optional_placement_deployment(project_dir, meta, trace)
    legacy_model_path = _resolve_project_file(
        project_dir,
        meta.get("roomcontract_legacy_path"),
        "roomcontract.v05.instance.json",
        required=False,
    )
    if legacy_model_path.exists():
        legacy_instance = _read_json(legacy_model_path)
        if (
            legacy_instance.get("schema") != "roomcontract_case_study"
            or legacy_instance.get("metamodelVersion") != V05_MODEL_VERSION
        ):
            raise RoomContractContractError(
                "Legacy model file must be a roomcontract_case_study with metamodelVersion 'v0.5'."
            )
    actions: List[Dict[str, Any]] = []
    for item in trace.get("runtime_actions", []):
        if not isinstance(item, Mapping):
            continue
        action_kind = _legacy_action_kind(item)
        if not action_kind:
            continue
        actions.append(
            {
                "action_kind": action_kind,
                "scenario_step_id": _legacy_step_id(trace, item.get("capability_id")),
                "capability_use_id": _legacy_capability_use_id(trace, item.get("capability_id")),
                "capability_id": _optional_text(item.get("capability_id")),
                "provider_entity_id": None,
                "target_ids": [],
                "runtime_binding_id": _optional_text(item.get("runtime_binding_id")),
                "runtime_action_id": _optional_text(item.get("runtime_action_id")),
                "locator": {
                    "kind": "endpoint" if item.get("endpoint") else ("tool" if item.get("tool") else "topic"),
                    "value": item.get("endpoint") or item.get("tool") or item.get("topic"),
                },
                "assertion_ids": [],
                "validation_case_ids": [],
                "runtime_validation_target_ids": [],
            }
        )
    context = {
        "schema": RUNTIME_CONTEXT_SCHEMA,
        "case_id": trace.get("case_id"),
        "model_version": V05_MODEL_VERSION,
        "model_sha256": "",
        "profile": "legacy",
        "trace_schema_version": "1.0",
        "main_scenario_id": trace.get("main_scenario_id"),
        "runtime_validation_target_id": None,
        "runtime_actions": actions,
        "assertions": [],
        "agents": list(trace.get("agents") or []),
    }
    return {
        "kind": "v05",
        "project": dict(meta),
        "model_version": V05_MODEL_VERSION,
        "profile": "legacy",
        "model_sha256": "",
        "trace_path": str(trace_path) if trace_path.exists() else "",
        "trace": trace,
        "runtime_context": context,
    }


def _validate_v2_instance(instance: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    if instance.get("schema") != V2_INSTANCE_SCHEMA:
        raise RoomContractContractError(
            f"Native V2 instance schema must be {V2_INSTANCE_SCHEMA!r}."
        )
    if instance.get("metamodelVersion") != V2_MODEL_VERSION:
        raise RoomContractContractError(
            f"Native V2 instance must target model {V2_MODEL_VERSION!r}."
        )
    if instance.get("serializationVersion") != "1.0":
        raise RoomContractContractError("Native V2 instance serializationVersion must be '1.0'.")
    _required_text(instance.get("id"), "native V2 instance.id")
    _required_text(instance.get("caseId"), "native V2 instance.caseId")
    if str(instance.get("fixture_profile") or instance.get("profile") or "") != "executable":
        raise RoomContractContractError("Runtime projects require the executable V2 profile.")
    objects = instance.get("objects")
    if not isinstance(objects, list) or not objects:
        raise RoomContractContractError("Native V2 instance requires a non-empty objects array.")
    by_id: Dict[str, Dict[str, Any]] = {}
    for index, raw in enumerate(objects):
        if not isinstance(raw, Mapping):
            raise RoomContractContractError(f"objects[{index}] must be an object.")
        object_id = _required_text(raw.get("id"), f"objects[{index}].id")
        object_type = _required_text(raw.get("type"), f"objects[{index}].type")
        if object_id in by_id:
            raise RoomContractContractError(f"Duplicate V2 object id {object_id!r}.")
        by_id[object_id] = dict(raw)
        if object_type == "Assertion":
            raise RoomContractContractError("Abstract Assertion cannot be instantiated.")

    source_entities: Dict[str, str] = {}
    source_agents: Dict[str, str] = {}
    for item in by_id.values():
        object_type = str(item.get("type") or "")
        if object_type not in {"Entity", "Agent"}:
            continue
        source_id = _required_text(
            item.get("sourceId"),
            f"{object_type} {item.get('id')!r}.sourceId",
        )
        if len(source_id) > SPATIAL_ID_MAX_LENGTH:
            raise RoomContractContractError(
                f"{object_type} {item.get('id')!r}.sourceId exceeds "
                f"{SPATIAL_ID_MAX_LENGTH} characters."
            )
        previous = source_entities.get(source_id)
        if previous is not None:
            raise RoomContractContractError(
                f"Duplicate V2 sourceId {source_id!r} on {previous!r} and "
                f"{item.get('id')!r}."
            )
        source_entities[source_id] = str(item.get("id"))
        if object_type == "Agent":
            source_agent_id = _required_text(
                item.get("sourceAgentId"),
                f"Agent {item.get('id')!r}.sourceAgentId",
            )
            if len(source_agent_id) > SPATIAL_ID_MAX_LENGTH:
                raise RoomContractContractError(
                    f"Agent {item.get('id')!r}.sourceAgentId exceeds "
                    f"{SPATIAL_ID_MAX_LENGTH} characters."
                )
            previous_agent = source_agents.get(source_agent_id)
            if previous_agent is not None:
                raise RoomContractContractError(
                    f"Duplicate V2 sourceAgentId {source_agent_id!r} on "
                    f"{previous_agent!r} and {item.get('id')!r}."
                )
            source_agents[source_agent_id] = str(item.get("id"))

    roots = [item for item in by_id.values() if item.get("type") == "DynamicFunctionalModel"]
    if len(roots) != 1:
        raise RoomContractContractError("Native V2 instance requires exactly one DynamicFunctionalModel root.")
    root = roots[0]
    if root.get("id") != instance.get("id"):
        raise RoomContractContractError(
            "DynamicFunctionalModel root id must equal the native V2 instance id."
        )
    _require_exact_typed_refs(root, "requirementsModel", by_id, "RequirementsModel", 1)
    _require_exact_typed_refs(root, "verificationValidation", by_id, "VerificationValidation", 1)
    _require_refs(root, "scenario", by_id, minimum=1, expected_type="Scenario")

    assertions = {
        "StateAssertion",
        "EventAssertion",
        "OutputAssertion",
        "GroundingAssertion",
        "RelationAssertion",
    }
    for item in by_id.values():
        object_type = str(item.get("type"))
        if object_type in assertions:
            _require_exact_refs(item, "subject", by_id, 1)
            _require_exact_typed_refs(item, "expression", by_id, "EAExpression", 1)
        elif object_type == "Effect":
            refs = _require_refs(item, "specifiedBy", by_id, minimum=1)
            if any(str(by_id[ref].get("type")) not in assertions for ref in refs):
                raise RoomContractContractError(f"Effect {item['id']!r} specifiedBy must reference Assertions.")
        elif object_type == "Capability":
            _require_refs(item, "effect", by_id, minimum=1, expected_type="Effect")
        elif object_type == "RuntimeBinding":
            _require_exact_typed_refs(item, "capability", by_id, "Capability", 1)
            _require_refs(item, "runtimeAction", by_id, minimum=1, expected_type="RuntimeAction")
        elif object_type == "RuntimeAction":
            _require_exact_typed_refs(item, "locator", by_id, "RuntimeActionLocator", 1)
            _require_exact_typed_refs(item, "inputSchema", by_id, "SchemaReference", 1)
            if "outputSchema" in item:
                _require_exact_typed_refs(item, "outputSchema", by_id, "SchemaReference", 1)
            _require_refs(item, "runtimeParameter", by_id, minimum=0, expected_type="RuntimeParameter")
        elif object_type == "RuntimeActionLocator":
            if item.get("kind") not in {"endpoint", "tool", "topic"} or not _optional_text(item.get("value")):
                raise RoomContractContractError(f"RuntimeActionLocator {item['id']!r} is invalid.")
        elif object_type == "CapabilityUse":
            capability_ids = _refs(item.get("typeRef") or item.get("capability"))
            if len(capability_ids) != 1 or capability_ids[0] not in by_id or by_id[capability_ids[0]].get("type") != "Capability":
                raise RoomContractContractError(f"CapabilityUse {item['id']!r} requires exactly one Capability type.")
            provider_ids = _require_refs(item, "provider", by_id, minimum=1, maximum=1)
            provider = by_id[provider_ids[0]]
            if capability_ids[0] not in _refs(provider.get("providedCapability")):
                raise RoomContractContractError(f"CapabilityUse {item['id']!r} provider does not provide its Capability.")
        elif object_type == "RuntimeValidationTarget":
            if not _optional_text(item.get("platform")):
                raise RoomContractContractError(f"RuntimeValidationTarget {item['id']!r} requires platform.")
            bindings = _require_refs(item, "runtimeBinding", by_id, minimum=0, expected_type="RuntimeBinding")
            if not set(bindings).issubset(set(_refs(item.get("element")))):
                raise RoomContractContractError(
                    f"RuntimeValidationTarget {item['id']!r} runtimeBinding must be a subset of element."
                )
            _require_refs(item, "element", by_id, minimum=1)
        elif object_type == "Entity":
            object_groups = _require_refs(
                item,
                "objectGroup",
                by_id,
                minimum=0,
                maximum=1,
                expected_type="Entity",
            )
            entity_role = str(item.get("entityRole") or "").strip()
            entity_kind = str(item.get("kind") or "").strip()
            if object_groups:
                if entity_role != "sceneObject" or entity_kind != "asset":
                    raise RoomContractContractError(
                        f"Entity {item['id']!r}.objectGroup is only valid for "
                        "asset/sceneObject entities."
                    )
                target = by_id[object_groups[0]]
                if (
                    str(target.get("entityRole") or "").strip() != "objectGroup"
                    or str(target.get("kind") or "").strip() != "asset"
                ):
                    raise RoomContractContractError(
                        f"Entity {item['id']!r}.objectGroup must reference an "
                        "asset/objectGroup Entity."
                    )
            if entity_role == "objectGroup":
                if entity_kind != "asset":
                    raise RoomContractContractError(
                        f"Object-group Entity {item['id']!r} must have kind 'asset'."
                    )
                if object_groups:
                    raise RoomContractContractError(
                        f"Object-group Entity {item['id']!r} cannot itself reference "
                        "objectGroup."
                    )
            if entity_role == "sceneObject" and entity_kind != "asset":
                raise RoomContractContractError(
                    f"Scene-object Entity {item['id']!r} must have kind 'asset'."
                )
        elif object_type == "Agent":
            _require_refs(item, "handoffTarget", by_id, minimum=0, expected_type="Agent")
            responsible_zones = _require_refs(
                item,
                "responsibleZone",
                by_id,
                minimum=0,
                expected_type="Entity",
            )
            grounded_assets = _require_refs(
                item,
                "groundedAsset",
                by_id,
                minimum=0,
                expected_type="Entity",
            )
            grounded_groups = _require_refs(
                item,
                "groundedObjectGroup",
                by_id,
                minimum=0,
                expected_type="Entity",
            )
            if any(str(by_id[ref].get("kind") or "") != "zone" for ref in responsible_zones):
                raise RoomContractContractError(
                    f"Agent {item['id']!r} responsibleZone must reference zone Entities."
                )
            if any(str(by_id[ref].get("kind") or "") != "asset" for ref in grounded_assets):
                raise RoomContractContractError(
                    f"Agent {item['id']!r} groundedAsset must reference asset Entities."
                )
            if any(
                str(by_id[ref].get("entityRole") or "") != "objectGroup"
                for ref in grounded_groups
            ):
                raise RoomContractContractError(
                    f"Agent {item['id']!r} groundedObjectGroup must reference object-group Entities."
                )
        elif object_type == "ValidationCase":
            _require_refs(item, "vvSubject", by_id, minimum=1)
            _require_refs(
                item,
                "vvTarget",
                by_id,
                minimum=1,
                expected_type="RuntimeValidationTarget",
            )
            _require_refs(
                item,
                "vvProcedure",
                by_id,
                minimum=0,
                expected_type="RuntimeValidationProcedure",
            )

    use_cases = [
        item for item in by_id.values() if item.get("type") == "UseCase"
    ]
    scenarios = [
        item for item in by_id.values() if item.get("type") == "Scenario"
    ]
    scenario_specifications = [
        item
        for item in by_id.values()
        if item.get("type") == "UseCaseScenarioSpecification"
    ]
    scenarios_by_use_case: Dict[str, List[Mapping[str, Any]]] = {
        str(item.get("id")): [] for item in use_cases
    }
    scenario_owner: Dict[str, str] = {}
    for specification in scenario_specifications:
        use_case_ids = _require_refs(
            specification,
            "useCase",
            by_id,
            minimum=1,
            maximum=1,
            expected_type="UseCase",
        )
        scenario_ids = _require_refs(
            specification,
            "scenario",
            by_id,
            minimum=1,
            maximum=1,
            expected_type="Scenario",
        )
        use_case_id = use_case_ids[0]
        scenario_id = scenario_ids[0]
        previous_owner = scenario_owner.setdefault(scenario_id, use_case_id)
        if previous_owner != use_case_id:
            raise RoomContractContractError(
                f"Scenario {scenario_id!r} belongs to more than one UseCase."
            )
        if by_id[scenario_id] not in scenarios_by_use_case[use_case_id]:
            scenarios_by_use_case[use_case_id].append(by_id[scenario_id])

    if (
        not scenario_specifications
        and len(use_cases) == 1
        and len(scenarios) == 1
    ):
        # Compatibility with the first native-V2 fixtures, which exposed one
        # global main Scenario before UseCase ownership became executable.
        use_case_id = str(use_cases[0].get("id"))
        scenario_id = str(scenarios[0].get("id"))
        scenarios_by_use_case[use_case_id] = [scenarios[0]]
        scenario_owner[scenario_id] = use_case_id
    else:
        unowned = [
            str(item.get("id"))
            for item in scenarios
            if str(item.get("id")) not in scenario_owner
        ]
        if unowned:
            raise RoomContractContractError(
                "Native V2 Scenarios require one UseCase owner: "
                + ", ".join(unowned)
                + "."
            )

    for use_case in use_cases:
        use_case_id = str(use_case.get("id"))
        main_scenarios = [
            scenario
            for scenario in scenarios_by_use_case.get(use_case_id, [])
            if scenario.get("kind") == "main"
        ]
        if len(main_scenarios) != 1:
            raise RoomContractContractError(
                f"Native V2 UseCase {use_case_id!r} requires exactly one main "
                f"Scenario; found {len(main_scenarios)}."
            )

    step_owner: Dict[str, str] = {}
    for scenario in scenarios:
        scenario_id = str(scenario.get("id"))
        for step_id in _refs(scenario.get("step")):
            previous_owner = step_owner.setdefault(step_id, scenario_id)
            if previous_owner != scenario_id:
                raise RoomContractContractError(
                    f"ScenarioStep {step_id!r} belongs to more than one Scenario."
                )
    unowned_steps = [
        str(item.get("id"))
        for item in by_id.values()
        if item.get("type") == "ScenarioStep"
        and str(item.get("id")) not in step_owner
    ]
    if unowned_steps:
        raise RoomContractContractError(
            "Native V2 ScenarioSteps require one Scenario owner: "
            + ", ".join(unowned_steps)
            + "."
        )

    for step in [item for item in by_id.values() if item.get("type") == "ScenarioStep"]:
        for use_id in _refs(step.get("capabilityUse")):
            use = by_id.get(use_id)
            if not use or use.get("type") != "CapabilityUse":
                raise RoomContractContractError(f"ScenarioStep {step['id']!r} references invalid CapabilityUse.")
            provider_ids = _refs(use.get("provider"))
            if not provider_ids or provider_ids[0] not in _refs(step.get("performedBy")):
                raise RoomContractContractError(
                    f"ScenarioStep {step['id']!r} must include its CapabilityUse provider in performedBy."
                )
    _validate_runtime_wire_contracts(by_id)
    return by_id


def _validate_v2_trace(
    trace: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    model_sha256: str,
    instance: Mapping[str, Any],
) -> None:
    if trace.get("schema") != V2_TRACE_SCHEMA or str(trace.get("schema_version")) != V2_TRACE_VERSION:
        raise RoomContractContractError("V2 trace map has an unsupported schema or schema_version.")
    if trace.get("model_version") != V2_MODEL_VERSION:
        raise RoomContractContractError("V2 trace map model_version does not match the native instance.")
    if str(trace.get("model_sha256") or "").upper() != model_sha256:
        raise RoomContractContractError("V2 trace map model_sha256 does not match the native instance.")
    if str(trace.get("case_id") or "") != str(instance.get("caseId") or ""):
        raise RoomContractContractError("V2 trace map case_id does not match the native instance.")
    instance_profile = str(instance.get("fixture_profile") or instance.get("profile") or "")
    if str(trace.get("profile") or "") != instance_profile:
        raise RoomContractContractError("V2 trace map profile does not match the native instance.")
    use_cases = [
        item for item in by_id.values() if item.get("type") == "UseCase"
    ]
    scenarios = [
        item for item in by_id.values() if item.get("type") == "Scenario"
    ]
    main_scenarios = [
        item for item in scenarios if item.get("kind") == "main"
    ]
    scenario_for_step: Dict[str, str] = {}
    for scenario in scenarios:
        scenario_id = str(scenario.get("id"))
        for step_id in _refs(scenario.get("step")):
            previous = scenario_for_step.setdefault(step_id, scenario_id)
            if previous != scenario_id:
                raise RoomContractContractError(
                    f"ScenarioStep {step_id!r} has ambiguous Scenario ownership."
                )
    use_case_for_scenario: Dict[str, str] = {}
    for specification in by_id.values():
        if specification.get("type") != "UseCaseScenarioSpecification":
            continue
        use_case_ids = _refs(specification.get("useCase"))
        scenario_ids = _refs(specification.get("scenario"))
        if len(use_case_ids) != 1 or len(scenario_ids) != 1:
            raise RoomContractContractError(
                "UseCaseScenarioSpecification must identify exactly one "
                "UseCase and Scenario."
            )
        previous = use_case_for_scenario.setdefault(
            scenario_ids[0],
            use_case_ids[0],
        )
        if previous != use_case_ids[0]:
            raise RoomContractContractError(
                f"Scenario {scenario_ids[0]!r} has ambiguous UseCase ownership."
            )
    if (
        not use_case_for_scenario
        and len(use_cases) == 1
        and len(scenarios) == 1
    ):
        use_case_for_scenario[str(scenarios[0].get("id"))] = str(
            use_cases[0].get("id")
        )

    expected_use_case_ids = [str(item.get("id")) for item in use_cases]
    expected_main_scenario_ids = [
        str(item.get("id")) for item in main_scenarios
    ]
    if "use_case_ids" in trace and _refs(trace.get("use_case_ids")) != expected_use_case_ids:
        raise RoomContractContractError(
            "V2 trace map use_case_ids do not exactly match the model."
        )
    if (
        "main_scenario_ids" in trace
        and _refs(trace.get("main_scenario_ids")) != expected_main_scenario_ids
    ):
        raise RoomContractContractError(
            "V2 trace map main_scenario_ids do not exactly match the model."
        )
    if len(main_scenarios) > 1 and (
        "use_case_ids" not in trace or "main_scenario_ids" not in trace
    ):
        raise RoomContractContractError(
            "A multi-UseCase V2 trace requires use_case_ids and "
            "main_scenario_ids."
        )
    actions = trace.get("runtime_actions")
    if not isinstance(actions, list) or not actions:
        raise RoomContractContractError("V2 trace map requires runtime_actions.")
    seen_action_kinds: Dict[str, int] = {}
    actual_chains: List[
        tuple[str, str, str, str, str, str, str, str]
    ] = []
    for index, raw in enumerate(actions):
        if not isinstance(raw, Mapping):
            raise RoomContractContractError(f"runtime_actions[{index}] must be an object.")
        required = (
            "scenario_step_id",
            "capability_use_id",
            "capability_id",
            "provider_entity_id",
            "runtime_binding_id",
            "runtime_action_id",
        )
        ids = {name: _required_text(raw.get(name), f"runtime_actions[{index}].{name}") for name in required}
        if any(value not in by_id for value in ids.values()):
            raise RoomContractContractError(f"runtime_actions[{index}] contains an unresolved model reference.")
        step = by_id[ids["scenario_step_id"]]
        use = by_id[ids["capability_use_id"]]
        capability = by_id[ids["capability_id"]]
        provider = by_id[ids["provider_entity_id"]]
        binding = by_id[ids["runtime_binding_id"]]
        action = by_id[ids["runtime_action_id"]]
        expected_scenario_id = scenario_for_step.get(
            ids["scenario_step_id"],
            "",
        )
        expected_use_case_id = use_case_for_scenario.get(
            expected_scenario_id,
            "",
        )
        if not expected_scenario_id or not expected_use_case_id:
            raise RoomContractContractError(
                f"runtime_actions[{index}] ScenarioStep has no unique "
                "Scenario/UseCase owner."
            )
        traced_scenario_id = _optional_text(raw.get("scenario_id"))
        traced_use_case_id = _optional_text(raw.get("use_case_id"))
        if len(scenarios) > 1 and (
            traced_scenario_id is None or traced_use_case_id is None
        ):
            raise RoomContractContractError(
                f"runtime_actions[{index}] in a multi-Scenario model requires "
                "scenario_id and use_case_id."
            )
        if traced_scenario_id not in {None, expected_scenario_id}:
            raise RoomContractContractError(
                f"runtime_actions[{index}] scenario_id does not own its "
                "ScenarioStep."
            )
        if traced_use_case_id not in {None, expected_use_case_id}:
            raise RoomContractContractError(
                f"runtime_actions[{index}] use_case_id does not own its Scenario."
            )
        if ids["capability_use_id"] not in _refs(step.get("capabilityUse")):
            raise RoomContractContractError(f"runtime_actions[{index}] bypasses ScenarioStep.capabilityUse.")
        if ids["capability_id"] not in _refs(use.get("typeRef") or use.get("capability")):
            raise RoomContractContractError(f"runtime_actions[{index}] CapabilityUse type mismatch.")
        if ids["provider_entity_id"] not in _refs(use.get("provider")) or ids["provider_entity_id"] not in _refs(step.get("performedBy")):
            raise RoomContractContractError(f"runtime_actions[{index}] provider chain mismatch.")
        if ids["capability_id"] not in _refs(provider.get("providedCapability")):
            raise RoomContractContractError(f"runtime_actions[{index}] provider does not provide the Capability.")
        if ids["capability_id"] not in _refs(binding.get("capability")):
            raise RoomContractContractError(f"runtime_actions[{index}] RuntimeBinding capability mismatch.")
        if ids["runtime_action_id"] not in _refs(binding.get("runtimeAction")):
            raise RoomContractContractError(f"runtime_actions[{index}] RuntimeAction is not owned by the binding.")
        if step.get("type") != "ScenarioStep" or use.get("type") != "CapabilityUse" or capability.get("type") != "Capability" or binding.get("type") != "RuntimeBinding" or action.get("type") != "RuntimeAction":
            raise RoomContractContractError(f"runtime_actions[{index}] contains a type-invalid chain.")
        actual_chains.append(
            (
                expected_use_case_id,
                expected_scenario_id,
                *(ids[name] for name in required),
            )
        )

        expected_targets = _refs(use.get("target"))
        expected_assertions: List[str] = []
        for effect_id in _refs(capability.get("effect")):
            expected_assertions.extend(_refs(by_id[effect_id].get("specifiedBy")))
        expected_assertions = list(dict.fromkeys(expected_assertions))
        expected_cases = [
            str(item.get("id"))
            for item in by_id.values()
            if item.get("type") == "ValidationCase" and ids["runtime_binding_id"] in _refs(item.get("vvSubject"))
        ]
        expected_runtime_targets: List[str] = []
        for validation_case in by_id.values():
            if validation_case.get("type") != "ValidationCase":
                continue
            for target_id in _refs(validation_case.get("vvTarget")):
                target = by_id[target_id]
                if ids["runtime_binding_id"] in _refs(target.get("runtimeBinding")):
                    expected_runtime_targets.append(target_id)
        expected_runtime_targets = list(dict.fromkeys(expected_runtime_targets))
        _require_exact_trace_list(raw, "target_ids", expected_targets, by_id, index)
        _require_exact_trace_list(raw, "assertion_ids", expected_assertions, by_id, index)
        _require_exact_trace_list(raw, "validation_case_ids", expected_cases, by_id, index)
        _require_exact_trace_list(
            raw,
            "runtime_validation_target_ids",
            expected_runtime_targets,
            by_id,
            index,
        )

        locator_ids = _refs(action.get("locator"))
        modeled_locator = by_id[locator_ids[0]]
        expected_locator = {
            "kind": modeled_locator.get("kind"),
            "value": modeled_locator.get("value"),
        }
        locator = raw.get("locator")
        if not isinstance(locator, Mapping) or dict(locator) != expected_locator:
            raise RoomContractContractError(
                f"runtime_actions[{index}].locator does not exactly match RuntimeAction.locator."
            )
        action_kind = _runtime_action_kind(action, by_id)
        if _optional_text(raw.get("action_kind")) != action_kind:
            raise RoomContractContractError(
                f"runtime_actions[{index}].action_kind does not match the modeled applicationActionKind."
            )
        seen_action_kinds[action_kind] = seen_action_kinds.get(action_kind, 0) + 1

    expected_chains: List[
        tuple[str, str, str, str, str, str, str, str]
    ] = []
    steps_for_use: Dict[str, List[Mapping[str, Any]]] = {}
    for step in by_id.values():
        if step.get("type") != "ScenarioStep":
            continue
        for use_id in _refs(step.get("capabilityUse")):
            steps_for_use.setdefault(use_id, []).append(step)
    uses_for_capability: Dict[str, List[Mapping[str, Any]]] = {}
    for use in by_id.values():
        if use.get("type") != "CapabilityUse":
            continue
        capability_ids = _refs(use.get("typeRef") or use.get("capability"))
        if len(capability_ids) == 1:
            uses_for_capability.setdefault(capability_ids[0], []).append(use)
    for binding in by_id.values():
        if binding.get("type") != "RuntimeBinding":
            continue
        capability_ids = _refs(binding.get("capability"))
        if len(capability_ids) != 1:
            continue
        capability_id = capability_ids[0]
        for action_id in _refs(binding.get("runtimeAction")):
            for use in uses_for_capability.get(capability_id, []):
                use_id = str(use.get("id"))
                steps = steps_for_use.get(use_id, [])
                if len(steps) != 1:
                    raise RoomContractContractError(
                        f"CapabilityUse {use_id!r} must belong to exactly one ScenarioStep for runtime mapping."
                    )
                providers = _refs(use.get("provider"))
                if len(providers) != 1:
                    raise RoomContractContractError(
                        f"CapabilityUse {use_id!r} must have exactly one provider for runtime mapping."
                    )
                expected_chains.append(
                    (
                        use_case_for_scenario[
                            scenario_for_step[str(steps[0].get("id"))]
                        ],
                        scenario_for_step[str(steps[0].get("id"))],
                        str(steps[0].get("id")),
                        use_id,
                        capability_id,
                        providers[0],
                        str(binding.get("id")),
                        action_id,
                    )
                )
    if len(actual_chains) != len(set(actual_chains)):
        raise RoomContractContractError("V2 runtime trace contains duplicate runtime action chains.")
    if set(actual_chains) != set(expected_chains):
        raise RoomContractContractError(
            "V2 runtime trace is not a complete, exact projection of the model's runtime action chains."
        )

    if seen_action_kinds.get("setup") != 1:
        raise RoomContractContractError(
            "V2 runtime trace requires exactly one 'setup' action mapping; "
            f"found {seen_action_kinds.get('setup', 0)}."
        )
    for action_kind in ("chat", "handoff"):
        if seen_action_kinds.get(action_kind, 0) < 1:
            raise RoomContractContractError(
                f"V2 runtime trace requires at least one {action_kind!r} "
                f"action mapping; found {seen_action_kinds.get(action_kind, 0)}."
            )

    setup_chain = next(
        (
            raw
            for raw in actions
            if isinstance(raw, Mapping)
            and str(raw.get("action_kind") or "").lower() == "setup"
        ),
        None,
    )
    assert setup_chain is not None
    setup_step_id = str(setup_chain.get("scenario_step_id") or "")
    setup_scenario_id = scenario_for_step.get(setup_step_id, "")
    setup_use_case_id = use_case_for_scenario.get(setup_scenario_id, "")
    if trace.get("main_scenario_id") != setup_scenario_id:
        raise RoomContractContractError(
            "V2 trace map main_scenario_id must identify the Scenario that "
            "owns the unique setup chain."
        )
    if trace.get("use_case_id") != setup_use_case_id:
        raise RoomContractContractError(
            "V2 trace map use_case_id must identify the UseCase that owns the "
            "unique setup chain."
        )


def _build_v2_runtime_context(
    instance: Mapping[str, Any],
    trace: Mapping[str, Any],
    model_sha256: str,
) -> Dict[str, Any]:
    objects = [dict(item) for item in instance.get("objects", []) if isinstance(item, Mapping)]
    assertions = []
    assertion_types = {
        "StateAssertion",
        "EventAssertion",
        "OutputAssertion",
        "GroundingAssertion",
        "RelationAssertion",
    }
    by_id = {str(item.get("id")): item for item in objects}
    for item in objects:
        if item.get("type") not in assertion_types:
            continue
        expression_ids = _refs(item.get("expression"))
        expression = by_id.get(expression_ids[0], {}) if expression_ids else {}
        assertions.append(
            {
                "id": item.get("id"),
                "assertion_type": item.get("type"),
                "subject_id": (_refs(item.get("subject")) or [None])[0],
                "expression_text": item.get("expressionText")
                or expression.get("mixedStringContent")
                or expression.get("expression")
                or "",
                "severity": item.get("severity"),
            }
        )
    targets = [item for item in objects if item.get("type") == "RuntimeValidationTarget"]
    unity_target = next((item for item in targets if "unity" in str(item.get("platform") or "").lower()), None)
    if unity_target is None and targets:
        unity_target = targets[0]
    spatial_entities = []
    for item in objects:
        if item.get("type") != "Entity":
            continue
        spatial_entities.append(
            {
                "entity_id": item.get("id"),
                "kind": item.get("kind"),
                "entity_role": item.get("entityRole"),
                "name": item.get("name"),
                "source_id": item.get("sourceId"),
                "source_object_ids": _refs(item.get("sourceObjectId")),
                "source_group": item.get("sourceGroup"),
                "object_group_ids": _refs(item.get("objectGroup")),
            }
        )
    agents = []
    for item in objects:
        if item.get("type") != "Agent":
            continue
        handoff_target_ids = _refs(item.get("handoffTarget"))
        agents.append(
            {
                "roomcontract_agent_id": item.get("id"),
                "entity_id": item.get("id"),
                "source_agent_id": item.get("sourceAgentId"),
                "provided_capability_ids": _refs(item.get("providedCapability")),
                "plays_actor_ids": _refs(item.get("playsActor")),
                "responsible_zone_ids": _refs(item.get("responsibleZone")),
                "grounded_asset_ids": _refs(item.get("groundedAsset")),
                "grounded_object_group_ids": _refs(item.get("groundedObjectGroup")),
                "handoff_target_ids": handoff_target_ids,
                "handoff_target_source_agent_ids": [
                    by_id[target_id].get("sourceAgentId")
                    for target_id in handoff_target_ids
                    if target_id in by_id
                ],
            }
        )
    runtime_actions: List[Dict[str, Any]] = []
    for raw_action in trace.get("runtime_actions", []):
        if not isinstance(raw_action, Mapping):
            continue
        action = by_id.get(str(raw_action.get("runtime_action_id") or ""))
        if action is None:
            continue
        action_kind = str(raw_action.get("action_kind") or "").strip().lower()
        request_schema = _wire_schema_document(
            action,
            by_id,
            "inputSchema",
            required=True,
        )
        response_schema = _wire_schema_document(
            action,
            by_id,
            "outputSchema",
            required=action_kind in {"chat", "handoff"},
        )
        runtime_action = dict(raw_action)
        runtime_action["request_wire_schema"] = request_schema
        runtime_action["response_wire_schema"] = response_schema
        runtime_actions.append(runtime_action)
    return {
        "schema": RUNTIME_CONTEXT_SCHEMA,
        "case_id": trace.get("case_id"),
        "model_version": V2_MODEL_VERSION,
        "model_sha256": model_sha256,
        "profile": "executable",
        "trace_schema_version": V2_TRACE_VERSION,
        "main_scenario_id": trace.get("main_scenario_id"),
        "main_scenario_ids": list(
            trace.get("main_scenario_ids")
            or ([trace.get("main_scenario_id")] if trace.get("main_scenario_id") else [])
        ),
        "use_case_id": trace.get("use_case_id"),
        "use_case_ids": list(
            trace.get("use_case_ids")
            or ([trace.get("use_case_id")] if trace.get("use_case_id") else [])
        ),
        "runtime_validation_target_id": unity_target.get("id") if unity_target else None,
        "runtime_actions": runtime_actions,
        "assertions": assertions,
        "spatial_entities": spatial_entities,
        "agents": agents,
    }


def _resolve_contract_version(project_dir: Path, meta: Mapping[str, Any]) -> str:
    declared = [
        str(meta.get(field) or "").strip()
        for field in ("roomcontract_model_version", "metamodelVersion")
        if str(meta.get(field) or "").strip()
    ]
    normalized = [V05_MODEL_VERSION if value == "0.5" else value for value in declared]
    if len(set(normalized)) > 1:
        raise RoomContractContractError(
            f"Conflicting RoomContract version declarations in project.json: {normalized!r}."
        )
    declared_version = normalized[0] if normalized else ""

    active_trace_path = _resolve_project_file(
        project_dir,
        meta.get("roomcontract_trace_map_path"),
        "trace_map.json",
        required=False,
    )
    active_trace_schema = ""
    if active_trace_path.exists():
        active_trace_schema = str(_read_json(active_trace_path).get("schema") or "")

    native_model_path = _resolve_project_file(
        project_dir,
        meta.get("roomcontract_model_path"),
        "roomcontract.v2.instance.json",
        required=False,
    )
    native_schema = ""
    native_version = ""
    if native_model_path.exists():
        native_model = _read_json(native_model_path)
        native_schema = str(native_model.get("schema") or "")
        native_version = str(native_model.get("metamodelVersion") or "")

    v2_hints = {
        "active trace schema": active_trace_schema == V2_TRACE_SCHEMA,
        "native model schema": native_schema == V2_INSTANCE_SCHEMA,
        "native model version": native_version == V2_MODEL_VERSION,
        "project model schema": str(meta.get("roomcontract_model_schema") or "") == V2_INSTANCE_SCHEMA,
        "project trace version": str(meta.get("roomcontract_trace_schema_version") or "") == V2_TRACE_VERSION,
    }
    has_v2_hint = any(v2_hints.values())
    if declared_version in {V05_MODEL_VERSION, ""} and has_v2_hint:
        hints = ", ".join(name for name, present in v2_hints.items() if present)
        raise RoomContractContractError(
            "Mixed or downgraded RoomContract contract: project.json does not explicitly "
            f"declare {V2_MODEL_VERSION!r}, but V2 evidence is present ({hints})."
        )
    if declared_version == V2_MODEL_VERSION:
        if active_trace_schema and active_trace_schema != V2_TRACE_SCHEMA:
            raise RoomContractContractError(
                f"V2 project points to incompatible active trace schema {active_trace_schema!r}."
            )
        return V2_MODEL_VERSION
    if declared_version in {V05_MODEL_VERSION, ""}:
        return V05_MODEL_VERSION
    return declared_version


def _validate_v2_project_metadata(
    project_dir: Path,
    meta: Mapping[str, Any],
    instance: Mapping[str, Any],
) -> None:
    expected = {
        "metamodelVersion": V2_MODEL_VERSION,
        "roomcontract_model_version": V2_MODEL_VERSION,
        "roomcontract_model_schema": V2_INSTANCE_SCHEMA,
        "roomcontract_profile": "executable",
        "roomcontract_trace_schema_version": V2_TRACE_VERSION,
    }
    for field, value in expected.items():
        if meta.get(field) != value:
            raise RoomContractContractError(
                f"V2 project metadata {field} must be {value!r}, got {meta.get(field)!r}."
            )
    case_id = str(instance.get("caseId") or "")
    if str(meta.get("id") or "") != case_id or project_dir.name != case_id:
        raise RoomContractContractError(
            "V2 project id, project directory, and native instance caseId must match exactly."
        )


def _require_exact_trace_list(
    action: Mapping[str, Any],
    field: str,
    expected: List[str],
    by_id: Mapping[str, Mapping[str, Any]],
    action_index: int,
) -> None:
    raw = action.get(field)
    if not isinstance(raw, list) or any(not isinstance(value, str) or not value for value in raw):
        raise RoomContractContractError(
            f"runtime_actions[{action_index}].{field} must be an explicit string array."
        )
    actual = list(raw)
    for ref in actual:
        if ref not in by_id:
            raise RoomContractContractError(
                f"runtime_actions[{action_index}].{field} contains unresolved {ref!r}."
            )
    if actual != expected:
        raise RoomContractContractError(
            f"runtime_actions[{action_index}].{field} does not exactly match its modeled derivation."
        )


def _runtime_action_kind(
    action: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    markers: List[str] = []
    for schema_id in _refs(action.get("inputSchema")):
        schema = by_id.get(schema_id)
        if not schema or schema.get("type") != "SchemaReference":
            continue
        raw = schema.get("text")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        marker = str(payload.get("applicationActionKind") or "").strip().lower()
        if marker:
            markers.append(marker)
    allowed = {"setup", "chat", "handoff", "runtime"}
    if len(markers) != 1 or markers[0] not in allowed:
        raise RoomContractContractError(
            f"RuntimeAction {action.get('id')!r} requires exactly one modeled "
            f"applicationActionKind in {sorted(allowed)!r}; found {markers!r}."
        )
    return markers[0]


def _wire_schema_document(
    action: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    field_name: str,
    *,
    required: bool,
) -> Optional[Dict[str, Any]]:
    schema_ids = _refs(action.get(field_name))
    if not schema_ids:
        if required:
            raise RoomContractContractError(
                f"RuntimeAction {action.get('id')!r} requires a modeled "
                f"{field_name} SchemaReference."
            )
        return None
    if len(schema_ids) != 1:
        raise RoomContractContractError(
            f"RuntimeAction {action.get('id')!r}.{field_name} must contain "
            "exactly one SchemaReference."
        )
    schema_reference = by_id.get(schema_ids[0])
    if not schema_reference or schema_reference.get("type") != "SchemaReference":
        raise RoomContractContractError(
            f"RuntimeAction {action.get('id')!r}.{field_name} is not a "
            "SchemaReference."
        )
    raw = schema_reference.get("text")
    if not isinstance(raw, str) or not raw.strip():
        raise RoomContractContractError(
            f"SchemaReference {schema_ids[0]!r} requires an executable JSON "
            "Schema document in text."
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RoomContractContractError(
            f"SchemaReference {schema_ids[0]!r}.text is not valid JSON: {exc}."
        ) from exc
    if not isinstance(payload, dict):
        raise RoomContractContractError(
            f"SchemaReference {schema_ids[0]!r}.text must encode a JSON object."
        )
    return payload


def _wire_condition(
    schema: Mapping[str, Any],
    interaction_mode: str,
) -> Optional[Mapping[str, Any]]:
    for condition in schema.get("allOf") or []:
        if not isinstance(condition, Mapping):
            continue
        predicate = condition.get("if")
        if not isinstance(predicate, Mapping):
            continue
        properties = predicate.get("properties")
        if not isinstance(properties, Mapping):
            continue
        mode_schema = properties.get("interaction_mode")
        if (
            isinstance(mode_schema, Mapping)
            and mode_schema.get("const") == interaction_mode
        ):
            then = condition.get("then")
            return then if isinstance(then, Mapping) else None
    return None


def _validate_chat_request_wire_schema(
    action_id: str,
    schema: Mapping[str, Any],
) -> None:
    required = set(schema.get("required") or [])
    expected_required = {
        "session_id",
        "active_agent_id",
        "user_text",
        "interaction_mode",
    }
    if not expected_required.issubset(required):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} request schema must require "
            f"{sorted(expected_required)!r}."
        )
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} request schema requires properties."
        )
    interaction_mode = properties.get("interaction_mode")
    if (
        not isinstance(interaction_mode, Mapping)
        or interaction_mode.get("type") != "string"
        or list(interaction_mode.get("enum") or []) != list(INTERACTION_MODES)
    ):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} must model interaction_mode as "
            f"{list(INTERACTION_MODES)!r}."
        )
    spatial = properties.get("spatial_context")
    if not isinstance(spatial, Mapping) or spatial.get("type") != "object":
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} must model spatial_context as an object."
        )
    spatial_required = set(spatial.get("required") or [])
    if not {
        "model_sha256",
        "state",
        "hit_position",
        "distance_m",
        "selection_modality",
    }.issubset(spatial_required):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} spatial_context omits required "
            "grounding observations."
        )
    spatial_properties = spatial.get("properties")
    if not isinstance(spatial_properties, Mapping):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} spatial_context requires properties."
        )
    candidates = spatial_properties.get("candidate_entity_ids")
    if (
        not isinstance(candidates, Mapping)
        or candidates.get("maxItems") != SPATIAL_CANDIDATE_LIMIT
    ):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} must enforce the modeled spatial "
            f"candidate limit {SPATIAL_CANDIDATE_LIMIT}."
        )
    reason = spatial_properties.get("ambiguity_reason")
    if (
        not isinstance(reason, Mapping)
        or reason.get("maxLength") != SPATIAL_REASON_MAX_LENGTH
    ):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} must enforce the modeled ambiguity "
            f"reason limit {SPATIAL_REASON_MAX_LENGTH}."
        )
    deictic = _wire_condition(schema, "deictic")
    if (
        not isinstance(deictic, Mapping)
        or "spatial_context" not in set(deictic.get("required") or [])
    ):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} must require spatial_context when "
            "interaction_mode is deictic."
        )
    non_deictic = _wire_condition(schema, "non_deictic")
    if (
        not isinstance(non_deictic, Mapping)
        or dict(non_deictic.get("not") or {})
        != {"required": ["spatial_context"]}
    ):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} must forbid spatial_context when "
            "interaction_mode is non_deictic."
        )


def _validate_chat_response_wire_schema(
    action_id: str,
    schema: Mapping[str, Any],
) -> None:
    grounding_fields = {
        "grounded_entity_ids",
        "grounding_evidence",
        "routing_reason",
        "grounding",
        "routing",
    }
    required = set(schema.get("required") or [])
    expected_required = {
        "session_id",
        "active_agent_id",
        "memory_mode",
        "handoff",
        "events",
        "interaction_mode",
        "model_binding",
    }
    if not expected_required.issubset(required):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} response schema must require "
            f"{sorted(expected_required)!r}."
        )
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} response schema requires properties."
        )
    mode_schema = properties.get("interaction_mode")
    if (
        not isinstance(mode_schema, Mapping)
        or list(mode_schema.get("enum") or []) != list(INTERACTION_MODES)
    ):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} response schema has no exact "
            "interaction_mode contract."
        )
    if not grounding_fields.issubset(set(properties)):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} response schema does not model all "
            "grounding and routing evidence fields."
        )
    deictic = _wire_condition(schema, "deictic")
    if not isinstance(deictic, Mapping) or not grounding_fields.issubset(
        set(deictic.get("required") or [])
    ):
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} response schema must require "
            "grounding and routing evidence for deictic interaction."
        )
    non_deictic = _wire_condition(schema, "non_deictic")
    forbidden = (
        (non_deictic or {}).get("not", {}).get("anyOf", [])
        if isinstance(non_deictic, Mapping)
        else []
    )
    forbidden_fields = {
        str(next(iter(item.get("required") or []), ""))
        for item in forbidden
        if isinstance(item, Mapping)
    }
    if forbidden_fields != grounding_fields:
        raise RoomContractContractError(
            f"RuntimeAction {action_id!r} response schema must forbid every "
            "grounding field for non_deictic interaction."
        )


def _validate_runtime_wire_contracts(
    by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    bindings_by_action: Dict[str, List[Mapping[str, Any]]] = {}
    uses_by_capability: Dict[str, List[str]] = {}
    for item in by_id.values():
        if item.get("type") == "RuntimeBinding":
            for action_id in _refs(item.get("runtimeAction")):
                bindings_by_action.setdefault(action_id, []).append(item)
        elif item.get("type") == "CapabilityUse":
            for capability_id in _refs(item.get("typeRef") or item.get("capability")):
                uses_by_capability.setdefault(capability_id, []).append(
                    str(item.get("id"))
                )

    for action in by_id.values():
        if action.get("type") != "RuntimeAction":
            continue
        action_id = str(action.get("id"))
        action_kind = _runtime_action_kind(action, by_id)
        input_schema = _wire_schema_document(
            action,
            by_id,
            "inputSchema",
            required=True,
        )
        assert input_schema is not None
        output_schema = _wire_schema_document(
            action,
            by_id,
            "outputSchema",
            required=action_kind in {"chat", "handoff"},
        )
        schemas = [input_schema]
        if output_schema is not None:
            schemas.append(output_schema)
        bindings = bindings_by_action.get(action_id, [])
        if len(bindings) != 1:
            raise RoomContractContractError(
                f"RuntimeAction {action_id!r} must belong to exactly one "
                "RuntimeBinding for executable wire binding."
            )
        binding = bindings[0]
        binding_id = str(binding.get("id"))
        capability_ids = _refs(binding.get("capability"))
        if len(capability_ids) != 1:
            raise RoomContractContractError(
                f"RuntimeBinding {binding_id!r} must bind exactly one Capability."
            )
        capability_use_ids = [
            use_id
            for capability_id in capability_ids
            for use_id in uses_by_capability.get(capability_id, [])
        ]
        expected_binding = {
            "runtimeBindingId": binding_id,
            "runtimeActionId": action_id,
            "capabilityIds": capability_ids,
            "capabilityUseIds": capability_use_ids,
        }
        for schema in schemas:
            if schema.get("$schema") != WIRE_SCHEMA_DIALECT:
                raise RoomContractContractError(
                    f"RuntimeAction {action_id!r} wire schema must use "
                    f"{WIRE_SCHEMA_DIALECT!r}."
                )
            if schema.get("type") != "object":
                raise RoomContractContractError(
                    f"RuntimeAction {action_id!r} wire schema root must be object."
                )
            if schema.get("wireContractVersion") != WIRE_CONTRACT_VERSION:
                raise RoomContractContractError(
                    f"RuntimeAction {action_id!r} wire contract version mismatch."
                )
            if schema.get("applicationActionKind") != action_kind:
                raise RoomContractContractError(
                    f"RuntimeAction {action_id!r} wire action kind mismatch."
                )
            if schema.get("modelBinding") != expected_binding:
                raise RoomContractContractError(
                    f"RuntimeAction {action_id!r} wire modelBinding does not "
                    "exactly match RuntimeBinding/CapabilityUse relations."
                )
        if action_kind in {"chat", "handoff"}:
            _validate_chat_request_wire_schema(action_id, input_schema)
            assert output_schema is not None
            _validate_chat_response_wire_schema(action_id, output_schema)


def _placement_projection_sha256(agents: Any) -> str:
    if not isinstance(agents, list):
        raise RoomContractContractError("agents.json agents must be an array.")
    projection: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, agent in enumerate(agents):
        if not isinstance(agent, Mapping):
            raise RoomContractContractError(f"agents[{index}] must be an object.")
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id or agent_id in seen_ids:
            raise RoomContractContractError(
                "Placement projection requires unique, non-empty agent ids."
            )
        seen_ids.add(agent_id)
        vectors: Dict[str, Dict[str, Any]] = {}
        for field_name in ("position", "forward"):
            vector = agent.get(field_name)
            if not isinstance(vector, Mapping):
                raise RoomContractContractError(
                    f"agents[{index}].{field_name} must be an object."
                )
            components: Dict[str, Any] = {}
            for axis in ("x", "y", "z"):
                value = vector.get(axis)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise RoomContractContractError(
                        f"agents[{index}].{field_name}.{axis} must be a finite JSON number."
                    )
                components[axis] = value
            vectors[field_name] = components
        projection.append(
            {
                "id": agent_id,
                "position": vectors["position"],
                "forward": vectors["forward"],
            }
        )
    projection.sort(key=lambda item: item["id"])
    canonical = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_optional_placement_deployment(
    project_dir: Path,
    meta: Mapping[str, Any],
    trace: Mapping[str, Any],
) -> None:
    agents_path = project_dir / "agents.json"
    agents_payload = _read_json(agents_path) if agents_path.exists() else {}
    declarations = {
        "project.json": meta,
        "active trace map": trace,
        "agents.json": agents_payload,
    }
    if not any(
        field_name in document
        for document in declarations.values()
        for field_name in PLACEMENT_DEPLOYMENT_FIELDS
    ):
        # Backward compatibility for projects materialized before placement
        # deployment provenance became part of the runtime contract.
        return

    expected_values: Dict[str, Any] = {}
    for field_name in PLACEMENT_DEPLOYMENT_FIELDS:
        values = {
            document_name: document.get(field_name)
            for document_name, document in declarations.items()
        }
        if any(value in (None, "") for value in values.values()):
            raise RoomContractContractError(
                f"Placement deployment field {field_name!r} must be declared by "
                "project.json, the active trace map, and agents.json."
            )
        distinct = {str(value) for value in values.values()}
        if len(distinct) != 1:
            raise RoomContractContractError(
                f"Placement deployment field {field_name!r} disagrees across declarations: {values}."
            )
        expected_values[field_name] = next(iter(values.values()))

    expected_contract = {
        "placement_schema": PLACEMENT_ARTIFACT_SCHEMA,
        "placement_schema_version": PLACEMENT_ARTIFACT_SCHEMA_VERSION,
        "placement_algorithm_version": PLACEMENT_ALGORITHM_VERSION,
    }
    for field_name, expected in expected_contract.items():
        if expected_values.get(field_name) != expected:
            raise RoomContractContractError(
                f"Placement deployment {field_name} must be {expected!r}."
            )
    if expected_values.get("placement_origin") not in PLACEMENT_ORIGINS:
        raise RoomContractContractError("Placement deployment origin is unsupported.")
    artifact_hash = str(expected_values.get("placement_artifact_sha256") or "")
    if len(artifact_hash) != 64 or any(char not in "0123456789abcdef" for char in artifact_hash):
        raise RoomContractContractError(
            "Placement artifact SHA-256 must be a lowercase 64-character hexadecimal digest."
        )
    projection_hash = _placement_projection_sha256(agents_payload.get("agents"))
    if projection_hash != expected_values.get("placement_projection_sha256"):
        raise RoomContractContractError(
            "agents.json id/position/forward projection does not match its declared SHA-256."
        )


def _resolve_project_file(
    project_dir: Path,
    raw_path: Any,
    default_name: str,
    *,
    required: bool = True,
) -> Path:
    text = _optional_text(raw_path)
    candidate = Path(text) if text else project_dir / default_name
    if not candidate.is_absolute():
        candidate = project_dir / candidate
    candidate = candidate.resolve()
    if required and not candidate.is_file():
        raise RoomContractContractError(f"Required RoomContract project file is missing: {candidate}")
    return candidate


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RoomContractContractError(f"Required JSON file is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RoomContractContractError(f"Invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RoomContractContractError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path, scheme: str = "sha256-lf-v1") -> str:
    """Hash declared serialization; LF scheme normalizes CRLF bytes only."""
    payload = Path(path).read_bytes()
    if scheme == "sha256-lf-v1":
        payload = payload.replace(b"\r\n", b"\n")
    elif scheme != "sha256-raw-v1":
        raise RoomContractContractError(f"Unsupported digest scheme {scheme!r}.")
    return hashlib.sha256(payload).hexdigest().upper()


def _refs(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _require_refs(
    item: Mapping[str, Any],
    field: str,
    by_id: Mapping[str, Mapping[str, Any]],
    *,
    minimum: int,
    maximum: Optional[int] = None,
    expected_type: Optional[str] = None,
) -> List[str]:
    refs = _refs(item.get(field))
    if len(refs) < minimum or (maximum is not None and len(refs) > maximum):
        upper = "*" if maximum is None else str(maximum)
        raise RoomContractContractError(
            f"{item.get('type')} {item.get('id')!r}.{field} requires {minimum}..{upper} references."
        )
    for ref in refs:
        target = by_id.get(ref)
        if target is None:
            raise RoomContractContractError(f"{item.get('id')!r}.{field} contains unresolved reference {ref!r}.")
        if expected_type and target.get("type") != expected_type:
            raise RoomContractContractError(
                f"{item.get('id')!r}.{field} must reference {expected_type}, got {target.get('type')}."
            )
    return refs


def _require_exact_refs(
    item: Mapping[str, Any],
    field: str,
    by_id: Mapping[str, Mapping[str, Any]],
    count: int,
) -> List[str]:
    return _require_refs(item, field, by_id, minimum=count, maximum=count)


def _require_exact_typed_refs(
    item: Mapping[str, Any],
    field: str,
    by_id: Mapping[str, Mapping[str, Any]],
    expected_type: str,
    count: int,
) -> List[str]:
    return _require_refs(
        item,
        field,
        by_id,
        minimum=count,
        maximum=count,
        expected_type=expected_type,
    )


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if not text:
        raise RoomContractContractError(f"{field} is required.")
    return text


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _legacy_action_kind(item: Mapping[str, Any]) -> Optional[str]:
    endpoint = str(item.get("endpoint") or "")
    action_id = str(item.get("runtime_action_id") or "")
    capability_id = str(item.get("capability_id") or "")
    if endpoint == "POST /setup":
        return "setup"
    if endpoint == "POST /chat" and ("HANDOFF" in action_id or "HANDOFF" in capability_id):
        return "handoff"
    if endpoint == "POST /chat":
        return "chat"
    return None


def _legacy_capability_use_id(trace: Mapping[str, Any], capability_id: Any) -> Optional[str]:
    capability_id = _optional_text(capability_id)
    if not capability_id:
        return None
    case_id = str(trace.get("case_id") or "").upper()
    prefix = f"CAP-{case_id}-"
    suffix = capability_id[len(prefix) :] if capability_id.startswith(prefix) else capability_id
    for step in trace.get("scenario_steps", []):
        if not isinstance(step, Mapping):
            continue
        for use_id in _refs(step.get("capability_use_ids")):
            if use_id.endswith(suffix):
                return use_id
    return None


def _legacy_step_id(trace: Mapping[str, Any], capability_id: Any) -> Optional[str]:
    use_id = _legacy_capability_use_id(trace, capability_id)
    if not use_id:
        return None
    for step in trace.get("scenario_steps", []):
        if isinstance(step, Mapping) and use_id in _refs(step.get("capability_use_ids")):
            return _optional_text(step.get("scenario_step_id"))
    return None
