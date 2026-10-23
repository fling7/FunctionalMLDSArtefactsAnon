from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from ..common import read_json, update_manifest, write_json


@dataclass
class InvariantCheck:
    invariant_id: str
    description: str
    checked_count: int
    errors: List[str]

    def to_report(self) -> Dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "description": self.description,
            "status": "valid" if not self.errors else "invalid",
            "checked_count": self.checked_count,
            "error_count": len(self.errors),
            "errors": self.errors,
        }


def _use_cases(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        use_case
        for use_case in (instance.get("requirementsModel") or {}).get("useCases") or []
        if isinstance(use_case, dict)
    ]


def _scenarios(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    scenarios: List[Dict[str, Any]] = []
    for use_case in _use_cases(instance):
        for scenario in use_case.get("scenarios") or []:
            if isinstance(scenario, dict):
                scenario = dict(scenario)
                scenario["_owning_use_case_id"] = use_case.get("id")
                scenarios.append(scenario)
    return scenarios


def _steps(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for scenario in _scenarios(instance):
        for step in scenario.get("steps") or []:
            if isinstance(step, dict):
                step = dict(step)
                step["_owning_scenario_id"] = scenario.get("id")
                steps.append(step)
    return steps


def _id_set(items: Iterable[Dict[str, Any]]) -> Set[str]:
    return {str(item.get("id")) for item in items if isinstance(item.get("id"), str) and item.get("id")}


def _check_main_scenario(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    use_cases = _use_cases(instance)
    for use_case in use_cases:
        scenarios = [item for item in use_case.get("scenarios") or [] if isinstance(item, dict)]
        main_scenarios = [item for item in scenarios if item.get("kind") == "main"]
        if len(main_scenarios) != 1:
            errors.append(
                f"UseCase {use_case.get('id')} must have exactly one main Scenario, got {len(main_scenarios)}."
            )
    return InvariantCheck(
        "UC_MAIN_SCENARIO_EXACTLY_ONE",
        "Every UseCase owns exactly one Scenario with kind=main.",
        len(use_cases),
        errors,
    )


def _check_scenario_has_step(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    scenarios = _scenarios(instance)
    for scenario in scenarios:
        steps = [item for item in scenario.get("steps") or [] if isinstance(item, dict)]
        if not steps:
            errors.append(f"Scenario {scenario.get('id')} has no ScenarioStep.")
    return InvariantCheck(
        "SCENARIO_HAS_STEP",
        "Every Scenario contains at least one ScenarioStep.",
        len(scenarios),
        errors,
    )


def _check_step_no_runtime_action(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    forbidden_fields = {
        "runtimeActionId",
        "runtimeActionIds",
        "runtime_action_id",
        "runtime_action_ids",
        "runtimeAction",
        "runtimeActions",
        "runtime_action",
        "runtime_actions",
    }
    steps = _steps(instance)
    for step in steps:
        present = sorted(field for field in forbidden_fields if field in step)
        if present:
            errors.append(f"ScenarioStep {step.get('id')} directly references RuntimeAction via {present}.")
    return InvariantCheck(
        "SCENARIO_STEP_NO_DIRECT_RUNTIME_ACTION",
        "ScenarioStep instances do not directly reference RuntimeAction instances.",
        len(steps),
        errors,
    )


def _check_capability_use(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    capabilities = _id_set(instance.get("capabilities") or [])
    capability_uses = [item for item in instance.get("capabilityUses") or [] if isinstance(item, dict)]
    for capability_use in capability_uses:
        capability_id = capability_use.get("capability_id")
        if not isinstance(capability_id, str) or not capability_id:
            errors.append(f"CapabilityUse {capability_use.get('id')} has no capability_id.")
        elif capability_id not in capabilities:
            errors.append(f"CapabilityUse {capability_use.get('id')} references unknown Capability {capability_id}.")
        for forbidden in ("capability_ids", "capabilityIds", "capabilities"):
            if forbidden in capability_use:
                errors.append(f"CapabilityUse {capability_use.get('id')} violates exactly-one rule via {forbidden}.")
    return InvariantCheck(
        "CAPABILITY_USE_REFERENCES_EXACTLY_ONE_CAPABILITY",
        "Every CapabilityUse references exactly one existing Capability.",
        len(capability_uses),
        errors,
    )


def _check_capability_effect(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    capabilities = [item for item in instance.get("capabilities") or [] if isinstance(item, dict)]
    for capability in capabilities:
        effects = [item for item in capability.get("effects") or [] if isinstance(item, dict)]
        if not effects:
            errors.append(f"Capability {capability.get('id')} has no Effect.")
    return InvariantCheck(
        "CAPABILITY_HAS_EFFECT",
        "Every Capability owns at least one Effect.",
        len(capabilities),
        errors,
    )


def _check_runtime_binding_action(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    runtime_bindings = [item for item in instance.get("runtimeBindings") or [] if isinstance(item, dict)]
    for runtime_binding in runtime_bindings:
        actions = [item for item in runtime_binding.get("runtimeActions") or [] if isinstance(item, dict)]
        if not actions:
            errors.append(f"RuntimeBinding {runtime_binding.get('id')} has no RuntimeAction.")
    return InvariantCheck(
        "RUNTIME_BINDING_HAS_RUNTIME_ACTION",
        "Every RuntimeBinding owns at least one RuntimeAction.",
        len(runtime_bindings),
        errors,
    )


def _check_handoff_runtime_binding(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    capabilities = {
        str(item.get("id")): item
        for item in instance.get("capabilities") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    runtime_bindings = [
        item
        for item in instance.get("runtimeBindings") or []
        if isinstance(item, dict)
    ]
    answer_capability_ids = [
        capability_id
        for capability_id in capabilities
        if capability_id.endswith("-ANSWER-ROOM-GROUNDED-QUESTION")
    ]
    handoff_capability_ids = [
        capability_id
        for capability_id in capabilities
        if capability_id.endswith("-HANDOFF-TO-RESPONSIBLE-AGENT")
    ]
    if not answer_capability_ids:
        errors.append("Missing Capability ANSWER-ROOM-GROUNDED-QUESTION.")
    if not handoff_capability_ids:
        errors.append("Missing Capability HANDOFF-TO-RESPONSIBLE-AGENT.")
    handoff_bindings = [
        binding
        for binding in runtime_bindings
        if str(binding.get("capability_id") or "") in handoff_capability_ids
    ]
    if not handoff_bindings:
        errors.append("HANDOFF-TO-RESPONSIBLE-AGENT has no RuntimeBinding.")
    handoff_actions = [
        action
        for binding in handoff_bindings
        for action in binding.get("runtimeActions") or []
        if isinstance(action, dict) and str(action.get("id") or "").endswith("-BACKEND-CHAT-HANDOFF")
    ]
    if not handoff_actions:
        errors.append("Handoff RuntimeBinding has no BACKEND-CHAT-HANDOFF RuntimeAction.")
    for action in handoff_actions:
        if action.get("endpoint") != "POST /chat":
            errors.append(f"RuntimeAction {action.get('id')} must use endpoint POST /chat.")
    return InvariantCheck(
        "HANDOFF_CAPABILITY_HAS_CHAT_RUNTIME_BINDING",
        "Room-answer and handoff Capabilities exist, and handoff is bound to BACKEND-CHAT-HANDOFF on POST /chat.",
        len(answer_capability_ids) + len(handoff_capability_ids) + len(handoff_bindings) + len(handoff_actions),
        errors,
    )


def _check_validation_case_testable(instance: Dict[str, Any]) -> InvariantCheck:
    errors: List[str] = []
    state_assertions = _id_set(instance.get("stateAssertions") or [])
    runtime_bindings = _id_set(instance.get("runtimeBindings") or [])
    validation_cases = [item for item in instance.get("validationCases") or [] if isinstance(item, dict)]
    for validation_case in validation_cases:
        expected = [str(item) for item in validation_case.get("expectedOutcome") or [] if item]
        bindings = [str(item) for item in validation_case.get("runtime_binding_ids") or [] if item]
        known_expected = [item for item in expected if item in state_assertions]
        known_bindings = [item for item in bindings if item in runtime_bindings]

        for state_id in expected:
            if state_id not in state_assertions:
                errors.append(
                    f"ValidationCase {validation_case.get('id')} references unknown StateAssertion {state_id}."
                )
        for binding_id in bindings:
            if binding_id not in runtime_bindings:
                errors.append(
                    f"ValidationCase {validation_case.get('id')} references unknown RuntimeBinding {binding_id}."
                )
        if not known_expected and not known_bindings:
            errors.append(
                f"ValidationCase {validation_case.get('id')} references no testable StateAssertion or RuntimeBinding."
            )
    return InvariantCheck(
        "VALIDATION_CASE_REFERENCES_TESTABLE_ELEMENT",
        "Every ValidationCase references at least one existing StateAssertion or RuntimeBinding.",
        len(validation_cases),
        errors,
    )


def validate_roomcontract_invariants(instance: Dict[str, Any]) -> Dict[str, Any]:
    checks = [
        _check_main_scenario(instance),
        _check_scenario_has_step(instance),
        _check_step_no_runtime_action(instance),
        _check_capability_use(instance),
        _check_capability_effect(instance),
        _check_runtime_binding_action(instance),
        _check_handoff_runtime_binding(instance),
        _check_validation_case_testable(instance),
    ]
    reports = [check.to_report() for check in checks]
    errors = [error for report in reports for error in report["errors"]]
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": [],
        "metrics": {
            "invariant_count": len(reports),
            "passed_invariant_count": sum(1 for report in reports if report["status"] == "valid"),
            "failed_invariant_count": sum(1 for report in reports if report["status"] != "valid"),
            "checked_element_count": sum(int(report["checked_count"]) for report in reports),
            "error_count": len(errors),
        },
        "invariants": reports,
    }


def run_roomcontract_invariant_validation_for_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    instance_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
    validation_path = case_dir / "validation" / "roomcontract_invariants_validation.json"
    instance = read_json(instance_path)
    validation = validate_roomcontract_invariants(instance)
    write_json(validation_path, validation)
    update_manifest(
        case_dir,
        stage_id="roomcontract_invariants",
        status="success" if validation["status"] == "valid" else "failed",
        input_paths=[instance_path],
        output_paths=[validation_path],
        errors=validation["errors"],
        warnings=validation["warnings"],
        metadata=validation["metrics"],
    )
    return {
        "case_id": case_dir.name,
        "status": "success" if validation["status"] == "valid" else "failed",
        "validation": validation,
        "validation_path": str(validation_path),
    }


def run_roomcontract_invariant_validation_for_cases(case_dirs: Iterable[Path]) -> List[Dict[str, Any]]:
    return [run_roomcontract_invariant_validation_for_case(case_dir) for case_dir in case_dirs]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate explicit RoomContract metamodel invariants.")
    parser.add_argument("--case-dir", type=Path, action="append")
    parser.add_argument("--case-root", type=Path)
    args = parser.parse_args(argv)
    case_dirs = args.case_dir or []
    if args.case_root:
        case_dirs.extend(sorted(path for path in args.case_root.iterdir() if path.is_dir()))
    if not case_dirs:
        parser.error("Pass --case-dir or --case-root.")
    results = run_roomcontract_invariant_validation_for_cases(case_dirs)
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
