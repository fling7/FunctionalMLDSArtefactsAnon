from __future__ import annotations

"""Canonical, machine-readable Dynamic Functional RDL V2 metamodel.

The imported EAST-ADL elements below are a deliberately selected, unmodified
slice of EAST-ADL V2.1.12.  All project-specific semantics live in packages
below ``RCM::V2``.  This module contains data only; the companion generator
creates every human-readable and graphical artifact from ``MODEL``.
"""

from typing import Any


def attribute(
    name: str,
    type_: str,
    multiplicity: str = "1",
    *,
    derived: bool = False,
    ordered: bool = False,
    default: Any | None = None,
    description: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "type": type_,
        "multiplicity": multiplicity,
    }
    if derived:
        result["derived"] = True
    if ordered:
        result["ordered"] = True
    if default is not None:
        result["default"] = default
    if description:
        result["description"] = description
    return result


def metaclass(
    name: str,
    package: str,
    *,
    abstract: bool = False,
    bases: tuple[str, ...] = (),
    attributes: tuple[dict[str, Any], ...] = (),
    description: str,
    source: str | None = None,
    stereotypes: tuple[str, ...] = (),
    optional: bool = False,
) -> tuple[str, dict[str, Any]]:
    qualified_name = f"{package}::{name}"
    result: dict[str, Any] = {
        "name": name,
        "package": package,
        "abstract": abstract,
        "bases": list(bases),
        "attributes": list(attributes),
        "description": description,
    }
    if source:
        result["east_adl_source"] = source
    if stereotypes:
        result["stereotypes"] = list(stereotypes)
    if optional:
        result["optional"] = True
    return qualified_name, result


def association(
    id_: str,
    package: str,
    source: str,
    target: str,
    source_role: str,
    target_role: str,
    source_multiplicity: str,
    target_multiplicity: str,
    *,
    composition: bool = False,
    owner: str | None = None,
    ordered: bool = False,
    stereotype: str | None = None,
    description: str,
    optional: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": id_,
        "package": package,
        "source": source,
        "target": target,
        "source_role": source_role,
        "target_role": target_role,
        "source_multiplicity": source_multiplicity,
        "target_multiplicity": target_multiplicity,
        "composition": composition,
        "owner": owner,
        "ordered": ordered,
        "description": description,
    }
    if stereotype:
        result["stereotype"] = stereotype
    if optional:
        result["optional"] = True
    return result


def invariant(
    id_: str,
    scope: str,
    expression: str,
    text: str,
    *,
    severity: str = "error",
    profile: str = "core",
) -> dict[str, str]:
    return {
        "id": id_,
        "scope": scope,
        "severity": severity,
        "profile": profile,
        "expression": expression,
        "text": text,
    }


P_ELEMENTS = "EAST-ADL::Elements"
P_DATATYPES = "EAST-ADL::Datatypes"
P_VALUES = "EAST-ADL::Values"
P_REQUIREMENTS = "EAST-ADL::Requirements"
P_USECASES = "EAST-ADL::UseCases"
P_SYSTEM = "EAST-ADL::SystemModeling"
P_FUNCTION = "EAST-ADL::FunctionModeling"
P_BEHAVIOR = "EAST-ADL::Behavior"
P_TIMING = "EAST-ADL::Timing"
P_EVENTS = "EAST-ADL::Events"
P_VV = "EAST-ADL::VerificationValidation"
P_ANNEX_BEHAVIOR = "EAST-ADL::AnnexC::BehaviorDescription"
P_ANNEX_VALUE = "EAST-ADL::AnnexC::AttributeQuantificationConstraint"
P_ANNEX_COMPUTATION = "EAST-ADL::AnnexC::ComputationConstraint"
P_ANNEX_TEMPORAL = "EAST-ADL::AnnexC::TemporalConstraint"
P_FEATURE = "EAST-ADL::FeatureModeling"
P_VEHICLE_FEATURE = "EAST-ADL::VehicleFeatureModeling"
P_CORE = "RCM::V2::Core"
P_ANNEX_BRIDGE = "RCM::V2::AnnexCBridge"
P_FEATURE_BRIDGE = "RCM::V2::FeatureBridge"
P_KNOWLEDGE = "RCM::V2::AgentKnowledge"


PACKAGES: dict[str, dict[str, Any]] = {
    P_ELEMENTS: {
        "name": "Elements",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [],
        "description": "Selected exact EAST-ADL V2.1.12 infrastructure slice (section 25).",
    },
    P_DATATYPES: {
        "name": "Datatypes",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS],
        "description": "Selected exact EAST-ADL datatype slice (section 23).",
    },
    P_VALUES: {
        "name": "Values",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_DATATYPES],
        "description": "Selected exact EAST-ADL value slice (section 24).",
    },
    P_REQUIREMENTS: {
        "name": "Requirements",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS, P_USECASES, P_BEHAVIOR],
        "description": "Selected exact EAST-ADL requirements slice (section 11).",
    },
    P_USECASES: {
        "name": "UseCases",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS],
        "description": "Exact EAST-ADL Actor, UseCase, Extend, Include and ExtensionPoint slice (section 12).",
    },
    P_SYSTEM: {
        "name": "SystemModeling",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS, P_FUNCTION],
        "description": "Selected exact EAST-ADL abstraction-level slice (section 3).",
    },
    P_FUNCTION: {
        "name": "FunctionModeling",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS, P_DATATYPES, P_VALUES],
        "description": "Selected exact EAST-ADL function type/prototype slice (section 6).",
    },
    P_BEHAVIOR: {
        "name": "Behavior",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS, P_FUNCTION, P_VALUES],
        "description": "Selected exact EAST-ADL FunctionBehavior slice (section 9).",
    },
    P_TIMING: {
        "name": "Timing",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS],
        "description": "Selected exact EAST-ADL timing event slice (section 14).",
    },
    P_EVENTS: {
        "name": "Events",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_TIMING],
        "description": "Selected exact EAST-ADL ExternalEvent slice (section 16).",
    },
    P_VV: {
        "name": "VerificationValidation",
        "kind": "imported-east-adl",
        "normative": True,
        "imports": [P_ELEMENTS, P_REQUIREMENTS],
        "description": "Exact EAST-ADL V&V container and element slice (section 13).",
    },
    P_CORE: {
        "name": "Core",
        "kind": "rcm-extension",
        "normative": True,
        "imports": [
            P_ELEMENTS,
            P_DATATYPES,
            P_VALUES,
            P_REQUIREMENTS,
            P_USECASES,
            P_SYSTEM,
            P_FUNCTION,
            P_BEHAVIOR,
            P_TIMING,
            P_EVENTS,
            P_VV,
        ],
        "description": "Conservative RCM V2 extension; imported EAST-ADL packages never import it.",
    },
    P_ANNEX_BEHAVIOR: {
        "name": "BehaviorDescription",
        "kind": "imported-east-adl-annex-c",
        "normative": False,
        "preliminary": True,
        "imports": [P_ELEMENTS, P_FUNCTION, P_BEHAVIOR, P_VEHICLE_FEATURE],
        "description": "Preliminary Annex C behavior-description slice.",
    },
    P_ANNEX_VALUE: {
        "name": "AttributeQuantificationConstraint",
        "kind": "imported-east-adl-annex-c",
        "normative": False,
        "preliminary": True,
        "imports": [P_ELEMENTS, P_VALUES],
        "description": "Preliminary Annex C quantification slice.",
    },
    P_ANNEX_COMPUTATION: {
        "name": "ComputationConstraint",
        "kind": "imported-east-adl-annex-c",
        "normative": False,
        "preliminary": True,
        "imports": [P_ELEMENTS, P_ANNEX_VALUE],
        "description": "Preliminary Annex C logical-computation slice.",
    },
    P_ANNEX_TEMPORAL: {
        "name": "TemporalConstraint",
        "kind": "imported-east-adl-annex-c",
        "normative": False,
        "preliminary": True,
        "imports": [P_ELEMENTS, P_VALUES, P_TIMING, P_ANNEX_BEHAVIOR, P_ANNEX_VALUE],
        "description": "Preliminary Annex C temporal-constraint slice; TransitionEvent is not Timing::Event.",
    },
    P_ANNEX_BRIDGE: {
        "name": "AnnexCBridge",
        "kind": "optional-rcm-extension",
        "normative": False,
        "preliminary": True,
        "imports": [P_ELEMENTS, P_CORE, P_ANNEX_COMPUTATION, P_ANNEX_TEMPORAL, P_ANNEX_VALUE, P_ANNEX_BEHAVIOR],
        "description": "Optional semantic mapping onto preliminary Annex C; Core has no dependency on it.",
    },
    P_FEATURE: {
        "name": "FeatureModeling",
        "kind": "imported-east-adl-optional",
        "normative": True,
        "imports": [P_ELEMENTS],
        "description": "Minimal target slice for optional generic feature mapping.",
    },
    P_VEHICLE_FEATURE: {
        "name": "VehicleFeatureModeling",
        "kind": "imported-east-adl-optional",
        "normative": True,
        "imports": [P_FEATURE],
        "description": "Automotive-only VehicleFeature target slice.",
    },
    P_FEATURE_BRIDGE: {
        "name": "FeatureBridge",
        "kind": "optional-rcm-extension",
        "normative": False,
        "imports": [P_ELEMENTS, P_CORE, P_FEATURE, P_VEHICLE_FEATURE],
        "description": "Optional feature mapping; no VehicleFeature dependency in Core.",
    },
    P_KNOWLEDGE: {
        "name": "AgentKnowledge",
        "kind": "optional-rcm-extension",
        "normative": False,
        "imports": [P_ELEMENTS, P_CORE],
        "description": "Optional perception, provenance, knowledge and modification-rights module.",
    },
}


PRIMITIVES: dict[str, dict[str, str]] = {
    "Boolean": {"description": "Boolean primitive."},
    "Identifier": {"description": "EAST-ADL identifier primitive."},
    "Integer": {"description": "Integer primitive."},
    "Numerical": {"description": "EAST-ADL numerical literal primitive."},
    "Real": {"description": "Real-number primitive."},
    "String": {"description": "String primitive."},
}


ENUMS: dict[str, dict[str, Any]] = {
    f"{P_BEHAVIOR}::FunctionBehaviorKind": {
        "name": "FunctionBehaviorKind",
        "package": P_BEHAVIOR,
        "literals": ["ASCET", "MARTE", "OTHER", "SCADE", "SCILAB", "SDL", "SIMULINK", "STATEMATE", "UML"],
        "east_adl_source": "9.2.3, pp. 70-71",
    },
    f"{P_BEHAVIOR}::TriggerPolicyKind": {
        "name": "TriggerPolicyKind",
        "package": P_BEHAVIOR,
        "literals": ["EVENT", "TIME"],
        "east_adl_source": "9.2.7, p. 73",
    },
    f"{P_FUNCTION}::EADirectionKind": {
        "name": "EADirectionKind",
        "package": P_FUNCTION,
        "literals": ["in", "inout", "out"],
        "east_adl_source": "6.2.9, p. 45",
    },
    f"{P_CORE}::ScenarioKind": {
        "name": "ScenarioKind",
        "package": P_CORE,
        "literals": ["main", "alternative", "exception"],
    },
    f"{P_CORE}::ScenarioStepKind": {
        "name": "ScenarioStepKind",
        "package": P_CORE,
        "literals": ["actorIntent", "systemResponse", "environmentObservation"],
    },
    f"{P_CORE}::StepRelationKind": {
        "name": "StepRelationKind",
        "package": P_CORE,
        "literals": ["sequence", "alternative", "exception", "fork", "join", "loop"],
    },
    f"{P_CORE}::ConditionKind": {
        "name": "ConditionKind",
        "package": P_CORE,
        "literals": ["guard", "precondition", "postcondition", "spatial", "timing"],
    },
    f"{P_CORE}::ScenarioEventKind": {
        "name": "ScenarioEventKind",
        "package": P_CORE,
        "literals": ["temporal", "spatial", "signal", "user", "environment"],
    },
    f"{P_CORE}::AssertionSeverity": {
        "name": "AssertionSeverity",
        "package": P_CORE,
        "literals": ["info", "warning", "error", "critical"],
    },
    f"{P_CORE}::AssertionVerdict": {
        "name": "AssertionVerdict",
        "package": P_CORE,
        "literals": ["pass", "fail", "inconclusive", "error"],
    },
    f"{P_CORE}::EntityKind": {
        "name": "EntityKind",
        "package": P_CORE,
        "literals": ["agent", "asset", "zone", "signal", "stateObject"],
    },
    f"{P_CORE}::RuntimeLocatorKind": {
        "name": "RuntimeLocatorKind",
        "package": P_CORE,
        "literals": ["endpoint", "tool", "topic"],
    },
    f"{P_CORE}::RuntimeParameterDirection": {
        "name": "RuntimeParameterDirection",
        "package": P_CORE,
        "literals": ["input", "output", "inout"],
    },
    f"{P_CORE}::DistributionKind": {
        "name": "DistributionKind",
        "package": P_CORE,
        "literals": ["constant", "uniform", "normal", "bernoulli", "custom"],
    },
    f"{P_KNOWLEDGE}::KnowledgePermission": {
        "name": "KnowledgePermission",
        "package": P_KNOWLEDGE,
        "literals": ["perceive", "know", "explain", "modify"],
    },
    f"{P_KNOWLEDGE}::KnowledgeProvenanceKind": {
        "name": "KnowledgeProvenanceKind",
        "package": P_KNOWLEDGE,
        "literals": ["authored", "observed", "imported", "inferred"],
    },
}


CLASSES: dict[str, dict[str, Any]] = dict(
    [
        # EAST-ADL infrastructure (exact selected slice)
        metaclass("Comment", P_ELEMENTS, attributes=(attribute("body", "String"),), description="Textual annotation.", source="25.2.1, pp. 188-189"),
        metaclass("Referrable", P_ELEMENTS, abstract=True, attributes=(attribute("shortName", "Identifier"),), description="Element referable by a context-unique shortName.", source="25.2.14, p. 194"),
        metaclass("Identifiable", P_ELEMENTS, abstract=True, bases=(f"{P_ELEMENTS}::Referrable",), attributes=(attribute("category", "Identifier", "0..1"), attribute("uuid", "String", "0..1")), description="Referrable element with optional category and UUID.", source="25.2.11, pp. 192-193"),
        metaclass("EAElement", P_ELEMENTS, abstract=True, bases=(f"{P_ELEMENTS}::Identifiable",), attributes=(attribute("name", "String", "0..1"),), description="Arbitrary named EAST-ADL domain-model entity.", source="25.2.4, pp. 189-190"),
        metaclass("EAPackageableElement", P_ELEMENTS, abstract=True, bases=(f"{P_ELEMENTS}::EAElement",), description="Element that may be directly contained in an EAPackage.", source="25.2.6, pp. 190-191"),
        metaclass("Context", P_ELEMENTS, abstract=True, bases=(f"{P_ELEMENTS}::EAPackageableElement",), description="Owns relationships and identifies traceable specifications in a model context.", source="25.2.2, p. 189"),
        metaclass("Relationship", P_ELEMENTS, abstract=True, bases=(f"{P_ELEMENTS}::EAElement",), description="Relationship between arbitrary elements.", source="25.2.15, pp. 194-195"),
        metaclass("TraceableSpecification", P_ELEMENTS, abstract=True, bases=(f"{P_ELEMENTS}::EAPackageableElement",), attributes=(attribute("text", "String", "0..1"),), description="Specification allocatable to a Context; text is its only local attribute.", source="25.2.16, p. 195"),
        metaclass("EAType", P_ELEMENTS, abstract=True, description="Abstract type-pattern marker; it has no generalization.", source="25.2.9, p. 191"),
        metaclass("EAPrototype", P_ELEMENTS, abstract=True, description="Abstract prototype-pattern marker; it has no generalization.", source="25.2.8, p. 191"),
        metaclass("EAPort", P_ELEMENTS, abstract=True, description="Abstract port marker; it has no generalization.", source="25.2.7, p. 191"),
        metaclass("EAConnector", P_ELEMENTS, abstract=True, description="Abstract connector marker; it has no generalization.", source="25.2.3, p. 189"),

        # EAST-ADL datatypes and values
        metaclass("EADatatype", P_DATATYPES, abstract=True, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Type whose instances are identified only by value.", source="23.2.4, p. 178", stereotypes=("atpType",)),
        metaclass("EADatatypePrototype", P_DATATYPES, bases=(f"{P_ELEMENTS}::EAElement",), description="Typed variable acting as an appearance of an EADatatype.", source="23.2.5, p. 178", stereotypes=("atpPrototype",)),
        metaclass("EABoolean", P_DATATYPES, bases=(f"{P_DATATYPES}::EADatatype",), description="Boolean datatype with true and false values.", source="23.2.3, p. 177"),
        metaclass("EANumerical", P_DATATYPES, bases=(f"{P_DATATYPES}::EADatatype",), attributes=(attribute("max", "Numerical", "0..1"), attribute("min", "Numerical", "0..1")), description="Numerical datatype with optional range bounds.", source="23.2.6, pp. 178-179"),
        metaclass("EAValue", P_VALUES, abstract=True, description="Abstract non-identifiable typed value.", source="24.2.8, p. 186", stereotypes=("atpPrototype",)),
        metaclass("EAExpression", P_VALUES, bases=(f"{P_VALUES}::EAValue",), description="Mixed-string expression capable of model references.", source="24.2.5, p. 185", stereotypes=("atpMixedString",)),
        metaclass("EANumericalValue", P_VALUES, bases=(f"{P_VALUES}::EAValue",), attributes=(attribute("value", "Numerical"),), description="Numerical value typed by EANumerical or RangeableValueType.", source="24.2.6, p. 185"),

        # EAST-ADL requirements and use cases
        metaclass("RequirementsRelationship", P_REQUIREMENTS, abstract=True, bases=(f"{P_ELEMENTS}::Relationship",), description="Abstract base for requirement relationships.", source="11.2.10, p. 97"),
        metaclass("Requirement", P_REQUIREMENTS, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("formalism", "String", "0..1"), attribute("url", "String", "0..1")), description="Capability or condition to be satisfied; text is inherited and optional.", source="11.2.6, pp. 94-95"),
        metaclass("RequirementsModel", P_REQUIREMENTS, bases=(f"{P_ELEMENTS}::Context",), description="Container for requirements, their relationships and use cases.", source="11.2.9, p. 97"),
        metaclass("Refine", P_REQUIREMENTS, bases=(f"{P_REQUIREMENTS}::RequirementsRelationship",), description="Exact requirement-to-EAElement refinement relationship.", source="11.2.5, p. 94"),
        metaclass("Satisfy", P_REQUIREMENTS, bases=(f"{P_REQUIREMENTS}::RequirementsRelationship",), description="Relates Requirement or UseCase suppliers to satisfying Identifiables.", source="11.2.12, pp. 98-99"),
        metaclass("Actor", P_USECASES, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="External role interacting with a UseCase, not a concrete physical entity.", source="12.2.1, p. 101"),
        metaclass("RedefinableElement", P_USECASES, abstract=True, bases=(f"{P_ELEMENTS}::EAElement",), description="Named element that can be redefined in a specializing context.", source="12.2.5, pp. 102-103"),
        metaclass("ExtensionPoint", P_USECASES, bases=(f"{P_USECASES}::RedefinableElement",), description="Point where a UseCase can be augmented; name is inherited and optional.", source="12.2.3, p. 102"),
        metaclass("Include", P_USECASES, bases=(f"{P_ELEMENTS}::Relationship",), description="Mandatory insertion of an addition UseCase.", source="12.2.4, p. 102"),
        metaclass("Extend", P_USECASES, bases=(f"{P_ELEMENTS}::Relationship",), description="Extends a UseCase at one or more ExtensionPoints; EAST-ADL defines no condition property.", source="12.2.2, pp. 101-102"),
        metaclass("UseCase", P_USECASES, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Usage of a system; text is inherited and optional.", source="12.2.6, p. 103"),

        # EAST-ADL function/system/behavior
        metaclass("AllocateableElement", P_FUNCTION, abstract=True, description="Abstract marker for allocateable elements.", source="6.2.1, p. 41"),
        metaclass("FunctionPort", P_FUNCTION, abstract=True, bases=(f"{P_ELEMENTS}::EAPort", f"{P_ELEMENTS}::EAElement"), description="Abstract function interaction port.", source="6.2.16, pp. 49-50", stereotypes=("atpPrototype",)),
        metaclass("FunctionFlowPort", P_FUNCTION, bases=(f"{P_FUNCTION}::FunctionPort",), attributes=(attribute("direction", f"{P_FUNCTION}::EADirectionKind"),), description="Single-buffer flow port typed by an EADatatype.", source="6.2.15, pp. 48-49"),
        metaclass("FunctionConnector", P_FUNCTION, bases=(f"{P_FUNCTION}::AllocateableElement", f"{P_ELEMENTS}::EAConnector", f"{P_ELEMENTS}::EAElement"), description="Connector between exactly two FunctionPorts through an instance reference.", source="6.2.14, pp. 47-48", stereotypes=("atpStructureElement",)),
        metaclass("PortGroup", P_FUNCTION, bases=(f"{P_ELEMENTS}::EAElement",), description="Graphical grouping of FunctionPorts without added behavior semantics.", source="6.2.23, p. 54"),
        metaclass("FunctionPrototype", P_FUNCTION, abstract=True, bases=(f"{P_ELEMENTS}::EAElement", f"{P_ELEMENTS}::EAPrototype"), description="Occurrence of a FunctionType when acting as a part.", source="6.2.18, pp. 50-51", stereotypes=("atpPrototype",)),
        metaclass("FunctionType", P_FUNCTION, abstract=True, bases=(f"{P_ELEMENTS}::EAType", f"{P_ELEMENTS}::Context"), attributes=(attribute("isElementary", "Boolean"),), description="Abstract function component type owning ports, connectors and port groups.", source="6.2.19, p. 51", stereotypes=("atpType",)),
        metaclass("AnalysisFunctionPrototype", P_FUNCTION, bases=(f"{P_FUNCTION}::FunctionPrototype",), description="Prototype typed by AnalysisFunctionType.", source="6.2.3, p. 42"),
        metaclass("AnalysisFunctionType", P_FUNCTION, bases=(f"{P_FUNCTION}::FunctionType",), description="Function type used at AnalysisLevel; owns analysis parts.", source="6.2.4, pp. 42-43"),
        metaclass("DesignFunctionPrototype", P_FUNCTION, bases=(f"{P_FUNCTION}::AllocateableElement", f"{P_FUNCTION}::FunctionPrototype"), description="Allocateable prototype typed by DesignFunctionType.", source="6.2.7, p. 44"),
        metaclass("DesignFunctionType", P_FUNCTION, bases=(f"{P_FUNCTION}::FunctionType",), description="Function type used at DesignLevel; owns design parts.", source="6.2.8, pp. 44-45"),
        metaclass("AnalysisLevel", P_SYSTEM, bases=(f"{P_ELEMENTS}::Context",), description="Analysis abstraction level containing an optional FAA root prototype.", source="3.2.1, pp. 20-21", stereotypes=("atpStructureElement",)),
        metaclass("DesignLevel", P_SYSTEM, bases=(f"{P_ELEMENTS}::Context",), description="Design abstraction level containing an optional FDA root prototype.", source="3.2.2, pp. 21-22", stereotypes=("atpStructureElement",)),
        metaclass("Mode", P_BEHAVIOR, bases=(f"{P_ELEMENTS}::EAElement",), attributes=(attribute("condition", "String"),), description="Execution mode with its mandatory activation condition.", source="9.2.5, p. 72"),
        metaclass("FunctionBehavior", P_BEHAVIOR, bases=(f"{P_ELEMENTS}::Context",), attributes=(attribute("path", "String"), attribute("representation", f"{P_BEHAVIOR}::FunctionBehaviorKind")), description="Synchronous run-to-completion behavior assigned to at most one FunctionType.", source="9.2.2, pp. 69-70"),
        metaclass("FunctionTrigger", P_BEHAVIOR, bases=(f"{P_VALUES}::EAExpression", f"{P_ELEMENTS}::EAElement"), attributes=(attribute("triggerPolicy", f"{P_BEHAVIOR}::TriggerPolicyKind"),), description="Event- or time-driven trigger for a FunctionType or FunctionPrototype.", source="9.2.4, pp. 71-72"),

        # EAST-ADL timing and events
        metaclass("TimingDescription", P_TIMING, abstract=True, bases=(f"{P_ELEMENTS}::EAElement",), description="Abstract timing description.", source="14.2.6, p. 116"),
        metaclass("Event", P_TIMING, abstract=True, bases=(f"{P_TIMING}::TimingDescription",), description="Identifiable form of state change with semantic occurrences.", source="14.2.1, pp. 113-114"),
        metaclass("ExternalEvent", P_EVENTS, bases=(f"{P_TIMING}::Event",), description="Particular externally described form of state change.", source="16.2.8, p. 139"),

        # EAST-ADL Verification & Validation
        metaclass("VerificationValidation", P_VV, bases=(f"{P_ELEMENTS}::Context",), description="Container for related VVTargets, VVCases and Verify relationships.", source="13.2.1, p. 106"),
        metaclass("Verify", P_VV, bases=(f"{P_REQUIREMENTS}::RequirementsRelationship",), description="Relates Requirements to verifying VVCases and optional VVProcedures.", source="13.2.2, pp. 106-107"),
        metaclass("VVActualOutcome", P_VV, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Actual output captured by a VVLog.", source="13.2.3, p. 107"),
        metaclass("VVCase", P_VV, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Groups VVProcedures and identifies subjects and concrete test targets.", source="13.2.4, pp. 107-108"),
        metaclass("VVIntendedOutcome", P_VV, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Expected output of a concrete VVProcedure.", source="13.2.5, p. 108"),
        metaclass("VVLog", P_VV, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("date", "String"),), description="Execution log of a concrete VVCase; owns the actual outcomes.", source="13.2.6, pp. 108-109"),
        metaclass("VVProcedure", P_VV, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Individual abstract or concrete task in a V&V effort.", source="13.2.7, pp. 109-110"),
        metaclass("VVStimuli", P_VV, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Concrete input values used by a VVProcedure.", source="13.2.8, p. 110"),
        metaclass("VVTarget", P_VV, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Concrete testing environment, distinct from VVCase.vvSubject.", source="13.2.9, pp. 110-111"),

        # RCM V2 conservative core
        metaclass("DynamicFunctionalModel", P_CORE, bases=(f"{P_ELEMENTS}::Context",), description="Single root Context for a RCM V2 model."),
        metaclass("UseCaseScenarioSpecification", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), description="Conservative RCM relationship from an unchanged EAST-ADL UseCase to scenarios."),
        metaclass("ActorParticipation", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), description="RCM relationship assigning external Actor roles to UseCases."),
        metaclass("ConditionalExtend", P_CORE, bases=(f"{P_USECASES}::Extend",), description="Condition-bearing specialization of EAST-ADL Extend; remains admissible in UseCase.extend."),
        metaclass("Scenario", P_CORE, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("kind", f"{P_CORE}::ScenarioKind"),), description="Complete main, alternative or exception execution flow."),
        metaclass("ScenarioStep", P_CORE, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("stepNumber", "Integer", derived=True, description="Display-only order derived from control flow."), attribute("kind", f"{P_CORE}::ScenarioStepKind")), description="Traceable step in a scenario; it never references a RuntimeAction directly."),
        metaclass("StepRelation", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), attributes=(attribute("kind", f"{P_CORE}::StepRelationKind"),), description="Canonical local control-flow edge between scenario steps."),
        metaclass("ParallelGroup", P_CORE, bases=(f"{P_ELEMENTS}::EAElement",), description="Structural grouping of parallel steps bounded by matching fork and join flow."),
        metaclass("ScenarioEvent", P_CORE, bases=(f"{P_TIMING}::Event", f"{P_VALUES}::EAExpression"), attributes=(attribute("kind", f"{P_CORE}::ScenarioEventKind"), attribute("expressionText", "String")), description="Identifiable timing event with an EAExpression lexical representation."),
        metaclass("ScenarioExternalEvent", P_CORE, bases=(f"{P_CORE}::ScenarioEvent", f"{P_EVENTS}::ExternalEvent"), description="Scenario event representing a user, environment, spatial or other external state change."),
        metaclass("ScenarioCondition", P_CORE, bases=(f"{P_ELEMENTS}::EAElement", f"{P_VALUES}::EAExpression"), attributes=(attribute("kind", f"{P_CORE}::ConditionKind"), attribute("expressionText", "String")), description="Identifiable Boolean-typed EAExpression used as guard, pre/post, spatial or timing condition."),
        metaclass("ProbabilityValue", P_CORE, bases=(f"{P_VALUES}::EANumericalValue",), description="Numerical value whose type is the bounded RCM Probability datatype."),
        metaclass("Assertion", P_CORE, abstract=True, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("expressionText", "String", derived=True, description="Compatibility/display projection of expression."), attribute("severity", f"{P_CORE}::AssertionSeverity", "0..1")), description="Abstract reusable, evaluable assertion about an identifiable subject."),
        metaclass("StateAssertion", P_CORE, bases=(f"{P_CORE}::Assertion",), description="Assertion about a state or state transition; retained as the v0.5-compatible specialization."),
        metaclass("EventAssertion", P_CORE, bases=(f"{P_CORE}::Assertion",), description="Assertion that an event occurred or did not occur."),
        metaclass("OutputAssertion", P_CORE, bases=(f"{P_CORE}::Assertion",), description="Assertion about an emitted visual, audio, textual or technical output."),
        metaclass("GroundingAssertion", P_CORE, bases=(f"{P_CORE}::Assertion",), description="Assertion that information or interaction is grounded in an identifiable model element or source."),
        metaclass("RelationAssertion", P_CORE, bases=(f"{P_CORE}::Assertion",), description="Assertion about a relation between identifiable model elements."),
        metaclass("Entity", P_CORE, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("kind", f"{P_CORE}::EntityKind", "0..1"), attribute("sourceId", "String", "0..1"), attribute("entityRole", "String", "0..1"), attribute("sourceObjectId", "String", "*", ordered=True), attribute("purpose", "String", "0..1"), attribute("sourceGroup", "String", "0..1"), attribute("objectType", "String", "0..1")), description="Concrete participant, asset, zone, signal or state object with optional source/provenance metadata."),
        metaclass("Agent", P_CORE, bases=(f"{P_CORE}::Entity",), attributes=(attribute("sourceAgentId", "String", "0..1"), attribute("displayName", "String", "0..1"), attribute("persona", "String", "0..1"), attribute("expertise", "String", "*", ordered=True), attribute("knowledgeTag", "String", "*", ordered=True), attribute("voice", "String", "0..1"), attribute("voiceGender", "String", "0..1"), attribute("voiceStyle", "String", "0..1"), attribute("ttsModel", "String", "0..1")), description="Entity capable of providing capabilities, grounded runtime interaction and handoffs."),
        metaclass("Capability", P_CORE, bases=(f"{P_ELEMENTS}::EAType", f"{P_ELEMENTS}::TraceableSpecification"), description="Domain-independent capability type retaining traceable intent and effects."),
        metaclass("CapabilityUse", P_CORE, bases=(f"{P_ELEMENTS}::EAPrototype", f"{P_ELEMENTS}::EAElement"), description="Typed occurrence of a Capability in a ScenarioStep."),
        metaclass("Effect", P_CORE, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Observable promised effect of a Capability."),
        metaclass("CapabilityFunctionMapping", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), description="Optional mapping, not identity, to an exact analysis/design function type or prototype."),
        metaclass("CapabilityBehaviorBinding", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), attributes=(attribute("requiresRunToCompletion", "Boolean", default=True),), description="Optional relationship to a synchronous EAST-ADL FunctionBehavior; it is not Refine."),
        metaclass("RuntimeBinding", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), attributes=(attribute("targetPlatform", "String"),), description="Ordered technical realization choices for a Capability."),
        metaclass("RuntimeAction", P_CORE, bases=(f"{P_ELEMENTS}::EAElement",), description="Atomic technical action with exactly one structured locator."),
        metaclass("RuntimeActionLocator", P_CORE, bases=(f"{P_ELEMENTS}::EAElement",), attributes=(attribute("kind", f"{P_CORE}::RuntimeLocatorKind"), attribute("value", "String")), description="Exclusive endpoint, tool or topic locator."),
        metaclass("SchemaReference", P_CORE, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("uri", "String", "0..1"), attribute("dialect", "String", "0..1")), description="Reference to, or textual form of, a runtime data schema."),
        metaclass("KeyValueParameter", P_CORE, bases=(f"{P_DATATYPES}::EADatatypePrototype",), description="Typed capability-use parameter; shortName is the key."),
        metaclass("RuntimeParameter", P_CORE, bases=(f"{P_DATATYPES}::EADatatypePrototype",), attributes=(attribute("direction", f"{P_CORE}::RuntimeParameterDirection"),), description="Typed runtime input/output parameter."),
        metaclass("ParameterBinding", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), description="Maps capability-use parameters to runtime parameters with an optional typed transformation."),
        metaclass("ValidationCase", P_CORE, bases=(f"{P_VV}::VVCase",), description="RCM runtime-validation specialization of VVCase; legacy level is preserved by projection, not inferred."),
        metaclass("RuntimeValidationProcedure", P_CORE, bases=(f"{P_VV}::VVProcedure",), description="Runtime-validation specialization of VVProcedure."),
        metaclass("RuntimeStimulus", P_CORE, bases=(f"{P_VV}::VVStimuli",), description="Runtime stimulus specialization."),
        metaclass("AssertionOutcome", P_CORE, abstract=True, bases=(f"{P_VV}::VVIntendedOutcome",), description="Intended outcome specified by one or more reusable Assertions."),
        metaclass("StateAssertionOutcome", P_CORE, bases=(f"{P_CORE}::AssertionOutcome",), description="v0.5-compatible intended-outcome specialization for StateAssertions."),
        metaclass("AssertionResult", P_CORE, bases=(f"{P_ELEMENTS}::EAElement",), attributes=(attribute("verdict", f"{P_CORE}::AssertionVerdict"), attribute("evidenceRef", "String", "0..1"), attribute("timestamp", "String", "0..1")), description="Structured runtime evaluation result for exactly one Assertion."),
        metaclass("RuntimeActualOutcome", P_CORE, bases=(f"{P_VV}::VVActualOutcome",), description="Actual runtime outcome; owned only by RuntimeValidationLog."),
        metaclass("RuntimeValidationLog", P_CORE, bases=(f"{P_VV}::VVLog",), description="Runtime execution log containing actual outcomes."),
        metaclass("RuntimeValidationTarget", P_CORE, bases=(f"{P_VV}::VVTarget",), attributes=(attribute("platform", "String"), attribute("environmentRef", "String", "0..1")), description="Runtime test environment with an explicit platform; its elements need not equal the case's vvSubjects."),
        metaclass("ValidationCaseUseCaseBinding", P_CORE, bases=(f"{P_ELEMENTS}::Relationship",), description="RCM relationship for legacy validates_use_case_ids; Verify remains requirement-only."),

        # Preliminary Annex C reference slice and optional bridge
        metaclass("BehaviorConstraintParameter", P_ANNEX_BEHAVIOR, abstract=True, description="Abstract Annex C behavior-constraint parameter with no generalization.", source="Annex C 30.2.4, p. 217", optional=True),
        metaclass("BehaviorConstraintType", P_ANNEX_BEHAVIOR, bases=(f"{P_ELEMENTS}::Context",), description="Preliminary Annex C behavior-constraint type.", source="Annex C 30.2.7, pp. 219-220", stereotypes=("atpType",), optional=True),
        metaclass("BehaviorConstraintTargetBinding", P_ANNEX_BEHAVIOR, bases=(f"{P_ELEMENTS}::Relationship",), description="Preliminary Annex C relationship assigning a BehaviorConstraintType to behavior targets.", source="Annex C 30.2.6, pp. 218-219", optional=True),
        metaclass("Quantification", P_ANNEX_VALUE, bases=(f"{P_ELEMENTS}::EAElement", f"{P_VALUES}::EAExpression"), description="Preliminary Annex C value-condition expression.", source="Annex C 31.2.5, pp. 223-224", optional=True),
        metaclass("LogicalPath", P_ANNEX_COMPUTATION, bases=(f"{P_ELEMENTS}::EAElement",), description="Preliminary Annex C ordered/parallel logical cause-effect path.", source="Annex C 32.2.2, pp. 226-227", optional=True),
        metaclass("LogicalTransformation", P_ANNEX_COMPUTATION, bases=(f"{P_ELEMENTS}::EAElement",), attributes=(attribute("isClientServerInterface", "Boolean", default=False),), description="Preliminary Annex C logical computation restriction.", source="Annex C 32.2.3, pp. 227-228", optional=True),
        metaclass("TransformationOccurrence", P_ANNEX_COMPUTATION, bases=(f"{P_ELEMENTS}::EAElement",), description="Activation of a logical transformation.", source="Annex C 32.2.4, pp. 228-229", optional=True),
        metaclass("LogicalTimeCondition", P_ANNEX_TEMPORAL, bases=(f"{P_ELEMENTS}::EAElement",), attributes=(attribute("isLogicalTimeSuspended", "Boolean", default=False),), description="Preliminary Annex C logical time interval condition.", source="Annex C 33.2.1, p. 232", optional=True),
        metaclass("State", P_ANNEX_TEMPORAL, bases=(f"{P_ELEMENTS}::EAElement",), attributes=(attribute("isErrorState", "Boolean", default=False), attribute("isHazard", "Boolean", default=False), attribute("isInitState", "Boolean", default=False), attribute("isMode", "Boolean", default=False)), description="Preliminary Annex C discrete state.", source="Annex C 33.2.2, pp. 232-233", optional=True),
        metaclass("TransitionEvent", P_ANNEX_TEMPORAL, bases=(f"{P_ELEMENTS}::EAElement", f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintParameter"), description="Occurrence parameter firing a transition; deliberately not a Timing::Event subtype.", source="Annex C 33.2.7, p. 236", optional=True),
        metaclass("ScenarioAnnexMapping", P_ANNEX_BRIDGE, bases=(f"{P_ELEMENTS}::Relationship",), description="Optional bridge to preliminary Annex C constructs; never a Core prerequisite.", optional=True),

        # Optional generic/vehicle feature targets and bridge
        metaclass("FeatureTreeNode", P_FEATURE, abstract=True, bases=(f"{P_ELEMENTS}::Context",), description="Abstract base for elements in a feature tree.", source="4.2.8, p. 32", optional=True),
        metaclass("Feature", P_FEATURE, bases=(f"{P_FEATURE}::FeatureTreeNode",), attributes=(attribute("cardinality", "String"),), description="Generic EAST-ADL feature.", source="4.2.3, pp. 28-29", stereotypes=("atpStructureElement",), optional=True),
        metaclass("VehicleFeature", P_VEHICLE_FEATURE, bases=(f"{P_FEATURE}::Feature",), attributes=(attribute("isCustomerVisible", "Boolean"), attribute("isDesignVariabilityRationale", "Boolean"), attribute("isRemoved", "Boolean")), description="Automotive VehicleLevel feature; never required by the domain-independent Core.", source="5.2.3, pp. 38-39", optional=True),
        metaclass("CapabilityFeatureMapping", P_FEATURE_BRIDGE, bases=(f"{P_ELEMENTS}::Relationship",), description="Optional mapping from Capability to generic Feature or automotive VehicleFeature.", optional=True),

        # Optional agent knowledge module
        metaclass("KnowledgeItem", P_KNOWLEDGE, bases=(f"{P_ELEMENTS}::TraceableSpecification",), description="Optional traceable knowledge item.", optional=True),
        metaclass("KnowledgeSource", P_KNOWLEDGE, bases=(f"{P_ELEMENTS}::TraceableSpecification",), attributes=(attribute("uri", "String", "0..1"),), description="Optional source/provenance record.", optional=True),
        metaclass("AgentKnowledgeBinding", P_KNOWLEDGE, bases=(f"{P_ELEMENTS}::Relationship",), attributes=(attribute("permissions", f"{P_KNOWLEDGE}::KnowledgePermission", "1..*"), attribute("provenanceKind", f"{P_KNOWLEDGE}::KnowledgeProvenanceKind")), description="Optional permissions and provenance relationship for agent knowledge.", optional=True),
    ]
)


DATATYPES: dict[str, dict[str, Any]] = {
    f"{P_CORE}::Probability": {
        "name": "Probability",
        "package": P_CORE,
        "abstract": False,
        "bases": [f"{P_DATATYPES}::EANumerical"],
        "attributes": [],
        "min": 0,
        "max": 1,
        "description": "EANumerical specialization with closed value range [0, 1].",
    },
    f"{P_CORE}::RandomVariable": {
        "name": "RandomVariable",
        "package": P_CORE,
        "abstract": False,
        "bases": [f"{P_DATATYPES}::EANumerical"],
        "attributes": [attribute("distribution", f"{P_CORE}::DistributionKind")],
        "description": "Typed stochastic quantity used by optional probabilistic expressions.",
    },
}


ASSOCIATIONS: list[dict[str, Any]] = [
    # Exact EAST-ADL infrastructure associations
    association("EAElement_ownedComment", P_ELEMENTS, f"{P_ELEMENTS}::EAElement", f"{P_ELEMENTS}::Comment", "commentOwner", "ownedComment", "1", "*", composition=True, owner="source", description="Comment owned by EAElement."),
    association("Context_ownedRelationship", P_ELEMENTS, f"{P_ELEMENTS}::Context", f"{P_ELEMENTS}::Relationship", "owningContext", "ownedRelationship", "1", "*", composition=True, owner="source", description="Relationships owned by a Context."),
    association("Context_traceableSpecification", P_ELEMENTS, f"{P_ELEMENTS}::Context", f"{P_ELEMENTS}::TraceableSpecification", "context", "traceableSpecification", "*", "*", description="Traceable specifications identified by a Context."),
    association("EADatatypePrototype_type", P_DATATYPES, f"{P_DATATYPES}::EADatatypePrototype", f"{P_DATATYPES}::EADatatype", "typedPrototype", "type", "*", "1", stereotype="isOfType", description="Exact datatype-prototype typing."),
    association("EAValue_type", P_VALUES, f"{P_VALUES}::EAValue", f"{P_DATATYPES}::EADatatype", "typedValue", "type", "*", "1", stereotype="isOfType", description="Exact EAValue typing; EAValue remains non-identifiable."),

    # Exact EAST-ADL Requirements/UseCases slice
    association("Requirement_mode", P_REQUIREMENTS, f"{P_REQUIREMENTS}::Requirement", f"{P_BEHAVIOR}::Mode", "validRequirement", "mode", "*", "*", description="Modes in which the Requirement is valid."),
    association("RequirementsModel_requirement", P_REQUIREMENTS, f"{P_REQUIREMENTS}::RequirementsModel", f"{P_REQUIREMENTS}::Requirement", "requirementsModel", "requirement", "1", "*", composition=True, owner="source", description="Requirements owned by RequirementsModel."),
    association("RequirementsModel_useCase", P_REQUIREMENTS, f"{P_REQUIREMENTS}::RequirementsModel", f"{P_USECASES}::UseCase", "requirementsModel", "useCase", "1", "*", composition=True, owner="source", description="UseCases owned by RequirementsModel."),
    association("Refine_refinedRequirement", P_REQUIREMENTS, f"{P_REQUIREMENTS}::Refine", f"{P_REQUIREMENTS}::Requirement", "refine", "refinedRequirement", "*", "1..*", description="Requirements refined by EAElements."),
    association("Refine_refinedBy", P_REQUIREMENTS, f"{P_REQUIREMENTS}::Refine", f"{P_ELEMENTS}::EAElement", "refine", "refinedBy", "*", "1..*", stereotype="instanceRef", description="EAElements refining the Requirements; Requirement/RequirementContainer are excluded."),
    association("Satisfy_satisfiedRequirement", P_REQUIREMENTS, f"{P_REQUIREMENTS}::Satisfy", f"{P_REQUIREMENTS}::Requirement", "satisfy", "satisfiedRequirement", "*", "*", description="Requirements satisfied by the relationship."),
    association("Satisfy_satisfiedUseCase", P_REQUIREMENTS, f"{P_REQUIREMENTS}::Satisfy", f"{P_USECASES}::UseCase", "satisfy", "satisfiedUseCase", "*", "*", description="UseCases satisfied by the relationship."),
    association("Satisfy_satisfiedBy", P_REQUIREMENTS, f"{P_REQUIREMENTS}::Satisfy", f"{P_ELEMENTS}::Identifiable", "satisfy", "satisfiedBy", "*", "1..*", stereotype="instanceRef", description="Identifiables intended to satisfy the supplier."),
    association("UseCase_extensionPoint", P_USECASES, f"{P_USECASES}::UseCase", f"{P_USECASES}::ExtensionPoint", "useCase", "extensionPoint", "1", "*", composition=True, owner="source", description="ExtensionPoints owned by a UseCase."),
    association("UseCase_include", P_USECASES, f"{P_USECASES}::UseCase", f"{P_USECASES}::Include", "includingUseCase", "include", "1", "*", composition=True, owner="source", description="Include relationships owned by a UseCase."),
    association("UseCase_extend", P_USECASES, f"{P_USECASES}::UseCase", f"{P_USECASES}::Extend", "extendingUseCase", "extend", "1", "*", composition=True, owner="source", description="Extend relationships owned by the extending UseCase."),
    association("Include_addition", P_USECASES, f"{P_USECASES}::Include", f"{P_USECASES}::UseCase", "include", "addition", "*", "1", description="UseCase whose behavior is inserted."),
    association("Extend_extendedCase", P_USECASES, f"{P_USECASES}::Extend", f"{P_USECASES}::UseCase", "extend", "extendedCase", "*", "1", description="UseCase being extended."),
    association("Extend_extensionLocation", P_USECASES, f"{P_USECASES}::Extend", f"{P_USECASES}::ExtensionPoint", "extend", "extensionLocation", "*", "1..*", description="ExtensionPoints of the extendedCase."),

    # Exact EAST-ADL function/system/behavior slice
    association("FunctionConnector_port", P_FUNCTION, f"{P_FUNCTION}::FunctionConnector", f"{P_FUNCTION}::FunctionPort", "functionConnector", "port", "*", "2", stereotype="instanceRef", description="Exactly two FunctionPorts connected through concrete prototype paths."),
    association("FunctionFlowPort_type", P_FUNCTION, f"{P_FUNCTION}::FunctionFlowPort", f"{P_DATATYPES}::EADatatype", "typedPort", "type", "*", "1", stereotype="isOfType", description="Exact FunctionFlowPort datatype."),
    association("FunctionFlowPort_defaultValue", P_FUNCTION, f"{P_FUNCTION}::FunctionFlowPort", f"{P_VALUES}::EAValue", "functionFlowPort", "defaultValue", "1", "0..1", composition=True, owner="source", description="Optional typed default value."),
    association("FunctionType_port", P_FUNCTION, f"{P_FUNCTION}::FunctionType", f"{P_FUNCTION}::FunctionPort", "functionType", "port", "1", "*", composition=True, owner="source", description="FunctionPorts owned by FunctionType."),
    association("FunctionType_connector", P_FUNCTION, f"{P_FUNCTION}::FunctionType", f"{P_FUNCTION}::FunctionConnector", "functionType", "connector", "1", "*", composition=True, owner="source", description="FunctionConnectors owned by FunctionType."),
    association("FunctionType_portGroup", P_FUNCTION, f"{P_FUNCTION}::FunctionType", f"{P_FUNCTION}::PortGroup", "functionType", "portGroup", "1", "*", composition=True, owner="source", description="PortGroups owned by FunctionType."),
    association("PortGroup_port", P_FUNCTION, f"{P_FUNCTION}::PortGroup", f"{P_FUNCTION}::FunctionPort", "portGroup", "port", "*", "*", description="FunctionPorts grouped by PortGroup."),
    association("PortGroup_portGroup", P_FUNCTION, f"{P_FUNCTION}::PortGroup", f"{P_FUNCTION}::PortGroup", "parentPortGroup", "portGroup", "0..1", "*", composition=True, owner="source", description="Nested PortGroups."),
    association("AnalysisFunctionPrototype_type", P_FUNCTION, f"{P_FUNCTION}::AnalysisFunctionPrototype", f"{P_FUNCTION}::AnalysisFunctionType", "typedPrototype", "type", "*", "1", stereotype="isOfType", description="Exact analysis prototype typing."),
    association("AnalysisFunctionType_part", P_FUNCTION, f"{P_FUNCTION}::AnalysisFunctionType", f"{P_FUNCTION}::AnalysisFunctionPrototype", "analysisFunctionType", "part", "1", "*", composition=True, owner="source", description="Analysis function parts."),
    association("DesignFunctionPrototype_type", P_FUNCTION, f"{P_FUNCTION}::DesignFunctionPrototype", f"{P_FUNCTION}::DesignFunctionType", "typedPrototype", "type", "*", "1", stereotype="isOfType", description="Exact design prototype typing."),
    association("DesignFunctionType_part", P_FUNCTION, f"{P_FUNCTION}::DesignFunctionType", f"{P_FUNCTION}::DesignFunctionPrototype", "designFunctionType", "part", "1", "*", composition=True, owner="source", description="Design function parts."),
    association("AnalysisLevel_functionalAnalysisArchitecture", P_SYSTEM, f"{P_SYSTEM}::AnalysisLevel", f"{P_FUNCTION}::AnalysisFunctionPrototype", "analysisLevel", "functionalAnalysisArchitecture", "1", "0..1", composition=True, owner="source", description="FAA root is a prototype, not a metaclass."),
    association("DesignLevel_functionalDesignArchitecture", P_SYSTEM, f"{P_SYSTEM}::DesignLevel", f"{P_FUNCTION}::DesignFunctionPrototype", "designLevel", "functionalDesignArchitecture", "1", "0..1", composition=True, owner="source", description="FDA root is a prototype, not a metaclass."),
    association("FunctionBehavior_function", P_BEHAVIOR, f"{P_BEHAVIOR}::FunctionBehavior", f"{P_FUNCTION}::FunctionType", "functionBehavior", "function", "*", "0..1", description="FunctionType whose behavior is described."),
    association("FunctionBehavior_mode", P_BEHAVIOR, f"{P_BEHAVIOR}::FunctionBehavior", f"{P_BEHAVIOR}::Mode", "functionBehavior", "mode", "*", "*", description="Modes in which FunctionBehavior may execute."),
    association("FunctionTrigger_port", P_BEHAVIOR, f"{P_BEHAVIOR}::FunctionTrigger", f"{P_FUNCTION}::FunctionPort", "functionTrigger", "port", "*", "*", description="Input FunctionFlowPorts acting as event triggers."),
    association("FunctionTrigger_function", P_BEHAVIOR, f"{P_BEHAVIOR}::FunctionTrigger", f"{P_FUNCTION}::FunctionType", "functionTrigger", "function", "*", "0..1", description="FunctionType targeted by the trigger."),
    association("FunctionTrigger_functionPrototype", P_BEHAVIOR, f"{P_BEHAVIOR}::FunctionTrigger", f"{P_FUNCTION}::FunctionPrototype", "functionTrigger", "functionPrototype", "*", "0..1", description="FunctionPrototype targeted by the trigger."),
    association("FunctionTrigger_mode", P_BEHAVIOR, f"{P_BEHAVIOR}::FunctionTrigger", f"{P_BEHAVIOR}::Mode", "functionTrigger", "mode", "*", "*", description="Modes in which the trigger is active."),

    # Exact EAST-ADL Verification & Validation slice
    association("VerificationValidation_vvTarget", P_VV, f"{P_VV}::VerificationValidation", f"{P_VV}::VVTarget", "verificationValidation", "vvTarget", "1", "*", composition=True, owner="source", description="VVTargets owned by the exact container."),
    association("VerificationValidation_vvCase", P_VV, f"{P_VV}::VerificationValidation", f"{P_VV}::VVCase", "verificationValidation", "vvCase", "1", "*", composition=True, owner="source", description="VVCases owned only by the exact container."),
    association("VerificationValidation_verify", P_VV, f"{P_VV}::VerificationValidation", f"{P_VV}::Verify", "verificationValidation", "verify", "1", "*", composition=True, owner="source", description="Verify relationships owned by the exact container."),
    association("Verify_verifiedRequirement", P_VV, f"{P_VV}::Verify", f"{P_REQUIREMENTS}::Requirement", "verify", "verifiedRequirement", "*", "1..*", description="Requirements being verified."),
    association("Verify_verifiedByProcedure", P_VV, f"{P_VV}::Verify", f"{P_VV}::VVProcedure", "verify", "verifiedByProcedure", "*", "*", description="Optional abstract procedures verifying the Requirements."),
    association("Verify_verifiedByCase", P_VV, f"{P_VV}::Verify", f"{P_VV}::VVCase", "verify", "verifiedByCase", "*", "1..*", description="VVCases verifying the Requirements."),
    association("VVActualOutcome_intendedOutcome", P_VV, f"{P_VV}::VVActualOutcome", f"{P_VV}::VVIntendedOutcome", "actualOutcome", "intendedOutcome", "*", "0..1", description="Intended outcome to be matched."),
    association("VVCase_vvProcedure", P_VV, f"{P_VV}::VVCase", f"{P_VV}::VVProcedure", "vvCase", "vvProcedure", "1", "*", composition=True, owner="source", ordered=True, description="Ordered VVProcedures owned by a VVCase."),
    association("VVCase_vvTarget", P_VV, f"{P_VV}::VVCase", f"{P_VV}::VVTarget", "vvCase", "vvTarget", "*", "*", description="Concrete testing environments used by a case."),
    association("VVCase_vvLog", P_VV, f"{P_VV}::VVCase", f"{P_VV}::VVLog", "vvCase", "vvLog", "1", "*", composition=True, owner="source", description="Logs owned by a concrete VVCase."),
    association("VVCase_abstractVVCase", P_VV, f"{P_VV}::VVCase", f"{P_VV}::VVCase", "concreteVVCase", "abstractVVCase", "*", "0..1", description="Optional abstract case identified from a concrete case."),
    association("VVCase_vvSubject", P_VV, f"{P_VV}::VVCase", f"{P_ELEMENTS}::Identifiable", "vvCase", "vvSubject", "*", "*", stereotype="instanceRef", description="Primary subjects under verification; distinct from VVTarget.element."),
    association("VVLog_performedVVProcedure", P_VV, f"{P_VV}::VVLog", f"{P_VV}::VVProcedure", "vvLog", "performedVVProcedure", "*", "1", description="Procedure performed for this log."),
    association("VVLog_vvActualOutcome", P_VV, f"{P_VV}::VVLog", f"{P_VV}::VVActualOutcome", "vvLog", "vvActualOutcome", "1", "*", composition=True, owner="source", description="Actual results exist only inside execution logs."),
    association("VVProcedure_abstractVVProcedure", P_VV, f"{P_VV}::VVProcedure", f"{P_VV}::VVProcedure", "concreteVVProcedure", "abstractVVProcedure", "*", "0..1", description="Optional abstract procedure identified from a concrete procedure."),
    association("VVProcedure_vvStimuli", P_VV, f"{P_VV}::VVProcedure", f"{P_VV}::VVStimuli", "vvProcedure", "vvStimuli", "1", "*", composition=True, owner="source", description="Stimuli of a concrete procedure."),
    association("VVProcedure_vvIntendedOutcome", P_VV, f"{P_VV}::VVProcedure", f"{P_VV}::VVIntendedOutcome", "vvProcedure", "vvIntendedOutcome", "1", "*", composition=True, owner="source", description="Intended outcomes of a concrete procedure."),
    association("VVTarget_element", P_VV, f"{P_VV}::VVTarget", f"{P_ELEMENTS}::Identifiable", "vvTarget", "element", "*", "*", stereotype="instanceRef", description="Elements realized by the testing environment; may include support elements or none."),

    # RCM V2 root and scenario semantics
    association("DynamicFunctionalModel_requirementsModel", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_REQUIREMENTS}::RequirementsModel", "dynamicFunctionalModel", "requirementsModel", "1", "1", composition=True, owner="source", description="Single requirements/use-case container of the model."),
    association("DynamicFunctionalModel_actor", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_USECASES}::Actor", "dynamicFunctionalModel", "actor", "1", "*", composition=True, owner="source", description="Actors owned by the RCM root without modifying EAST-ADL Actor."),
    association("DynamicFunctionalModel_scenario", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_CORE}::Scenario", "dynamicFunctionalModel", "scenario", "1", "*", composition=True, owner="source", description="Scenarios owned by the root; UseCases reference them through a relationship."),
    association("DynamicFunctionalModel_scenarioEvent", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_CORE}::ScenarioEvent", "dynamicFunctionalModel", "scenarioEvent", "1", "*", composition=True, owner="source", description="Reusable scenario events owned by the root."),
    association("DynamicFunctionalModel_scenarioCondition", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_CORE}::ScenarioCondition", "dynamicFunctionalModel", "scenarioCondition", "1", "*", composition=True, owner="source", description="Reusable typed conditions owned by the root."),
    association("DynamicFunctionalModel_assertion", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_CORE}::Assertion", "dynamicFunctionalModel", "assertion", "1", "*", composition=True, owner="source", description="Reusable assertions of every concrete Assertion kind owned by the root."),
    association("DynamicFunctionalModel_entity", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_CORE}::Entity", "dynamicFunctionalModel", "entity", "1", "*", composition=True, owner="source", description="Entities owned by the root."),
    association("DynamicFunctionalModel_capability", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_CORE}::Capability", "dynamicFunctionalModel", "capability", "1", "*", composition=True, owner="source", description="Capabilities owned by the root."),
    association("DynamicFunctionalModel_runtimeBinding", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_CORE}::RuntimeBinding", "dynamicFunctionalModel", "runtimeBinding", "1", "*", composition=True, owner="source", description="Runtime bindings owned by the root."),
    association("DynamicFunctionalModel_verificationValidation", P_CORE, f"{P_CORE}::DynamicFunctionalModel", f"{P_VV}::VerificationValidation", "dynamicFunctionalModel", "verificationValidation", "1", "1", composition=True, owner="source", description="Exactly one exact EAST-ADL V&V container; cases are not double-composed by the root."),
    association("UseCaseScenarioSpecification_useCase", P_CORE, f"{P_CORE}::UseCaseScenarioSpecification", f"{P_USECASES}::UseCase", "specification", "useCase", "*", "1", description="Unchanged EAST-ADL UseCase being specified."),
    association("UseCaseScenarioSpecification_scenario", P_CORE, f"{P_CORE}::UseCaseScenarioSpecification", f"{P_CORE}::Scenario", "specification", "scenario", "*", "1", description="One RCM scenario per relationship; zero or more relationships may specify a UseCase."),
    association("ActorParticipation_actor", P_CORE, f"{P_CORE}::ActorParticipation", f"{P_USECASES}::Actor", "participation", "actor", "*", "1", description="External role participating in a UseCase."),
    association("ActorParticipation_useCase", P_CORE, f"{P_CORE}::ActorParticipation", f"{P_USECASES}::UseCase", "participation", "useCase", "*", "1", description="UseCase in which the Actor participates."),
    association("ConditionalExtend_condition", P_CORE, f"{P_CORE}::ConditionalExtend", f"{P_CORE}::ScenarioCondition", "conditionalExtend", "condition", "*", "1", description="Boolean condition of the RCM Extend specialization."),
    association("Scenario_variantOf", P_CORE, f"{P_CORE}::Scenario", f"{P_CORE}::Scenario", "variant", "variantOf", "*", "0..1", description="Alternative/exception flow's main scenario."),
    association("Scenario_precondition", P_CORE, f"{P_CORE}::Scenario", f"{P_CORE}::ScenarioCondition", "scenario", "precondition", "*", "*", description="Reusable preconditions."),
    association("Scenario_postcondition", P_CORE, f"{P_CORE}::Scenario", f"{P_CORE}::ScenarioCondition", "scenario", "postcondition", "*", "*", description="Reusable postconditions."),
    association("Scenario_step", P_CORE, f"{P_CORE}::Scenario", f"{P_CORE}::ScenarioStep", "scenario", "step", "1", "1..*", composition=True, owner="source", description="Steps owned by a scenario; storage order is not control-flow semantics."),
    association("Scenario_stepRelation", P_CORE, f"{P_CORE}::Scenario", f"{P_CORE}::StepRelation", "scenario", "stepRelation", "1", "*", composition=True, owner="source", description="Canonical control-flow edges owned by a scenario."),
    association("Scenario_parallelGroup", P_CORE, f"{P_CORE}::Scenario", f"{P_CORE}::ParallelGroup", "scenario", "parallelGroup", "1", "*", composition=True, owner="source", description="Structural parallel groups owned by a scenario."),
    association("ScenarioStep_performedBy", P_CORE, f"{P_CORE}::ScenarioStep", f"{P_CORE}::Entity", "scenarioStep", "performedBy", "*", "*", description="Concrete executing entities."),
    association("ScenarioStep_actorRole", P_CORE, f"{P_CORE}::ScenarioStep", f"{P_USECASES}::Actor", "scenarioStep", "actorRole", "*", "*", description="External roles involved in the step, kept distinct from performers."),
    association("ScenarioStep_triggeredBy", P_CORE, f"{P_CORE}::ScenarioStep", f"{P_CORE}::ScenarioEvent", "scenarioStep", "triggeredBy", "*", "*", description="Events triggering the step."),
    association("ScenarioStep_guard", P_CORE, f"{P_CORE}::ScenarioStep", f"{P_CORE}::ScenarioCondition", "scenarioStep", "guard", "*", "0..1", description="Boolean guard for executing the step."),
    association("ScenarioStep_resultingAssertion", P_CORE, f"{P_CORE}::ScenarioStep", f"{P_CORE}::Assertion", "scenarioStep", "resultingAssertion", "*", "*", description="Reusable assertions established by the step; legacy resultingState is a StateAssertion-only projection."),
    association("ScenarioStep_occurrenceProbability", P_CORE, f"{P_CORE}::ScenarioStep", f"{P_CORE}::ProbabilityValue", "scenarioStep", "occurrenceProbability", "1", "0..1", composition=True, owner="source", description="Optional probability value, distinct from UML multiplicity."),
    association("ScenarioStep_capabilityUse", P_CORE, f"{P_CORE}::ScenarioStep", f"{P_CORE}::CapabilityUse", "scenarioStep", "capabilityUse", "1", "*", composition=True, owner="source", ordered=True, description="Capability occurrences required by the step."),
    association("StepRelation_sourceStep", P_CORE, f"{P_CORE}::StepRelation", f"{P_CORE}::ScenarioStep", "outgoingRelation", "sourceStep", "*", "1", description="Control-flow source."),
    association("StepRelation_targetStep", P_CORE, f"{P_CORE}::StepRelation", f"{P_CORE}::ScenarioStep", "incomingRelation", "targetStep", "*", "1", description="Control-flow target."),
    association("StepRelation_guard", P_CORE, f"{P_CORE}::StepRelation", f"{P_CORE}::ScenarioCondition", "stepRelation", "guard", "*", "0..1", description="Optional local branch guard."),
    association("StepRelation_probability", P_CORE, f"{P_CORE}::StepRelation", f"{P_CORE}::ProbabilityValue", "stepRelation", "probability", "1", "0..1", composition=True, owner="source", description="Optional local branch probability."),
    association("ParallelGroup_memberStep", P_CORE, f"{P_CORE}::ParallelGroup", f"{P_CORE}::ScenarioStep", "parallelGroup", "memberStep", "*", "2..*", ordered=True, description="Structurally grouped parallel steps."),
    association("Assertion_subject", P_CORE, f"{P_CORE}::Assertion", f"{P_ELEMENTS}::Identifiable", "assertion", "subject", "*", "1", stereotype="instanceRef", description="Exactly one identifiable subject of every concrete Assertion."),
    association("Assertion_expression", P_CORE, f"{P_CORE}::Assertion", f"{P_VALUES}::EAExpression", "assertion", "expression", "1", "1", composition=True, owner="source", description="Exactly one typed EAST-ADL expression evaluated by the Assertion."),

    # RCM V2 entity/capability/runtime bridge
    association("Entity_playsActor", P_CORE, f"{P_CORE}::Entity", f"{P_USECASES}::Actor", "entity", "playsActor", "*", "*", description="Actor roles played by any Entity, including but not limited to Agent."),
    association("Entity_providedCapability", P_CORE, f"{P_CORE}::Entity", f"{P_CORE}::Capability", "provider", "providedCapability", "*", "*", description="Capabilities provided by an Entity."),
    association("Entity_objectGroup", P_CORE, f"{P_CORE}::Entity", f"{P_CORE}::Entity", "groupMember", "objectGroup", "*", "0..1", description="Optional object-group Entity used by the existing Unity projection."),
    association("Agent_handoffTarget", P_CORE, f"{P_CORE}::Agent", f"{P_CORE}::Agent", "handoffSource", "handoffTarget", "*", "*", description="Permitted agent handoff targets."),
    association("Agent_responsibleZone", P_CORE, f"{P_CORE}::Agent", f"{P_CORE}::Entity", "responsibleAgent", "responsibleZone", "*", "*", description="Zone entities for which the Agent is responsible."),
    association("Agent_groundedAsset", P_CORE, f"{P_CORE}::Agent", f"{P_CORE}::Entity", "groundedAgent", "groundedAsset", "*", "*", description="Asset entities grounded for the Agent."),
    association("Agent_groundedObjectGroup", P_CORE, f"{P_CORE}::Agent", f"{P_CORE}::Entity", "groundedAgent", "groundedObjectGroup", "*", "*", description="Object-group entities grounded for the Agent."),
    association("CapabilityUse_type", P_CORE, f"{P_CORE}::CapabilityUse", f"{P_CORE}::Capability", "typedCapabilityUse", "type", "*", "1", stereotype="isOfType", description="Formal Capability type/prototype pattern."),
    association("CapabilityUse_provider", P_CORE, f"{P_CORE}::CapabilityUse", f"{P_CORE}::Entity", "providedCapabilityUse", "provider", "*", "0..1", description="Explicit performer of this CapabilityUse; optional only in the compatibility core and mandatory in the executable profile."),
    association("CapabilityUse_target", P_CORE, f"{P_CORE}::CapabilityUse", f"{P_ELEMENTS}::Identifiable", "targetedCapabilityUse", "target", "*", "*", stereotype="instanceRef", description="Optional identifiable interaction or observation targets of this CapabilityUse."),
    association("CapabilityUse_parameter", P_CORE, f"{P_CORE}::CapabilityUse", f"{P_CORE}::KeyValueParameter", "capabilityUse", "parameter", "1", "*", composition=True, owner="source", ordered=True, description="Ordered typed parameters of a CapabilityUse."),
    association("KeyValueParameter_value", P_CORE, f"{P_CORE}::KeyValueParameter", f"{P_VALUES}::EAValue", "keyValueParameter", "value", "1", "0..1", composition=True, owner="source", description="Optional typed value supplied at the use site."),
    association("Capability_precondition", P_CORE, f"{P_CORE}::Capability", f"{P_CORE}::ScenarioCondition", "capability", "precondition", "*", "*", description="Conditions required by the Capability."),
    association("Capability_effect", P_CORE, f"{P_CORE}::Capability", f"{P_CORE}::Effect", "capability", "effect", "1", "1..*", composition=True, owner="source", description="At least one promised observable effect."),
    association("Effect_specifiedBy", P_CORE, f"{P_CORE}::Effect", f"{P_CORE}::Assertion", "effect", "specifiedBy", "*", "1..*", description="Expected, testable Assertions that specify the promised Effect; they are not evidence by themselves."),
    association("Effect_observableBy", P_CORE, f"{P_CORE}::Effect", f"{P_USECASES}::Actor", "effect", "observableBy", "*", "*", description="Actor roles able to observe the effect."),
    association("CapabilityFunctionMapping_capability", P_CORE, f"{P_CORE}::CapabilityFunctionMapping", f"{P_CORE}::Capability", "functionMapping", "capability", "*", "1", description="Capability being mapped."),
    association("CapabilityFunctionMapping_capabilityUse", P_CORE, f"{P_CORE}::CapabilityFunctionMapping", f"{P_CORE}::CapabilityUse", "functionMapping", "capabilityUse", "*", "0..1", description="Optional prototype-level capability occurrence being mapped."),
    association("CapabilityFunctionMapping_analysisType", P_CORE, f"{P_CORE}::CapabilityFunctionMapping", f"{P_FUNCTION}::AnalysisFunctionType", "functionMapping", "analysisFunctionType", "*", "0..1", description="Optional analysis type target."),
    association("CapabilityFunctionMapping_analysisPrototype", P_CORE, f"{P_CORE}::CapabilityFunctionMapping", f"{P_FUNCTION}::AnalysisFunctionPrototype", "functionMapping", "analysisFunctionPrototype", "*", "0..1", description="Optional analysis prototype target."),
    association("CapabilityFunctionMapping_designType", P_CORE, f"{P_CORE}::CapabilityFunctionMapping", f"{P_FUNCTION}::DesignFunctionType", "functionMapping", "designFunctionType", "*", "0..1", description="Optional design type target."),
    association("CapabilityFunctionMapping_designPrototype", P_CORE, f"{P_CORE}::CapabilityFunctionMapping", f"{P_FUNCTION}::DesignFunctionPrototype", "functionMapping", "designFunctionPrototype", "*", "0..1", description="Optional design prototype target."),
    association("CapabilityBehaviorBinding_capability", P_CORE, f"{P_CORE}::CapabilityBehaviorBinding", f"{P_CORE}::Capability", "behaviorBinding", "capability", "*", "1", description="Capability whose optional formal behavior is linked."),
    association("CapabilityBehaviorBinding_functionBehavior", P_CORE, f"{P_CORE}::CapabilityBehaviorBinding", f"{P_BEHAVIOR}::FunctionBehavior", "behaviorBinding", "functionBehavior", "*", "1", description="Synchronous FunctionBehavior target."),
    association("RuntimeBinding_capability", P_CORE, f"{P_CORE}::RuntimeBinding", f"{P_CORE}::Capability", "runtimeBinding", "capability", "*", "1", description="Capability realized by this binding."),
    association("RuntimeBinding_runtimeAction", P_CORE, f"{P_CORE}::RuntimeBinding", f"{P_CORE}::RuntimeAction", "runtimeBinding", "runtimeAction", "1", "1..*", composition=True, owner="source", ordered=True, description="Ordered action sequence; scenario flow semantics remain separate."),
    association("RuntimeAction_locator", P_CORE, f"{P_CORE}::RuntimeAction", f"{P_CORE}::RuntimeActionLocator", "runtimeAction", "locator", "1", "1", composition=True, owner="source", description="Exactly one structured endpoint/tool/topic locator."),
    association("RuntimeAction_inputSchema", P_CORE, f"{P_CORE}::RuntimeAction", f"{P_CORE}::SchemaReference", "runtimeAction", "inputSchema", "1", "0..1", composition=True, owner="source", description="Optional input schema."),
    association("RuntimeAction_outputSchema", P_CORE, f"{P_CORE}::RuntimeAction", f"{P_CORE}::SchemaReference", "runtimeAction", "outputSchema", "1", "0..1", composition=True, owner="source", description="Optional output schema."),
    association("RuntimeAction_runtimeParameter", P_CORE, f"{P_CORE}::RuntimeAction", f"{P_CORE}::RuntimeParameter", "runtimeAction", "runtimeParameter", "1", "*", composition=True, owner="source", ordered=True, description="Ordered typed input/output parameters."),
    association("ParameterBinding_capabilityParameter", P_CORE, f"{P_CORE}::ParameterBinding", f"{P_CORE}::KeyValueParameter", "parameterBinding", "capabilityParameter", "*", "1", description="Source CapabilityUse parameter."),
    association("ParameterBinding_runtimeParameter", P_CORE, f"{P_CORE}::ParameterBinding", f"{P_CORE}::RuntimeParameter", "parameterBinding", "runtimeParameter", "*", "1", description="Target runtime parameter."),
    association("ParameterBinding_transformation", P_CORE, f"{P_CORE}::ParameterBinding", f"{P_VALUES}::EAExpression", "parameterBinding", "transformation", "1", "0..1", composition=True, owner="source", description="Optional typed conversion expression."),

    # RCM V2 V&V specializations and compatibility relations
    association("AssertionOutcome_assertion", P_CORE, f"{P_CORE}::AssertionOutcome", f"{P_CORE}::Assertion", "assertionOutcome", "assertion", "*", "1..*", description="Reusable Assertions that constitute the intended outcome."),
    association("AssertionResult_assertion", P_CORE, f"{P_CORE}::AssertionResult", f"{P_CORE}::Assertion", "assertionResult", "assertion", "*", "1", description="The single expected Assertion evaluated by this result."),
    association("AssertionResult_observedValue", P_CORE, f"{P_CORE}::AssertionResult", f"{P_VALUES}::EAValue", "assertionResult", "observedValue", "1", "0..1", composition=True, owner="source", description="Optional typed value observed during evaluation."),
    association("RuntimeActualOutcome_result", P_CORE, f"{P_CORE}::RuntimeActualOutcome", f"{P_CORE}::AssertionResult", "runtimeActualOutcome", "result", "1", "1..*", composition=True, owner="source", description="Structured results captured by one actual runtime outcome."),
    association("RuntimeValidationTarget_runtimeBinding", P_CORE, f"{P_CORE}::RuntimeValidationTarget", f"{P_CORE}::RuntimeBinding", "runtimeValidationTarget", "runtimeBinding", "*", "*", stereotype="instanceRef", description="Runtime bindings configured in this platform/environment; each is also an inherited VVTarget.element."),
    association("RuntimeStimulus_scenarioEvent", P_CORE, f"{P_CORE}::RuntimeStimulus", f"{P_CORE}::ScenarioEvent", "runtimeStimulus", "scenarioEvent", "*", "0..1", description="Optional scenario event stimulus."),
    association("RuntimeStimulus_runtimeAction", P_CORE, f"{P_CORE}::RuntimeStimulus", f"{P_CORE}::RuntimeAction", "runtimeStimulus", "runtimeAction", "*", "0..1", description="Optional runtime-action stimulus."),
    association("ValidationCaseUseCaseBinding_validationCase", P_CORE, f"{P_CORE}::ValidationCaseUseCaseBinding", f"{P_CORE}::ValidationCase", "useCaseBinding", "validationCase", "*", "1", description="ValidationCase associated with a UseCase."),
    association("ValidationCaseUseCaseBinding_useCase", P_CORE, f"{P_CORE}::ValidationCaseUseCaseBinding", f"{P_USECASES}::UseCase", "useCaseBinding", "useCase", "*", "1", description="One UseCase validated per relationship; separate from requirement Verify."),

    # Exact preliminary Annex C bridge facts
    association("BehaviorConstraintTargetBinding_behaviorConstraintType", P_ANNEX_BEHAVIOR, f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintTargetBinding", f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintType", "targetBinding", "behaviorConstraintType", "*", "1", description="BehaviorConstraintType assigned to the targets.", optional=True),
    association("BehaviorConstraintTargetBinding_targetedFunctionType", P_ANNEX_BEHAVIOR, f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintTargetBinding", f"{P_FUNCTION}::FunctionType", "targetBinding", "targetedFunctionType", "*", "*", description="Target functions of a behavior-constraint description.", optional=True),
    association("BehaviorConstraintTargetBinding_targetedVehicleFeature", P_ANNEX_BEHAVIOR, f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintTargetBinding", f"{P_VEHICLE_FEATURE}::VehicleFeature", "targetBinding", "targetedVehicleFeature", "*", "*", description="Target vehicle features of a behavior-constraint description.", optional=True),
    association("BehaviorConstraintTargetBinding_constrainedModeBehavior", P_ANNEX_BEHAVIOR, f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintTargetBinding", f"{P_BEHAVIOR}::Mode", "targetBinding", "constrainedModeBehavior", "*", "*", description="Modes constrained by a behavior-constraint description.", optional=True),
    association("BehaviorConstraintTargetBinding_constrainedFunctionBehavior", P_ANNEX_BEHAVIOR, f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintTargetBinding", f"{P_BEHAVIOR}::FunctionBehavior", "targetBinding", "constrainedFunctionBehavior", "*", "*", description="Function behaviors constrained by a behavior-constraint description.", optional=True),
    association("BehaviorConstraintTargetBinding_constrainedFunctionTriggering", P_ANNEX_BEHAVIOR, f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintTargetBinding", f"{P_BEHAVIOR}::FunctionTrigger", "targetBinding", "constrainedFunctionTriggering", "*", "*", description="Function triggers constrained by a behavior-constraint description.", optional=True),
    association("LogicalPath_segment", P_ANNEX_COMPUTATION, f"{P_ANNEX_COMPUTATION}::LogicalPath", f"{P_ANNEX_COMPUTATION}::LogicalPath", "logicalPath", "segment", "*", "*", ordered=True, description="Ordered subordinate logical paths in sequence.", optional=True),
    association("LogicalPath_strand", P_ANNEX_COMPUTATION, f"{P_ANNEX_COMPUTATION}::LogicalPath", f"{P_ANNEX_COMPUTATION}::LogicalPath", "logicalPath", "strand", "*", "*", description="Logical paths in parallel.", optional=True),
    association("LogicalPath_transformationOccurrence", P_ANNEX_COMPUTATION, f"{P_ANNEX_COMPUTATION}::LogicalPath", f"{P_ANNEX_COMPUTATION}::TransformationOccurrence", "logicalPath", "transformationOccurrence", "1", "0..1", composition=True, owner="source", description="Optional activation of logical transformations in a path.", optional=True),
    association("TransformationOccurrence_invokedLogicalTransformation", P_ANNEX_COMPUTATION, f"{P_ANNEX_COMPUTATION}::TransformationOccurrence", f"{P_ANNEX_COMPUTATION}::LogicalTransformation", "transformationOccurrence", "invokedLogicalTransformation", "*", "1", description="Logical transformation invoked by the occurrence.", optional=True),
    association("TransitionEvent_occurredExecutionEvent", P_ANNEX_TEMPORAL, f"{P_ANNEX_TEMPORAL}::TransitionEvent", f"{P_TIMING}::Event", "transitionEvent", "occurredExecutionEvent", "*", "*", description="Association bridge to occurred Timing::Events; never generalization.", optional=True),
    association("ScenarioAnnexMapping_scenarioStep", P_ANNEX_BRIDGE, f"{P_ANNEX_BRIDGE}::ScenarioAnnexMapping", f"{P_CORE}::ScenarioStep", "annexMapping", "scenarioStep", "*", "0..1", description="Optional source scenario step.", optional=True),
    association("ScenarioAnnexMapping_stepRelation", P_ANNEX_BRIDGE, f"{P_ANNEX_BRIDGE}::ScenarioAnnexMapping", f"{P_CORE}::StepRelation", "annexMapping", "stepRelation", "*", "0..1", description="Optional source flow edge.", optional=True),
    association("ScenarioAnnexMapping_scenarioEvent", P_ANNEX_BRIDGE, f"{P_ANNEX_BRIDGE}::ScenarioAnnexMapping", f"{P_CORE}::ScenarioEvent", "annexMapping", "scenarioEvent", "*", "0..1", description="Optional source scenario event.", optional=True),
    association("ScenarioAnnexMapping_stateAssertion", P_ANNEX_BRIDGE, f"{P_ANNEX_BRIDGE}::ScenarioAnnexMapping", f"{P_CORE}::StateAssertion", "annexMapping", "stateAssertion", "*", "0..1", description="Optional source state assertion.", optional=True),
    association("ScenarioAnnexMapping_capability", P_ANNEX_BRIDGE, f"{P_ANNEX_BRIDGE}::ScenarioAnnexMapping", f"{P_CORE}::Capability", "annexMapping", "capability", "*", "0..1", description="Optional source capability for a BehaviorConstraintType mapping.", optional=True),
    association("ScenarioAnnexMapping_annexElement", P_ANNEX_BRIDGE, f"{P_ANNEX_BRIDGE}::ScenarioAnnexMapping", f"{P_ELEMENTS}::EAElement", "annexMapping", "annexElement", "*", "1..*", description="Target constrained by mapping kind to the declared preliminary Annex C classes.", optional=True),

    # Optional feature and knowledge modules
    association("CapabilityFeatureMapping_capability", P_FEATURE_BRIDGE, f"{P_FEATURE_BRIDGE}::CapabilityFeatureMapping", f"{P_CORE}::Capability", "featureMapping", "capability", "*", "1", description="Capability being mapped.", optional=True),
    association("CapabilityFeatureMapping_feature", P_FEATURE_BRIDGE, f"{P_FEATURE_BRIDGE}::CapabilityFeatureMapping", f"{P_FEATURE}::Feature", "featureMapping", "feature", "*", "1", description="Generic or VehicleFeature target through specialization.", optional=True),
    association("AgentKnowledgeBinding_agent", P_KNOWLEDGE, f"{P_KNOWLEDGE}::AgentKnowledgeBinding", f"{P_CORE}::Agent", "knowledgeBinding", "agent", "*", "1", description="Agent receiving rights/knowledge.", optional=True),
    association("AgentKnowledgeBinding_knowledgeItem", P_KNOWLEDGE, f"{P_KNOWLEDGE}::AgentKnowledgeBinding", f"{P_KNOWLEDGE}::KnowledgeItem", "knowledgeBinding", "knowledgeItem", "*", "1", description="Knowledge subject.", optional=True),
    association("AgentKnowledgeBinding_source", P_KNOWLEDGE, f"{P_KNOWLEDGE}::AgentKnowledgeBinding", f"{P_KNOWLEDGE}::KnowledgeSource", "knowledgeBinding", "source", "*", "0..1", description="Optional provenance source.", optional=True),
    association("AgentKnowledgeBinding_groundedEntity", P_KNOWLEDGE, f"{P_KNOWLEDGE}::AgentKnowledgeBinding", f"{P_CORE}::Entity", "knowledgeBinding", "groundedEntity", "*", "*", description="Entities grounding the knowledge item.", optional=True),
]


INVARIANTS: list[dict[str, str]] = [
    invariant("INV-001", "PackageDependency", "EAST_ADL.packages.imports->excludes(RCM_V2)", "Dependencies are one-way: RCM may import EAST-ADL; no EAST-ADL package imports RCM."),
    invariant("INV-002", "TraceableSpecification", "localAttributes = {'text: String [0..1]'}", "The imported TraceableSpecification has exactly one local optional text attribute."),
    invariant("INV-003", "EAType|EAPrototype|EAPort|EAConnector", "bases->isEmpty()", "The four imported infrastructure marker metaclasses have no generalizations."),
    invariant("INV-004", "Satisfy", "satisfiedRequirement->notEmpty() xor satisfiedUseCase->notEmpty()", "Satisfy targets Requirements or UseCases, never both in one relationship."),
    invariant("INV-005", "Satisfy", "satisfiedBy->forAll(not oclIsKindOf(Requirement) and not oclIsKindOf(RequirementContainer))", "satisfiedBy excludes Requirement and RequirementContainer."),
    invariant("INV-006", "Extend", "localAttributes->isEmpty() and localAssociations->excludes(condition)", "Imported EAST-ADL Extend has no condition; ConditionalExtend adds it conservatively."),
    invariant("INV-007", "UseCaseScenarioSpecification", "scenario->size() >= 0", "An unchanged EAST-ADL UseCase may have zero RCM scenarios in the core profile."),
    invariant("INV-008", "UseCaseScenarioSpecification", "scenario->select(kind=main)->size() = 1", "The executable RCM profile requires exactly one main scenario per specified UseCase.", profile="executable"),
    invariant("INV-009", "Scenario", "kind=main implies variantOf->isEmpty()", "A main scenario has no variantOf reference."),
    invariant("INV-010", "Scenario", "kind<>main implies variantOf->size()=1 and variantOf.kind=main", "Every alternative or exception scenario references exactly one main scenario."),
    invariant("INV-011", "Scenario", "stepRelation->select(kind=sequence or kind=fork or kind=join or kind=alternative or kind=exception or kind=loop)", "StepRelation is the single semantic source of control flow; collection order and stepNumber are display/projection data."),
    invariant("INV-012", "ScenarioStep", "stepNumber = deriveTopologicalDisplayOrder(self)", "stepNumber is derived for display and is not a third control-flow authority."),
    invariant("INV-013", "ParallelGroup", "memberStep->size()>=2 and boundedByReachableForkJoin(self)", "A ParallelGroup is structural and all members are reachable between matching fork and join relations."),
    invariant("INV-014", "ScenarioStep", "not hasDirectReference(RuntimeAction)", "ScenarioStep never directly references RuntimeAction; the capability chain remains mandatory."),
    invariant("INV-015", "ScenarioCondition", "type.oclIsKindOf(EABoolean)", "Every ScenarioCondition EAExpression is Boolean-typed."),
    invariant("INV-016", "ScenarioEvent", "oclIsKindOf(Timing::Event) and oclIsKindOf(EAExpression)", "ScenarioEvent combines identifiable timing-event semantics with expression semantics."),
    invariant("INV-017", "Probability", "min=0 and max=1", "Probability is an EANumerical type with the closed range [0,1]; this is not a UML multiplicity."),
    invariant("INV-018", "ProbabilityValue", "type.oclIsTypeOf(Probability) and value>=0 and value<=1", "Every ProbabilityValue is typed by Probability and lies in its range."),
    invariant("INV-019", "Agent|Entity", "oclIsKindOf(Agent) iff kind=EntityKind::agent", "Unity-compatible EntityKind.agent is retained and exactly equivalent to Agent specialization."),
    invariant("INV-020", "ScenarioStep", "performedBy->forAll(oclIsKindOf(Entity)) and actorRole->forAll(oclIsKindOf(Actor))", "Concrete performers and external Actor roles remain separate."),
    invariant("INV-021", "CapabilityUse", "type->size()=1 and type.oclIsKindOf(Capability)", "CapabilityUse follows the formal EAPrototype-to-EAType pattern."),
    invariant("INV-022", "Capability", "effect->size()>=1", "Every Capability promises at least one observable Effect."),
    invariant("INV-023", "Effect", "specifiedBy->size()>=1", "Every Effect is specified by at least one reusable, testable Assertion; an expectation is not mislabeled as evidence."),
    invariant("INV-024", "CapabilityFunctionMapping", "targetCount(analysisFunctionType,analysisFunctionPrototype,designFunctionType,designFunctionPrototype)=1", "A function mapping selects exactly one real EAST-ADL type/prototype target; FAA/FDA are not invented metaclasses."),
    invariant("INV-025", "FunctionType", "isElementary implies parts()->isEmpty()", "Elementary FunctionTypes have no analysis/design parts (exact EAST-ADL constraint)."),
    invariant("INV-026", "FunctionConnector", "port->size()=2", "FunctionConnector links exactly two FunctionPorts through instance references."),
    invariant("INV-027", "FunctionBehavior", "path->size()=1 and representation->size()=1", "FunctionBehavior keeps both mandatory EAST-ADL attributes."),
    invariant("INV-028", "FunctionBehavior", "executionSemantics=readInputs_executeToCompletion_publishOutputs", "FunctionBehavior has synchronous run-to-completion execution semantics."),
    invariant("INV-029", "CapabilityBehaviorBinding", "requiresRunToCompletion=true", "A behavior binding is admissible only where the bound behavior's run-to-completion semantics fit; it is never a Refine relation."),
    invariant("INV-030", "RuntimeBinding", "runtimeAction->size()>=1 and runtimeAction.isOrdered=true", "Every RuntimeBinding owns at least one ordered RuntimeAction."),
    invariant("INV-031", "RuntimeAction", "locator->size()=1", "Every V2 RuntimeAction has exactly one structured locator."),
    invariant("INV-032", "RuntimeActionLocator", "kind=endpoint xor kind=tool xor kind=topic", "Locator kind is exclusive; legacy endpoint/tool/topic slots are projection fields."),
    invariant("INV-033", "ParameterBinding", "capabilityParameter->size()=1 and runtimeParameter->size()=1", "ParameterBinding maps one typed use parameter to one typed runtime parameter."),
    invariant("INV-034", "DynamicFunctionalModel", "verificationValidation->size()=1", "The root owns exactly one exact VerificationValidation container."),
    invariant("INV-035", "ValidationCase", "compositeOwner(self).oclIsKindOf(VerificationValidation)", "ValidationCase is composed only through VerificationValidation.vvCase, never directly by the root."),
    invariant("INV-036", "VVCase", "vvLog->notEmpty() implies isConcrete(self)", "Only a concrete VVCase may own VVLogs."),
    invariant("INV-037", "VVCase", "vvTarget->notEmpty() implies isConcrete(self)", "Only a concrete VVCase may have VVTargets."),
    invariant("INV-038", "VVCase", "abstractVVCase->notEmpty() implies isConcrete(self)", "Only a concrete VVCase may identify an abstractVVCase."),
    invariant("INV-039", "VVProcedure", "(vvStimuli->notEmpty() or vvIntendedOutcome->notEmpty() or abstractVVProcedure->notEmpty()) implies isConcrete(self)", "Stimuli, intended outcomes and abstractVVProcedure are concrete-procedure features."),
    invariant("INV-040", "RuntimeActualOutcome", "compositeOwner(self).oclIsKindOf(RuntimeValidationLog)", "Actual runtime outcomes exist only under RuntimeValidationLog/VVLog."),
    invariant("INV-041", "VVCase", "distinctRoles(vvSubject,VVTarget.element) and not requiredEqual(vvSubject,VVTarget.element)", "vvSubject and VVTarget.element have distinct roles but may coincidentally reference some of the same elements."),
    invariant("INV-042", "Verify", "verifiedRequirement->size()>=1 and verifiedByCase->size()>=1", "Verify remains a RequirementsRelationship between Requirements and VVCases/optional procedures."),
    invariant("INV-043", "ValidationCaseUseCaseBinding", "validationCase->size()=1 and useCase->size()=1", "Each UseCase-validation relationship has exactly one case and one UseCase and does not overload Verify."),
    invariant("INV-044", "ValidationCase", "legacyLevel is suppliedBy(V05ProjectionLedger)", "Legacy abstract/concrete level is not uniquely derivable from abstractVVCase and must be preserved by the projection ledger."),
    invariant("INV-045", "V05Projection", "exportV05(importV05(x,ledger),ledger)=x", "Every valid v0.5 instance round-trips byte-semantically, including IDs, array order, null/missing distinctions and enum lexemes.", profile="compatibility"),
    invariant("INV-046", "V05Projection", "reverseRoundTripRequires(isV05Representable(v2) or completeLedger(v2))", "V2-to-v0.5 reverse projection is total only for the representable subset or with a complete sidecar ledger.", profile="compatibility"),
    invariant("INV-047", "V05Projection", "mainScenario is serialized before variants", "The v0.5 compatibility view keeps the main scenario first for existing backend selection behavior.", profile="compatibility"),
    invariant("INV-048", "V05Projection", "preserveAgentEntityAlias(AG_id,ENT_AGENT_id)", "The two existing Agent identities and their provenance are preserved exactly.", profile="compatibility"),
    invariant("INV-049", "TransitionEvent", "not oclIsKindOf(Timing::Event)", "Annex C TransitionEvent is EAElement plus BehaviorConstraintParameter, not a Timing::Event subtype.", profile="annex-c"),
    invariant("INV-050", "TransitionEvent", "occurredExecutionEvent->forAll(oclIsKindOf(Timing::Event))", "The Annex C connection to Timing::Event is an association only.", profile="annex-c"),
    invariant("INV-051", "AnnexCBridge", "optional=true and preliminary=true and not Core.imports(AnnexCBridge)", "Annex C mapping is optional and preliminary and creates no Core back-dependency.", profile="annex-c"),
    invariant("INV-052", "FeatureBridge", "optional=true and not Core.imports(FeatureBridge)", "Generic/VehicleFeature mapping is optional; the domain-independent Core has no automotive dependency.", profile="feature"),
    invariant("INV-053", "AgentKnowledge", "optional=true and not Core.imports(AgentKnowledge)", "Knowledge/perception/provenance support is optional and does not invalidate existing Agent instances.", profile="agent-knowledge"),
    invariant("INV-054", "CapabilityFunctionMapping", "capabilityUse->notEmpty() and prototypeTarget->notEmpty() implies prototypeTarget.type = mappedTypeFor(capabilityUse.type)", "A CapabilityUse-to-function-prototype mapping must use a prototype whose type matches the function type mapped for the same Capability."),
    invariant("INV-055", "BehaviorConstraintType", "targetBindings(self).targets()->notEmpty() or refinedRequirements(self)->notEmpty()", "An Annex C BehaviorConstraintType references at least one requirement, vehicle feature, mode, function type, function behavior, function trigger or error behavior definition.", profile="annex-c"),
    invariant("INV-056", "RuntimeStimulus", "scenarioEvent->notEmpty() or runtimeAction->notEmpty()", "A concrete RuntimeStimulus identifies at least one ScenarioEvent or RuntimeAction."),
    invariant("INV-057", "Agent", "responsibleZone.kind=zone and groundedAsset.kind=asset", "Agent responsibility and grounding references retain the Unity-visible zone/asset meaning."),
    invariant("INV-058", "Refine", "refinedBy->forAll(not oclIsKindOf(Requirement) and not oclIsKindOf(RequirementContainer))", "The exact Refine.refinedBy role excludes Requirement and RequirementContainer."),
    invariant("INV-059", "FunctionTrigger", "triggerPolicy=EVENT implies port->notEmpty()", "An event-driven FunctionTrigger references at least one triggering port."),
    invariant("INV-060", "FunctionTrigger", "triggerPolicy=TIME implies port->isEmpty()", "A time-driven FunctionTrigger has no triggering port."),
    invariant("INV-061", "FunctionTrigger", "function->notEmpty() xor functionPrototype->notEmpty()", "A FunctionTrigger identifies either one FunctionType or one FunctionPrototype, never both."),
    invariant("INV-062", "FunctionTrigger", "port->forAll(oclIsKindOf(FunctionFlowPort) and direction=in)", "Every triggering port is an input FunctionFlowPort."),
    invariant("INV-063", "DynamicFunctionalModel", "requirementsModel->size()=1", "The RCM application profile requires exactly one RequirementsModel in addition to exactly one VerificationValidation container."),
    invariant("INV-064", "CapabilityUse", "provider->notEmpty() implies scenarioStep.performedBy->includes(provider) and provider.providedCapability->includes(type)", "An explicit CapabilityUse provider must perform the owning step and provide the referenced Capability type."),
    invariant("INV-065", "CapabilityUse", "provider->size()=1", "Every CapabilityUse in the executable authoring profile has exactly one explicit provider; the compatibility core remains [0..1] because legacy data cannot identify one unambiguously.", profile="executable"),
    invariant("INV-066", "Assertion", "not self.oclIsTypeOf(Assertion) and subject->size()=1 and expression->size()=1", "Only concrete Assertion specializations may be instantiated, each with exactly one identifiable subject and one EAExpression."),
    invariant("INV-067", "AssertionResult", "assertion->size()=1 and verdict->size()=1", "Each structured result evaluates exactly one Assertion and records exactly one verdict."),
    invariant("INV-068", "RuntimeActualOutcome", "result->size()>=1", "Every runtime actual outcome contains at least one structured AssertionResult."),
    invariant("INV-069", "RuntimeValidationTarget", "platform->size()=1 and runtimeBinding->forAll(rb | element->includes(rb))", "Every runtime target names one platform and exposes every configured RuntimeBinding through the inherited VVTarget.element role."),
    invariant("INV-070", "ValidationCase", "vvSubject->forAll(s | s.oclIsKindOf(ScenarioStep) or s.oclIsKindOf(Capability) or s.oclIsKindOf(RuntimeBinding) or s.oclIsKindOf(Entity))", "RCM ValidationCase subjects are ScenarioSteps, Capabilities, RuntimeBindings or Entities while EAST-ADL VVCase.vvSubject remains unchanged."),
    invariant("INV-071", "StepRelation", "sourceStep.scenario = targetStep.scenario", "Both endpoints of a StepRelation belong to the same owning Scenario."),
    invariant("INV-072", "ParallelGroup", "memberStep->forAll(s | s.scenario = self.scenario) and memberStep->size()>=2 and boundedByReachableForkJoin(self)", "A ParallelGroup is owned with at least two members in one Scenario, structurally between matching fork and join relations."),
    invariant("INV-073", "StepRelation", "probability->notEmpty() implies (kind=alternative or kind=exception)", "A control-flow probability is permitted only on alternative or exception edges."),
    invariant("INV-074", "Scenario", "completeProbabilisticBranches()->forAll(b | abs(b.outgoing.probability.value->sum()-1.0)<0.000001)", "If every alternative/exception edge of a branch carries a probability, the complete branch probabilities sum to one."),
    invariant("INV-075", "Entity", "sceneObjects()->forAll(t | decidingOwners(t)->size() <= 1)", "Every scene object has at most one provider at the first nonempty asset/group/zone responsibility level; no fallback follows an ambiguity.", profile="executable"),
    invariant("INV-076", "Entity", "sceneObjects()->forAll(t | decidingOwners(t)->notEmpty())", "Every scene object has an owner at some responsibility level; together INV-075 and INV-076 require exactly one deciding provider.", profile="executable"),
    invariant("INV-077", "CapabilityUse", "sceneObjects()->forAll(t | uniqueAnsweringPath(decidingProvider(t), t))", "Each uniquely owned scene object has one native ScenarioStep-to-CapabilityUse-to-Capability-to-RuntimeBinding-to-RuntimeAction answering path and one matching chat trace projection.", profile="executable"),
    invariant("INV-078", "Agent", "handoffTarget->isUnique(id) and handoffTarget->excludes(self) and handoffTarget->forAll(oclIsKindOf(Agent))", "Handoff references identify distinct other agents, without self-loops or duplicates.", profile="executable"),
    invariant("INV-079", "Entity", "sharedGroupOrZoneOwners()->forAll(e | members(e)->forAll(t | assetOwners(t)->size()=1))", "Warn when a group or zone has several owners and any member lacks unique asset-level coverage; fully shielded shared ownership is also reported.", severity="warning", profile="executable"),
    invariant("INV-080", "Agent|Entity", "agentObjectPairs()->report(shortestHandoffs > 1 or noPath)", "Report every start-agent/object pair needing more than one handoff or having no directed path; these pairs reject at runtime and do not invalidate publication.", severity="report", profile="executable"),
    invariant("INV-081", "ProjectPublication", "digestScheme='sha256-lf-v1' and declarationsMatch(SHA256(normalizeCRLF(serializedModel)))", "Project and trace declare sha256-lf-v1 and a matching model digest. This is a project-level publication obligation, not a metamodel class.", profile="executable"),

]


VIEWS: dict[str, dict[str, Any]] = {
    "dynamic_functional_rdl_v2_metamodel": {
        "kind": "overview",
        "title": "Compact metamodel for Dynamic Functional RDL (V2)",
        "description": "Central EAST-ADL-aligned A/B/C overview; seven detailed views cover the complete model.",
        "rows": [
            [
                f"{P_CORE}::DynamicFunctionalModel",
                f"{P_REQUIREMENTS}::RequirementsModel",
                f"{P_REQUIREMENTS}::Requirement",
                f"{P_REQUIREMENTS}::Satisfy",
                f"{P_USECASES}::Actor",
                f"{P_CORE}::ActorParticipation",
                f"{P_USECASES}::UseCase",
                f"{P_CORE}::UseCaseScenarioSpecification",
                f"{P_USECASES}::ExtensionPoint",
                f"{P_USECASES}::Include",
                f"{P_USECASES}::Extend",
                f"{P_CORE}::ConditionalExtend",
            ],
            [
                f"{P_CORE}::ScenarioEvent",
                f"{P_CORE}::Scenario",
                f"{P_CORE}::ScenarioCondition",
                f"{P_CORE}::ScenarioStep",
                f"{P_CORE}::StepRelation",
                f"{P_CORE}::ParallelGroup",
                f"{P_CORE}::Assertion",
                f"{P_CORE}::StateAssertion",
                f"{P_CORE}::ProbabilityValue",
                f"{P_CORE}::CapabilityUse",
            ],
            [
                f"{P_CORE}::Agent",
                f"{P_CORE}::Entity",
                f"{P_CORE}::Capability",
                f"{P_CORE}::Effect",
                f"{P_CORE}::CapabilityBehaviorBinding",
                f"{P_BEHAVIOR}::FunctionBehavior",
                f"{P_CORE}::RuntimeBinding",
                f"{P_CORE}::RuntimeAction",
                f"{P_VV}::VerificationValidation",
                f"{P_CORE}::ValidationCase",
                f"{P_CORE}::RuntimeValidationProcedure",
                f"{P_CORE}::RuntimeStimulus",
                f"{P_CORE}::StateAssertionOutcome",
                f"{P_CORE}::RuntimeValidationLog",
                f"{P_CORE}::RuntimeActualOutcome",
                f"{P_CORE}::RuntimeValidationTarget",
                f"{P_CORE}::AssertionResult",
            ],
        ],
    },
    "01_east_adl_infrastructure": {
        "title": "EAST-ADL V2.1.12 – selected infrastructure slice",
        "description": "Exact selected infrastructure, datatype and value inheritance.",
        "row_labels": ["Element and type bases", "Values and datatypes", "Identifiable elements", "Packageable elements", "Contexts"],
        "rows": [
            [f"{P_ELEMENTS}::Referrable", f"{P_ELEMENTS}::EAType", f"{P_ELEMENTS}::EAPrototype", f"{P_ELEMENTS}::EAPort", f"{P_ELEMENTS}::EAConnector", f"{P_VALUES}::EAValue"],
            [f"{P_DATATYPES}::EADatatype", f"{P_DATATYPES}::EADatatypePrototype", f"{P_VALUES}::EAExpression", f"{P_VALUES}::EANumericalValue"],
            [f"{P_ELEMENTS}::Identifiable", f"{P_ELEMENTS}::EAElement", f"{P_DATATYPES}::EABoolean", f"{P_DATATYPES}::EANumerical"],
            [f"{P_ELEMENTS}::EAPackageableElement", f"{P_ELEMENTS}::Relationship", f"{P_ELEMENTS}::Comment"],
            [f"{P_ELEMENTS}::Context", f"{P_ELEMENTS}::TraceableSpecification"],
        ],
        "diagram_association_ids": ["EAElement_ownedComment", "Context_ownedRelationship", "Context_traceableSpecification", "EADatatypePrototype_type", "EAValue_type"],
    },
    "02_east_adl_requirements_usecases": {
        "title": "EAST-ADL Requirements/UseCases – selected slice",
        "description": "Unmodified Requirements and UseCases metaclasses plus their exact infrastructure bases.",
        "row_labels": ["EAST-ADL bases", "Requirements and UseCases", "UseCase relationships", "Requirements relationships"],
        "rows": [
            [f"{P_ELEMENTS}::Context", f"{P_ELEMENTS}::TraceableSpecification", f"{P_ELEMENTS}::EAElement"],
            [f"{P_REQUIREMENTS}::RequirementsModel", f"{P_REQUIREMENTS}::Requirement", f"{P_USECASES}::Actor", f"{P_USECASES}::UseCase", f"{P_ELEMENTS}::Relationship", f"{P_USECASES}::RedefinableElement"],
            [f"{P_REQUIREMENTS}::RequirementsRelationship", f"{P_USECASES}::Include", f"{P_USECASES}::Extend", f"{P_USECASES}::ExtensionPoint"],
            [f"{P_REQUIREMENTS}::Satisfy", f"{P_REQUIREMENTS}::Refine", f"{P_VV}::Verify"],
        ],
        "diagram_association_ids": [
            "RequirementsModel_requirement", "Satisfy_satisfiedRequirement",
            "UseCase_include", "UseCase_extend",
            "Extend_extensionLocation",
        ],
    },
    "03_east_adl_function_system_behavior": {
        "title": "EAST-ADL Function/System/Behavior – selected slice",
        "description": "Exact type/prototype, FAA/FDA root, connector and behavior semantics.",
        "row_labels": ["EAST-ADL bases", "Generic function structure", "Analysis and design", "Architecture contexts"],
        "rows": [
            [f"{P_ELEMENTS}::EAType", f"{P_ELEMENTS}::EAPrototype", f"{P_ELEMENTS}::EAElement", f"{P_ELEMENTS}::EAPort", f"{P_ELEMENTS}::EAConnector", f"{P_ELEMENTS}::Context"],
            [f"{P_FUNCTION}::FunctionType", f"{P_FUNCTION}::FunctionPrototype", f"{P_FUNCTION}::FunctionPort", f"{P_FUNCTION}::FunctionConnector", f"{P_FUNCTION}::PortGroup", f"{P_FUNCTION}::FunctionFlowPort", f"{P_BEHAVIOR}::FunctionBehavior"],
            [f"{P_FUNCTION}::AnalysisFunctionType", f"{P_FUNCTION}::AnalysisFunctionPrototype", f"{P_FUNCTION}::DesignFunctionType", f"{P_FUNCTION}::DesignFunctionPrototype"],
            [f"{P_SYSTEM}::AnalysisLevel", f"{P_SYSTEM}::DesignLevel"],
        ],
        "diagram_association_ids": [
            "FunctionConnector_port", "FunctionType_port", "FunctionType_connector", "PortGroup_portGroup",
            "AnalysisFunctionPrototype_type", "AnalysisFunctionType_part",
            "DesignFunctionPrototype_type", "DesignFunctionType_part",
        ],
    },
    "04_rcm_scenario_flow": {
        "title": "RCM V2 – conservative scenario and control-flow core",
        "description": "UseCase binding, actor/entity separation, typed events/conditions and canonical control flow.",
        "row_labels": [
            "EAST-ADL bases",
            "UseCase and role binding",
            "Scenario",
            "Control flow",
            "Events, conditions and probabilities",
            "Abstract assertion base",
            "Specialized assertion kinds",
        ],
        "rows": [
            [f"{P_ELEMENTS}::Context", f"{P_ELEMENTS}::TraceableSpecification", f"{P_ELEMENTS}::Relationship", f"{P_ELEMENTS}::Identifiable", f"{P_TIMING}::Event", f"{P_VALUES}::EAExpression"],
            [f"{P_CORE}::DynamicFunctionalModel", f"{P_USECASES}::Actor", f"{P_CORE}::ActorParticipation", f"{P_USECASES}::UseCase", f"{P_CORE}::UseCaseScenarioSpecification", f"{P_CORE}::ConditionalExtend"],
            [f"{P_CORE}::Scenario"],
            [f"{P_CORE}::ScenarioStep", f"{P_CORE}::StepRelation", f"{P_CORE}::ParallelGroup"],
            [f"{P_CORE}::Entity", f"{P_EVENTS}::ExternalEvent", f"{P_CORE}::ScenarioEvent", f"{P_CORE}::ScenarioExternalEvent", f"{P_CORE}::ScenarioCondition", f"{P_CORE}::ProbabilityValue", f"{P_CORE}::Probability"],
            [f"{P_CORE}::Assertion"],
            [f"{P_CORE}::StateAssertion", f"{P_CORE}::EventAssertion", f"{P_CORE}::OutputAssertion", f"{P_CORE}::GroundingAssertion", f"{P_CORE}::RelationAssertion"],
        ],
        "diagram_association_ids": [
            "UseCaseScenarioSpecification_useCase", "UseCaseScenarioSpecification_scenario",
            "ActorParticipation_actor",
            "Scenario_step", "Scenario_stepRelation", "Scenario_parallelGroup",
            "StepRelation_sourceStep", "StepRelation_targetStep", "StepRelation_probability",
        ],
        "same_row_route_sides": {"StepRelation_sourceStep": "bottom"},
        "adjacent_route_shifts": {"StepRelation_probability": 70.0},
        "source_port_shifts": {"StepRelation_probability": 120.0},
    },
    "05_rcm_capability_runtime": {
        "layout": "capability_runtime",
        "title": "RCM V2 – Capability, Function and Runtime bridge",
        "description": "EAType/EAPrototype capability pattern, optional exact function mapping and ordered runtime realization.",
        "row_labels": ["EAST-ADL bases", "Capability core", "Technical runtime realization", "Behavior and function mapping", "EAST-ADL function targets"],
        "rows": [
            [f"{P_ELEMENTS}::Identifiable", f"{P_ELEMENTS}::EAType", f"{P_ELEMENTS}::EAPrototype", f"{P_ELEMENTS}::EAElement", f"{P_ELEMENTS}::TraceableSpecification", f"{P_ELEMENTS}::Relationship"],
            [f"{P_CORE}::Entity", f"{P_CORE}::Agent", f"{P_CORE}::CapabilityUse", f"{P_CORE}::Capability", f"{P_CORE}::Effect", f"{P_CORE}::Assertion"],
            [f"{P_CORE}::KeyValueParameter", f"{P_CORE}::ParameterBinding", f"{P_CORE}::RuntimeBinding", f"{P_CORE}::RuntimeAction", f"{P_CORE}::RuntimeActionLocator", f"{P_CORE}::SchemaReference", f"{P_CORE}::RuntimeParameter"],
            [f"{P_CORE}::CapabilityFunctionMapping", f"{P_CORE}::CapabilityBehaviorBinding", f"{P_BEHAVIOR}::FunctionBehavior"],
            [f"{P_FUNCTION}::AnalysisFunctionType", f"{P_FUNCTION}::AnalysisFunctionPrototype", f"{P_FUNCTION}::DesignFunctionType", f"{P_FUNCTION}::DesignFunctionPrototype"],
        ],
        "diagram_association_ids": [
            "CapabilityUse_type", "CapabilityUse_provider", "CapabilityUse_target",
            "Capability_effect", "Effect_specifiedBy",
            "RuntimeBinding_capability", "RuntimeBinding_runtimeAction", "RuntimeAction_locator",
            "CapabilityFunctionMapping_analysisType", "CapabilityFunctionMapping_designType",
            "CapabilityBehaviorBinding_functionBehavior",
        ],
    },
    "06_east_adl_rcm_verification_validation": {
        "title": "EAST-ADL / RCM V2 – Verification & Validation",
        "description": "Exact V&V container ownership with RCM specializations, logs and distinct subject/target semantics.",
        "row_labels": ["Requirements and infrastructure links", "EAST-ADL V&V container", "EAST-ADL V&V flow", "RCM specializations", "Bindings, assertions and results"],
        "rows": [
            [f"{P_ELEMENTS}::Context", f"{P_ELEMENTS}::TraceableSpecification", f"{P_ELEMENTS}::Identifiable", f"{P_REQUIREMENTS}::RequirementsRelationship", f"{P_REQUIREMENTS}::Requirement", f"{P_VV}::Verify"],
            [f"{P_VV}::VerificationValidation"],
            [f"{P_VV}::VVTarget", f"{P_VV}::VVCase", f"{P_VV}::VVProcedure", f"{P_VV}::VVStimuli", f"{P_VV}::VVIntendedOutcome", f"{P_VV}::VVLog", f"{P_VV}::VVActualOutcome"],
            [f"{P_CORE}::RuntimeValidationTarget", f"{P_CORE}::ValidationCase", f"{P_CORE}::RuntimeValidationProcedure", f"{P_CORE}::RuntimeStimulus", f"{P_CORE}::AssertionOutcome", f"{P_CORE}::StateAssertionOutcome", f"{P_CORE}::RuntimeValidationLog", f"{P_CORE}::RuntimeActualOutcome"],
            [f"{P_CORE}::RuntimeBinding", f"{P_CORE}::ValidationCaseUseCaseBinding", f"{P_USECASES}::UseCase", f"{P_CORE}::StateAssertion", f"{P_CORE}::Assertion", f"{P_VALUES}::EAValue", f"{P_CORE}::AssertionResult"],
        ],
        "diagram_association_ids": [
            "VerificationValidation_vvCase", "VVCase_vvTarget",
            "VVLog_vvActualOutcome",
            "VVProcedure_vvStimuli", "VVProcedure_vvIntendedOutcome",
            "AssertionOutcome_assertion", "AssertionResult_assertion", "AssertionResult_observedValue",
            "RuntimeActualOutcome_result", "RuntimeValidationTarget_runtimeBinding",
            "ValidationCaseUseCaseBinding_useCase",
        ],
        "same_row_route_sides": {
            "ValidationCaseUseCaseBinding_useCase": "bottom",
            "AssertionResult_assertion": "bottom",
            "AssertionResult_observedValue": "top",
        },
    },
    "07_optional_annex_feature_knowledge": {
        "layout": "optional_modules",
        "title": "RCM V2 – optional Annex C, Feature and Knowledge modules",
        "description": "Optional one-way bridges; Annex C is preliminary and TransitionEvent is not Timing::Event.",
        "row_labels": ["Core anchors", "Optional bridges", "Annex C", "Target models and knowledge"],
        "rows": [
            [f"{P_CORE}::ScenarioStep", f"{P_CORE}::StepRelation", f"{P_CORE}::ScenarioEvent", f"{P_CORE}::StateAssertion", f"{P_CORE}::Capability", f"{P_CORE}::Agent", f"{P_CORE}::Entity"],
            [f"{P_ANNEX_BRIDGE}::ScenarioAnnexMapping", f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintTargetBinding", f"{P_ANNEX_BEHAVIOR}::BehaviorConstraintType", f"{P_FEATURE_BRIDGE}::CapabilityFeatureMapping", f"{P_KNOWLEDGE}::AgentKnowledgeBinding"],
            [f"{P_ANNEX_COMPUTATION}::LogicalTransformation", f"{P_ANNEX_COMPUTATION}::TransformationOccurrence", f"{P_ANNEX_COMPUTATION}::LogicalPath", f"{P_ANNEX_VALUE}::Quantification", f"{P_ANNEX_TEMPORAL}::LogicalTimeCondition", f"{P_ANNEX_TEMPORAL}::State", f"{P_ANNEX_TEMPORAL}::TransitionEvent"],
            [f"{P_TIMING}::Event", f"{P_BEHAVIOR}::FunctionTrigger", f"{P_BEHAVIOR}::FunctionBehavior", f"{P_FUNCTION}::FunctionType", f"{P_FEATURE}::Feature", f"{P_VEHICLE_FEATURE}::VehicleFeature", f"{P_KNOWLEDGE}::KnowledgeItem", f"{P_KNOWLEDGE}::KnowledgeSource"],
        ],
        "diagram_association_ids": [
            "BehaviorConstraintTargetBinding_behaviorConstraintType", "BehaviorConstraintTargetBinding_targetedFunctionType",
            "LogicalPath_transformationOccurrence",
            "TransformationOccurrence_invokedLogicalTransformation", "TransitionEvent_occurredExecutionEvent",
            "ScenarioAnnexMapping_scenarioStep",
            "CapabilityFeatureMapping_capability", "CapabilityFeatureMapping_feature",
            "AgentKnowledgeBinding_agent", "AgentKnowledgeBinding_knowledgeItem",
        ],
    },
}


COMPATIBILITY_CONTRACT: dict[str, Any] = {
    "source_version": "Dynamic Functional RDL v0.5",
    "projection_name": "V05ProjectionLedger",
    "canonical_v2_independence": "The v0.5 JSON schema and runtime implementation remain unchanged.",
    "laws": [
        "exportV05(importV05(x, ledger), ledger) == x for every valid v0.5 instance",
        "importV05(exportV05(y, ledger), ledger) == y only for the v0.5-representable V2 subset or a complete ledger",
    ],
    "ledger_preserves": [
        "complete envelope and unknown extension data",
        "array order and main-scenario-first ordering",
        "presence versus explicit null versus empty values",
        "all opaque identifiers and enum lexemes",
        "raw stepNumber and storage order",
        "AG-* to ENT-AGENT-* alias/provenance pairs",
        "legacy ValidationCase.level without deriving it from abstractVVCase",
        "legacy endpoint/tool/topic slots while V2 uses one RuntimeActionLocator",
    ],
    "required_chain": ["ScenarioStep", "CapabilityUse", "Capability", "RuntimeBinding", "RuntimeAction"],
    "forbidden_shortcut": "ScenarioStep -> RuntimeAction",
}


ANNEX_MAPPINGS: list[dict[str, Any]] = [
    {"source": "ScenarioStep", "target": "LogicalTransformation / TransformationOccurrence", "kind": "optional-semantic", "status": "preliminary"},
    {"source": "StepRelation.sequence", "target": "LogicalPath.segment", "kind": "optional-semantic", "status": "preliminary"},
    {"source": "ParallelGroup and fork/join", "target": "LogicalPath.strand", "kind": "optional-semantic", "status": "preliminary"},
    {"source": "ScenarioEvent", "target": "TransitionEvent.occurredExecutionEvent -> Timing::Event", "kind": "association-bridge", "status": "preliminary"},
    {"source": "ScenarioCondition value condition", "target": "Quantification", "kind": "optional-semantic", "status": "preliminary"},
    {"source": "ScenarioCondition timing condition", "target": "LogicalTimeCondition", "kind": "optional-semantic", "status": "preliminary"},
    {"source": "StateAssertion", "target": "State / Quantification / VVIntendedOutcome", "kind": "context-dependent", "status": "preliminary"},
    {"source": "Capability behavior", "target": "BehaviorConstraintType", "kind": "optional-semantic", "status": "preliminary"},
]


MODEL: dict[str, Any] = {
    "metadata": {
        "name": "Dynamic Functional RDL V2",
        "namespace": "RCM::V2",
        "model_version": "2.1.0-executable",
        "status": "executable-routing-profile",
        "date": "2026-10-15",
        "east_adl_version": "2.1.12",
        "east_adl_specification_sha256": "6B1645C4FA668DBFA8AF24C37B83BC0B7343B9B6284E1DD29E1085B10BC59C3D",
        "canonical_source": "tools/dynamic_functional_rdl_v2_model.py",
        "scope": "native V2 model consumed by backend and authoring pipeline; executable routing profile with publish-time verification",
    },
    "packages": PACKAGES,
    "primitives": PRIMITIVES,
    "enums": ENUMS,
    "datatypes": DATATYPES,
    "classes": CLASSES,
    "associations": ASSOCIATIONS,
    "invariants": INVARIANTS,
    "invariant_index": [entry["id"] for entry in INVARIANTS],
    "views": VIEWS,
    "compatibility_contract": COMPATIBILITY_CONTRACT,
    "annex_mappings": ANNEX_MAPPINGS,
}


__all__ = ["MODEL"]
