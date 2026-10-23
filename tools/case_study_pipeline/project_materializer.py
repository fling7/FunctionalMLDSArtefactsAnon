from __future__ import annotations

import json
import hashlib
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .common import copy_file, read_json, update_manifest, write_json
from .agent_roles import voice_gender_for_voice
from .agent_placement import (
    FORWARD_NORMALIZATION_TOLERANCE,
    PLACEMENT_ALGORITHM_VERSION,
    PLACEMENT_ARTIFACT_SCHEMA,
    PLACEMENT_ARTIFACT_SCHEMA_VERSION,
    PLACEMENT_FLOOR_TOLERANCE,
    PLACEMENT_ORIGINS,
    placement_artifact_sha256,
)


DEFAULT_BACKEND_ROOT = Path("app/backend_root/agent_backend")
V2_INSTANCE_FILENAME = "roomcontract.v2.instance.json"
V2_PROJECT_INSTANCE_FILENAME = "roomcontract.v2.instance.json"
V05_PROJECT_INSTANCE_FILENAME = "roomcontract.v05.instance.json"
V2_MODEL_VERSION = "2.0.0-model"
V2_INSTANCE_SCHEMA = "dynamic_functional_rdl_v2_instance"
V2_PROFILE = "executable"
V2_TRACE_SCHEMA = "roomcontract_trace_map_v2"
V2_TRACE_VERSION = "2.0"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _copy_kb(src_root: Path, dst_root: Path) -> List[Path]:
    written: List[Path] = []
    if dst_root.exists():
        shutil.rmtree(dst_root)
    for src in src_root.rglob("*.txt"):
        relative = src.relative_to(src_root)
        dst = dst_root / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        written.append(dst)
    return written


def _load_backend_agent_spec(backend_root: Path):
    root = str(backend_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    from backend.state import AgentSpec  # type: ignore

    return AgentSpec


def _ensure_v2_instance(case_dir: Path) -> Path:
    """Return a native V2 artifact proven to derive from the current v0.5 source.

    Existence alone is not sufficient: handoff derivation intentionally mutates
    the preserved v0.5 instance.  A V2 file assembled before that mutation is
    stale even though it still satisfies the V2 schema.  The semantic
    projection hash in ``sourceContract`` is the canonical provenance link.
    """

    path = case_dir / "roomcontract" / V2_INSTANCE_FILENAME
    report_path = case_dir / "roomcontract" / "roomcontract.v2.assembly_report.json"
    source_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    if path.exists() and report_path.exists() and source_path.exists():
        try:
            from .roomcontract_v2_assembler import import_v05, structural_sha256

            source = read_json(source_path)
            projection = import_v05(source)
            semantic = projection.get("dynamicFunctionalModel")
            current_v2 = read_json(path)
            current_report = read_json(report_path)
            source_contract = current_v2.get("sourceContract") or {}
            if (
                isinstance(semantic, Mapping)
                and isinstance(source_contract, Mapping)
                and current_report.get("status") == "valid"
                and source_contract.get("semanticProjectionSha256") == structural_sha256(semantic)
            ):
                return path
        except Exception:
            # Regeneration below produces the authoritative diagnostic when
            # either source or cached artifact is malformed.
            pass
    from .roomcontract_v2_assembler import run_roomcontract_v2_assembly_for_case

    result = run_roomcontract_v2_assembly_for_case(case_dir)
    if str(result.get("status") or "").lower() != "success" or not path.exists():
        raise RuntimeError(
            "Native RoomContract V2 assembly failed before project materialization: "
            + json.dumps(result, ensure_ascii=False, default=str)
        )
    return path


def _validate_v2_agent_provider_contract(
    *,
    roomcontract_instance: Mapping[str, Any],
    agent_roles: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Fail closed on the Unity-visible V2 agent and provider projection.

    The legacy materializer used dictionaries and ``continue`` statements while
    joining source agents to RoomContract agents.  Consequently a duplicate or
    unknown ``sourceAgentId`` could be silently dropped and later appear as an
    empty reference in ``agents.json``.  V2 is an executable contract, so the
    join must be a complete bijection and all outgoing references must already be
    resolvable before a trace or project file is written.
    """

    errors: List[str] = []
    expected_metadata = {
        "schema": V2_INSTANCE_SCHEMA,
        "metamodelVersion": V2_MODEL_VERSION,
        "profile": V2_PROFILE,
        "fixture_profile": V2_PROFILE,
    }
    for field, expected in expected_metadata.items():
        if roomcontract_instance.get(field) != expected:
            errors.append(
                f"V2 instance {field} must be {expected!r}; "
                f"found {roomcontract_instance.get(field)!r}."
            )

    raw_objects = roomcontract_instance.get("objects")
    if not isinstance(raw_objects, list):
        errors.append("V2 instance objects must be an array.")
        raw_objects = []
    objects = [item for item in raw_objects if isinstance(item, Mapping)]
    if len(objects) != len(raw_objects):
        errors.append("Every V2 instance object must be a JSON object.")

    by_id: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(objects):
        object_id = str(item.get("id") or "").strip()
        if not object_id:
            errors.append(f"V2 objects[{index}] has no non-empty id.")
            continue
        if object_id in by_id:
            errors.append(f"V2 object id {object_id!r} is duplicated.")
            continue
        by_id[object_id] = dict(item)

    raw_source_agents = agent_roles.get("agents")
    if not isinstance(raw_source_agents, list):
        errors.append("agent_roles.agents must be an array.")
        raw_source_agents = []
    source_agents: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(raw_source_agents):
        if not isinstance(item, Mapping):
            errors.append(f"agent_roles.agents[{index}] must be an object.")
            continue
        source_id = str(item.get("id") or "").strip()
        if not source_id:
            errors.append(f"agent_roles.agents[{index}] has no non-empty id.")
        elif source_id in source_agents:
            errors.append(f"Source agent id {source_id!r} is duplicated.")
        else:
            source_agents[source_id] = dict(item)

    native_by_source: Dict[str, Dict[str, Any]] = {}
    native_agents = [item for item in objects if item.get("type") == "Agent"]
    for item in native_agents:
        agent_id = str(item.get("id") or "").strip()
        source_id = str(item.get("sourceAgentId") or "").strip()
        if not source_id:
            errors.append(f"Native Agent {agent_id!r} has no non-empty sourceAgentId.")
            continue
        if source_id in native_by_source:
            errors.append(
                f"Native sourceAgentId {source_id!r} is ambiguous; it is used by "
                f"{native_by_source[source_id].get('id')!r} and {agent_id!r}."
            )
            continue
        native_by_source[source_id] = dict(item)
        if item.get("kind") != "agent":
            errors.append(f"Native Agent {agent_id!r} must also have Entity kind 'agent'.")

    missing_native = sorted(set(source_agents) - set(native_by_source))
    unknown_native = sorted(set(native_by_source) - set(source_agents))
    if missing_native:
        errors.append(
            "Source agents without exactly one native Agent/Entity mapping: "
            + ", ".join(missing_native)
        )
    if unknown_native:
        errors.append(
            "Native Agents with unknown sourceAgentId: " + ", ".join(unknown_native)
        )
    if len(native_agents) != len(source_agents):
        errors.append(
            "Source-agent/native-Agent cardinality mismatch: "
            f"{len(source_agents)} source agents versus {len(native_agents)} native Agents."
        )

    def checked_refs(
        owner: Mapping[str, Any],
        field: str,
        *,
        expected_type: str,
        expected_kind: str | None = None,
    ) -> List[str]:
        owner_id = str(owner.get("id") or "")
        raw = owner.get(field)
        if raw is None:
            return []
        if not isinstance(raw, list):
            errors.append(f"{owner_id}.{field} must be an explicit reference array.")
            return []
        refs: List[str] = []
        for index, value in enumerate(raw):
            ref = str(value or "").strip() if isinstance(value, str) else ""
            if not ref:
                errors.append(f"{owner_id}.{field}[{index}] must be a non-empty string reference.")
                continue
            refs.append(ref)
            target = by_id.get(ref)
            if target is None:
                errors.append(f"{owner_id}.{field} contains unresolved reference {ref!r}.")
                continue
            if target.get("type") != expected_type:
                errors.append(
                    f"{owner_id}.{field} reference {ref!r} must target {expected_type}, "
                    f"found {target.get('type')!r}."
                )
            if expected_kind is not None and target.get("kind") != expected_kind:
                errors.append(
                    f"{owner_id}.{field} reference {ref!r} must target Entity kind "
                    f"{expected_kind!r}, found {target.get('kind')!r}."
                )
        if len(refs) != len(set(refs)):
            errors.append(f"{owner_id}.{field} must not contain duplicate references.")
        return refs

    domain_agent_ids_by_capability: Dict[str, set[str]] = {}
    for agent in native_agents:
        checked_refs(agent, "playsActor", expected_type="Actor")
        for capability_id in checked_refs(
            agent,
            "providedCapability",
            expected_type="Capability",
        ):
            domain_agent_ids_by_capability.setdefault(
                capability_id,
                set(),
            ).add(str(agent.get("id") or ""))
        checked_refs(agent, "responsibleZone", expected_type="Entity", expected_kind="zone")
        checked_refs(agent, "groundedAsset", expected_type="Entity", expected_kind="asset")
        checked_refs(
            agent,
            "groundedObjectGroup",
            expected_type="Entity",
        )
        checked_refs(agent, "handoffTarget", expected_type="Agent")

    orchestrators = [
        item
        for item in objects
        if item.get("type") == "Entity"
        and item.get("entityRole") == "runtimeOrchestrator"
    ]
    for orchestrator in orchestrators:
        overlap = sorted(
            set(_as_reference_list(orchestrator.get("providedCapability")))
            & set(domain_agent_ids_by_capability)
        )
        if overlap:
            errors.append(
                f"{orchestrator.get('id')} must not advertise Agent-owned domain "
                f"Capabilities: {overlap!r}."
            )

    for use in [item for item in objects if item.get("type") == "CapabilityUse"]:
        use_id = str(use.get("id") or "")
        capability_ids = checked_refs(use, "typeRef", expected_type="Capability")
        if not capability_ids and "capability" in use:
            capability_ids = checked_refs(use, "capability", expected_type="Capability")
        provider_ids = []
        raw_providers = use.get("provider")
        if not isinstance(raw_providers, list):
            errors.append(f"{use_id}.provider must be an explicit reference array.")
        else:
            for index, value in enumerate(raw_providers):
                provider_id = str(value or "").strip() if isinstance(value, str) else ""
                if not provider_id:
                    errors.append(f"{use_id}.provider[{index}] must be a non-empty string reference.")
                    continue
                provider_ids.append(provider_id)
                provider = by_id.get(provider_id)
                if provider is None:
                    errors.append(f"{use_id}.provider contains unresolved reference {provider_id!r}.")
                elif provider.get("type") not in {"Entity", "Agent"}:
                    errors.append(
                        f"{use_id}.provider reference {provider_id!r} must target Entity/Agent, "
                        f"found {provider.get('type')!r}."
                    )
        if len(capability_ids) != 1:
            errors.append(f"{use_id} must reference exactly one Capability; found {capability_ids!r}.")
        if len(provider_ids) != 1:
            errors.append(f"{use_id} must reference exactly one provider; found {provider_ids!r}.")
        if len(capability_ids) == 1 and len(provider_ids) == 1:
            provider = by_id.get(provider_ids[0], {})
            provided = provider.get("providedCapability")
            provided_ids = provided if isinstance(provided, list) else []
            if capability_ids[0] not in provided_ids:
                errors.append(
                    f"{use_id} provider {provider_ids[0]!r} does not provide Capability "
                    f"{capability_ids[0]!r}."
                )
            domain_provider_ids = domain_agent_ids_by_capability.get(
                capability_ids[0],
                set(),
            )
            if domain_provider_ids and provider_ids[0] not in domain_provider_ids:
                errors.append(
                    f"{use_id} references Agent-owned domain Capability "
                    f"{capability_ids[0]!r}, but provider {provider_ids[0]!r} is "
                    "not a modeled Domain Agent for that Capability."
                )

    if errors:
        raise ValueError("Invalid V2 agent/provider contract: " + " ".join(errors))
    return native_by_source


def build_trace_map(
    *,
    case_dir: Path,
    project_dir: Path,
    roomcontract_instance: Dict[str, Any],
    agent_roles: Dict[str, Any],
) -> Dict[str, Any]:
    use_cases = (roomcontract_instance.get("requirementsModel") or {}).get("useCases") or []
    main_use_case = use_cases[0] if use_cases else {}
    main_scenario = (main_use_case.get("scenarios") or [{}])[0]
    scenario_steps = main_scenario.get("steps") or []
    runtime_bindings = roomcontract_instance.get("runtimeBindings") or []
    validation_cases = roomcontract_instance.get("validationCases") or []
    capabilities = roomcontract_instance.get("capabilities") or []

    agent_refs = []
    generated_agents = roomcontract_instance.get("agents") or []
    generated_by_source = {agent.get("source_agent_id"): agent for agent in generated_agents if isinstance(agent, dict)}
    for agent in agent_roles.get("agents") or []:
        source_agent_id = str(agent.get("id") or "")
        functional_agent = generated_by_source.get(source_agent_id, {})
        agent_refs.append(
            {
                "agent_id": source_agent_id,
                "roomcontract_agent_id": functional_agent.get("id"),
                "entity_id": functional_agent.get("entity_id"),
                "plays_actor": functional_agent.get("playsActor") or [],
                "knowledge_tags": agent.get("knowledge_tags") or [],
            }
        )

    runtime_action_refs = []
    for binding in runtime_bindings:
        for action in binding.get("runtimeActions") or []:
            runtime_action_refs.append(
                {
                    "runtime_binding_id": binding.get("id"),
                    "capability_id": binding.get("capability_id"),
                    "runtime_action_id": action.get("id"),
                    "endpoint": action.get("endpoint"),
                    "tool": action.get("tool"),
                    "topic": action.get("topic"),
                }
            )

    return {
        "schema": "roomcontract_trace_map",
        "case_id": case_dir.name,
        "roomcontract_path": str(case_dir / "roomcontract" / "roomcontract.instance.generated.json"),
        "project_files": {
            "project": str(project_dir / "project.json"),
            "room_plan": str(project_dir / "room_plan.json"),
            "agents": str(project_dir / "agents.json"),
            "kb_root": str(project_dir / "kb"),
        },
        "use_case_id": main_use_case.get("id"),
        "main_scenario_id": main_scenario.get("id"),
        "scenario_steps": [
            {
                "scenario_step_id": step.get("id"),
                "step_number": step.get("stepNumber"),
                "capability_use_ids": step.get("capabilityUseIds") or [],
                "resulting_state_ids": step.get("resultingState") or [],
            }
            for step in scenario_steps
        ],
        "capabilities": [
            {
                "capability_id": capability.get("id"),
                "effect_ids": [effect.get("id") for effect in capability.get("effects") or []],
            }
            for capability in capabilities
        ],
        "runtime_actions": runtime_action_refs,
        "validation_cases": [
            {
                "validation_case_id": validation_case.get("id"),
                "runtime_binding_ids": validation_case.get("runtime_binding_ids") or [],
                "expected_outcome_ids": validation_case.get("expectedOutcome") or [],
            }
            for validation_case in validation_cases
        ],
        "agents": agent_refs,
    }


def build_trace_map_v2(
    *,
    case_dir: Path,
    project_dir: Path,
    roomcontract_instance: Dict[str, Any],
    agent_roles: Dict[str, Any],
    model_sha256: str,
) -> Dict[str, Any]:
    native_agent_by_source = _validate_v2_agent_provider_contract(
        roomcontract_instance=roomcontract_instance,
        agent_roles=agent_roles,
    )
    objects = [dict(item) for item in roomcontract_instance.get("objects") or [] if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in objects if str(item.get("id") or "")}

    def typed(type_name: str) -> List[Dict[str, Any]]:
        return [item for item in objects if item.get("type") == type_name]

    def refs(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item)]

    use_cases = typed("UseCase")
    scenarios = typed("Scenario")
    main_scenarios = [
        item for item in scenarios if str(item.get("kind") or "") == "main"
    ]
    scenario_steps = typed("ScenarioStep")
    capability_uses = typed("CapabilityUse")
    capabilities = typed("Capability")
    runtime_bindings = typed("RuntimeBinding")
    validation_cases = typed("ValidationCase")
    validation_targets = typed("RuntimeValidationTarget")
    assertions = [
        item
        for item in objects
        if item.get("type")
        in {"StateAssertion", "EventAssertion", "OutputAssertion", "GroundingAssertion", "RelationAssertion"}
    ]

    scenario_for_step: Dict[str, str] = {}
    for scenario in scenarios:
        scenario_id = str(scenario.get("id") or "")
        for step_id in refs(scenario.get("step")):
            previous = scenario_for_step.setdefault(step_id, scenario_id)
            if previous != scenario_id:
                raise ValueError(
                    f"ScenarioStep {step_id!r} belongs to more than one Scenario: "
                    f"{previous!r}, {scenario_id!r}."
                )

    use_case_for_scenario: Dict[str, str] = {}
    for specification in typed("UseCaseScenarioSpecification"):
        use_case_ids = refs(specification.get("useCase"))
        scenario_ids = refs(specification.get("scenario"))
        if len(use_case_ids) != 1 or len(scenario_ids) != 1:
            raise ValueError(
                "UseCaseScenarioSpecification requires exactly one UseCase and Scenario."
            )
        scenario_id = scenario_ids[0]
        use_case_id = use_case_ids[0]
        previous = use_case_for_scenario.setdefault(scenario_id, use_case_id)
        if previous != use_case_id:
            raise ValueError(
                f"Scenario {scenario_id!r} belongs to more than one UseCase: "
                f"{previous!r}, {use_case_id!r}."
            )
    if (
        len(use_cases) == 1
        and len(scenarios) == 1
        and not use_case_for_scenario
    ):
        # Compatibility with early native-V2 fixtures that predate the explicit
        # UseCaseScenarioSpecification projection.
        use_case_for_scenario[str(scenarios[0].get("id") or "")] = str(
            use_cases[0].get("id") or ""
        )

    step_for_use: Dict[str, Dict[str, Any]] = {}
    for step in scenario_steps:
        for use_id in refs(step.get("capabilityUse")):
            if use_id in step_for_use:
                raise ValueError(
                    f"CapabilityUse {use_id!r} belongs to more than one ScenarioStep."
                )
            step_for_use[use_id] = step
    uses_for_capability: Dict[str, List[Dict[str, Any]]] = {}
    for use in capability_uses:
        for capability_id in refs(use.get("typeRef") or use.get("capability")):
            uses_for_capability.setdefault(capability_id, []).append(use)
    assertion_ids_for_capability: Dict[str, List[str]] = {}
    for capability in capabilities:
        assertion_ids: List[str] = []
        for effect_id in refs(capability.get("effect")):
            effect = by_id.get(effect_id, {})
            assertion_ids.extend(refs(effect.get("specifiedBy")))
        assertion_ids_for_capability[str(capability.get("id"))] = list(dict.fromkeys(assertion_ids))

    cases_for_binding: Dict[str, List[str]] = {}
    targets_for_binding: Dict[str, List[str]] = {}
    for validation_case in validation_cases:
        case_id = str(validation_case.get("id") or "")
        for binding_id in refs(validation_case.get("vvSubject")):
            if by_id.get(binding_id, {}).get("type") == "RuntimeBinding":
                cases_for_binding.setdefault(binding_id, []).append(case_id)
        for target_id in refs(validation_case.get("vvTarget")):
            target = by_id.get(target_id, {})
            for binding_id in refs(target.get("runtimeBinding")):
                targets_for_binding.setdefault(binding_id, []).append(target_id)

    runtime_action_refs: List[Dict[str, Any]] = []
    for binding in runtime_bindings:
        binding_id = str(binding.get("id") or "")
        capability_ids = refs(binding.get("capability"))
        if len(capability_ids) != 1:
            continue
        capability_id = capability_ids[0]
        for action_id in refs(binding.get("runtimeAction")):
            action = by_id.get(action_id, {})
            locator_ids = refs(action.get("locator"))
            locator = by_id.get(locator_ids[0], {}) if len(locator_ids) == 1 else {}
            for use in uses_for_capability.get(capability_id, []):
                use_id = str(use.get("id") or "")
                step = step_for_use.get(use_id, {})
                provider_ids = refs(use.get("provider"))
                if not step or len(provider_ids) != 1:
                    continue
                locator_kind = str(locator.get("kind") or "")
                locator_value = str(locator.get("value") or "")
                action_kind = _runtime_action_kind_v2(action=action, by_id=by_id)
                step_id = str(step.get("id") or "")
                scenario_id = scenario_for_step.get(step_id, "")
                use_case_id = use_case_for_scenario.get(scenario_id, "")
                if not scenario_id or not use_case_id:
                    raise ValueError(
                        f"Runtime action chain for ScenarioStep {step_id!r} has no "
                        "unique Scenario/UseCase owner."
                    )
                item = {
                    "action_kind": action_kind,
                    "use_case_id": use_case_id,
                    "scenario_id": scenario_id,
                    "scenario_step_id": step_id,
                    "capability_use_id": use_id,
                    "capability_id": capability_id,
                    "provider_entity_id": provider_ids[0],
                    "target_ids": refs(use.get("target")),
                    "runtime_binding_id": binding_id,
                    "runtime_action_id": action_id,
                    "locator": {"kind": locator_kind, "value": locator_value},
                    "assertion_ids": assertion_ids_for_capability.get(capability_id, []),
                    "validation_case_ids": list(dict.fromkeys(cases_for_binding.get(binding_id, []))),
                    "runtime_validation_target_ids": list(dict.fromkeys(targets_for_binding.get(binding_id, []))),
                    # Compatibility display fields; V2 resolution uses locator and exact IDs above.
                    "endpoint": locator_value if locator_kind == "endpoint" else None,
                    "tool": locator_value if locator_kind == "tool" else None,
                    "topic": locator_value if locator_kind == "topic" else None,
                }
                runtime_action_refs.append(item)

    setup_actions = [
        item
        for item in runtime_action_refs
        if item.get("action_kind") == "setup"
    ]
    if len(setup_actions) == 1:
        primary_scenario_id = str(setup_actions[0].get("scenario_id") or "")
        primary_use_case_id = str(setup_actions[0].get("use_case_id") or "")
    else:
        primary_scenario_id = str(
            (main_scenarios[0] if main_scenarios else {}).get("id") or ""
        )
        primary_use_case_id = use_case_for_scenario.get(primary_scenario_id, "")

    agent_refs = []
    for source_agent in agent_roles.get("agents") or []:
        source_agent_id = str(source_agent.get("id") or "")
        agent = native_agent_by_source[source_agent_id]
        agent_refs.append(
            {
                "agent_id": source_agent_id,
                "roomcontract_agent_id": agent.get("id"),
                "entity_id": agent.get("id"),
                "plays_actor": refs(agent.get("playsActor")),
                "provided_capability_ids": refs(agent.get("providedCapability")),
                "responsible_zone_ids": refs(agent.get("responsibleZone")),
                "grounded_asset_ids": refs(agent.get("groundedAsset")),
                "grounded_object_group_ids": refs(agent.get("groundedObjectGroup")),
                "knowledge_tags": agent.get("knowledgeTag") or [],
            }
        )

    return {
        "schema": V2_TRACE_SCHEMA,
        "schema_version": V2_TRACE_VERSION,
        "model_version": V2_MODEL_VERSION,
        "model_sha256": model_sha256,
        "digest_scheme": "sha256-lf-v1",
        "profile": V2_PROFILE,
        "case_id": case_dir.name,
        "roomcontract_path": str(case_dir / "roomcontract" / "roomcontract.instance.generated.json"),
        "roomcontract_v2_path": str(case_dir / "roomcontract" / V2_INSTANCE_FILENAME),
        "project_files": {
            "project": str(project_dir / "project.json"),
            "room_plan": str(project_dir / "room_plan.json"),
            "agents": str(project_dir / "agents.json"),
            "kb_root": str(project_dir / "kb"),
        },
        # Singular aliases remain for older Unity clients.  They identify the
        # authoring/setup chain; the plural fields and per-chain ownership below
        # are authoritative for multi-UseCase models.
        "use_case_id": primary_use_case_id or None,
        "main_scenario_id": primary_scenario_id or None,
        "use_case_ids": [str(item.get("id")) for item in use_cases],
        "main_scenario_ids": [str(item.get("id")) for item in main_scenarios],
        "scenario_steps": [
            {
                "use_case_id": use_case_for_scenario.get(
                    scenario_for_step.get(str(step.get("id") or ""), ""),
                ),
                "scenario_id": scenario_for_step.get(str(step.get("id") or "")),
                "scenario_step_id": step.get("id"),
                "step_number": step.get("stepNumber"),
                "capability_use_ids": refs(step.get("capabilityUse")),
                "provider_entity_ids": refs(step.get("performedBy")),
                "resulting_assertion_ids": refs(step.get("resultingAssertion")),
                "resulting_state_ids": [
                    ref
                    for ref in refs(step.get("resultingAssertion"))
                    if by_id.get(ref, {}).get("type") == "StateAssertion"
                ],
            }
            for step in scenario_steps
        ],
        "step_relations": [
            {
                "step_relation_id": item.get("id"),
                "kind": item.get("kind"),
                "source_step_id": (refs(item.get("source")) or [None])[0],
                "target_step_id": (refs(item.get("target")) or [None])[0],
                "guard_id": (refs(item.get("guard")) or [None])[0],
                "probability": (
                    by_id.get((refs(item.get("probability")) or [None])[0], {}).get("value")
                    if refs(item.get("probability"))
                    else None
                ),
            }
            for item in typed("StepRelation")
        ],
        "parallel_groups": [
            {
                "parallel_group_id": item.get("id"),
                "label": item.get("name") or item.get("label"),
                "member_step_ids": refs(item.get("memberStep")),
            }
            for item in typed("ParallelGroup")
        ],
        "guards": [
            {
                "guard_id": item.get("id"),
                "kind": item.get("kind"),
                "value": item.get("value"),
                "expression": item.get("mixedStringContent") or item.get("expressionText"),
            }
            for item in typed("ScenarioCondition")
        ],
        "capabilities": [
            {
                "capability_id": capability.get("id"),
                "effect_ids": refs(capability.get("effect")),
                "assertion_ids": assertion_ids_for_capability.get(str(capability.get("id")), []),
            }
            for capability in capabilities
        ],
        "assertions": [
            {
                "assertion_id": item.get("id"),
                "assertion_type": item.get("type"),
                "subject_id": (refs(item.get("subject")) or [None])[0],
                "expression_id": (refs(item.get("expression")) or [None])[0],
                "severity": item.get("severity"),
            }
            for item in assertions
        ],
        "runtime_actions": runtime_action_refs,
        "validation_cases": [
            {
                "validation_case_id": item.get("id"),
                "vv_subject_ids": refs(item.get("vvSubject")),
                "runtime_validation_target_ids": refs(item.get("vvTarget")),
                "procedure_ids": refs(item.get("vvProcedure")),
            }
            for item in validation_cases
        ],
        "runtime_validation_targets": [
            {
                "runtime_validation_target_id": item.get("id"),
                "platform": item.get("platform"),
                "environment_ref": item.get("environmentRef"),
                "runtime_binding_ids": refs(item.get("runtimeBinding")),
                "element_ids": refs(item.get("element")),
            }
            for item in validation_targets
        ],
        "agents": agent_refs,
    }


def _runtime_action_kind_v2(
    *,
    action: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
) -> str:
    """Read the explicit application mapping encoded in a modeled SchemaReference.

    Runtime consumers must never infer setup/chat/handoff from IDs or locator text. The
    V2 assembler stores this application projection as JSON in RuntimeAction.inputSchema.
    """

    markers: List[str] = []
    for schema_id in _as_reference_list(action.get("inputSchema")):
        schema = by_id.get(schema_id, {})
        if schema.get("type") != "SchemaReference":
            continue
        raw = schema.get("text")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        marker = str(payload.get("applicationActionKind") or "").strip().lower()
        if marker:
            markers.append(marker)
    markers = list(dict.fromkeys(markers))
    allowed = {"setup", "chat", "handoff", "runtime"}
    if len(markers) != 1 or markers[0] not in allowed:
        raise ValueError(
            f"RuntimeAction {action.get('id')!r} requires exactly one explicit "
            f"applicationActionKind in its input SchemaReference; found {markers!r}."
        )
    return markers[0]


def _as_reference_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _sha256_file(path: Path) -> str:
    """Portable model serialization digest: normalize CRLF, preserve other bytes."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()


def _validate_and_index_agent_placements(
    agent_roles: Mapping[str, Any],
    placements: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Require a complete, unambiguous and executable placement projection."""

    if placements.get("schema") != PLACEMENT_ARTIFACT_SCHEMA:
        raise ValueError(f"placement schema must be exactly {PLACEMENT_ARTIFACT_SCHEMA!r}.")
    if placements.get("schema_version") != PLACEMENT_ARTIFACT_SCHEMA_VERSION:
        raise ValueError(
            f"placement schema_version must be exactly {PLACEMENT_ARTIFACT_SCHEMA_VERSION!r}."
        )
    if placements.get("placement_algorithm_version") != PLACEMENT_ALGORITHM_VERSION:
        raise ValueError(
            f"placement_algorithm_version must be exactly {PLACEMENT_ALGORITHM_VERSION!r}."
        )
    if placements.get("origin") not in PLACEMENT_ORIGINS:
        raise ValueError(
            "placement origin must be one of: " + ", ".join(sorted(PLACEMENT_ORIGINS)) + "."
        )
    # Ensure the complete document is canonical JSON before projecting any of
    # its values into runtime files.
    placement_artifact_sha256(placements)

    role_ids = [
        str(agent.get("id") or "").strip()
        for agent in agent_roles.get("agents") or []
        if isinstance(agent, Mapping)
    ]
    if any(not agent_id for agent_id in role_ids) or len(role_ids) != len(set(role_ids)):
        raise ValueError("agent_roles contains empty or duplicate agent ids.")

    indexed: Dict[str, Dict[str, Any]] = {}
    for index, placement in enumerate(placements.get("agent_placements") or []):
        if not isinstance(placement, dict):
            raise ValueError(f"agent_placements[{index}] must be an object.")
        agent_id = str(placement.get("id") or "").strip()
        if not agent_id:
            raise ValueError(f"agent_placements[{index}] has no agent id.")
        if agent_id in indexed:
            raise ValueError(f"agent_placements contains duplicate agent id {agent_id!r}.")

        position = placement.get("position")
        forward = placement.get("forward")
        if not isinstance(position, Mapping) or not isinstance(forward, Mapping):
            raise ValueError(f"agent placement {agent_id!r} requires position and forward objects.")
        raw_values = [position.get(axis) for axis in ("x", "y", "z")]
        raw_direction = [forward.get(axis) for axis in ("x", "y", "z")]
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in raw_values + raw_direction
        ):
            raise ValueError(
                f"agent placement {agent_id!r} requires finite JSON-number x/y/z position and forward values."
            )
        values = [float(value) for value in raw_values]
        direction = [float(value) for value in raw_direction]
        if abs(values[1]) > PLACEMENT_FLOOR_TOLERANCE or abs(direction[1]) > PLACEMENT_FLOOR_TOLERANCE:
            raise ValueError(f"agent placement {agent_id!r} must be planar (y=0).")
        forward_length = math.hypot(direction[0], direction[2])
        if abs(forward_length - 1.0) > FORWARD_NORMALIZATION_TOLERANCE:
            raise ValueError(f"agent placement {agent_id!r} forward must be normalized on X/Z.")
        canonical = dict(placement)
        canonical["id"] = agent_id
        canonical["position"] = {"x": values[0], "y": values[1], "z": values[2]}
        canonical["forward"] = {
            "x": direction[0],
            "y": direction[1],
            "z": direction[2],
        }
        indexed[agent_id] = canonical

    expected = set(role_ids)
    actual = set(indexed)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise ValueError("agent placements must match agent roles exactly (" + "; ".join(details) + ").")
    return indexed


PLACEMENT_DEPLOYMENT_FIELDS = (
    "placement_schema",
    "placement_schema_version",
    "placement_algorithm_version",
    "placement_origin",
    "placement_artifact_sha256",
    "placement_projection_sha256",
)


def placement_projection_sha256(agents: List[Mapping[str, Any]]) -> str:
    """Hash the exact deployed id/position/forward projection, independent of formatting."""

    projection: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, agent in enumerate(agents):
        if not isinstance(agent, Mapping):
            raise ValueError(f"agents[{index}] must be an object for placement projection hashing.")
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id or agent_id in seen_ids:
            raise ValueError("Placement projection requires unique, non-empty agent ids.")
        seen_ids.add(agent_id)
        position = agent.get("position")
        forward = agent.get("forward")
        if not isinstance(position, Mapping) or not isinstance(forward, Mapping):
            raise ValueError(f"Agent {agent_id!r} requires position and forward objects.")
        vectors: Dict[str, Dict[str, Any]] = {}
        for field_name, vector in (("position", position), ("forward", forward)):
            components: Dict[str, Any] = {}
            for axis in ("x", "y", "z"):
                value = vector.get(axis)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(
                        f"Agent {agent_id!r} {field_name}.{axis} must be a finite JSON number."
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


def _placement_artifact_deployment_metadata(placements: Mapping[str, Any]) -> Dict[str, str]:
    return {
        "placement_schema": str(placements.get("schema") or ""),
        "placement_schema_version": str(placements.get("schema_version") or ""),
        "placement_algorithm_version": str(placements.get("placement_algorithm_version") or ""),
        "placement_origin": str(placements.get("origin") or ""),
        "placement_artifact_sha256": placement_artifact_sha256(placements),
    }


def materialize_project(
    *,
    case_dir: Path,
    backend_root: Path = DEFAULT_BACKEND_ROOT,
) -> Dict[str, Path]:
    case_dir = case_dir.resolve()
    backend_root = backend_root.resolve()
    project_dir = backend_root / "projects" / case_dir.name
    project_dir.mkdir(parents=True, exist_ok=True)

    source_rdl = case_dir / "input" / "source_rdl.json"
    agent_roles = read_json(case_dir / "intermediate" / "agent_roles.generated.json")
    placements = read_json(case_dir / "intermediate" / "agent_placements.json")
    placement_by_id = _validate_and_index_agent_placements(agent_roles, placements)
    placement_metadata = _placement_artifact_deployment_metadata(placements)
    roomcontract_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    roomcontract_instance = read_json(roomcontract_path)
    roomcontract_v2_path = _ensure_v2_instance(case_dir)
    roomcontract_v2_instance = read_json(roomcontract_v2_path)
    kb_source = case_dir / "interactive_agents_project" / "kb"

    project_v05_path = project_dir / V05_PROJECT_INSTANCE_FILENAME
    project_v2_path = project_dir / V2_PROJECT_INSTANCE_FILENAME
    copy_file(roomcontract_path, project_v05_path)
    copy_file(roomcontract_v2_path, project_v2_path)
    model_sha256 = _sha256_file(project_v2_path)

    trace_map_v05 = build_trace_map(
        case_dir=case_dir,
        project_dir=project_dir,
        roomcontract_instance=roomcontract_instance,
        agent_roles=agent_roles,
    )
    trace_map_v2 = build_trace_map_v2(
        case_dir=case_dir,
        project_dir=project_dir,
        roomcontract_instance=roomcontract_v2_instance,
        agent_roles=agent_roles,
        model_sha256=model_sha256,
    )

    existing_project = project_dir / "project.json"
    created_ms = _now_ms()
    if existing_project.exists():
        try:
            created_ms = int(read_json(existing_project).get("created_ms") or created_ms)
        except Exception:
            pass

    project_json = {
        "id": case_dir.name,
        "display_name": case_dir.name.replace("_", " ").title(),
        "description": "Generated RoomContract case-study project for Interactive Agents.",
        "created_ms": created_ms,
        "updated_ms": _now_ms(),
        "generation_mode": "roomcontract",
        # The original trace source remains the v0.5 case artifact so legacy runtime logs
        # keep their established location. All model resolution uses the explicit fields below.
        "roomcontract_trace_path": str(roomcontract_path),
        "roomcontract_case_dir": str(case_dir),
        "source_rdl_path": str(source_rdl),
        "metamodelVersion": V2_MODEL_VERSION,
        "roomcontract_model_version": V2_MODEL_VERSION,
        "roomcontract_model_schema": V2_INSTANCE_SCHEMA,
        "roomcontract_profile": V2_PROFILE,
        "roomcontract_model_sha256": model_sha256,
        "roomcontract_digest_scheme": "sha256-lf-v1",
        "roomcontract_model_path": V2_PROJECT_INSTANCE_FILENAME,
        "roomcontract_legacy_path": V05_PROJECT_INSTANCE_FILENAME,
        "roomcontract_trace_map_path": "trace_map.v2.json",
        "roomcontract_legacy_trace_map_path": "trace_map.v05.json",
        "roomcontract_trace_schema_version": V2_TRACE_VERSION,
    }
    agents_out = []
    v2_agent_by_source = {
        str(item.get("agent_id") or ""): item
        for item in trace_map_v2.get("agents") or []
        if isinstance(item, dict) and str(item.get("agent_id") or "")
    }
    for agent in agent_roles.get("agents") or []:
        agent_id = str(agent.get("id") or "")
        placement = placement_by_id[agent_id]
        v2_agent = v2_agent_by_source[agent_id]
        voice = agent.get("voice") or "alloy"
        voice_gender = agent.get("voice_gender") or voice_gender_for_voice(str(voice))
        agents_out.append(
            {
                "id": agent_id,
                "display_name": agent.get("display_name") or agent_id,
                "persona": agent.get("persona") or "",
                "voice": voice,
                "voice_gender": voice_gender,
                "voice_style": agent.get("voice_style") or "neutral",
                "tts_model": "gpt-4o-mini-tts" if str(agent.get("tts_model") or "").lower() == "standard" else (agent.get("tts_model") or "gpt-4o-mini-tts"),
                "expertise": agent.get("expertise") or [],
                "knowledge_tags": agent.get("knowledge_tags") or [],
                "responsible_zone_ids": agent.get("responsible_zone_ids") or [],
                "grounded_object_ids": agent.get("grounded_object_ids") or [],
                "handoff_targets": agent.get("handoff_targets") or [],
                "preferred_zone_ids": agent.get("responsible_zone_ids") or [],
                "position": placement["position"],
                "forward": placement["forward"],
                "roomcontract_agent_ref": v2_agent.get("roomcontract_agent_id"),
                "roomcontract_entity_ref": v2_agent.get("entity_id"),
                "provided_capability_ids": v2_agent.get("provided_capability_ids") or [],
                "plays_actor_ids": v2_agent.get("plays_actor") or [],
            }
        )

    deployment_metadata = {
        **placement_metadata,
        "placement_projection_sha256": placement_projection_sha256(agents_out),
    }
    project_json.update(deployment_metadata)
    trace_map_v05.update(deployment_metadata)
    trace_map_v2.update(deployment_metadata)

    project_path = project_dir / "project.json"
    room_plan_path = project_dir / "room_plan.json"
    agents_path = project_dir / "agents.json"
    trace_map_path = project_dir / "trace_map.json"
    trace_map_v2_path = project_dir / "trace_map.v2.json"
    trace_map_v05_path = project_dir / "trace_map.v05.json"
    write_json(project_path, project_json)
    copy_file(source_rdl, room_plan_path)
    write_json(agents_path, {**deployment_metadata, "agents": agents_out})
    write_json(trace_map_v05_path, trace_map_v05)
    write_json(trace_map_v2_path, trace_map_v2)
    # The unqualified name is the active contract. It is intentionally byte-equivalent
    # at the JSON data level to the explicitly versioned V2 trace map.
    write_json(trace_map_path, trace_map_v2)
    written_kb = _copy_kb(kb_source, project_dir / "kb")
    return {
        "project_dir": project_dir,
        "project_json": project_path,
        "room_plan": room_plan_path,
        "agents": agents_path,
        "trace_map": trace_map_path,
        "trace_map_v2": trace_map_v2_path,
        "trace_map_v05": trace_map_v05_path,
        "roomcontract_v2": project_v2_path,
        "roomcontract_v05": project_v05_path,
        "kb_root": project_dir / "kb",
        "written_kb_count": len(written_kb),
    }


def validate_materialized_project(project_paths: Dict[str, Path], *, case_dir: Path, backend_root: Path = DEFAULT_BACKEND_ROOT) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    project_json_path = project_paths["project_json"]
    room_plan_path = project_paths["room_plan"]
    agents_path = project_paths["agents"]
    trace_map_path = project_paths.get("trace_map")
    trace_map_v2_path = project_paths.get("trace_map_v2")
    trace_map_v05_path = project_paths.get("trace_map_v05")
    roomcontract_v2_path = project_paths.get("roomcontract_v2")
    roomcontract_v05_path = project_paths.get("roomcontract_v05")
    kb_root = project_paths["kb_root"]

    for path in (
        project_json_path,
        room_plan_path,
        agents_path,
        trace_map_path,
        trace_map_v2_path,
        trace_map_v05_path,
        roomcontract_v2_path,
        roomcontract_v05_path,
    ):
        if path is None:
            errors.append("Missing trace_map path in project_paths.")
            continue
        if not path.exists():
            errors.append(f"Missing project file: {path}")
        else:
            try:
                json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                errors.append(f"Invalid JSON in {path}: {exc}")

    project_json = read_json(project_json_path) if project_json_path.exists() else {}
    for field in (
        "id",
        "display_name",
        "description",
        "created_ms",
        "updated_ms",
        "generation_mode",
        "roomcontract_trace_path",
        "roomcontract_case_dir",
        "source_rdl_path",
        "metamodelVersion",
        "roomcontract_model_version",
        "roomcontract_model_schema",
        "roomcontract_profile",
        "roomcontract_model_sha256",
        "roomcontract_model_path",
        "roomcontract_legacy_path",
        "roomcontract_trace_map_path",
        "roomcontract_legacy_trace_map_path",
        "roomcontract_trace_schema_version",
        *PLACEMENT_DEPLOYMENT_FIELDS,
    ):
        if field not in project_json:
            errors.append(f"project.json missing field: {field}")
    if project_json.get("generation_mode") != "roomcontract":
        errors.append("project.json generation_mode must be 'roomcontract'.")
    expected_v2_metadata = {
        "metamodelVersion": V2_MODEL_VERSION,
        "roomcontract_model_version": V2_MODEL_VERSION,
        "roomcontract_model_schema": V2_INSTANCE_SCHEMA,
        "roomcontract_profile": V2_PROFILE,
        "roomcontract_trace_schema_version": V2_TRACE_VERSION,
    }
    for field, expected in expected_v2_metadata.items():
        if project_json.get(field) != expected:
            errors.append(
                f"project.json {field} must be exactly {expected!r}; "
                f"found {project_json.get(field)!r}."
            )
    for field in (
        "roomcontract_trace_path",
        "roomcontract_case_dir",
        "source_rdl_path",
        "metamodelVersion",
        "roomcontract_model_version",
        "roomcontract_model_schema",
        "roomcontract_profile",
        "roomcontract_model_sha256",
        "roomcontract_model_path",
        "roomcontract_legacy_path",
        "roomcontract_trace_map_path",
        "roomcontract_legacy_trace_map_path",
        "roomcontract_trace_schema_version",
    ):
        if not str(project_json.get(field) or "").strip():
            errors.append(f"project.json field is empty: {field}")

    agents_payload = read_json(agents_path) if agents_path.exists() else {"agents": []}
    agents = agents_payload.get("agents") or []
    if not agents:
        errors.append("agents.json contains no agents.")

    trace_map = read_json(trace_map_path) if trace_map_path is not None and trace_map_path.exists() else {}
    trace_map_v2 = (
        read_json(trace_map_v2_path)
        if trace_map_v2_path is not None and trace_map_v2_path.exists()
        else {}
    )
    trace_map_v05 = (
        read_json(trace_map_v05_path)
        if trace_map_v05_path is not None and trace_map_v05_path.exists()
        else {}
    )

    expected_placement_metadata: Dict[str, str] = {}
    try:
        source_placements = read_json(case_dir / "intermediate" / "agent_placements.json")
        source_agent_roles = read_json(case_dir / "intermediate" / "agent_roles.generated.json")
        source_placement_by_id = _validate_and_index_agent_placements(
            source_agent_roles,
            source_placements,
        )
        source_projection_sha = placement_projection_sha256(
            list(source_placement_by_id.values())
        )
        deployed_projection_sha = placement_projection_sha256(agents)
        if deployed_projection_sha != source_projection_sha:
            errors.append(
                "agents.json id/position/forward projection does not match the source placement artifact."
            )
        expected_placement_metadata = {
            **_placement_artifact_deployment_metadata(source_placements),
            "placement_projection_sha256": deployed_projection_sha,
        }
    except Exception as exc:
        errors.append(f"Placement deployment provenance validation failed: {exc}")

    if expected_placement_metadata:
        declarations = {
            "project.json": project_json,
            "agents.json": agents_payload,
            "trace_map.json": trace_map,
            "trace_map.v2.json": trace_map_v2,
            "trace_map.v05.json": trace_map_v05,
        }
        for document_name, document in declarations.items():
            for field_name, expected in expected_placement_metadata.items():
                if document.get(field_name) != expected:
                    errors.append(
                        f"{document_name} {field_name} must be exactly {expected!r}; "
                        f"found {document.get(field_name)!r}."
                    )

    for field in (
        "schema",
        "schema_version",
        "model_version",
        "model_sha256",
        "profile",
        "case_id",
        "roomcontract_path",
        "roomcontract_v2_path",
        "use_case_id",
        "main_scenario_id",
        "use_case_ids",
        "main_scenario_ids",
        "scenario_steps",
        "step_relations",
        "parallel_groups",
        "guards",
        "runtime_actions",
        "assertions",
        "validation_cases",
        "runtime_validation_targets",
        "agents",
        *PLACEMENT_DEPLOYMENT_FIELDS,
    ):
        if field not in trace_map:
            errors.append(f"trace_map.json missing field: {field}")
    if trace_map.get("case_id") != case_dir.name:
        errors.append("trace_map.json case_id does not match project/case directory.")
    if not trace_map.get("scenario_steps"):
        errors.append("trace_map.json has no scenario_steps.")
    if not trace_map.get("runtime_actions"):
        errors.append("trace_map.json has no runtime_actions.")
    if not trace_map.get("validation_cases"):
        errors.append("trace_map.json has no validation_cases.")
    if trace_map.get("schema") != V2_TRACE_SCHEMA:
        errors.append(f"trace_map.json schema must be {V2_TRACE_SCHEMA!r}.")
    if str(trace_map.get("schema_version") or "") != V2_TRACE_VERSION:
        errors.append(f"trace_map.json schema_version must be {V2_TRACE_VERSION!r}.")
    if trace_map.get("model_version") != V2_MODEL_VERSION:
        errors.append(f"trace_map.json model_version must be {V2_MODEL_VERSION!r}.")
    if trace_map.get("profile") != V2_PROFILE:
        errors.append(f"trace_map.json profile must be {V2_PROFILE!r}.")
    action_kind_counts = {
        kind: len(
            [
                item
                for item in trace_map.get("runtime_actions") or []
                if isinstance(item, dict) and item.get("action_kind") == kind
            ]
        )
        for kind in ("setup", "chat", "handoff")
    }
    if action_kind_counts["setup"] != 1:
        errors.append(
            "trace_map.json requires exactly one 'setup' action; "
            f"found {action_kind_counts['setup']}."
        )
    for kind in ("chat", "handoff"):
        if action_kind_counts[kind] < 1:
            errors.append(
                f"trace_map.json requires at least one {kind!r} action; "
                f"found {action_kind_counts[kind]}."
            )
    for index, action in enumerate(trace_map.get("runtime_actions") or []):
        if not isinstance(action, dict):
            continue
        if not str(action.get("scenario_id") or ""):
            errors.append(
                f"trace_map.json runtime_actions[{index}] has no scenario_id."
            )
        if not str(action.get("use_case_id") or ""):
            errors.append(
                f"trace_map.json runtime_actions[{index}] has no use_case_id."
            )

    if roomcontract_v2_path is not None and roomcontract_v2_path.exists():
        v2_instance = read_json(roomcontract_v2_path)
        if v2_instance.get("schema") != V2_INSTANCE_SCHEMA:
            errors.append("roomcontract.v2.instance.json has the wrong schema discriminator.")
        if v2_instance.get("metamodelVersion") != V2_MODEL_VERSION:
            errors.append("roomcontract.v2.instance.json has the wrong metamodelVersion.")
        if v2_instance.get("profile") != V2_PROFILE or v2_instance.get("fixture_profile") != V2_PROFILE:
            errors.append("roomcontract.v2.instance.json must use the executable profile.")
        actual_hash = _sha256_file(roomcontract_v2_path)
        if actual_hash != str(project_json.get("roomcontract_model_sha256") or "").upper():
            errors.append("project.json RoomContract model hash does not match the V2 instance.")
        if actual_hash != str(trace_map.get("model_sha256") or "").upper():
            errors.append("trace_map.json RoomContract model hash does not match the V2 instance.")

        native_agent_by_source: Dict[str, Dict[str, Any]] = {}
        try:
            agent_roles = read_json(case_dir / "intermediate" / "agent_roles.generated.json")
            native_agent_by_source = _validate_v2_agent_provider_contract(
                roomcontract_instance=v2_instance,
                agent_roles=agent_roles,
            )
        except Exception as exc:
            errors.append(f"V2 agent/provider contract validation failed: {exc}")

        if native_agent_by_source:
            agents_by_source: Dict[str, Dict[str, Any]] = {}
            for index, agent in enumerate(agents):
                if not isinstance(agent, dict):
                    errors.append(f"agents[{index}] must be an object.")
                    continue
                source_id = str(agent.get("id") or "")
                if source_id in agents_by_source:
                    errors.append(f"agents.json contains duplicate source agent id {source_id!r}.")
                else:
                    agents_by_source[source_id] = agent
            if set(agents_by_source) != set(native_agent_by_source):
                errors.append(
                    "agents.json source agents must match the native Agent/Entity mapping exactly."
                )

            trace_agents_by_source: Dict[str, Dict[str, Any]] = {}
            for index, item in enumerate(trace_map.get("agents") or []):
                if not isinstance(item, dict):
                    errors.append(f"trace_map.json agents[{index}] must be an object.")
                    continue
                source_id = str(item.get("agent_id") or "")
                if source_id in trace_agents_by_source:
                    errors.append(
                        f"trace_map.json agents contains duplicate source agent id {source_id!r}."
                    )
                else:
                    trace_agents_by_source[source_id] = item
            if set(trace_agents_by_source) != set(native_agent_by_source):
                errors.append(
                    "trace_map.json agents must be a complete 1:1 projection of native Agents."
                )

            trace_field_mapping = {
                "roomcontract_agent_id": "id",
                "entity_id": "id",
                "plays_actor": "playsActor",
                "provided_capability_ids": "providedCapability",
                "responsible_zone_ids": "responsibleZone",
                "grounded_asset_ids": "groundedAsset",
                "grounded_object_group_ids": "groundedObjectGroup",
            }
            for source_id, native in native_agent_by_source.items():
                output_agent = agents_by_source.get(source_id)
                if output_agent is not None:
                    expected_agent_fields = {
                        "roomcontract_agent_ref": native.get("id"),
                        "roomcontract_entity_ref": native.get("id"),
                        "provided_capability_ids": native.get("providedCapability") or [],
                        "plays_actor_ids": native.get("playsActor") or [],
                    }
                    for field, expected in expected_agent_fields.items():
                        if output_agent.get(field) != expected:
                            errors.append(
                                f"agents.json agent {source_id!r} field {field} must exactly match "
                                "the native Agent/Entity projection."
                            )
                trace_agent = trace_agents_by_source.get(source_id)
                if trace_agent is not None:
                    for trace_field, native_field in trace_field_mapping.items():
                        expected = native.get(native_field)
                        if native_field == "id":
                            expected = native.get("id")
                        elif expected is None:
                            expected = []
                        if trace_agent.get(trace_field) != expected:
                            errors.append(
                                f"trace_map.json agent {source_id!r} field {trace_field} must "
                                "exactly match the native Agent/Entity projection."
                            )
    if roomcontract_v05_path is not None and roomcontract_v05_path.exists():
        v05_instance = read_json(roomcontract_v05_path)
        if v05_instance.get("schema") != "roomcontract_case_study":
            errors.append("roomcontract.v05.instance.json does not preserve the v0.5 schema.")
        if str(v05_instance.get("metamodelVersion") or "") != "v0.5":
            errors.append("roomcontract.v05.instance.json does not preserve metamodelVersion v0.5.")

    try:
        backend_root_text = str(Path(backend_root).resolve())
        if backend_root_text not in sys.path:
            sys.path.insert(0, backend_root_text)
        from backend.roomcontract_v2_runtime import load_project_contract  # type: ignore

        contract = load_project_contract(Path(project_paths["project_dir"]))
        if contract.get("kind") != "v2":
            errors.append("Backend did not load the materialized project as native V2.")
    except Exception as exc:
        errors.append(f"Backend V2 contract validation failed: {exc}")

    try:
        AgentSpec = _load_backend_agent_spec(backend_root)
        for index, agent in enumerate(agents):
            AgentSpec.from_dict(agent, index)
    except Exception as exc:
        errors.append(f"Backend AgentSpec could not load generated agents: {exc}")

    for index, agent in enumerate(agents):
        if str(agent.get("tts_model") or "").lower() == "standard":
            errors.append(f"agents[{index}].tts_model is still 'standard'.")
        for field in (
            "id",
            "display_name",
            "persona",
            "expertise",
            "knowledge_tags",
            "responsible_zone_ids",
            "grounded_object_ids",
            "handoff_targets",
            "preferred_zone_ids",
            "voice",
            "voice_gender",
            "voice_style",
            "tts_model",
            "roomcontract_agent_ref",
            "roomcontract_entity_ref",
        ):
            value = agent.get(field)
            if field in {"expertise", "knowledge_tags", "responsible_zone_ids", "grounded_object_ids", "handoff_targets", "preferred_zone_ids"}:
                if not isinstance(value, list):
                    errors.append(f"agents[{index}].{field} must be a list.")
            elif not str(value or "").strip():
                errors.append(f"agents[{index}].{field} is empty.")
        for field in ("provided_capability_ids", "plays_actor_ids"):
            if not isinstance(agent.get(field), list):
                errors.append(f"agents[{index}].{field} must be a list.")
        if not isinstance(agent.get("position"), dict):
            errors.append(f"agents[{index}] has no position object.")
        if not isinstance(agent.get("forward"), dict):
            errors.append(f"agents[{index}] has no forward object.")
        for tag in agent.get("knowledge_tags") or []:
            tag_dir = kb_root / str(tag)
            if not tag_dir.exists():
                errors.append(f"Missing KB folder for tag: {tag}")
            elif not list(tag_dir.glob("*.txt")):
                errors.append(f"KB folder for tag has no text files: {tag}")

    empty_kb_files = [str(path) for path in kb_root.rglob("*.txt") if not path.read_text(encoding="utf-8").strip()]
    if empty_kb_files:
        errors.append("Empty KB files: " + ", ".join(empty_kb_files[:5]))

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "agent_count": len(agents),
            "kb_file_count": len(list(kb_root.rglob("*.txt"))) if kb_root.exists() else 0,
            "trace_step_count": len(trace_map.get("scenario_steps") or []),
            "trace_runtime_action_count": len(trace_map.get("runtime_actions") or []),
            "trace_validation_case_count": len(trace_map.get("validation_cases") or []),
        },
    }


def run_project_materializer_for_case(case_dir: Path, *, backend_root: Path = DEFAULT_BACKEND_ROOT) -> Dict[str, Any]:
    case_dir = case_dir.resolve()
    backend_root = backend_root.resolve()
    source_rdl = case_dir / "input" / "source_rdl.json"
    agent_roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
    placements_path = case_dir / "intermediate" / "agent_placements.json"
    knowledge_path = case_dir / "intermediate" / "knowledge.generated.json"
    roomcontract_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    validation_path = case_dir / "validation" / "project_materialization_validation.json"

    project_paths = materialize_project(case_dir=case_dir, backend_root=backend_root)
    validation = validate_materialized_project(project_paths, case_dir=case_dir, backend_root=backend_root)
    write_json(validation_path, validation)
    status = "success" if validation["status"] == "valid" else "needs_manual_review"
    output_paths = [
        project_paths["project_json"],
        project_paths["room_plan"],
        project_paths["agents"],
        project_paths["trace_map"],
        project_paths["trace_map_v2"],
        project_paths["trace_map_v05"],
        project_paths["roomcontract_v2"],
        project_paths["roomcontract_v05"],
        validation_path,
        *list(project_paths["kb_root"].rglob("*.txt")),
    ]
    update_manifest(
        case_dir,
        stage_id="project_materialization",
        status=status,
        input_paths=[
            source_rdl,
            agent_roles_path,
            placements_path,
            knowledge_path,
            roomcontract_path,
            case_dir / "roomcontract" / V2_INSTANCE_FILENAME,
            Path(__file__).resolve(),
        ],
        output_paths=output_paths,
        errors=validation.get("errors"),
        warnings=validation.get("warnings"),
        metadata=validation.get("metrics"),
    )
    return {
        "case_id": case_dir.name,
        "status": status,
        "validation": validation,
        "project_dir": str(project_paths["project_dir"]),
        "validation_path": str(validation_path),
    }
