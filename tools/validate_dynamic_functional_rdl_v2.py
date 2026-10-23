from __future__ import annotations

"""Executable structural and semantic validation for Dynamic Functional RDL V2.

The validator deliberately consumes the canonical, data-only ``MODEL`` mapping
instead of inspecting generated diagrams or prose.  It therefore catches a
model mutation even when the generated documentation still happens to contain
the expected words.  The accepted mapping shape is documented by
``dynamic_functional_rdl_v2_model.py``; the small adapter functions in this
module also accept list-based sections to make fixture construction convenient.

The CLI writes machine-readable JSON and a compact Markdown evidence report to
``output/metamodel_v2/evidence`` by default.
"""

import argparse
import importlib
import importlib.util
import json
import re
import sys
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = ROOT / "output" / "metamodel_v2" / "evidence"

# Explicit evidence registry, separate from generic invariant-ID synchronization.
# Unmapped statements are not credited as enforced without an audited negative fixture.
INVARIANT_CHECK_REGISTRY = {
    f"INV-{number:03d}": {"status": "not enforced", "check_codes": [], "fixture": "", "evidence": "No complete check-and-negative-fixture enforcement audit; related checks may exist."}
    for number in range(1, 82)
}
INVARIANT_CHECK_REGISTRY.update({
    "INV-064": {"status": "enforced", "check_codes": ["ICAP004", "ICAP005"], "fixture": "tests/fixtures/routing/inv064_fail.json", "evidence": "InstanceValidator.check_capability_uses; tests/test_routing_verifier.py::test_existing_invariant_evidence"},
    "INV-065": {"status": "enforced", "check_codes": ["ICAP002"], "fixture": "tests/fixtures/routing/inv065_fail.json", "evidence": "Executable fixture profile; tests/test_routing_verifier.py::test_existing_invariant_evidence"},
})
for _number in range(75, 82):
    INVARIANT_CHECK_REGISTRY[f"INV-{_number:03d}"] = {
        "status": "enforced" if _number not in (79, 80) else "warning" if _number == 79 else "report",
        "check_codes": [f"ROUTE{_number:03d}"],
        "fixture": f"tests/fixtures/routing/inv{_number:03d}_fail.json",
        "evidence": "tools.routing_verifier.CHECK_REGISTRY; tests/test_routing_verifier.py::test_each_new_invariant_pass_and_fail",
    }



@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    location: str = "model"
    severity: str = "error"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    title: str
    status: str
    issue_count: int


@dataclass
class ValidationReport:
    subject: str
    issues: list[ValidationIssue] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    def codes(self) -> set[str]:
        return {issue.code for issue in self.issues}

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "ok": self.ok,
            "generated_at": self.generated_at,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "checks": [asdict(check) for check in self.checks],
            "evidence": _plain(self.evidence),
            "issues": [asdict(issue) for issue in self.issues],
        }


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _records(section: Any) -> list[dict[str, Any]]:
    """Normalize a dict- or list-based model section into record mappings."""

    section = _plain(section)
    if section is None:
        return []
    if isinstance(section, Mapping):
        records: list[dict[str, Any]] = []
        for key, value in section.items():
            if isinstance(value, Mapping):
                record = dict(value)
            else:
                record = {"value": value}
            record.setdefault("_key", str(key))
            record.setdefault("name", str(key).split("::")[-1])
            records.append(record)
        return records
    if isinstance(section, Sequence) and not isinstance(section, (str, bytes)):
        result = []
        for index, value in enumerate(section):
            if isinstance(value, Mapping):
                result.append(dict(value))
            else:
                result.append({"name": str(value), "_key": str(index)})
        return result
    return []


def _simple(name: Any) -> str:
    text = str(name or "")
    text = re.sub(r"\s*\[[^]]*]\s*$", "", text)
    text = re.sub(r"\s*\{[^}]*}\s*$", "", text)
    text = text.replace("/", "::").replace(".", "::")
    return text.split("::")[-1].strip()


def _mult(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    text = text.strip("[] ")
    text = text.replace(" ", "")
    aliases = {"*": "0..*", "many": "0..*", "one": "1", "optional": "0..1"}
    return aliases.get(text.lower(), text)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    return [value]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "source", "owned"}


def _package_family(name: Any) -> str:
    lowered = str(name or "").lower().replace("_", "-")
    if "annex" in lowered:
        return "annex"
    if "rcm" in lowered or "dynamicfunctional" in lowered:
        return "rcm"
    if "east" in lowered:
        return "east"
    return "other"


def _type_parts(type_name: Any) -> list[str]:
    if not type_name:
        return []
    text = str(type_name)
    text = re.sub(r"\[[^]]*]", "", text)
    text = re.sub(r"\b(?:Set|Sequence|OrderedSet|Bag|List|Optional)\s*[<(]", "", text)
    text = text.replace(">", "").replace(")", "")
    return [part.strip() for part in re.split(r"\s*[|,]\s*", text) if part.strip()]


class ModelIndex:
    def __init__(self, model: Mapping[str, Any]):
        self.model = _plain(model)
        self.classes = _records(self.model.get("classes"))
        self.enums = _records(self.model.get("enums"))
        self.datatypes = _records(self.model.get("datatypes"))
        self.packages = _records(self.model.get("packages"))
        self.associations = _records(self.model.get("associations"))
        self.invariants = _records(self.model.get("invariants"))
        self.class_by_qname: dict[str, dict[str, Any]] = {}
        self.class_by_simple: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for cls in self.classes:
            qname = str(cls.get("qualified_name") or cls.get("qname") or cls.get("_key") or cls.get("name"))
            cls.setdefault("qualified_name", qname)
            self.class_by_qname[qname] = cls
            self.class_by_simple[_simple(cls.get("name") or qname)].append(cls)
        self.enum_by_simple = {_simple(item.get("name") or item.get("_key")): item for item in self.enums}
        self.datatype_by_simple = {_simple(item.get("name") or item.get("_key")): item for item in self.datatypes}
        primitives = self.model.get("primitives", [])
        if isinstance(primitives, Mapping):
            primitives = list(primitives)
        self.primitives = {
            _simple(item)
            for item in _as_list(primitives)
        } | {
            "String", "Boolean", "Integer", "Real", "Float", "Double",
            "Number", "Natural", "UnlimitedNatural", "Identifier", "UUID",
            "URI", "DateTime", "Any", "Object", "Numerical",
        }

    def class_(self, name: Any, *, prefer_east: bool = False) -> dict[str, Any] | None:
        text = str(name or "")
        if text in self.class_by_qname:
            return self.class_by_qname[text]
        matches = self.class_by_simple.get(_simple(text), [])
        if not matches:
            return None
        if prefer_east:
            east = [item for item in matches if _package_family(item.get("package")) == "east"]
            if len(east) == 1:
                return east[0]
        return matches[0] if len(matches) == 1 else None

    def bases(self, cls: Mapping[str, Any]) -> set[str]:
        return {_simple(item) for item in _as_list(cls.get("bases") or cls.get("base"))}

    def ancestors(self, cls: Mapping[str, Any]) -> set[str]:
        found: set[str] = set()
        queue = deque(self.bases(cls))
        while queue:
            name = queue.popleft()
            if name in found:
                continue
            found.add(name)
            parent = self.class_(name, prefer_east=True)
            if parent:
                queue.extend(self.bases(parent))
        return found

    def is_subclass(self, cls_or_name: Any, base: str) -> bool:
        cls = cls_or_name if isinstance(cls_or_name, Mapping) else self.class_(cls_or_name)
        if not cls:
            return False
        return _simple(cls.get("name")) == base or base in self.ancestors(cls)

    def attributes(self, cls_or_name: Any) -> list[dict[str, Any]]:
        cls = cls_or_name if isinstance(cls_or_name, Mapping) else self.class_(cls_or_name)
        return _records(cls.get("attributes")) if cls else []

    def attr(self, cls_or_name: Any, name: str) -> dict[str, Any] | None:
        return next((item for item in self.attributes(cls_or_name) if item.get("name") == name), None)

    def associations_from(self, name: str) -> list[dict[str, Any]]:
        return [item for item in self.associations if _simple(item.get("source")) == name]

    def associations_to(self, name: str) -> list[dict[str, Any]]:
        return [item for item in self.associations if _simple(item.get("target")) == name]


class ModelValidator:
    EXACT_EAST_BASES: dict[str, set[str]] = {
        "Referrable": set(),
        "Identifiable": {"Referrable"},
        "EAElement": {"Identifiable"},
        "EAPackageableElement": {"EAElement"},
        "Context": {"EAPackageableElement"},
        "Relationship": {"EAElement"},
        "RequirementsRelationship": {"Relationship"},
        "RedefinableElement": {"EAElement"},
        "TraceableSpecification": {"EAPackageableElement"},
        "EAType": set(),
        "EAPrototype": set(),
        "EAPort": set(),
        "EAConnector": set(),
        "RequirementsModel": {"Context"},
        "Requirement": {"TraceableSpecification"},
        "Actor": {"TraceableSpecification"},
        "UseCase": {"TraceableSpecification"},
        "ExtensionPoint": {"RedefinableElement"},
        "Include": {"Relationship"},
        "Extend": {"Relationship"},
        "Satisfy": {"RequirementsRelationship"},
        "EADatatype": {"TraceableSpecification"},
        "EABoolean": {"EADatatype"},
        "EAExpression": {"EAValue"},
        "EANumerical": {"EADatatype"},
        "EANumericalValue": {"EAValue"},
        "FunctionBehavior": {"Context"},
        "FunctionType": {"EAType", "Context"},
        "FunctionPrototype": {"EAElement", "EAPrototype"},
        "FunctionPort": {"EAPort", "EAElement"},
        "FunctionConnector": {"AllocateableElement", "EAConnector", "EAElement"},
        "AnalysisFunctionType": {"FunctionType"},
        "AnalysisFunctionPrototype": {"FunctionPrototype"},
        "DesignFunctionType": {"FunctionType"},
        "DesignFunctionPrototype": {"FunctionPrototype", "AllocateableElement"},
        "TimingDescription": {"EAElement"},
        "Event": {"TimingDescription"},
        "ExternalEvent": {"Event"},
        "Mode": {"EAElement"},
        "VerificationValidation": {"Context"},
        "VVCase": {"TraceableSpecification"},
        "VVProcedure": {"TraceableSpecification"},
        "VVStimuli": {"TraceableSpecification"},
        "VVIntendedOutcome": {"TraceableSpecification"},
        "VVActualOutcome": {"TraceableSpecification"},
        "VVTarget": {"TraceableSpecification"},
        "VVLog": {"TraceableSpecification"},
        "Verify": {"RequirementsRelationship"},
        "FeatureTreeNode": {"Context"},
    }

    REQUIRED_EAST_CLASSES = {
        "Referrable", "Identifiable", "EAElement", "EAPackageableElement",
        "Context", "Relationship", "TraceableSpecification", "EAType",
        "EAPrototype", "RequirementsRelationship", "RedefinableElement",
        "RequirementsModel", "Requirement", "Actor", "UseCase",
        "ExtensionPoint", "Include", "Extend", "Satisfy", "EAValue",
        "EAExpression", "EADatatype", "EABoolean", "EANumerical", "EANumericalValue",
        "FunctionBehavior", "FunctionType", "FunctionPrototype", "FunctionPort",
        "FunctionConnector", "Mode", "FeatureTreeNode",
        "AnalysisFunctionType", "AnalysisFunctionPrototype",
        "DesignFunctionType", "DesignFunctionPrototype", "TimingDescription",
        "Event", "ExternalEvent", "VerificationValidation", "VVCase",
        "VVProcedure", "VVStimuli", "VVIntendedOutcome", "VVActualOutcome",
        "VVTarget", "VVLog", "Verify",
    }

    def __init__(self, model: Mapping[str, Any]):
        self.model = _plain(model)
        self.index = ModelIndex(self.model)
        metadata = self.model.get("metadata", {})
        self.report = ValidationReport(
            subject=str(metadata.get("id") or metadata.get("name") or "Dynamic Functional RDL V2")
        )

    def issue(self, code: str, message: str, location: str = "model", severity: str = "error") -> None:
        self.report.issues.append(ValidationIssue(code, message, location, severity))

    def run(self, check_id: str, title: str, method: Any) -> None:
        before = len(self.report.issues)
        method()
        count = len(self.report.issues) - before
        self.report.checks.append(CheckResult(check_id, title, "pass" if count == 0 else "fail", count))

    def validate(self) -> ValidationReport:
        checks = [
            ("META-01", "reference, type and enumeration closure", self.check_closure),
            ("EAST-01", "exact EAST-ADL bases and properties", self.check_east_exactness),
            ("META-02", "no inherited attribute shadows", self.check_shadow_attributes),
            ("PKG-01", "one-way RCM to EAST-ADL dependency", self.check_package_dependencies),
            ("OWN-01", "single composition owner and relationship ownership", self.check_ownership),
            ("INV-01", "invariant identifier synchronization", self.check_invariant_sync),
            ("ROOT-01", "exact root requirements and V&V containers", self.check_root_containers),
            ("CAP-01", "capability type/prototype pattern", self.check_capability_pattern),
            ("AST-01", "reusable assertion and assertion-result structure", self.check_assertions),
            ("VAL-01", "Boolean condition and probability datatype", self.check_values),
            ("RUN-01", "runtime locator and ordered action structure", self.check_runtime),
            ("SCN-01", "scenario variants and control-flow structure", self.check_scenarios),
            ("ENT-01", "agent discriminator contract", self.check_entity_agent),
            ("REQ-01", "Satisfy XOR and exclusions", self.check_satisfy),
            ("VV-01", "verification and validation structure", self.check_vv),
            ("FUN-01", "FunctionBehavior exact required properties", self.check_function_behavior),
            ("ARCH-01", "functional architecture is not reified", self.check_no_faa_fda),
            ("ANNEX-01", "optional preliminary Annex mapping", self.check_annex),
        ]
        for check_id, title, method in checks:
            self.run(check_id, title, method)
        return self.report

    def check_closure(self) -> None:
        index = self.index
        if not index.classes:
            self.issue("REF001", "classes section is empty", "classes")
            return
        known_simple = (
            set(index.class_by_simple)
            | set(index.enum_by_simple)
            | set(index.datatype_by_simple)
            | index.primitives
        )
        for cls in index.classes:
            qname = cls.get("qualified_name", cls.get("name", "?"))
            for base in _as_list(cls.get("bases") or cls.get("base")):
                if _simple(base) not in index.class_by_simple:
                    self.issue("REF002", f"unknown base {base!r}", f"classes.{qname}.bases")
            seen_attrs: set[str] = set()
            for attr in index.attributes(cls):
                attr_name = str(attr.get("name") or "")
                if not attr_name or attr_name in seen_attrs:
                    self.issue("REF003", f"missing or duplicate attribute name {attr_name!r}", f"classes.{qname}.attributes")
                seen_attrs.add(attr_name)
                for part in _type_parts(attr.get("type")):
                    if _simple(part) not in known_simple:
                        self.issue("REF004", f"unknown attribute type {part!r}", f"classes.{qname}.{attr_name}")
        assoc_ids: set[str] = set()
        for assoc in index.associations:
            assoc_id = str(assoc.get("id") or assoc.get("name") or "")
            if not assoc_id or assoc_id in assoc_ids:
                self.issue("REF005", f"missing or duplicate association id {assoc_id!r}", "associations")
            assoc_ids.add(assoc_id)
            for end in ("source", "target"):
                if index.class_(assoc.get(end)) is None:
                    self.issue("REF006", f"unknown association {end} {assoc.get(end)!r}", f"associations.{assoc_id}.{end}")
        for enum in index.enums:
            name = enum.get("name") or enum.get("_key")
            literals = _as_list(enum.get("literals") or enum.get("values"))
            normalized = [str(item.get("name")) if isinstance(item, Mapping) else str(item) for item in literals]
            if not normalized or any(not item for item in normalized) or len(set(normalized)) != len(normalized):
                self.issue("ENUM001", "enumeration must have unique, non-empty literals", f"enums.{name}")
        for required in self.REQUIRED_EAST_CLASSES:
            if self._east_class(required) is None:
                self.issue("REF007", f"required EAST-ADL class {required} is absent", "classes")

    def _east_class(self, name: str) -> dict[str, Any] | None:
        matches = self.index.class_by_simple.get(name, [])
        east = [item for item in matches if _package_family(item.get("package")) == "east"]
        return east[0] if len(east) == 1 else None

    def check_east_exactness(self) -> None:
        for name, expected_bases in self.EXACT_EAST_BASES.items():
            cls = self._east_class(name)
            if cls is None:
                continue
            actual = self.index.bases(cls)
            if actual != expected_bases:
                self.issue("EAST001", f"{name} bases {sorted(actual)} != {sorted(expected_bases)}", f"classes.{cls.get('qualified_name')}.bases")
        forbidden_local = {
            "Requirement": {"text"},
            "UseCase": {"text"},
            "ExtensionPoint": {"name"},
            "Extend": {"condition"},
        }
        for class_name, forbidden in forbidden_local.items():
            cls = self._east_class(class_name)
            if not cls:
                continue
            actual = {str(attr.get("name")) for attr in self.index.attributes(cls)}
            for name in sorted(actual & forbidden):
                self.issue("EAST002", f"{class_name}.{name} shadows or changes inherited EAST-ADL semantics", f"classes.{class_name}.{name}")
        required_attrs = {
            "Referrable": {"shortName": ("Identifier", "1")},
            "Identifiable": {"category": ("Identifier", "0..1"), "uuid": ("String", "0..1")},
            "EAElement": {"name": ("String", "0..1")},
            "TraceableSpecification": {"text": ("String", "0..1")},
            "Requirement": {"formalism": ("String", "0..1"), "url": ("String", "0..1")},
            "EAValue": {"type": ("EADatatype", "1")},
            "EANumerical": {"min": ("Numerical", "0..1"), "max": ("Numerical", "0..1")},
            "EANumericalValue": {"value": ("Numerical", "1")},
            "Mode": {"condition": ("String", "1")},
        }
        for class_name, expected in required_attrs.items():
            cls = self._east_class(class_name)
            if not cls:
                continue
            attrs = {str(item.get("name")): item for item in self.index.attributes(cls)}
            for name, (type_name, multiplicity) in expected.items():
                attr = attrs.get(name)
                association = self._property_association(class_name, name)
                if not attr and not association:
                    self.issue("EAST003", f"missing EAST-ADL property {class_name}.{name}", f"classes.{class_name}")
                    continue
                actual_type = _simple(attr.get("type")) if attr else _simple(association.get("target"))
                actual_mult = _mult(attr.get("multiplicity")) if attr else _mult(association.get("target_multiplicity"))
                if actual_type != type_name or actual_mult != multiplicity:
                    self.issue("EAST004", f"{class_name}.{name} must be {type_name} [{multiplicity}]", f"classes.{class_name}.{name}")
        connector_port = self._property_association("FunctionConnector", "port")
        if (
            not connector_port
            or _simple(connector_port.get("target")) != "FunctionPort"
            or _mult(connector_port.get("target_multiplicity")) != "2"
            or "instanceref" not in str(connector_port.get("stereotype") or "").lower()
        ):
            self.issue("EAST005", "FunctionConnector.port must be FunctionPort [2] <<instanceRef>>", "associations.FunctionConnector_port")

    def _property_association(self, source: str, role: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.index.associations
                if _simple(item.get("source")) == source
                and str(item.get("target_role") or "") == role
            ),
            None,
        )

    def check_shadow_attributes(self) -> None:
        for cls in self.index.classes:
            inherited: dict[str, str] = {}
            queue = deque(self.index.bases(cls))
            visited: set[str] = set()
            while queue:
                parent_name = queue.popleft()
                if parent_name in visited:
                    continue
                visited.add(parent_name)
                parent = self.index.class_(parent_name, prefer_east=True)
                if not parent:
                    continue
                for attr in self.index.attributes(parent):
                    inherited[str(attr.get("name"))] = _simple(parent.get("name"))
                queue.extend(self.index.bases(parent))
            for attr in self.index.attributes(cls):
                name = str(attr.get("name"))
                if name in inherited:
                    self.issue("SHADOW001", f"{cls.get('name')}.{name} shadows inherited {inherited[name]}.{name}", f"classes.{cls.get('qualified_name')}.{name}")

    def check_package_dependencies(self) -> None:
        package_names = {str(item.get("_key") or item.get("name")) for item in self.index.packages}
        simple_names = {_simple(item) for item in package_names} | {
            str(item.get("name")) for item in self.index.packages
        }
        for package in self.index.packages:
            source = str(package.get("_key") or package.get("name"))
            source_family = _package_family(source)
            imports = _as_list(package.get("imports") or package.get("depends_on") or package.get("dependencies"))
            for target in imports:
                target_name = str(target.get("package") if isinstance(target, Mapping) else target)
                if target_name not in package_names and _simple(target_name) not in simple_names:
                    self.issue("PKG001", f"unknown imported package {target_name!r}", f"packages.{source}.imports")
                target_family = _package_family(target_name)
                if source_family == "east" and target_family == "rcm":
                    self.issue("PKG002", "EAST-ADL must not import RCM", f"packages.{source}.imports")
                if source_family not in {"rcm", "annex"} and target_family == "rcm":
                    self.issue("PKG003", f"reverse dependency {source} -> {target_name} is forbidden", f"packages.{source}.imports")
                if source_family != "annex" and target_family == "annex":
                    self.issue("PKG004", "core package must not depend on optional Annex", f"packages.{source}.imports")

    def _composition_owned_class(self, assoc: Mapping[str, Any]) -> str | None:
        if not _bool(assoc.get("composition")):
            return None
        owner = str(assoc.get("owner") or "source").lower()
        if owner in {"source", "src", "from"}:
            return _simple(assoc.get("target"))
        if owner in {"target", "dst", "to"}:
            return _simple(assoc.get("source"))
        return None

    def check_ownership(self) -> None:
        composition_signatures: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for assoc in self.index.associations:
            if not _bool(assoc.get("composition")):
                continue
            assoc_id = str(assoc.get("id") or assoc.get("name"))
            owned = self._composition_owned_class(assoc)
            if owned is None:
                self.issue("OWN001", "composition must declare owner=source or owner=target", f"associations.{assoc_id}")
                continue
            signature = (
                _simple(assoc.get("source")),
                _simple(assoc.get("target")),
                str(assoc.get("target_role") or ""),
            )
            composition_signatures[signature].append(assoc_id)
        for signature, assoc_ids in composition_signatures.items():
            if len(assoc_ids) > 1:
                self.issue("OWN002", f"duplicate composition end {signature}: {', '.join(assoc_ids)}", "associations")
        relationship = self._east_class("Relationship")
        if relationship:
            for cls in self.index.classes:
                if _package_family(cls.get("package")) != "rcm" or _bool(cls.get("abstract")):
                    continue
                if not self.index.is_subclass(cls, "Relationship"):
                    continue
                covered = any(
                    _bool(assoc.get("composition"))
                    and (
                        self.index.is_subclass(cls, _simple(assoc.get("target")))
                        or _simple(assoc.get("target")) == _simple(cls.get("name"))
                    )
                    for assoc in self.index.associations
                )
                if not covered:
                    self.issue("OWN003", f"concrete relationship {cls.get('name')} has no composition owner", f"classes.{cls.get('qualified_name')}")

    def check_invariant_sync(self) -> None:
        ids = [str(item.get("id") or item.get("_key") or "") for item in self.index.invariants]
        if not ids or any(not item for item in ids):
            self.issue("INV001", "invariants need stable, non-empty identifiers", "invariants")
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            self.issue("INV002", f"duplicate invariant ids: {', '.join(duplicates)}", "invariants")
        for invariant in self.index.invariants:
            scope = invariant.get("scope")
            if scope:
                pseudo_scopes = {"PackageDependency", "V05Projection", "ProjectPublication"}
                package_scopes = {
                    str(item.get("name")) for item in self.index.packages
                } | {
                    _simple(item.get("_key")) for item in self.index.packages
                }
                unresolved = []
                for part in str(scope).split("|"):
                    name = _simple(part)
                    if (
                        self.index.class_(name) is None
                        and name not in self.index.datatype_by_simple
                        and name not in pseudo_scopes
                        and name not in package_scopes
                    ):
                        unresolved.append(name)
                if unresolved:
                    self.issue("INV003", f"unknown invariant scope {scope!r}", f"invariants.{invariant.get('id')}")
            if not invariant.get("expression"):
                self.issue("INV004", "invariant has no executable expression", f"invariants.{invariant.get('id')}")
        metadata = self.model.get("metadata", {})
        declared = self.model.get("invariant_index")
        if declared is None and isinstance(metadata, Mapping):
            declared = metadata.get("invariant_ids")
        if declared is None:
            self.issue("INV005", "metadata.invariant_ids or invariant_index is required", "metadata")
        elif set(map(str, _as_list(declared))) != set(ids) or len(_as_list(declared)) != len(ids):
            self.issue("INV006", "declared invariant index is not exactly synchronized", "metadata.invariant_ids")
        self._check_invariant_references(self.model.get("views"), set(ids), "views")
        self._check_invariant_references(self.model.get("compatibility_contract"), set(ids), "compatibility_contract")

    def _check_invariant_references(self, value: Any, known: set[str], location: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                child_location = f"{location}.{key}"
                if str(key) in {"invariant_ids", "invariants"} and isinstance(item, (list, tuple, set)):
                    dangling = sorted(set(map(str, item)) - known)
                    if dangling:
                        self.issue("INV007", f"dangling invariant references: {', '.join(dangling)}", child_location)
                self._check_invariant_references(item, known, child_location)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._check_invariant_references(item, known, f"{location}[{index}]")

    def _require_bases(self, class_name: str, required: set[str], code: str) -> None:
        cls = self.index.class_(class_name)
        if not cls:
            self.issue(code, f"required class {class_name} is absent", f"classes.{class_name}")
            return
        actual = self.index.bases(cls)
        missing = required - actual
        if missing:
            self.issue(code, f"{class_name} misses direct bases {sorted(missing)}", f"classes.{class_name}.bases")

    def _find_assoc(self, source: str, target: str, role: str | None = None) -> list[dict[str, Any]]:
        result = []
        for assoc in self.index.associations:
            if _simple(assoc.get("source")) != source or _simple(assoc.get("target")) != target:
                continue
            roles = {str(assoc.get("source_role") or ""), str(assoc.get("target_role") or "")}
            if role is None or role in roles:
                result.append(assoc)
        return result

    def check_capability_pattern(self) -> None:
        self._require_bases("Capability", {"EAType", "TraceableSpecification"}, "CAP001")
        self._require_bases("CapabilityUse", {"EAPrototype", "EAElement"}, "CAP002")
        typing = self._find_assoc("CapabilityUse", "Capability", "type")
        if not typing:
            attr = self.index.attr("CapabilityUse", "type")
            if not attr or _simple(attr.get("type")) != "Capability" or _mult(attr.get("multiplicity")) != "1":
                self.issue("CAP003", "CapabilityUse requires type: Capability [1] <<isOfType>>", "classes.CapabilityUse")
        else:
            assoc = typing[0]
            if _mult(assoc.get("target_multiplicity")) != "1" or "isoftype" not in str(assoc.get("stereotype") or "").lower().replace("_", ""):
                self.issue("CAP003", "CapabilityUse typing association must be [1] <<isOfType>>", f"associations.{assoc.get('id')}")
        for assoc in self.index.associations:
            if _simple(assoc.get("source")) == "Capability" and _simple(assoc.get("target")) == "FunctionBehavior":
                if "refine" in " ".join(str(assoc.get(key) or "") for key in ("id", "stereotype", "description")).lower():
                    self.issue("CAP004", "Capability must not use EAST-ADL Refine semantics toward FunctionBehavior", f"associations.{assoc.get('id')}")

        providers = self._find_assoc("CapabilityUse", "Entity", "provider")
        if not providers or _mult(providers[0].get("target_multiplicity")) != "0..1":
            self.issue("CAP005", "CapabilityUse.provider must be Entity [0..1] in the compatibility core", "associations")
        targets = self._find_assoc("CapabilityUse", "Identifiable", "target")
        if not targets or _mult(targets[0].get("target_multiplicity")) != "0..*":
            self.issue("CAP006", "CapabilityUse.target must be Identifiable [*]", "associations")
        if not self._invariant_mentions("CapabilityUse", "provider", "performedby", "providedcapability", "type"):
            self.issue("CAP007", "CapabilityUse provider must perform the step and provide its Capability type", "invariants")
        if not self._invariant_mentions("CapabilityUse", "provider", "size()=1"):
            self.issue("CAP008", "the executable profile must require exactly one CapabilityUse.provider", "invariants")

    def check_root_containers(self) -> None:
        required = (
            ("RequirementsModel", "requirementsModel", "ROOT001"),
            ("VerificationValidation", "verificationValidation", "ROOT002"),
        )
        for target, role, code in required:
            matches = self._find_assoc("DynamicFunctionalModel", target, role)
            if (
                not matches
                or _mult(matches[0].get("target_multiplicity")) != "1"
                or not _bool(matches[0].get("composition"))
            ):
                self.issue(code, f"DynamicFunctionalModel must compose exactly one {target} via {role}", "associations")
        if not self._invariant_mentions("DynamicFunctionalModel", "requirementsmodel", "size()=1"):
            self.issue("ROOT003", "missing exact-one RequirementsModel invariant", "invariants")
        if not self._invariant_mentions("DynamicFunctionalModel", "verificationvalidation", "size()=1"):
            self.issue("ROOT004", "missing exact-one VerificationValidation invariant", "invariants")

    def check_assertions(self) -> None:
        assertion = self.index.class_("Assertion")
        if not assertion:
            self.issue("AST001", "abstract Assertion is absent", "classes.Assertion")
            return
        if not _bool(assertion.get("abstract")) or "TraceableSpecification" not in self.index.bases(assertion):
            self.issue("AST001", "Assertion must be abstract and directly specialize TraceableSpecification", "classes.Assertion")

        for subtype in ("StateAssertion", "EventAssertion", "OutputAssertion", "GroundingAssertion", "RelationAssertion"):
            cls = self.index.class_(subtype)
            if not cls or "Assertion" not in self.index.bases(cls):
                self.issue("AST002", f"{subtype} must directly specialize Assertion", f"classes.{subtype}")

        severity = self.index.attr(assertion, "severity")
        if not severity or _simple(severity.get("type")) != "AssertionSeverity" or _mult(severity.get("multiplicity")) != "0..1":
            self.issue("AST003", "Assertion.severity must be AssertionSeverity [0..1]", "classes.Assertion.severity")
        severity_enum = self.index.enum_by_simple.get("AssertionSeverity")
        if not severity_enum:
            self.issue("AST004", "AssertionSeverity enumeration is absent", "enums.AssertionSeverity")

        subject = self._find_assoc("Assertion", "Identifiable", "subject")
        expression = self._find_assoc("Assertion", "EAExpression", "expression")
        if not subject or _mult(subject[0].get("target_multiplicity")) != "1":
            self.issue("AST005", "Assertion.subject must be Identifiable [1]", "associations")
        if (
            not expression
            or _mult(expression[0].get("target_multiplicity")) != "1"
            or not _bool(expression[0].get("composition"))
        ):
            self.issue("AST006", "Assertion.expression must compose EAExpression [1]", "associations")

        specified_by = self._find_assoc("Effect", "Assertion", "specifiedBy")
        if not specified_by or _mult(specified_by[0].get("target_multiplicity")) != "1..*":
            self.issue("AST007", "Effect.specifiedBy must reference Assertion [1..*]", "associations")

        outcome = self.index.class_("AssertionOutcome")
        state_outcome = self.index.class_("StateAssertionOutcome")
        if not outcome or not _bool(outcome.get("abstract")) or "VVIntendedOutcome" not in self.index.bases(outcome):
            self.issue("AST008", "AssertionOutcome must be abstract and specialize VVIntendedOutcome", "classes.AssertionOutcome")
        if not state_outcome or "AssertionOutcome" not in self.index.bases(state_outcome):
            self.issue("AST009", "StateAssertionOutcome must specialize AssertionOutcome", "classes.StateAssertionOutcome")
        outcome_assertions = self._find_assoc("AssertionOutcome", "Assertion", "assertion")
        if not outcome_assertions or _mult(outcome_assertions[0].get("target_multiplicity")) != "1..*":
            self.issue("AST010", "AssertionOutcome.assertion must reference Assertion [1..*]", "associations")

        self._require_bases("AssertionResult", {"EAElement"}, "AST011")
        result = self.index.class_("AssertionResult")
        verdict = self.index.attr(result, "verdict") if result else None
        if not verdict or _simple(verdict.get("type")) != "AssertionVerdict" or _mult(verdict.get("multiplicity")) != "1":
            self.issue("AST012", "AssertionResult.verdict must be AssertionVerdict [1]", "classes.AssertionResult.verdict")
        verdict_enum = self.index.enum_by_simple.get("AssertionVerdict")
        verdict_literals = {
            str(item.get("name")) if isinstance(item, Mapping) else str(item)
            for item in _as_list(verdict_enum.get("literals") or verdict_enum.get("values"))
        } if verdict_enum else set()
        if verdict_literals != {"pass", "fail", "inconclusive", "error"}:
            self.issue("AST013", "AssertionVerdict must contain pass, fail, inconclusive and error", "enums.AssertionVerdict")
        for name in ("evidenceRef", "timestamp"):
            value = self.index.attr(result, name) if result else None
            if not value or _simple(value.get("type")) != "String" or _mult(value.get("multiplicity")) != "0..1":
                self.issue("AST014", f"AssertionResult.{name} must be String [0..1]", f"classes.AssertionResult.{name}")

        result_assertion = self._find_assoc("AssertionResult", "Assertion", "assertion")
        observed = self._find_assoc("AssertionResult", "EAValue", "observedValue")
        actual_results = self._find_assoc("RuntimeActualOutcome", "AssertionResult", "result")
        if not result_assertion or _mult(result_assertion[0].get("target_multiplicity")) != "1":
            self.issue("AST015", "AssertionResult.assertion must reference Assertion [1]", "associations")
        if not observed or _mult(observed[0].get("target_multiplicity")) != "0..1" or not _bool(observed[0].get("composition")):
            self.issue("AST016", "AssertionResult.observedValue must compose EAValue [0..1]", "associations")
        if not actual_results or _mult(actual_results[0].get("target_multiplicity")) != "1..*" or not _bool(actual_results[0].get("composition")):
            self.issue("AST017", "RuntimeActualOutcome.result must compose AssertionResult [1..*]", "associations")

    def _invariant_mentions(self, scope: str, *tokens: str) -> bool:
        expected = [token.lower() for token in tokens]
        for invariant in self.index.invariants:
            scopes = {_simple(item) for item in str(invariant.get("scope") or "").split("|")}
            if scope not in scopes:
                continue
            expression = str(invariant.get("expression") or "").lower()
            if all(token in expression for token in expected):
                return True
        return False

    def check_values(self) -> None:
        self._require_bases("ScenarioCondition", {"EAExpression", "EAElement"}, "VAL001")
        if not self._invariant_mentions("ScenarioCondition", "type", "eaboolean"):
            self.issue("VAL002", "ScenarioCondition must constrain inherited EAValue.type to EABoolean", "invariants")
        probability = self.index.datatype_by_simple.get("Probability") or self.index.class_("Probability")
        if not probability:
            self.issue("VAL003", "Probability datatype is absent", "datatypes.Probability")
        else:
            bases = {_simple(item) for item in _as_list(probability.get("bases") or probability.get("base"))}
            minimum = probability.get("min", probability.get("minimum"))
            maximum = probability.get("max", probability.get("maximum"))
            if "EANumerical" not in bases or minimum != 0 or maximum != 1:
                self.issue("VAL004", "Probability must specialize EANumerical with min=0 and max=1", "datatypes.Probability")
        for cls in self.index.classes:
            for attr in self.index.attributes(cls):
                if attr.get("name") in {"probability", "occurrenceProbability"}:
                    if _simple(attr.get("type")) != "Probability":
                        self.issue("VAL005", f"{cls.get('name')}.{attr.get('name')} must be typed by Probability", f"classes.{cls.get('name')}.{attr.get('name')}")

    def check_runtime(self) -> None:
        self._require_bases("RuntimeBinding", {"Relationship"}, "RUN001")
        self._require_bases("RuntimeAction", {"EAElement"}, "RUN002")
        self._require_bases("RuntimeActionLocator", {"EAElement"}, "RUN003")
        actions = self._find_assoc("RuntimeBinding", "RuntimeAction", "runtimeAction")
        if not actions:
            self.issue("RUN004", "RuntimeBinding must own runtimeAction [1..*] {ordered}", "associations")
        else:
            assoc = actions[0]
            if _mult(assoc.get("target_multiplicity")) != "1..*" or not _bool(assoc.get("ordered")) or not _bool(assoc.get("composition")):
                self.issue("RUN004", "runtimeAction must be composition [1..*] {ordered}", f"associations.{assoc.get('id')}")
        locators = self._find_assoc("RuntimeAction", "RuntimeActionLocator", "locator")
        if not locators or _mult(locators[0].get("target_multiplicity")) != "1" or not _bool(locators[0].get("composition")):
            self.issue("RUN005", "RuntimeAction must own exactly one RuntimeActionLocator", "associations")
        enum = self.index.enum_by_simple.get("RuntimeLocatorKind") or self.index.enum_by_simple.get("LocatorKind")
        if not enum:
            self.issue("RUN006", "runtime locator kind enumeration is absent", "enums")
        else:
            literals = {str(item.get("name")) if isinstance(item, Mapping) else str(item) for item in _as_list(enum.get("literals") or enum.get("values"))}
            if not {"endpoint", "tool", "topic"}.issubset(literals):
                self.issue("RUN007", "runtime locator kinds must include endpoint, tool and topic", f"enums.{enum.get('name')}")

    def check_scenarios(self) -> None:
        self._require_bases("Scenario", {"TraceableSpecification"}, "SCN001")
        self._require_bases("ScenarioStep", {"TraceableSpecification"}, "SCN002")
        self._require_bases("StepRelation", {"Relationship"}, "SCN003")
        variant = self._find_assoc("Scenario", "Scenario", "variantOf")
        if not variant or _mult(variant[0].get("target_multiplicity")) != "0..1":
            self.issue("SCN004", "Scenario.variantOf must be Scenario [0..1]", "associations")
        for role, aliases in (("source", {"source", "sourceStep"}), ("target", {"target", "targetStep"})):
            matches = [
                item
                for item in self._find_assoc("StepRelation", "ScenarioStep")
                if str(item.get("target_role") or "") in aliases
            ]
            if not matches or _mult(matches[0].get("target_multiplicity")) != "1":
                self.issue("SCN005", f"StepRelation.{role} must reference ScenarioStep [1]", "associations")
        step_number = self.index.attr("ScenarioStep", "stepNumber")
        if step_number and not _bool(step_number.get("derived")):
            self.issue("SCN006", "ScenarioStep.stepNumber must be derived; StepRelation is canonical control flow", "classes.ScenarioStep.stepNumber")
        required_patterns = [
            ("Scenario", ("kind", "variantof"), "SCN007"),
            ("Scenario", ("main",), "SCN008"),
            ("ParallelGroup", ("fork", "join"), "SCN009"),
            ("StepRelation", ("probability", "alternative", "exception"), "SCN010"),
            ("Scenario", ("probability", "sum()", "1.0"), "SCN011"),
        ]
        for scope, tokens, code in required_patterns:
            if not self._invariant_mentions(scope, *tokens):
                self.issue(code, f"missing executable {scope} invariant containing {tokens}", "invariants")

    def check_entity_agent(self) -> None:
        agent = self.index.class_("Agent")
        if not agent or "Entity" not in self.index.bases(agent):
            self.issue("ENT001", "Agent must directly specialize Entity", "classes.Agent.bases")
        enum = self.index.enum_by_simple.get("EntityKind")
        if not enum:
            self.issue("ENT002", "EntityKind enumeration is absent", "enums.EntityKind")
        else:
            literals = {str(item.get("name")) if isinstance(item, Mapping) else str(item) for item in _as_list(enum.get("literals") or enum.get("values"))}
            if "agent" not in literals:
                self.issue("ENT003", "EntityKind must retain the agent literal for v0.5", "enums.EntityKind")
        if not self._invariant_mentions("Entity", "agent", "agent"):
            self.issue("ENT004", "missing Entity.kind=agent iff object is Agent invariant", "invariants")

    def check_satisfy(self) -> None:
        satisfy = self._east_class("Satisfy")
        if satisfy and self.index.bases(satisfy) != {"RequirementsRelationship"}:
            self.issue("REQ001", "Satisfy must specialize RequirementsRelationship exactly", "classes.Satisfy.bases")
        if not self._invariant_mentions("Satisfy", "satisfiedrequirement", "satisfiedusecase", "xor"):
            self.issue("REQ002", "Satisfy needs Requirement/UseCase XOR invariant", "invariants")
        if not self._invariant_mentions("Satisfy", "satisfiedby", "requirementcontainer"):
            self.issue("REQ003", "Satisfy.satisfiedBy must exclude Requirement and RequirementContainer", "invariants")

    def check_vv(self) -> None:
        required_bases = {
            "ValidationCase": {"VVCase"},
            "RuntimeValidationProcedure": {"VVProcedure"},
            "RuntimeStimulus": {"VVStimuli"},
            "AssertionOutcome": {"VVIntendedOutcome"},
            "StateAssertionOutcome": {"AssertionOutcome"},
            "AssertionResult": {"EAElement"},
            "RuntimeActualOutcome": {"VVActualOutcome"},
            "RuntimeValidationTarget": {"VVTarget"},
            "RuntimeValidationLog": {"VVLog"},
            "ValidationCaseUseCaseBinding": {"Relationship"},
        }
        for class_name, bases in required_bases.items():
            self._require_bases(class_name, bases, "VV001")
        root_to_vv = self._find_assoc("DynamicFunctionalModel", "VerificationValidation")
        vv_to_case = self._composition_covering("VerificationValidation", "ValidationCase")
        if not root_to_vv or not _bool(root_to_vv[0].get("composition")):
            self.issue("VV002", "DynamicFunctionalModel must own one VerificationValidation container", "associations")
        if not vv_to_case:
            self.issue("VV003", "VerificationValidation must own ValidationCase", "associations")
        if any(_bool(item.get("composition")) for item in self._find_assoc("DynamicFunctionalModel", "ValidationCase")):
            self.issue("VV004", "ValidationCase must not have a second direct root composition", "associations")
        actual_owners = self._composition_covering("RuntimeValidationLog", "RuntimeActualOutcome")
        incompatible_actual_owners = [
            assoc
            for assoc in self.index.associations
            if _bool(assoc.get("composition"))
            and self.index.is_subclass("RuntimeActualOutcome", _simple(assoc.get("target")))
            and not self.index.is_subclass("RuntimeValidationLog", _simple(assoc.get("source")))
            and not self.index.is_subclass(_simple(assoc.get("source")), "RuntimeValidationLog")
        ]
        if not actual_owners or incompatible_actual_owners:
            self.issue("VV005", "actual outcomes must be composed exclusively by RuntimeValidationLog", "associations")
        verify = self._east_class("Verify")
        if not verify or not self.index.is_subclass(verify, "RequirementsRelationship"):
            self.issue("VV006", "EAST-ADL Verify must specialize RequirementsRelationship", "classes.Verify")
        verify_targets = {
            _simple(item.get("target"))
            for item in self.index.associations_from("Verify")
        }
        if "Requirement" not in verify_targets or not ({"VVCase", "VVProcedure", "ValidationCase"} & verify_targets):
            self.issue("VV007", "Verify must connect requirements with VVCase/VVProcedure", "associations")
        validation = self.index.class_("ValidationCase")
        if validation and self.index.attr(validation, "level"):
            self.issue("VV008", "ValidationCase.level is a v0.5 projection, not a V2 model property", "classes.ValidationCase.level")
        subjects = [
            item for item in self.index.associations
            if self.index.is_subclass("ValidationCase", _simple(item.get("source")))
            and str(item.get("target_role")) == "vvSubject"
        ]
        targets = [
            item for item in self.index.associations
            if self.index.is_subclass("RuntimeValidationTarget", _simple(item.get("source")))
            and str(item.get("target_role")) == "element"
        ]
        if not subjects or not targets:
            self.issue("VV009", "vvSubject and VVTarget.element must be modeled as separate associations", "associations")
        elif subjects[0].get("id") == targets[0].get("id"):
            self.issue("VV010", "vvSubject and VVTarget.element may not be collapsed", "associations")
        for invariant in self.index.invariants:
            expression = re.sub(r"\s+", "", str(invariant.get("expression") or "")).lower()
            if "vvsubject" in expression and "vvtarget.element" in expression:
                forces_value_difference = any(
                    marker in expression
                    for marker in ("vvsubject<>vvtarget.element", "excludesall", "intersection(vvtarget.element)->isempty")
                )
                if forces_value_difference:
                    self.issue(
                        "VV011",
                        "vvSubject and VVTarget.element are distinct roles but may reference the same Identifiable; value inequality is forbidden",
                        f"invariants.{invariant.get('id')}",
                    )

        target_class = self.index.class_("RuntimeValidationTarget")
        platform = self.index.attr(target_class, "platform") if target_class else None
        environment = self.index.attr(target_class, "environmentRef") if target_class else None
        if not platform or _simple(platform.get("type")) != "String" or _mult(platform.get("multiplicity")) != "1":
            self.issue("VV012", "RuntimeValidationTarget.platform must be String [1]", "classes.RuntimeValidationTarget.platform")
        if not environment or _simple(environment.get("type")) != "String" or _mult(environment.get("multiplicity")) != "0..1":
            self.issue("VV013", "RuntimeValidationTarget.environmentRef must be String [0..1]", "classes.RuntimeValidationTarget.environmentRef")
        runtime_bindings = self._find_assoc("RuntimeValidationTarget", "RuntimeBinding", "runtimeBinding")
        if not runtime_bindings or _mult(runtime_bindings[0].get("target_multiplicity")) != "0..*":
            self.issue("VV014", "RuntimeValidationTarget.runtimeBinding must reference RuntimeBinding [*]", "associations")
        if not self._invariant_mentions("RuntimeValidationTarget", "runtimebinding", "element", "includes"):
            self.issue("VV015", "RuntimeValidationTarget.runtimeBinding must be constrained as a subset of inherited element", "invariants")
        if not self._invariant_mentions("ValidationCase", "vvsubject", "scenariostep", "capability", "runtimebinding", "entity"):
            self.issue("VV016", "ValidationCase.vvSubject must be restricted to the four RCM subject kinds", "invariants")

    def _composition_covering(self, source_subtype: str, target_subtype: str) -> list[dict[str, Any]]:
        return [
            assoc
            for assoc in self.index.associations
            if _bool(assoc.get("composition"))
            and self.index.is_subclass(source_subtype, _simple(assoc.get("source")))
            and self.index.is_subclass(target_subtype, _simple(assoc.get("target")))
        ]

    def check_function_behavior(self) -> None:
        cls = self._east_class("FunctionBehavior")
        if not cls:
            return
        expected = {
            "path": ("String", "1"),
            "representation": ("FunctionBehaviorKind", "1"),
            "function": ("FunctionType", "0..1"),
            "mode": ("Mode", "0..*"),
        }
        attrs = {str(item.get("name")): item for item in self.index.attributes(cls)}
        for name, (type_name, multiplicity) in expected.items():
            attr = attrs.get(name)
            association = self._property_association("FunctionBehavior", name)
            actual_type = _simple(attr.get("type")) if attr else _simple(association.get("target")) if association else ""
            actual_mult = _mult(attr.get("multiplicity")) if attr else _mult(association.get("target_multiplicity")) if association else ""
            if actual_type != type_name or actual_mult != multiplicity:
                self.issue("FUN001", f"FunctionBehavior.{name} must be {type_name} [{multiplicity}]", f"classes.FunctionBehavior.{name}")

    def check_no_faa_fda(self) -> None:
        forbidden = {"FAA", "FDA", "FunctionalAnalysisArchitecture", "FunctionalDesignArchitecture"}
        for cls in self.index.classes:
            if _simple(cls.get("name") or cls.get("_key")) in forbidden:
                self.issue("ARCH001", f"{cls.get('name')} is not an EAST-ADL metaclass", f"classes.{cls.get('qualified_name')}")
        analysis_level = self._east_class("AnalysisLevel")
        design_level = self._east_class("DesignLevel")
        if analysis_level:
            attr = self.index.attr(analysis_level, "functionalAnalysisArchitecture")
            association = self._property_association("AnalysisLevel", "functionalAnalysisArchitecture")
            actual_type = _simple(attr.get("type")) if attr else _simple(association.get("target")) if association else ""
            actual_mult = _mult(attr.get("multiplicity")) if attr else _mult(association.get("target_multiplicity")) if association else ""
            if actual_type != "AnalysisFunctionPrototype" or actual_mult != "0..1":
                self.issue("ARCH002", "AnalysisLevel.functionalAnalysisArchitecture must be AnalysisFunctionPrototype [0..1]", "classes.AnalysisLevel")
        if design_level:
            attr = self.index.attr(design_level, "functionalDesignArchitecture")
            association = self._property_association("DesignLevel", "functionalDesignArchitecture")
            actual_type = _simple(attr.get("type")) if attr else _simple(association.get("target")) if association else ""
            actual_mult = _mult(attr.get("multiplicity")) if attr else _mult(association.get("target_multiplicity")) if association else ""
            if actual_type != "DesignFunctionPrototype" or actual_mult != "0..1":
                self.issue("ARCH003", "DesignLevel.functionalDesignArchitecture must be DesignFunctionPrototype [0..1]", "classes.DesignLevel")

    def check_annex(self) -> None:
        mappings = self.model.get("annex_mappings")
        if not mappings:
            self.issue("ANNEX001", "explicit optional Annex mapping table is absent", "annex_mappings")
        elif isinstance(mappings, Mapping):
            status = str(mappings.get("status") or "").lower()
            optional = mappings.get("optional")
            if "preliminary" not in status and "vorläufig" not in status:
                self.issue("ANNEX002", "Annex mapping must be marked preliminary", "annex_mappings.status")
            if optional is not True:
                self.issue("ANNEX003", "Annex mapping must be optional", "annex_mappings.optional")
        elif isinstance(mappings, list):
            if any(str(item.get("status") or "").lower() != "preliminary" for item in mappings if isinstance(item, Mapping)):
                self.issue("ANNEX002", "every Annex mapping must be marked preliminary", "annex_mappings")
            bridge = next(
                (
                    package for package in self.index.packages
                    if _simple(package.get("_key")) == "AnnexCBridge"
                ),
                None,
            )
            if not bridge or bridge.get("normative") is not False or bridge.get("preliminary") is not True:
                self.issue("ANNEX003", "AnnexCBridge package must be optional/non-normative and preliminary", "packages.AnnexCBridge")
        annex_classes = {
            _simple(cls.get("name"))
            for cls in self.index.classes
            if _package_family(cls.get("package")) == "annex"
        }
        for cls in self.index.classes:
            if _package_family(cls.get("package")) == "rcm":
                bad = self.index.bases(cls) & annex_classes
                if bad:
                    self.issue("ANNEX004", f"core class {cls.get('name')} depends on Annex base {sorted(bad)}", f"classes.{cls.get('qualified_name')}.bases")
        transition = next((cls for cls in self.index.classes if _simple(cls.get("name")) == "TransitionEvent" and _package_family(cls.get("package")) == "annex"), None)
        if transition and "Event" in self.index.bases(transition):
            self.issue("ANNEX005", "Annex TransitionEvent is not a Timing::Event subtype", f"classes.{transition.get('qualified_name')}.bases")


def validate_model(model: Mapping[str, Any]) -> ValidationReport:
    return ModelValidator(model).validate()


def _object_records(instance: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("objects", "elements", "instances"):
        if key in instance:
            return _records(instance[key])
    return []


def _object_type(obj: Mapping[str, Any]) -> str:
    return _simple(obj.get("type") or obj.get("@type") or obj.get("metaclass") or obj.get("class"))


def _refs(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            reference = item.get("id") or item.get("ref") or item.get("$ref")
            if reference is not None:
                result.append(str(reference))
        elif item is not None:
            result.append(str(item))
    return result


def analyze_fixture_coverage(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Return structural coverage evidence for the synthetic full-surface fixture."""

    objects = _object_records(instance)
    by_id = {str(item.get("id")): item for item in objects if item.get("id")}

    def typed(name: str) -> list[dict[str, Any]]:
        return [item for item in objects if _object_type(item) == name]

    requirements: list[dict[str, Any]] = []

    def add(requirement_id: str, description: str, covered: bool, evidence: Iterable[Any] = ()) -> None:
        requirements.append(
            {
                "id": requirement_id,
                "description": description,
                "covered": bool(covered),
                "evidence": [str(item) for item in evidence],
            }
        )

    use_cases = typed("UseCase")
    includes = typed("Include")
    extends = typed("Extend")
    extension_points = typed("ExtensionPoint")
    add(
        "COV-USECASE-REL",
        "Include, Extend and ExtensionPoint with populated EAST-ADL ends",
        bool(
            extension_points
            and any(_refs(item.get("addition")) for item in includes)
            and any(_refs(item.get("extendedCase")) and _refs(item.get("extensionLocation")) for item in extends)
            and any(_refs(item.get("include")) and _refs(item.get("extend")) and _refs(item.get("extensionPoint")) for item in use_cases)
        ),
        [item.get("id") for item in extension_points + includes + extends],
    )
    scenario_kinds = {str(item.get("kind")) for item in typed("Scenario")}
    add(
        "COV-SCENARIO-KINDS",
        "main, alternative and exception scenarios",
        {"main", "alternative", "exception"}.issubset(scenario_kinds),
        sorted(scenario_kinds),
    )
    relation_kinds = {str(item.get("kind")) for item in typed("StepRelation")}
    required_relation_kinds = {"sequence", "alternative", "exception", "fork", "join", "loop"}
    add(
        "COV-RELATION-KINDS",
        "all canonical StepRelation kinds",
        required_relation_kinds.issubset(relation_kinds),
        sorted(relation_kinds),
    )
    signal_ids = [item.get("id") for item in typed("Entity") if item.get("kind") == "signal"]
    add("COV-SIGNAL", "signal Entity discriminator", bool(signal_ids), signal_ids)
    locator_kinds = {
        str(item.get("kind"))
        for item in typed("RuntimeActionLocator")
        if item.get("value")
    }
    add(
        "COV-LOCATORS",
        "positive endpoint, tool and topic locators",
        {"endpoint", "tool", "topic"}.issubset(locator_kinds),
        sorted(locator_kinds),
    )
    parameter_bindings = typed("ParameterBinding")
    runtime_actions = typed("RuntimeAction")
    add(
        "COV-PARAMETER-SCHEMA",
        "typed capability/runtime parameters, schemas and ParameterBinding",
        bool(
            any(_refs(item.get("capabilityParameter")) and _refs(item.get("runtimeParameter")) for item in parameter_bindings)
            and any(_refs(item.get("inputSchema")) and _refs(item.get("outputSchema")) for item in runtime_actions)
            and all(item.get("valueType") for item in typed("KeyValueParameter"))
        ),
        [item.get("id") for item in parameter_bindings + typed("SchemaReference") + typed("KeyValueParameter")],
    )
    abstract_cases = [item for item in typed("ValidationCase") if item.get("abstract") is True]
    abstract_procedures = [item for item in typed("RuntimeValidationProcedure") if item.get("abstract") is True]
    forbidden_case_features = {"vvTarget", "vvLog", "abstractVVCase"}
    forbidden_procedure_features = {"vvStimuli", "vvIntendedOutcome", "abstractVVProcedure"}
    add(
        "COV-ABSTRACT-VV",
        "abstract ValidationCase and Procedure omit concrete-only features",
        bool(
            abstract_cases
            and abstract_procedures
            and all(not any(_refs(item.get(name)) for name in forbidden_case_features) for item in abstract_cases)
            and all(not any(_refs(item.get(name)) for name in forbidden_procedure_features) for item in abstract_procedures)
        ),
        [item.get("id") for item in abstract_cases + abstract_procedures],
    )
    satisfies = typed("Satisfy")
    requirement_branch = [item.get("id") for item in satisfies if _refs(item.get("satisfiedRequirement")) and not _refs(item.get("satisfiedUseCase"))]
    usecase_branch = [item.get("id") for item in satisfies if _refs(item.get("satisfiedUseCase")) and not _refs(item.get("satisfiedRequirement"))]
    add(
        "COV-SATISFY-BRANCHES",
        "positive Requirement and UseCase XOR branches",
        bool(requirement_branch and usecase_branch),
        requirement_branch + usecase_branch,
    )
    capability_state_refs: set[str] = set()
    for capability in typed("Capability"):
        for effect_id in _refs(capability.get("effect")):
            effect = by_id.get(effect_id, {})
            capability_state_refs.update(_refs(effect.get("specifiedBy")))
    vv_state_refs = {
        reference
        for outcome in typed("StateAssertionOutcome")
        for reference in _refs(outcome.get("assertion"))
    }
    add(
        "COV-STATE-EVIDENCE",
        "StateAssertion reused as Capability effect specification and V&V intended outcome",
        bool(capability_state_refs and vv_state_refs and capability_state_refs & vv_state_refs),
        sorted(capability_state_refs & vv_state_refs),
    )
    assertion_types = {
        "StateAssertion", "EventAssertion", "OutputAssertion", "GroundingAssertion", "RelationAssertion"
    }
    present_assertion_types = {_object_type(item) for item in objects} & assertion_types
    add(
        "COV-ASSERTION-KINDS",
        "all five concrete Assertion specializations",
        present_assertion_types == assertion_types,
        sorted(present_assertion_types),
    )
    results = typed("AssertionResult")
    actuals = typed("RuntimeActualOutcome")
    add(
        "COV-ASSERTION-RESULT",
        "structured AssertionResult with verdict, observed value and actual-outcome ownership",
        bool(
            results
            and all(_refs(item.get("assertion")) and item.get("verdict") for item in results)
            and any(_refs(item.get("observedValue")) for item in results)
            and any(_refs(item.get("result")) for item in actuals)
        ),
        [item.get("id") for item in results + actuals],
    )
    capability_uses = typed("CapabilityUse")
    add(
        "COV-CAPABILITY-PERFORMER",
        "CapabilityUse has an explicit provider and identifiable target",
        bool(capability_uses) and all(_refs(item.get("provider")) and _refs(item.get("target")) for item in capability_uses),
        [item.get("id") for item in capability_uses],
    )
    runtime_targets = typed("RuntimeValidationTarget")
    add(
        "COV-RUNTIME-TARGET",
        "runtime validation target names a platform and exposes binding as element subset",
        bool(runtime_targets) and all(
            item.get("platform") and set(_refs(item.get("runtimeBinding"))).issubset(set(_refs(item.get("element"))))
            for item in runtime_targets
        ),
        [item.get("id") for item in runtime_targets],
    )
    branch_edges = [
        item for item in typed("StepRelation")
        if item.get("kind") in {"alternative", "exception"}
    ]
    add(
        "COV-BRANCH-PROBABILITY",
        "complete alternative/exception branch carries probabilities summing to one",
        bool(branch_edges)
        and all(item.get("probability") is not None for item in branch_edges)
        and abs(sum(float(item.get("probability")) for item in branch_edges) - 1.0) <= 1e-6,
        [item.get("id") for item in branch_edges],
    )
    roots = typed("DynamicFunctionalModel")
    add(
        "COV-ROOT-CONTAINERS",
        "root has exactly one RequirementsModel and one VerificationValidation",
        bool(roots) and all(
            len(_refs(item.get("requirementsModel"))) == 1
            and len(_refs(item.get("verificationValidation"))) == 1
            for item in roots
        ),
        [item.get("id") for item in roots],
    )
    coincident_refs: set[str] = set()
    for case in typed("ValidationCase"):
        subjects = set(_refs(case.get("vvSubject")))
        elements: set[str] = set()
        for target_id in _refs(case.get("vvTarget")):
            elements.update(_refs(by_id.get(target_id, {}).get("element")))
        coincident_refs.update(subjects & elements)
    add(
        "COV-VV-ROLE-SEPARATION",
        "separate vvSubject/VVTarget.element roles allow coincident Identifiable values",
        bool(coincident_refs),
        sorted(coincident_refs),
    )
    verifies = typed("Verify")
    add(
        "COV-VERIFY-CASE",
        "Verify always includes a VVCase in addition to Requirements",
        bool(verifies) and all(_refs(item.get("requirement")) and _refs(item.get("vvCase")) for item in verifies),
        [item.get("id") for item in verifies],
    )
    covered_count = sum(item["covered"] for item in requirements)
    return {
        "profile": str(instance.get("fixture_profile") or "unspecified"),
        "ok": covered_count == len(requirements),
        "covered_count": covered_count,
        "requirement_count": len(requirements),
        "requirements": requirements,
    }


class InstanceValidator:
    def __init__(self, model: Mapping[str, Any], instance: Mapping[str, Any], subject: str = "V2 fixture"):
        self.model = _plain(model)
        self.index = ModelIndex(self.model)
        self.instance = _plain(instance)
        self.objects = _object_records(self.instance)
        self.by_id: dict[str, dict[str, Any]] = {}
        self.report = ValidationReport(subject=subject)
        for obj in self.objects:
            object_id = str(obj.get("id") or obj.get("_key") or "")
            if object_id and object_id not in self.by_id:
                self.by_id[object_id] = obj

    def issue(self, code: str, message: str, location: str = "instance") -> None:
        self.report.issues.append(ValidationIssue(code, message, location))

    def run(self, check_id: str, title: str, method: Any) -> None:
        before = len(self.report.issues)
        method()
        count = len(self.report.issues) - before
        self.report.checks.append(CheckResult(check_id, title, "pass" if count == 0 else "fail", count))

    def validate(self) -> ValidationReport:
        checks = [
            ("I-REF", "instance identity and reference closure", self.check_reference_closure),
            ("I-OWN", "single instance composition owner", self.check_composition),
            ("I-ROOT", "exact root requirements and V&V containers", self.check_root_containers),
            ("I-CAP", "capability-use performer and targets", self.check_capability_uses),
            ("I-AST", "assertions and structured assertion results", self.check_assertions),
            ("I-VAL", "Boolean conditions and probabilities", self.check_values),
            ("I-RUN", "runtime locator and ordered actions", self.check_runtime),
            ("I-SCN", "main, variants, control-flow and fork/join", self.check_scenarios),
            ("I-ENT", "EntityKind agent equivalence", self.check_agent),
            ("I-REQ", "Satisfy XOR and exclusions", self.check_satisfy),
            ("I-VV", "V&V ownership, logging and separation", self.check_vv),
            ("I-FUN", "FunctionBehavior required values", self.check_function_behavior),
            ("I-COV", "full-surface fixture construction coverage", self.check_fixture_coverage),
        ]
        for check_id, title, method in checks:
            self.run(check_id, title, method)
        return self.report

    def _of_type(self, name: str) -> list[dict[str, Any]]:
        result = []
        for obj in self.objects:
            object_type = _object_type(obj)
            if object_type == name or self.index.is_subclass(object_type, name):
                result.append(obj)
        return result

    def check_reference_closure(self) -> None:
        seen: set[str] = set()
        for index, obj in enumerate(self.objects):
            object_id = str(obj.get("id") or obj.get("_key") or "")
            type_name = _object_type(obj)
            if not object_id or object_id in seen:
                self.issue("IREF001", f"missing or duplicate object id {object_id!r}", f"objects[{index}]")
            seen.add(object_id)
            if self.index.class_(type_name) is None and type_name not in self.index.datatype_by_simple:
                self.issue("IREF002", f"unknown object type {type_name!r}", f"objects.{object_id}.type")
        for assoc in self.index.associations:
            source_type = _simple(assoc.get("source"))
            role = str(assoc.get("target_role") or "")
            if not role:
                continue
            for obj in self._of_type(source_type):
                value = obj.get(role)
                # ``type`` is reserved by the generic object-envelope.  A
                # fixture uses typeRef/isOfType for the EAPrototype typing end.
                if role == "type" and value == obj.get("type"):
                    value = obj.get("typeRef", obj.get("isOfType"))
                for ref in _refs(value):
                    if ref not in self.by_id:
                        self.issue("IREF003", f"dangling {role} reference {ref!r}", f"objects.{obj.get('id')}.{role}")

    def check_composition(self) -> None:
        parent_refs: dict[str, list[str]] = defaultdict(list)
        for assoc in self.index.associations:
            if not _bool(assoc.get("composition")) or str(assoc.get("owner") or "source").lower() != "source":
                continue
            source_type = _simple(assoc.get("source"))
            role = str(assoc.get("target_role") or "")
            for parent in self._of_type(source_type):
                for child in _refs(parent.get(role)):
                    parent_refs[child].append(str(parent.get("id")))
        for child, parents in parent_refs.items():
            if len(parents) > 1:
                self.issue("IOWN001", f"object {child} has multiple composition owners {parents}", f"objects.{child}")
        for obj in self.objects:
            cls = self.index.class_(_object_type(obj))
            if cls and self.index.is_subclass(cls, "Relationship") and not _bool(cls.get("abstract")):
                object_id = str(obj.get("id"))
                if len(parent_refs.get(object_id, [])) != 1:
                    self.issue("IOWN002", f"relationship {object_id} must have exactly one owner", f"objects.{object_id}")

    def check_root_containers(self) -> None:
        roots = self._of_type("DynamicFunctionalModel")
        for root in roots:
            requirements = _refs(root.get("requirementsModel"))
            verification = _refs(root.get("verificationValidation"))
            if len(requirements) != 1:
                self.issue("IROOT001", "DynamicFunctionalModel requires exactly one RequirementsModel", f"objects.{root.get('id')}.requirementsModel")
            elif requirements[0] in self.by_id and not self.index.is_subclass(_object_type(self.by_id[requirements[0]]), "RequirementsModel"):
                self.issue("IROOT003", "requirementsModel must reference a RequirementsModel", f"objects.{root.get('id')}.requirementsModel")
            if len(verification) != 1:
                self.issue("IROOT002", "DynamicFunctionalModel requires exactly one VerificationValidation", f"objects.{root.get('id')}.verificationValidation")
            elif verification[0] in self.by_id and not self.index.is_subclass(_object_type(self.by_id[verification[0]]), "VerificationValidation"):
                self.issue("IROOT004", "verificationValidation must reference a VerificationValidation", f"objects.{root.get('id')}.verificationValidation")

    def check_capability_uses(self) -> None:
        executable_profile = str(self.instance.get("fixture_profile") or "").lower() in {
            "full-surface", "executable", "executable-authoring"
        }
        owners: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for step in self._of_type("ScenarioStep"):
            for use_id in _refs(step.get("capabilityUse")) + _refs(step.get("capabilityUses")):
                owners[use_id].append(step)
        for capability_use in self._of_type("CapabilityUse"):
            object_id = str(capability_use.get("id"))
            providers = _refs(capability_use.get("provider"))
            if len(providers) > 1:
                self.issue("ICAP001", "CapabilityUse.provider has core multiplicity [0..1]", f"objects.{object_id}.provider")
            if executable_profile and len(providers) != 1:
                self.issue("ICAP002", "executable CapabilityUse requires exactly one provider", f"objects.{object_id}.provider")
            for provider_id in providers:
                provider = self.by_id.get(provider_id)
                if not provider or not self.index.is_subclass(_object_type(provider), "Entity"):
                    self.issue("ICAP003", "CapabilityUse.provider must reference an Entity", f"objects.{object_id}.provider")
                    continue
                type_refs = _refs(capability_use.get("typeRef", capability_use.get("isOfType", capability_use.get("capability"))))
                if not type_refs and capability_use.get("type") != "CapabilityUse":
                    type_refs = _refs(capability_use.get("type"))
                if type_refs and not set(type_refs).issubset(set(_refs(provider.get("providedCapability")))):
                    self.issue("ICAP004", "CapabilityUse.provider must provide the referenced Capability type", f"objects.{object_id}.provider")
                if owners.get(object_id) and not all(provider_id in _refs(step.get("performedBy")) for step in owners[object_id]):
                    self.issue("ICAP005", "CapabilityUse.provider must perform every owning ScenarioStep", f"objects.{object_id}.provider")
            for target_id in _refs(capability_use.get("target")):
                target = self.by_id.get(target_id)
                if not target or not self.index.is_subclass(_object_type(target), "Identifiable"):
                    self.issue("ICAP006", "CapabilityUse.target must reference an Identifiable", f"objects.{object_id}.target")

    def check_assertions(self) -> None:
        verdicts = {"pass", "fail", "inconclusive", "error"}
        severity_enum = self.index.enum_by_simple.get("AssertionSeverity")
        severities = {
            str(item.get("name")) if isinstance(item, Mapping) else str(item)
            for item in _as_list(severity_enum.get("literals") or severity_enum.get("values"))
        } if severity_enum else set()
        for assertion in self._of_type("Assertion"):
            object_id = str(assertion.get("id"))
            if _object_type(assertion) == "Assertion":
                self.issue("IAST001", "abstract Assertion may not be instantiated", f"objects.{object_id}")
            subjects = _refs(assertion.get("subject", assertion.get("subjectRef")))
            expressions = _refs(assertion.get("expression"))
            if len(subjects) != 1:
                self.issue("IAST002", "Assertion requires exactly one subject", f"objects.{object_id}.subject")
            elif subjects[0] in self.by_id and not self.index.is_subclass(_object_type(self.by_id[subjects[0]]), "Identifiable"):
                self.issue("IAST003", "Assertion.subject must reference an Identifiable", f"objects.{object_id}.subject")
            if len(expressions) != 1:
                self.issue("IAST004", "Assertion requires exactly one expression", f"objects.{object_id}.expression")
            elif expressions[0] in self.by_id and not self.index.is_subclass(_object_type(self.by_id[expressions[0]]), "EAExpression"):
                self.issue("IAST005", "Assertion.expression must reference an EAExpression", f"objects.{object_id}.expression")
            if assertion.get("severity") is not None and assertion.get("severity") not in severities:
                self.issue("IAST006", "Assertion.severity is not an AssertionSeverity literal", f"objects.{object_id}.severity")

        for effect in self._of_type("Effect"):
            assertions = _refs(effect.get("specifiedBy", effect.get("specifiedByRefs")))
            if not assertions:
                self.issue("IAST007", "Effect must be specifiedBy at least one Assertion", f"objects.{effect.get('id')}.specifiedBy")
            for assertion_id in assertions:
                target = self.by_id.get(assertion_id)
                if target and not self.index.is_subclass(_object_type(target), "Assertion"):
                    self.issue("IAST008", "Effect.specifiedBy must reference Assertions", f"objects.{effect.get('id')}.specifiedBy")

        for outcome in self._of_type("AssertionOutcome"):
            object_id = str(outcome.get("id"))
            if _object_type(outcome) == "AssertionOutcome":
                self.issue("IAST009", "abstract AssertionOutcome may not be instantiated", f"objects.{object_id}")
            assertions = _refs(outcome.get("assertion"))
            if not assertions:
                self.issue("IAST010", "AssertionOutcome requires at least one Assertion", f"objects.{object_id}.assertion")
            for assertion_id in assertions:
                target = self.by_id.get(assertion_id)
                if target and not self.index.is_subclass(_object_type(target), "Assertion"):
                    self.issue("IAST019", "AssertionOutcome.assertion must reference Assertions", f"objects.{object_id}.assertion")

        for result in self._of_type("AssertionResult"):
            object_id = str(result.get("id"))
            assertions = _refs(result.get("assertion"))
            if len(assertions) != 1:
                self.issue("IAST011", "AssertionResult requires exactly one Assertion", f"objects.{object_id}.assertion")
            elif assertions[0] in self.by_id and not self.index.is_subclass(_object_type(self.by_id[assertions[0]]), "Assertion"):
                self.issue("IAST012", "AssertionResult.assertion must reference an Assertion", f"objects.{object_id}.assertion")
            if result.get("verdict") not in verdicts:
                self.issue("IAST013", "AssertionResult.verdict is invalid", f"objects.{object_id}.verdict")
            observed = _refs(result.get("observedValue"))
            if len(observed) > 1:
                self.issue("IAST014", "AssertionResult.observedValue has multiplicity [0..1]", f"objects.{object_id}.observedValue")
            elif observed and observed[0] in self.by_id and not self.index.is_subclass(_object_type(self.by_id[observed[0]]), "EAValue"):
                self.issue("IAST015", "AssertionResult.observedValue must reference an EAValue", f"objects.{object_id}.observedValue")
            for field_name in ("evidenceRef", "timestamp"):
                if result.get(field_name) is not None and not isinstance(result.get(field_name), str):
                    self.issue("IAST016", f"AssertionResult.{field_name} must be a String", f"objects.{object_id}.{field_name}")

        for actual in self._of_type("RuntimeActualOutcome"):
            results = _refs(actual.get("result"))
            if not results:
                self.issue("IAST017", "RuntimeActualOutcome requires at least one AssertionResult", f"objects.{actual.get('id')}.result")
            for result_id in results:
                result = self.by_id.get(result_id)
                if result and not self.index.is_subclass(_object_type(result), "AssertionResult"):
                    self.issue("IAST018", "RuntimeActualOutcome.result must reference AssertionResults", f"objects.{actual.get('id')}.result")

    def _numeric_value(self, raw: Any) -> float | None:
        value = raw
        if isinstance(value, Mapping):
            value = value.get("value")
        refs = _refs(value)
        if isinstance(value, (list, tuple, set, frozenset)) or (isinstance(value, str) and value in self.by_id):
            if len(refs) != 1:
                return None
            target = self.by_id.get(refs[0])
            if not target:
                return None
            value = target.get("value")
            if isinstance(value, Mapping):
                value = value.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def check_values(self) -> None:
        for condition in self._of_type("ScenarioCondition"):
            datatype = condition.get("datatype") or condition.get("valueType") or condition.get("typeRef")
            if _simple(datatype) != "EABoolean":
                self.issue("IVAL001", "ScenarioCondition value type must be EABoolean", f"objects.{condition.get('id')}")
        for obj in self.objects:
            for field_name in ("probability", "occurrenceProbability"):
                if field_name not in obj or obj[field_name] is None:
                    continue
                value = self._numeric_value(obj[field_name])
                if value is None or not 0 <= value <= 1:
                    self.issue("IVAL002", f"{field_name} must be numeric in [0,1]", f"objects.{obj.get('id')}.{field_name}")

    def check_runtime(self) -> None:
        for binding in self._of_type("RuntimeBinding"):
            actions = binding.get("runtimeAction", binding.get("runtimeActions"))
            if not isinstance(actions, list) or not actions:
                self.issue("IRUN001", "RuntimeBinding.runtimeAction must be a non-empty ordered list", f"objects.{binding.get('id')}.runtimeAction")
        for action in self._of_type("RuntimeAction"):
            locator = _refs(action.get("locator"))
            legacy = [name for name in ("endpoint", "tool", "topic") if action.get(name) not in (None, "")]
            if len(locator) != 1:
                self.issue("IRUN002", "RuntimeAction must reference exactly one locator", f"objects.{action.get('id')}.locator")
            if len(legacy) > 1:
                self.issue("IRUN003", "legacy endpoint/tool/topic projection must contain at most one value", f"objects.{action.get('id')}")
            if locator:
                target = self.by_id.get(locator[0])
                if not target or _object_type(target) != "RuntimeActionLocator" or target.get("kind") not in {"endpoint", "tool", "topic"} or not target.get("value"):
                    self.issue("IRUN004", "locator must have one supported kind and non-empty value", f"objects.{locator[0]}")

    def check_scenarios(self) -> None:
        specs = self._of_type("UseCaseScenarioSpecification")
        by_usecase: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for spec in specs:
            usecases = _refs(spec.get("useCase"))
            scenarios = _refs(spec.get("scenario"))
            if len(usecases) == 1:
                by_usecase[usecases[0]].extend(self.by_id[item] for item in scenarios if item in self.by_id)
        for usecase_id, scenarios in by_usecase.items():
            if not scenarios:
                continue
            mains = [item for item in scenarios if item.get("kind") == "main"]
            if len(mains) != 1:
                self.issue("ISCN001", f"executable use case {usecase_id} needs exactly one main scenario", f"objects.{usecase_id}")
            main_ids = {str(item.get("id")) for item in mains}
            for scenario in scenarios:
                kind = scenario.get("kind")
                variant = _refs(scenario.get("variantOf"))
                if kind == "main" and variant:
                    self.issue("ISCN002", "main scenario must not have variantOf", f"objects.{scenario.get('id')}.variantOf")
                if kind in {"alternative", "exception"} and (len(variant) != 1 or variant[0] not in main_ids):
                    self.issue("ISCN003", "alternative/exception scenario must reference the use case main scenario", f"objects.{scenario.get('id')}.variantOf")
        for scenario in self._of_type("Scenario"):
            step_ids = _refs(scenario.get("step")) or _refs(scenario.get("steps"))
            relation_ids = _refs(scenario.get("stepRelation")) or _refs(scenario.get("stepRelations"))
            relations = [self.by_id[item] for item in relation_ids if item in self.by_id]
            if step_ids and not relations and len(step_ids) > 1:
                self.issue("ISCN004", "multi-step scenario needs explicit StepRelation control flow", f"objects.{scenario.get('id')}")
                continue
            edges: list[tuple[str, str, str]] = []
            branch_probabilities: dict[str, list[float | None]] = defaultdict(list)
            for relation in relations:
                source = _refs(relation.get("source"))
                target = _refs(relation.get("target"))
                if len(source) != 1 or len(target) != 1 or source[0] not in step_ids or target[0] not in step_ids:
                    self.issue("ISCN005", "StepRelation endpoints must be owned by the same scenario", f"objects.{relation.get('id')}")
                    continue
                kind = str(relation.get("kind"))
                edges.append((source[0], target[0], kind))
                raw_probability = relation.get("probability")
                has_probability = raw_probability not in (None, "", [])
                if has_probability and kind not in {"alternative", "exception"}:
                    self.issue("ISCN010", "StepRelation.probability is allowed only for alternative/exception edges", f"objects.{relation.get('id')}.probability")
                if kind in {"alternative", "exception"}:
                    branch_probabilities[source[0]].append(
                        self._numeric_value(raw_probability) if has_probability else None
                    )
            for source_id, probabilities in branch_probabilities.items():
                if probabilities and all(value is not None for value in probabilities):
                    total = sum(value for value in probabilities if value is not None)
                    if abs(total - 1.0) > 1e-6:
                        self.issue("ISCN011", "complete alternative/exception branch probabilities must sum to 1", f"objects.{scenario.get('id')}.stepRelation[{source_id}]")
            if step_ids:
                incoming = {item: 0 for item in step_ids}
                adjacency: dict[str, list[str]] = defaultdict(list)
                for source, target, kind in edges:
                    if kind != "loop":
                        incoming[target] += 1
                    adjacency[source].append(target)
                starts = [item for item, count in incoming.items() if count == 0]
                if len(starts) != 1:
                    self.issue("ISCN006", "scenario control flow needs exactly one entry step", f"objects.{scenario.get('id')}")
                elif set(self._reachable(starts[0], adjacency)) != set(step_ids):
                    self.issue("ISCN007", "all scenario steps must be reachable from the entry", f"objects.{scenario.get('id')}")
            forks = [(source, target) for source, target, kind in edges if kind == "fork"]
            joins = [(source, target) for source, target, kind in edges if kind == "join"]
            groups = [self.by_id[item] for item in _refs(scenario.get("parallelGroup")) + _refs(scenario.get("parallelGroups")) if item in self.by_id]
            if groups and (not forks or not joins):
                self.issue("ISCN008", "ParallelGroup requires matching fork and join relations", f"objects.{scenario.get('id')}")
            for group in groups:
                members = set(_refs(group.get("memberStep")) or _refs(group.get("memberStepIds")))
                fork_targets = {target for _, target in forks}
                join_sources = {source for source, _ in joins}
                if len(members) < 2 or not members.issubset(fork_targets) or not members.issubset(join_sources):
                    self.issue("ISCN009", "parallel members must be branches between fork and join", f"objects.{group.get('id')}")

    @staticmethod
    def _reachable(start: str, adjacency: Mapping[str, list[str]]) -> list[str]:
        seen: set[str] = set()
        queue = deque([start])
        while queue:
            item = queue.popleft()
            if item in seen:
                continue
            seen.add(item)
            queue.extend(adjacency.get(item, []))
        return list(seen)

    def check_agent(self) -> None:
        for obj in self.objects:
            object_type = _object_type(obj)
            is_agent = object_type == "Agent" or (self.index.class_(object_type) and self.index.is_subclass(object_type, "Agent"))
            kind_agent = obj.get("kind") == "agent"
            if is_agent != kind_agent and object_type in {"Entity", "Agent"}:
                self.issue("IENT001", "Entity.kind=agent iff entity is an Agent", f"objects.{obj.get('id')}.kind")

    def check_satisfy(self) -> None:
        for satisfy in self._of_type("Satisfy"):
            requirements = _refs(satisfy.get("satisfiedRequirement"))
            usecases = _refs(satisfy.get("satisfiedUseCase"))
            satisfied_by = _refs(satisfy.get("satisfiedBy"))
            if bool(requirements) == bool(usecases):
                self.issue("IREQ001", "Satisfy must select exactly one of requirement/use case", f"objects.{satisfy.get('id')}")
            if not satisfied_by:
                self.issue("IREQ002", "Satisfy.satisfiedBy must be non-empty", f"objects.{satisfy.get('id')}.satisfiedBy")
            for ref in satisfied_by:
                target = self.by_id.get(ref)
                if target and _object_type(target) in {"Requirement", "RequirementContainer"}:
                    self.issue("IREQ003", "Satisfy.satisfiedBy excludes Requirement and RequirementContainer", f"objects.{satisfy.get('id')}.satisfiedBy")

    def check_vv(self) -> None:
        actual_owner: dict[str, list[str]] = defaultdict(list)
        for log in self._of_type("RuntimeValidationLog"):
            for ref in _refs(log.get("actualOutcome")) + _refs(log.get("actualOutcomes")):
                actual_owner[ref].append(str(log.get("id")))
        for outcome in self._of_type("RuntimeActualOutcome"):
            owners = actual_owner.get(str(outcome.get("id")), [])
            if len(owners) != 1:
                self.issue("IVV001", "RuntimeActualOutcome must be owned by exactly one RuntimeValidationLog", f"objects.{outcome.get('id')}")
        for case in self._of_type("ValidationCase"):
            subjects = _refs(case.get("vvSubject"))
            targets = _refs(case.get("vvTarget"))
            is_abstract = case.get("abstract") is True or case.get("isConcrete") is False
            if not is_abstract and not subjects:
                self.issue("IVV002", "ValidationCase requires at least one vvSubject", f"objects.{case.get('id')}.vvSubject")
            if not is_abstract and not targets:
                self.issue("IVV003", "ValidationCase requires at least one VVTarget", f"objects.{case.get('id')}.vvTarget")
            if is_abstract and any(_refs(case.get(name)) for name in ("vvTarget", "vvLog", "abstractVVCase")):
                self.issue("IVV007", "abstract ValidationCase uses a concrete-only property", f"objects.{case.get('id')}")
            if case.get("level") is not None:
                self.issue("IVV004", "legacy level is projection-ledger data, not a V2 ValidationCase property", f"objects.{case.get('id')}.level")
            for subject_id in subjects:
                subject = self.by_id.get(subject_id)
                if subject and not any(
                    self.index.is_subclass(_object_type(subject), allowed)
                    for allowed in ("ScenarioStep", "Capability", "RuntimeBinding", "Entity")
                ):
                    self.issue("IVV009", "ValidationCase.vvSubject has an unsupported RCM subject kind", f"objects.{case.get('id')}.vvSubject")
        for procedure in self._of_type("RuntimeValidationProcedure"):
            is_abstract = procedure.get("abstract") is True or procedure.get("isConcrete") is False
            if is_abstract and any(_refs(procedure.get(name)) for name in ("vvStimuli", "vvIntendedOutcome", "abstractVVProcedure")):
                self.issue("IVV008", "abstract VVProcedure uses a concrete-only property", f"objects.{procedure.get('id')}")
        for binding in self._of_type("ValidationCaseUseCaseBinding"):
            if len(_refs(binding.get("validationCase"))) != 1 or len(_refs(binding.get("useCase"))) != 1:
                self.issue("IVV005", "use-case validation trace requires one case and one use case", f"objects.{binding.get('id')}")
        for verify in self._of_type("Verify"):
            if not _refs(verify.get("requirement")) or not _refs(verify.get("vvCase")):
                self.issue("IVV006", "Verify must connect a requirement with at least one VVCase; a procedure alone is insufficient", f"objects.{verify.get('id')}")
        for target in self._of_type("RuntimeValidationTarget"):
            object_id = str(target.get("id"))
            if not isinstance(target.get("platform"), str) or not target.get("platform"):
                self.issue("IVV010", "RuntimeValidationTarget.platform is required", f"objects.{object_id}.platform")
            if target.get("environmentRef") is not None and not isinstance(target.get("environmentRef"), str):
                self.issue("IVV011", "RuntimeValidationTarget.environmentRef must be a String", f"objects.{object_id}.environmentRef")
            elements = set(_refs(target.get("element")))
            for binding_id in _refs(target.get("runtimeBinding")):
                binding = self.by_id.get(binding_id)
                if not binding or not self.index.is_subclass(_object_type(binding), "RuntimeBinding"):
                    self.issue("IVV012", "RuntimeValidationTarget.runtimeBinding must reference RuntimeBindings", f"objects.{object_id}.runtimeBinding")
                if binding_id not in elements:
                    self.issue("IVV013", "RuntimeValidationTarget.runtimeBinding must be a subset of inherited element", f"objects.{object_id}.runtimeBinding")

    def check_function_behavior(self) -> None:
        for behavior in self._of_type("FunctionBehavior"):
            if not isinstance(behavior.get("path"), str) or not behavior.get("path"):
                self.issue("IFUN001", "FunctionBehavior.path is required", f"objects.{behavior.get('id')}.path")
            if not behavior.get("representation"):
                self.issue("IFUN002", "FunctionBehavior.representation is required", f"objects.{behavior.get('id')}.representation")

    def check_fixture_coverage(self) -> None:
        if self.instance.get("fixture_profile") != "full-surface":
            return
        coverage = analyze_fixture_coverage(self.instance)
        self.report.evidence["fixture_coverage"] = coverage
        for requirement in coverage["requirements"]:
            if not requirement["covered"]:
                self.issue("ICOV001", f"uncovered fixture requirement {requirement['id']}: {requirement['description']}", "fixture_coverage")


def validate_instance(model: Mapping[str, Any], instance: Mapping[str, Any], subject: str = "V2 fixture") -> ValidationReport:
    return InstanceValidator(model, instance, subject).validate()


def validate_routing_publication(instance_path: Path, trace_path: Path, project_path: Path) -> ValidationReport:
    """Run opt-in executable routing checks without changing the structural baseline."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.routing_verifier import load_and_verify
    data = load_and_verify(instance_path, trace_path, project_path)
    report = ValidationReport(subject=f"executable routing: {instance_path}")
    for item in data["issues"]:
        report.issues.append(ValidationIssue(item["code"], item["message"], item["location"], item["severity"]))
    for inv, item in data["checks"].items():
        report.checks.append(CheckResult(item["code"], inv, item["status"], item["issue_count"]))
    report.evidence = {"profile": "executable-routing", "model_sha256": data["model_sha256"], "pairs": sum(len(v) for v in data["routing_table"].values()), "latent_ambiguities": data["latent_ambiguities"], "reachability": data["reachability"]}
    return report


def _load_module(name_or_path: str):
    path = Path(name_or_path)
    if path.exists():
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            raise RuntimeError(f"cannot import model module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module(name_or_path)


def _markdown_report(reports: Sequence[ValidationReport]) -> str:
    ok = all(report.ok for report in reports)
    lines = [
        "# Dynamic Functional RDL V2 – executable validation evidence",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Overall result: **{'PASS' if ok else 'FAIL'}**",
        "",
        "| Subject | Result | Errors | Warnings | Checks |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for report in reports:
        lines.append(f"| {report.subject} | {'PASS' if report.ok else 'FAIL'} | {report.error_count} | {report.warning_count} | {len(report.checks)} |")
    for report in reports:
        lines.extend(["", f"## {report.subject}", ""])
        if not report.issues:
            lines.append("All executable checks passed.")
        else:
            lines.extend(["| Severity | Code | Location | Message |", "| --- | --- | --- | --- |"])
            for issue in report.issues:
                message = issue.message.replace("|", "\\|")
                lines.append(f"| {issue.severity} | `{issue.code}` | `{issue.location}` | {message} |")
        coverage = report.evidence.get("fixture_coverage")
        if isinstance(coverage, Mapping):
            lines.extend(
                [
                    "",
                    f"Full-surface coverage: **{coverage.get('covered_count')}/{coverage.get('requirement_count')}**",
                    "",
                    "| Requirement | Covered | Structural evidence |",
                    "| --- | --- | --- |",
                ]
            )
            for requirement in coverage.get("requirements", []):
                evidence = ", ".join(requirement.get("evidence", [])).replace("|", "\\|")
                lines.append(
                    f"| `{requirement.get('id')}` | {'yes' if requirement.get('covered') else 'no'} | {evidence} |"
                )
    lines.append("")
    return "\n".join(lines)


def write_reports(reports: Sequence[ValidationReport], output_dir: Path, prefix: str = "v2_validation_report") -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{prefix}.json"
    markdown_path = output_dir / f"{prefix}.md"
    payload = {
        "ok": all(report.ok for report in reports),
        "reports": [report.to_dict() for report in reports],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown_report(reports), encoding="utf-8")
    return json_path, markdown_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="tools.dynamic_functional_rdl_v2_model", help="Python module or .py path exporting MODEL")
    parser.add_argument("--model-json", type=Path, help="optional JSON model description instead of --module")
    parser.add_argument("--instance", action="append", type=Path, default=[], help="V2 instance fixture JSON; repeatable")
    parser.add_argument(
        "--fixture-provider",
        action="append",
        default=[],
        metavar="MODULE:CALLABLE",
        help="callable returning {'model': MODEL, 'instance': INSTANCE}; repeatable",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--prefix", default="v2_validation_report")
    parser.add_argument("--profile", choices=("structural", "executable"), default="structural", help="structural preserves the packet baseline; executable additionally runs Gate 0")
    parser.add_argument("--trace", type=Path, help="trace map for the single executable-profile instance")
    parser.add_argument("--project", type=Path, help="project metadata for digest verification")
    args = parser.parse_args(argv)
    if args.profile == "executable" and (len(args.instance) != 1 or args.trace is None or args.project is None):
        parser.error("--profile executable requires exactly one --instance, --trace and --project")

    if args.model_json:
        model = json.loads(args.model_json.read_text(encoding="utf-8"))
        example_instances: list[Any] = []
    else:
        module = _load_module(args.module)
        if not hasattr(module, "MODEL"):
            raise RuntimeError(f"{args.module} does not export MODEL")
        model = _plain(module.MODEL)
        example_instances = list(getattr(module, "EXAMPLE_INSTANCES", []))

    reports = [validate_model(model)]
    for index, fixture in enumerate(example_instances):
        reports.append(validate_instance(model, _plain(fixture), f"embedded fixture {index + 1}"))
    for path in args.instance:
        reports.append(validate_instance(model, json.loads(path.read_text(encoding="utf-8")), str(path)))
    for provider_spec in args.fixture_provider:
        if ":" not in provider_spec:
            raise RuntimeError("--fixture-provider must use MODULE:CALLABLE")
        module_name, callable_name = provider_spec.rsplit(":", 1)
        provider_module = _load_module(module_name)
        provider = getattr(provider_module, callable_name, None)
        if not callable(provider):
            raise RuntimeError(f"fixture provider {provider_spec} is not callable")
        bundle = _plain(provider())
        if not isinstance(bundle, Mapping) or "model" not in bundle or "instance" not in bundle:
            raise RuntimeError(f"fixture provider {provider_spec} must return model and instance")
        fixture_model = bundle["model"]
        fixture_instance = bundle["instance"]
        reports.append(validate_model(fixture_model))
        reports.append(validate_instance(fixture_model, fixture_instance, str(fixture_instance.get("id") or provider_spec)))
    if args.profile == "executable":
        reports.append(validate_routing_publication(args.instance[0], args.trace, args.project))
    json_path, markdown_path = write_reports(reports, args.output_dir, args.prefix)
    print(json_path)
    print(markdown_path)
    return 0 if all(report.ok for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
