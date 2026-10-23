from __future__ import annotations

"""Presentation renderer for the canonical Dynamic Functional RDL V2 model.

The renderer deliberately separates the normative model from its presentation.
SVG and PNG are produced from one shared scene, so both formats have identical
cards, orthogonal routes and labels.  The overview uses a curated A/B/C layout;
detail views retain every local relation in a ledger while drawing only the
relations selected for that subject area.
"""

import math
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Iterable


Point = tuple[float, float]


@dataclass
class Box:
    key: str
    title: str
    package: str
    x: float
    y: float
    w: float
    h: float
    lines: list[str] = field(default_factory=list)
    stereotype: str = ""
    row: int = 0
    fill: str = "#EEF5FF"
    stroke: str = "#315C96"


@dataclass
class Edge:
    points: list[Point]
    label: str
    kind: str = "association"  # association | composition | generalization
    dashed: bool = False
    label_pos: Point | None = None


@dataclass
class Panel:
    x: float
    y: float
    w: float
    h: float
    title: str
    fill: str = "#FFFFFF"
    stroke: str = "#D5DFEA"


@dataclass
class Note:
    x: float
    y: float
    w: float
    h: float
    title: str
    lines: list[str]
    fill: str = "#F6F9FC"
    stroke: str = "#A8B7C8"


@dataclass
class Scene:
    width: int
    height: int
    title: str
    subtitle: str
    boxes: list[Box]
    edges: list[Edge]
    panels: list[Panel] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    ledger_top: int | None = None
    ledger_entries: list[str] = field(default_factory=list)


def _all_elements(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = dict(model["classes"])
    for name, datatype in model["datatypes"].items():
        item = dict(datatype)
        item["element_kind"] = "datatype"
        result[name] = item
    return result


def _members(view: dict[str, Any]) -> list[str]:
    return [name for row in view["rows"] for name in row]


def associations_for_view(model: dict[str, Any], view: dict[str, Any]) -> list[dict[str, Any]]:
    members = set(_members(view))
    return [
        item
        for item in model["associations"]
        if item["source"] in members and item["target"] in members
    ]


def diagram_associations(model: dict[str, Any], view: dict[str, Any]) -> list[dict[str, Any]]:
    local = associations_for_view(model, view)
    wanted = view.get("diagram_association_ids")
    if not wanted:
        return local
    by_id = {item["id"]: item for item in local}
    return [by_id[item_id] for item_id in wanted if item_id in by_id]


def generalizations_for_view(model: dict[str, Any], view: dict[str, Any]) -> list[tuple[str, str]]:
    elements = _all_elements(model)
    members = set(_members(view))
    result: list[tuple[str, str]] = []
    for derived in _members(view):
        for base in elements[derived].get("bases", []):
            if base in members:
                result.append((derived, base))
    return result


def _simple(name: str) -> str:
    return name.rsplit("::", 1)[-1]


def _package_label(package: str) -> str:
    return package.replace("EAST-ADL::", "EA::").replace("RCM::V2::", "DF::")


def _style(item: dict[str, Any]) -> tuple[str, str]:
    package = item["package"]
    if package == "RCM::V2::Core":
        return "#EAF8EF", "#27734D"
    if package.startswith("RCM::") or "AnnexC" in package or item.get("optional"):
        return "#FFF6DE", "#9A6A17"
    return "#EEF5FF", "#315C96"


def _attr_lines(item: dict[str, Any], limit: int = 3) -> list[str]:
    lines: list[str] = []
    bases = [_simple(base) for base in item.get("bases", [])]
    if bases:
        lines.append("Bases: " + ", ".join(bases))
    for attr in item.get("attributes", [])[:limit]:
        slash = "/" if attr.get("derived") else ""
        ordered = " {ordered}" if attr.get("ordered") else ""
        value = f"+ {slash}{attr['name']}: {_simple(attr['type'])} [{attr['multiplicity']}]{ordered}"
        lines.append(value if len(value) <= 47 else value[:44] + "…")
    remaining = len(item.get("attributes", [])) - limit
    if remaining > 0:
        lines.append(f"… {remaining} more attributes")
    if item.get("element_kind") == "datatype" and "min" in item:
        lines.append(f"Value range [{item['min']}, {item['max']}]")
    if not lines:
        lines.append("no local attributes")
    return lines


def _stereotype(item: dict[str, Any]) -> str:
    values: list[str] = []
    if item.get("abstract"):
        values.append("abstract")
    values.extend(item.get("stereotypes", []))
    if item.get("element_kind") == "datatype":
        values.append("datatype")
    if item.get("optional"):
        values.append("optional")
    return ", ".join(values)


def _longest_segment_label(points: list[Point]) -> Point:
    horizontal: list[tuple[float, Point]] = []
    for first, second in zip(points, points[1:]):
        if abs(first[1] - second[1]) < 0.1:
            horizontal.append((abs(second[0] - first[0]), ((first[0] + second[0]) / 2, first[1] - 8)))
    if horizontal:
        return max(horizontal, key=lambda item: item[0])[1]
    first, second = points[0], points[-1]
    return ((first[0] + second[0]) / 2 + 8, (first[1] + second[1]) / 2 - 8)


def _deduplicate(points: Iterable[Point]) -> list[Point]:
    result: list[Point] = []
    for point in points:
        normalized = (round(point[0], 2), round(point[1], 2))
        if not result or normalized != result[-1]:
            result.append(normalized)
    return result


def _port(box: Box, side: str, offset: float = 0.0) -> Point:
    if side == "top":
        return (box.x + box.w / 2 + offset, box.y)
    if side == "bottom":
        return (box.x + box.w / 2 + offset, box.y + box.h)
    if side == "left":
        return (box.x, box.y + box.h / 2 + offset)
    return (box.x + box.w, box.y + box.h / 2 + offset)


def _route_detail(
    source: Box,
    target: Box,
    index: int,
    width: int,
    row_extents: dict[int, tuple[float, float]],
    same_row_side: str | None = None,
    adjacent_shift: float = 0.0,
    source_port_shift: float = 0.0,
) -> list[Point]:
    lane = index % 7
    port_offset = (lane - 3) * 12
    if source.key == target.key:
        start = _port(source, "right", -source.h * 0.18)
        end = _port(source, "top", source.w * 0.28)
        # Keep the loop inside the inter-card gutter; a wide loop would enter
        # the neighbouring card in tightly packed rows.
        outer_x = source.x + source.w + 18 + (lane % 2) * 6
        outer_y = source.y - 28 - lane * 8
        return _deduplicate([start, (outer_x, start[1]), (outer_x, outer_y), (end[0], outer_y), end])

    row_delta = target.row - source.row
    if row_delta == 0:
        use_top = same_row_side == "top" or (
            same_row_side is None and source.row > 0 and index % 2 == 0
        )
        side = "top" if use_top else "bottom"
        start = _port(source, side, port_offset + source_port_shift)
        end = _port(target, side, -port_offset)
        if use_top:
            lane_y = row_extents[source.row][0] - 28 - lane * 11
        else:
            lane_y = row_extents[source.row][1] + 28 + lane * 11
        return _deduplicate([start, (start[0], lane_y), (end[0], lane_y), end])

    downward = row_delta > 0
    source_side = "bottom" if downward else "top"
    target_side = "top" if downward else "bottom"
    start = _port(source, source_side, port_offset + source_port_shift)
    end = _port(target, target_side, -port_offset)

    if abs(row_delta) == 1:
        upper_row = min(source.row, target.row)
        lower_row = max(source.row, target.row)
        gap_top = row_extents[upper_row][1]
        gap_bottom = row_extents[lower_row][0]
        mid = (gap_top + gap_bottom) / 2 + (lane - 3) * 9 + adjacent_shift
        return _deduplicate([start, (start[0], mid), (end[0], mid), end])

    source_gap = (
        row_extents[source.row][1] + 24 + lane * 8
        if downward
        else row_extents[source.row][0] - 24 - lane * 8
    )
    target_gap = (
        row_extents[target.row][0] - 24 - lane * 8
        if downward
        else row_extents[target.row][1] + 24 + lane * 8
    )
    average_x = (start[0] + end[0]) / 2
    use_left = average_x < width / 2
    gutter = 62 + lane * 10 if use_left else width - 62 - lane * 10
    return _deduplicate(
        [start, (start[0], source_gap), (gutter, source_gap), (gutter, target_gap), (end[0], target_gap), end]
    )


def _association_label(item: dict[str, Any]) -> str:
    ordered = " {ordered}" if item.get("ordered") else ""
    return f"{item['target_role']} [{item['target_multiplicity']}]{ordered}"


def _association_entry(item: dict[str, Any], prefix: str) -> str:
    symbol = "◆" if item["composition"] else "→"
    optional = " optional" if item.get("optional") else ""
    ordered = " {ordered}" if item.get("ordered") else ""
    return (
        f"{prefix} {symbol} {_simple(item['source'])}.{item['target_role']} "
        f"[{item['target_multiplicity']}]{ordered}{optional} → {_simple(item['target'])}"
    )


def _build_detail_scene(model: dict[str, Any], view: dict[str, Any]) -> Scene:
    elements = _all_elements(model)
    card_w = 286
    gap = 34
    side_margin = 150
    top = 155
    row_gap = 132
    width = max(1700, side_margin * 2 + max(len(row) for row in view["rows"]) * card_w + (max(len(row) for row in view["rows"]) - 1) * gap)
    boxes: list[Box] = []
    panels: list[Panel] = []
    row_extents: dict[int, tuple[float, float]] = {}
    labels = view.get("row_labels", [])
    y = top

    for row_index, row in enumerate(view["rows"]):
        prepared: list[tuple[str, dict[str, Any], list[str], float]] = []
        for qualified_name in row:
            item = elements[qualified_name]
            lines = _attr_lines(item)
            height = max(126, 78 + 19 * len(lines))
            prepared.append((qualified_name, item, lines, height))
        row_height = max(item[3] for item in prepared)
        row_width = len(row) * card_w + (len(row) - 1) * gap
        x = (width - row_width) / 2
        label = labels[row_index] if row_index < len(labels) else f"Ebene {row_index + 1}"
        panels.append(Panel(34, y - 38, width - 68, row_height + 76, label, "#FFFFFF", "#DCE5EE"))
        for qualified_name, item, lines, height in prepared:
            fill, stroke = _style(item)
            boxes.append(
                Box(
                    qualified_name,
                    item["name"],
                    item["package"],
                    x,
                    y + (row_height - height) / 2,
                    card_w,
                    height,
                    lines,
                    _stereotype(item),
                    row_index,
                    fill,
                    stroke,
                )
            )
            x += card_w + gap
        row_extents[row_index] = (y, y + row_height)
        y += row_height + row_gap

    by_key = {box.key: box for box in boxes}
    selected = diagram_associations(model, view)
    edges: list[Edge] = []
    for index, item in enumerate(selected):
        points = _route_detail(
            by_key[item["source"]],
            by_key[item["target"]],
            index,
            width,
            row_extents,
            view.get("same_row_route_sides", {}).get(item["id"]),
            view.get("adjacent_route_shifts", {}).get(item["id"], 0.0),
            view.get("source_port_shifts", {}).get(item["id"], 0.0),
        )
        edges.append(
            Edge(
                points,
                _association_label(item),
                "composition" if item["composition"] else "association",
                bool(item.get("optional") or item.get("stereotype") == "instanceRef"),
                _longest_segment_label(points),
            )
        )

    all_associations = associations_for_view(model, view)
    selected_ids = {item["id"] for item in selected}
    ledger = [_association_entry(item, "[Diagram]") for item in all_associations if item["id"] in selected_ids]
    ledger.extend(_association_entry(item, "[View]") for item in all_associations if item["id"] not in selected_ids)
    ledger.extend(
        f"[Inheritance] {_simple(derived)} → {_simple(base)}"
        for derived, base in generalizations_for_view(model, view)
    )
    ledger_top = int(y + 8)
    columns = 3 if width >= 2100 else 2
    ledger_rows = max(1, math.ceil(len(ledger) / columns))
    height = ledger_top + 100 + ledger_rows * 23 + 42
    return Scene(width, height, view["title"], view["description"], boxes, edges, panels, [], ledger_top, ledger)


def _overview_qnames(view: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in _members(view):
        simple = _simple(name)
        if simple in result:
            raise ValueError(f"Overview has ambiguous simple name {simple}")
        result[simple] = name
    return result


def _build_overview_scene(model: dict[str, Any], view: dict[str, Any]) -> Scene:
    elements = _all_elements(model)
    qnames = _overview_qnames(view)
    boxes: list[Box] = []

    summaries: dict[str, list[str]] = {
        "RequirementsModel": ["requirement: Requirement [*]", "useCase: UseCase [*]"],
        "Requirement": ["/text: String [0..1] {inherited}", "formalism / url: String [0..1]"],
        "Satisfy": ["satisfiedBy: Identifiable [1..*]", "{xor Requirement / UseCase}", "{excludes Requirement / RequirementContainer}"],
        "Actor": ["external role", "no physical entity"],
        "ActorParticipation": ["actor: Actor [1]", "useCase: UseCase [1]"],
        "UseCase": ["/text: String [0..1] {inherited}", "usage / captured functionality"],
        "UseCaseScenarioSpecification": ["useCase: UseCase [1]", "scenario: Scenario [1]"],
        "ExtensionPoint": ["/name: String [0..1] {inherited}", "belongs to the extended UseCase"],
        "Include": ["addition: UseCase [1]", "mandatory insertion"],
        "Extend": ["extendedCase: UseCase [1]", "extensionLocation: ExtensionPoint [1..*]"],
        "ConditionalExtend": ["condition: ScenarioCondition [1]", "specializes EAST-ADL Extend"],
        "ScenarioEvent": ["«Event, EAExpression»", "kind: temporal | spatial | signal | user | environment", "external: ScenarioExternalEvent <: ExternalEvent"],
        "Scenario": ["kind: main | alternative | exception", "variantOf / pre- / postcondition"],
        "ScenarioCondition": ["«EAElement, EAExpression»", "kind: guard | precondition | postcondition", "spatial | timing · expressionText: String [1]"],
        "ScenarioStep": ["kind: actorIntent | systemResponse", "environmentObservation · text: String [0..1]", "performedBy: Entity [*] · actorRole: Actor [*]", "occurrenceProbability: ProbabilityValue [0..1]"],
        "StepRelation": ["kind: sequence | alternative | exception", "fork | join | loop · sourceStep / targetStep", "guard: ScenarioCondition [0..1]", "probability: ProbabilityValue [0..1]"],
        "ParallelGroup": ["memberStep: ScenarioStep [2..*]", "{ordered}"],
        "Assertion": ["«abstract» · subject: Identifiable [1]", "expression: EAExpression [1]", "severity: AssertionSeverity [0..1]", "State / Event / Output / Grounding / Relation"],
        "StateAssertion": ["<: Assertion", "v0.5-compatible specialization"],
        "ProbabilityValue": ["EANumericalValue", "type: Probability [1]"],
        "CapabilityUse": ["«EAPrototype, EAElement»", "type: Capability [1] «isOfType»", "provider: Entity [0..1] (Core) / [1] (exec)", "target: Identifiable [*] · parameter [*]"],
        "Agent": ["specialized Entity", "retains roles, grounding and handoffs"],
        "Entity": ["kind / sourceId / entityRole / purpose", "playsActor: Actor [*]", "providedCapability: Capability [*]"],
        "Capability": ["«EAType, TraceableSpecification»", "text: String [0..1]", "precondition [*] · effect [1..*]"],
        "Effect": ["text: String [0..1]", "specifiedBy: Assertion [1..*]"],
        "CapabilityBehaviorBinding": ["capability: Capability [1]", "functionBehavior: FunctionBehavior [1]"],
        "FunctionBehavior": ["path: String [1]", "representation: FunctionBehaviorKind [1]", "function: FunctionType [0..1]"],
        "RuntimeBinding": ["targetPlatform: String [1]", "capability: Capability [1]", "runtimeAction: RuntimeAction [1..*] {ordered}"],
        "RuntimeAction": ["locator [1] · schemas [0..1]", "runtimeParameter [*]"],
        "RuntimeValidationTarget": ["<: VVTarget", "platform: String [1]", "runtimeBinding [*] · environmentRef [0..1]"],
        "ValidationCase": ["<: EAST-ADL VVCase", "vvSubject / vvTarget [*]", "procedure / log [*]"],
        "RuntimeValidationProcedure": ["<: VVProcedure", "stimuli / intended outcomes [*]"],
        "RuntimeStimulus": ["<: VVStimuli", "ScenarioEvent or RuntimeAction"],
        "StateAssertionOutcome": ["<: AssertionOutcome <: VVIntendedOutcome", "assertion: Assertion [1..*]"],
        "RuntimeValidationLog": ["<: VVLog", "actual outcomes [*]"],
        "RuntimeActualOutcome": ["<: VVActualOutcome", "result: AssertionResult [1..*]"],
        "AssertionResult": ["assertion: Assertion [1]", "verdict: pass | fail | inconclusive | error", "observedValue: EAValue [0..1]", "evidenceRef / timestamp: String [0..1]"],
    }

    positions: dict[str, tuple[float, float, float, float]] = {
        "RequirementsModel": (80, 250, 300, 135),
        "Requirement": (80, 550, 300, 120),
        "Satisfy": (430, 400, 320, 185),
        "Actor": (790, 540, 270, 130),
        "ActorParticipation": (1100, 500, 310, 150),
        "UseCase": (1480, 390, 330, 180),
        "UseCaseScenarioSpecification": (1480, 620, 330, 135),
        "ExtensionPoint": (1900, 250, 310, 130),
        "Include": (2300, 250, 290, 145),
        "Extend": (2300, 500, 290, 160),
        "ConditionalExtend": (2670, 500, 360, 160),
        "ScenarioEvent": (900, 870, 320, 155),
        "Scenario": (1470, 860, 330, 180),
        "ScenarioCondition": (900, 1110, 330, 150),
        "ScenarioStep": (1470, 1100, 350, 205),
        "StepRelation": (1980, 1100, 330, 190),
        "ParallelGroup": (2450, 1100, 320, 160),
        "StateAssertion": (900, 1340, 330, 145),
        "Assertion": (1590, 1340, 340, 160),
        "ProbabilityValue": (2450, 1340, 330, 145),
        "CapabilityUse": (760, 1600, 340, 180),
        "Capability": (1180, 1600, 340, 180),
        "Effect": (1590, 1600, 340, 180),
        "CapabilityBehaviorBinding": (2020, 1600, 380, 180),
        "FunctionBehavior": (2480, 1600, 330, 160),
        "Agent": (80, 1860, 300, 150),
        "Entity": (430, 1860, 330, 170),
        "RuntimeBinding": (1180, 1850, 340, 175),
        "RuntimeAction": (1590, 1850, 340, 190),
        "RuntimeValidationTarget": (60, 2170, 340, 155),
        "ValidationCase": (440, 2170, 340, 155),
        "RuntimeValidationProcedure": (820, 2170, 340, 155),
        "RuntimeStimulus": (1200, 2170, 340, 155),
        "StateAssertionOutcome": (1580, 2170, 340, 155),
        "RuntimeValidationLog": (1960, 2170, 340, 155),
        "RuntimeActualOutcome": (2340, 2170, 340, 155),
        "AssertionResult": (2720, 2170, 340, 155),
    }

    for simple, (x, y, w, h) in positions.items():
        item = elements[qnames[simple]]
        fill, stroke = _style(item)
        stereotype = _stereotype(item)
        boxes.append(Box(qnames[simple], simple, item["package"], x, y, w, h, summaries[simple], stereotype, 0, fill, stroke))

    by_simple = {_simple(box.key): box for box in boxes}

    def port(name: str, side: str, offset: float = 0.0) -> Point:
        return _port(by_simple[name], side, offset)

    edges: list[Edge] = []

    def edge(points: list[Point], label: str, kind: str = "association", dashed: bool = False, label_pos: Point | None = None) -> None:
        normalized = _deduplicate(points)
        orthogonal: list[Point] = [normalized[0]]
        for point in normalized[1:]:
            previous = orthogonal[-1]
            if abs(previous[0] - point[0]) > 0.1 and abs(previous[1] - point[1]) > 0.1:
                orthogonal.append((point[0], previous[1]))
            orthogonal.append(point)
        normalized = _deduplicate(orthogonal)
        edges.append(Edge(normalized, label, kind, dashed, label_pos or _longest_segment_label(normalized)))

    # A. Requirements / UseCases
    edge([port("RequirementsModel", "bottom"), port("Requirement", "top")], "requirement [*]", "composition")
    edge([port("RequirementsModel", "top"), (230, 230), (1435, 230), (1435, 420), port("UseCase", "left", -60)], "useCase [*]", "composition", label_pos=(930, 222))
    edge([port("Satisfy", "left", 20), (410, 510), (410, 610), port("Requirement", "right", 0)], "satisfiedRequirement [*]", label_pos=(500, 600))
    edge([port("Satisfy", "right", -20), (1110, 470), (1110, 455), port("UseCase", "left", -25)], "satisfiedUseCase [*]", label_pos=(930, 447))
    edge([port("ActorParticipation", "left", 20), (1080, 595), (1080, 625), port("Actor", "right", 20)], "")
    edge([port("ActorParticipation", "right", -18), port("UseCase", "left", 28)], "useCase", label_pos=(1445, 492))
    edge([port("UseCase", "right", -60), (1850, 420), (1850, 390), (2055, 390), port("ExtensionPoint", "bottom")], "extensionPoint [*]", "composition", label_pos=(1980, 402))
    edge([port("UseCase", "top", 70), (1715, 238), (2445, 238), port("Include", "top")], "include [*]", "composition", label_pos=(2075, 230))
    edge([port("UseCase", "right", 25), port("Extend", "left", -10)], "extend [*]", "composition")
    edge([port("UseCaseScenarioSpecification", "top"), port("UseCase", "bottom")], "useCase [1]")
    edge([port("UseCaseScenarioSpecification", "bottom"), port("Scenario", "top")], "scenario [1]", label_pos=(1705, 810))
    edge([port("ConditionalExtend", "left"), port("Extend", "right")], "", "generalization")

    # B. Scenario flow
    edge([port("Scenario", "bottom", -70), port("ScenarioStep", "top", -70)], "step [1..*]", "composition", label_pos=(1655, 1070))
    edge([port("Scenario", "right", 25), (1900, 975), (1900, 1070), (2145, 1070), port("StepRelation", "top")], "stepRelation [*]", "composition", label_pos=(2018, 1062))
    edge([port("Scenario", "right", -35), (2380, 930), (2380, 1060), (2610, 1060), port("ParallelGroup", "top")], "parallelGroup [*]", "composition", label_pos=(2495, 1052))
    edge([port("ScenarioStep", "top", -80), (1565, 1060), (1050, 1060), port("ScenarioEvent", "bottom")], "triggeredBy [*]", label_pos=(1310, 1052))
    edge([port("ScenarioStep", "left", -20), port("ScenarioCondition", "right", -10)], "guard [0..1]")
    edge([port("ScenarioStep", "bottom", -100), (1545, 1320), (1570, 1320), (1570, 1370), port("Assertion", "left", -50)], "resultingAssertion [*]", label_pos=(1450, 1355))
    edge([port("StateAssertion", "right"), port("Assertion", "left")], "", "generalization")
    edge([port("ScenarioStep", "bottom", -120), (1525, 1325), (850, 1325), (850, 1535), (930, 1535), port("CapabilityUse", "top")], "capabilityUse [*] {ordered}", "composition", label_pos=(1185, 1317))
    edge([port("StepRelation", "left", -35), port("ScenarioStep", "right", -48)], "sourceStep [1]")
    edge([port("StepRelation", "left", 35), (1900, 1230), (1900, 1270), port("ScenarioStep", "right", 62)], "targetStep [1]", label_pos=(1900, 1298))
    edge([port("ParallelGroup", "bottom"), (2610, 1320), (1745, 1320), port("ScenarioStep", "bottom", 100)], "memberStep [2..*] {ordered}", label_pos=(2240, 1312))

    # C. Capability / runtime bridge
    edge([port("Agent", "right"), (405, 1935), (405, 1945), port("Entity", "left")], "", "generalization")
    edge([port("Entity", "top", -70), (525, 1830), (1145, 1830), (1145, 1725), port("Capability", "left", 35)], "providedCapability [*]", label_pos=(835, 1822))
    edge([port("CapabilityUse", "bottom", -80), (850, 1800), (400, 1800), (400, 1895), port("Entity", "left", -50)], "provider [0..1] / [1] exec", dashed=True, label_pos=(625, 1792))
    edge([port("CapabilityUse", "right"), port("Capability", "left")], "type")
    edge([port("Capability", "right"), port("Effect", "left")], "effect", "composition")
    edge([port("Effect", "top"), port("Assertion", "bottom")], "specifiedBy [1..*]")
    edge([port("RuntimeBinding", "top"), port("Capability", "bottom")], "capability [1]")
    edge([port("RuntimeBinding", "bottom"), (1350, 2070), (1760, 2070), port("RuntimeAction", "bottom")], "runtimeAction [1..*] {ordered}", "composition", label_pos=(1555, 2062))
    edge([port("CapabilityBehaviorBinding", "bottom"), (2210, 1820), (1550, 1820), (1550, 1735), port("Capability", "right", 45)], "capability [1]", label_pos=(1880, 1812))
    edge([port("CapabilityBehaviorBinding", "bottom", 80), (2290, 1810), (2645, 1810), port("FunctionBehavior", "bottom")], "behavior [1]", label_pos=(2470, 1802))

    # Compact inherited V&V ownership strip.
    edge([port("ValidationCase", "top", -100), (510, 2135), (330, 2135), port("RuntimeValidationTarget", "top", 100)], "vvTarget [*]", label_pos=(420, 2127))
    edge([port("ValidationCase", "top", 100), (710, 2120), (890, 2120), port("RuntimeValidationProcedure", "top", -100)], "procedure", "composition", label_pos=(800, 2112))
    edge([port("RuntimeValidationProcedure", "top", 100), (1090, 2135), (1270, 2135), port("RuntimeStimulus", "top", -100)], "stimuli", "composition", label_pos=(1180, 2127))
    edge([port("RuntimeValidationProcedure", "bottom"), (990, 2345), (1750, 2345), port("StateAssertionOutcome", "bottom")], "vvIntendedOutcome [*]", "composition", label_pos=(1370, 2337))
    edge([port("ValidationCase", "top"), (610, 2080), (2130, 2080), port("RuntimeValidationLog", "top")], "vvLog [*]", "composition", label_pos=(1370, 2072))
    edge([port("RuntimeValidationLog", "top", 100), (2230, 2135), (2410, 2135), port("RuntimeActualOutcome", "top", -100)], "actual", "composition", label_pos=(2320, 2127))
    edge([port("RuntimeActualOutcome", "top", 100), (2610, 2120), (2790, 2120), port("AssertionResult", "top", -100)], "result [1..*]", "composition", label_pos=(2700, 2112))

    panels = [
        Panel(30, 180, 3140, 620, "A. EAST-ADL Requirements / UseCases – unchanged core", "#FCFDFF", "#C9D7E5"),
        Panel(30, 820, 3140, 700, "B. Scenario Layer – ordered, conditional and parallel flow", "#FCFEFD", "#C9DED2"),
        Panel(30, 1540, 3140, 950, "C. Capability / Runtime / V&V – domain capability before runtime binding", "#FDFCFD", "#DDD2E4"),
        Panel(60, 2110, 3080, 350, "EAST-ADL VerificationValidation «Context» – exactly one container", "#FAF8FC", "#CFC0D9"),
    ]
    notes = [
        Note(
            30,
            88,
            3140,
            82,
            "DynamicFunctionalModel «Context»",
            [
                "requirementsModel[1] (INV-063) · verificationValidation[1] (INV-034) · actor / scenario / event / condition / assertion / entity / capability / runtimeBinding [*]",
                "UML triangle = normative generalization; the seven detail views show complete inheritance chains.",
            ],
            "#EEF4FB",
            "#7590AE",
        ),
        Note(
            80,
            850,
            720,
            190,
            "Normative control-flow rules",
            [
                "StepRelation is the only source of control-flow semantics.",
                "Scenario.step is containment; stepNumber is for display.",
                "Both endpoints share one Scenario; ParallelGroup lies between fork and join.",
                "Probability only on alternative/exception; a complete branch sums to 1.",
            ],
            "#F4FAF6",
            "#78A58C",
        ),
        Note(
            2020,
            1850,
            1010,
            190,
            "Technical details are retained",
            [
                "RuntimeAction has locator[1], input/outputSchema[0..1] and runtimeParameter[*].",
                "CapabilityFunctionMapping optionally maps to actual Analysis/Design FunctionType/Prototype.",
                "Source, persona, expertise, knowledgeTag, voice, grounding and handoff fields are retained.",
                "Invariant: no direct ScenarioStep to RuntimeAction edge.",
            ],
            "#F5F2F8",
            "#A68DB6",
        ),
        Note(
            80,
            2365,
            1450,
            100,
            "Requirements and UseCase links",
            [
                "Verify(Requirement[1..*], VVCase[1..*])",
                "ValidationCaseUseCaseBinding(ValidationCase[1], UseCase[1])",
            ],
            "#FFFFFF",
            "#BCA9C8",
        ),
        Note(
            1570,
            2365,
            1380,
            100,
            "Executable V&V specialization",
            [
                "RuntimeStimulus: ScenarioEvent[0..1] or RuntimeAction[0..1], at least one",
                "AssertionOutcome.assertion[1..*] · RuntimeActualOutcome.result[1..*]",
                "vvSubject and VVTarget remain distinct EAST-ADL roles; no special direct RuntimeBinding edge.",
            ],
            "#FFFFFF",
            "#BCA9C8",
        ),
    ]
    return Scene(3200, 2520, view["title"], view["description"], boxes, edges, panels, notes)


def _build_optional_modules_scene(model: dict[str, Any], view: dict[str, Any]) -> Scene:
    """Lay out the three optional modules as independent presentation panels."""

    elements = _all_elements(model)
    qnames = _overview_qnames(view)
    boxes: list[Box] = []

    def add_box(simple: str, x: float, y: float, w: float = 350) -> None:
        item = elements[qnames[simple]]
        lines = _attr_lines(item)
        height = max(150, 78 + 19 * len(lines))
        fill, stroke = _style(item)
        boxes.append(
            Box(
                qnames[simple],
                simple,
                item["package"],
                x,
                y,
                w,
                height,
                lines,
                _stereotype(item),
                0,
                fill,
                stroke,
            )
        )

    # Annex-C panel: core anchors, bridges, Annex-C concepts and EAST targets.
    for simple, x in zip(
        ("ScenarioStep", "StepRelation", "ScenarioEvent", "StateAssertion"),
        (70, 470, 870, 1270),
    ):
        add_box(simple, x, 150)
    add_box("ScenarioAnnexMapping", 220, 390, 380)
    add_box("BehaviorConstraintTargetBinding", 720, 390, 410)
    add_box("BehaviorConstraintType", 1210, 390, 380)
    for simple, x in zip(
        ("LogicalTransformation", "TransformationOccurrence", "LogicalPath", "Quantification"),
        (70, 470, 870, 1270),
    ):
        add_box(simple, x, 620)
    for simple, x in zip(
        ("LogicalTimeCondition", "State", "TransitionEvent"),
        (270, 670, 1070),
    ):
        add_box(simple, x, 860)
    for simple, x in zip(
        ("Event", "FunctionTrigger", "FunctionBehavior", "FunctionType"),
        (70, 470, 870, 1270),
    ):
        add_box(simple, x, 1100)

    # Feature panel.
    add_box("Capability", 1850, 170, 390)
    add_box("CapabilityFeatureMapping", 1850, 455, 390)
    add_box("Feature", 1850, 740, 390)
    add_box("VehicleFeature", 1850, 1025, 390)

    # Agent-knowledge panel.
    add_box("Agent", 2380, 170, 270)
    add_box("Entity", 2680, 170, 270)
    add_box("AgentKnowledgeBinding", 2460, 455, 410)
    add_box("KnowledgeItem", 2380, 740, 270)
    add_box("KnowledgeSource", 2680, 740, 270)

    by_simple = {_simple(box.key): box for box in boxes}

    def port(simple: str, side: str, offset: float = 0.0) -> Point:
        return _port(by_simple[simple], side, offset)

    local = {item["id"]: item for item in associations_for_view(model, view)}
    edges: list[Edge] = []

    def add_edge(
        association_id: str,
        points: list[Point],
        label_pos: Point | None = None,
        label: str | None = None,
    ) -> None:
        item = local[association_id]
        normalized = _deduplicate(points)
        orthogonal: list[Point] = [normalized[0]]
        for point in normalized[1:]:
            previous = orthogonal[-1]
            if abs(previous[0] - point[0]) > 0.1 and abs(previous[1] - point[1]) > 0.1:
                orthogonal.append((point[0], previous[1]))
            orthogonal.append(point)
        normalized = _deduplicate(orthogonal)
        edges.append(
            Edge(
                normalized,
                label or _association_label(item),
                "composition" if item["composition"] else "association",
                True,
                label_pos or _longest_segment_label(normalized),
            )
        )

    add_edge(
        "ScenarioAnnexMapping_scenarioStep",
        [port("ScenarioAnnexMapping", "top"), (410, 350), (245, 350), port("ScenarioStep", "bottom")],
        (325, 342),
    )
    add_edge(
        "BehaviorConstraintTargetBinding_behaviorConstraintType",
        [port("BehaviorConstraintTargetBinding", "right"), port("BehaviorConstraintType", "left")],
        label="type",
    )
    add_edge(
        "BehaviorConstraintTargetBinding_targetedFunctionType",
        [port("BehaviorConstraintTargetBinding", "bottom"), (925, 590), (1665, 590), (1665, 1180), port("FunctionType", "right")],
        (1450, 582),
    )
    add_edge(
        "LogicalPath_transformationOccurrence",
        [port("LogicalPath", "left"), port("TransformationOccurrence", "right")],
        label="occ.",
    )
    add_edge(
        "TransformationOccurrence_invokedLogicalTransformation",
        [port("TransformationOccurrence", "left"), port("LogicalTransformation", "right")],
        label="call",
    )
    add_edge(
        "TransitionEvent_occurredExecutionEvent",
        [port("TransitionEvent", "bottom"), (1245, 1068), (245, 1068), port("Event", "top")],
        (745, 1060),
    )
    add_edge(
        "CapabilityFeatureMapping_capability",
        [port("CapabilityFeatureMapping", "top"), port("Capability", "bottom")],
    )
    add_edge(
        "CapabilityFeatureMapping_feature",
        [port("CapabilityFeatureMapping", "bottom"), port("Feature", "top")],
    )
    add_edge(
        "AgentKnowledgeBinding_agent",
        [port("AgentKnowledgeBinding", "top", -70), (2595, 425), (2515, 425), port("Agent", "bottom")],
        (2555, 417),
    )
    add_edge(
        "AgentKnowledgeBinding_knowledgeItem",
        [port("AgentKnowledgeBinding", "bottom", -70), (2595, 700), (2515, 700), port("KnowledgeItem", "top")],
        (2555, 692),
    )

    all_associations = associations_for_view(model, view)
    selected_ids = set(view.get("diagram_association_ids", []))
    ledger = [_association_entry(item, "[Diagram]") for item in all_associations if item["id"] in selected_ids]
    ledger.extend(_association_entry(item, "[View]") for item in all_associations if item["id"] not in selected_ids)
    ledger.extend(
        f"[Inheritance] {_simple(derived)} → {_simple(base)}"
        for derived, base in generalizations_for_view(model, view)
    )
    ledger_top = 1370
    rows = max(1, math.ceil(len(ledger) / 3))
    height = ledger_top + 100 + rows * 23 + 42
    panels = [
        Panel(25, 90, 1700, 1240, "Annex C – optional and preliminary", "#FFFCF4", "#D7BD7B"),
        Panel(1745, 90, 580, 1240, "Feature-Mapping – optional one-way bridge", "#FFFDF7", "#D7BD7B"),
        Panel(2345, 90, 630, 1240, "Agent Knowledge – optional", "#FFFDF7", "#D7BD7B"),
    ]
    return Scene(3000, height, view["title"], view["description"], boxes, edges, panels, [], ledger_top, ledger)


def _build_capability_runtime_scene(model: dict[str, Any], view: dict[str, Any]) -> Scene:
    """Presentation layout centred on the capability-to-runtime realization chain."""

    elements = _all_elements(model)
    qnames = _overview_qnames(view)
    boxes: list[Box] = []

    def add_box(simple: str, x: float, y: float, w: float = 360) -> None:
        item = elements[qnames[simple]]
        lines = _attr_lines(item)
        height = max(150, 78 + 19 * len(lines))
        fill, stroke = _style(item)
        boxes.append(
            Box(
                qnames[simple], simple, item["package"], x, y, w, height,
                lines, _stereotype(item), 0, fill, stroke,
            )
        )

    for simple, x in zip(
        ("EAType", "EAPrototype", "EAElement", "TraceableSpecification", "Relationship", "Identifiable"),
        (60, 500, 940, 1380, 1820, 2260),
    ):
        add_box(simple, x, 140, 380)

    add_box("Entity", 70, 430, 350)
    add_box("Agent", 70, 690, 350)
    add_box("CapabilityUse", 500, 430, 360)
    add_box("Capability", 980, 430, 360)
    add_box("Effect", 1460, 430, 360)
    add_box("Assertion", 1900, 430, 360)
    add_box("KeyValueParameter", 500, 700, 360)
    add_box("ParameterBinding", 500, 900, 360)
    add_box("RuntimeBinding", 980, 700, 360)
    add_box("RuntimeAction", 1460, 700, 360)
    add_box("RuntimeActionLocator", 1900, 700, 360)
    add_box("SchemaReference", 1900, 900, 360)
    add_box("RuntimeParameter", 2320, 700, 330)

    add_box("CapabilityFunctionMapping", 420, 1210, 410)
    add_box("AnalysisFunctionType", 70, 1460, 360)
    add_box("AnalysisFunctionPrototype", 460, 1460, 360)
    add_box("DesignFunctionType", 850, 1460, 360)
    add_box("DesignFunctionPrototype", 1240, 1460, 360)
    add_box("CapabilityBehaviorBinding", 1710, 1210, 420)
    add_box("FunctionBehavior", 2230, 1210, 400)

    by_simple = {_simple(box.key): box for box in boxes}

    def port(simple: str, side: str, offset: float = 0.0) -> Point:
        return _port(by_simple[simple], side, offset)

    local = {item["id"]: item for item in associations_for_view(model, view)}
    edges: list[Edge] = []

    def add_edge(association_id: str, points: list[Point], label: str, label_pos: Point) -> None:
        item = local[association_id]
        normalized = _deduplicate(points)
        orthogonal: list[Point] = [normalized[0]]
        for point in normalized[1:]:
            previous = orthogonal[-1]
            if abs(previous[0] - point[0]) > 0.1 and abs(previous[1] - point[1]) > 0.1:
                orthogonal.append((point[0], previous[1]))
            orthogonal.append(point)
        edges.append(
            Edge(
                _deduplicate(orthogonal), label,
                "composition" if item["composition"] else "association",
                bool(item.get("optional") or item.get("stereotype") == "instanceRef"),
                label_pos,
            )
        )

    add_edge(
        "CapabilityUse_provider",
        [port("CapabilityUse", "bottom", -90), (590, 650), (330, 650), port("Entity", "bottom", 80)],
        "provider [0..1] / [1] exec", (460, 642),
    )
    add_edge(
        "CapabilityUse_target",
        [port("CapabilityUse", "top"), (680, 345), (2450, 345), port("Identifiable", "bottom")],
        "target [*]", (1565, 337),
    )
    add_edge(
        "CapabilityUse_type",
        [port("CapabilityUse", "right"), port("Capability", "left")],
        "type [1]", (920, 505),
    )
    add_edge(
        "Capability_effect",
        [port("Capability", "right"), port("Effect", "left")],
        "effect [1..*]", (1400, 505),
    )
    add_edge(
        "Effect_specifiedBy",
        [port("Effect", "top"), (1640, 400), (2080, 400), port("Assertion", "top")],
        "specifiedBy [1..*]", (1860, 392),
    )
    add_edge(
        "RuntimeBinding_capability",
        [port("RuntimeBinding", "top"), port("Capability", "bottom")],
        "capability [1]", (1215, 665),
    )
    add_edge(
        "RuntimeBinding_runtimeAction",
        [port("RuntimeBinding", "bottom"), (1160, 890), (1640, 890), port("RuntimeAction", "bottom")],
        "runtimeAction [1..*] {ordered}", (1400, 882),
    )
    add_edge(
        "RuntimeAction_locator",
        [port("RuntimeAction", "right"), port("RuntimeActionLocator", "left")],
        "locator", (1860, 775),
    )
    add_edge(
        "CapabilityFunctionMapping_analysisType",
        [port("CapabilityFunctionMapping", "bottom", -100), (525, 1425), (250, 1425), port("AnalysisFunctionType", "top")],
        "analysis type", (385, 1417),
    )
    add_edge(
        "CapabilityFunctionMapping_designType",
        [port("CapabilityFunctionMapping", "bottom", 100), (725, 1405), (1030, 1405), port("DesignFunctionType", "top")],
        "design type", (875, 1397),
    )
    add_edge(
        "CapabilityBehaviorBinding_functionBehavior",
        [port("CapabilityBehaviorBinding", "right"), port("FunctionBehavior", "left")],
        "behavior [1]", (2180, 1285),
    )

    all_associations = associations_for_view(model, view)
    selected_ids = set(view.get("diagram_association_ids", []))
    ledger = [_association_entry(item, "[Diagram]") for item in all_associations if item["id"] in selected_ids]
    ledger.extend(_association_entry(item, "[View]") for item in all_associations if item["id"] not in selected_ids)
    ledger.extend(
        f"[Inheritance] {_simple(derived)} → {_simple(base)}"
        for derived, base in generalizations_for_view(model, view)
    )
    ledger_top = 1690
    rows = max(1, math.ceil(len(ledger) / 3))
    height = ledger_top + 100 + rows * 23 + 42
    panels = [
        Panel(25, 90, 2650, 230, "EAST-ADL bases", "#FBFDFF", "#CBD9E8"),
        Panel(25, 345, 2650, 800, "Capability and Runtime bridge", "#F8FCFA", "#BCD9C8"),
        Panel(25, 1170, 2650, 485, "Optional function and behavior mapping", "#FCFBFD", "#D8CFE0"),
    ]
    return Scene(2700, height, view["title"], view["description"], boxes, edges, panels, [], ledger_top, ledger)


def build_scene(model: dict[str, Any], view: dict[str, Any]) -> Scene:
    if view.get("kind") == "overview":
        return _build_overview_scene(model, view)
    if view.get("layout") == "capability_runtime":
        return _build_capability_runtime_scene(model, view)
    if view.get("layout") == "optional_modules":
        return _build_optional_modules_scene(model, view)
    return _build_detail_scene(model, view)


def _svg_marker_defs() -> str:
    return "\n".join(
        [
            "<defs>",
            '<marker id="triangle" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto"><path d="M 1 1 L 13 7 L 1 13 z" fill="#FFFFFF" stroke="#354B64" stroke-width="1.5"/></marker>',
            '<marker id="arrow" markerWidth="11" markerHeight="11" refX="10" refY="5.5" orient="auto"><path d="M 0 0 L 10 5.5 L 0 11 z" fill="#5D7189"/></marker>',
            '<marker id="diamond" markerWidth="15" markerHeight="11" refX="2" refY="5.5" orient="auto"><path d="M 1 5.5 L 7 1 L 13 5.5 L 7 10 z" fill="#263A52"/></marker>',
            "</defs>",
        ]
    )


def _svg_text(parts: list[str], x: float, y: float, text: str, size: int, fill: str, *, weight: int = 400, anchor: str = "start", family: str = "Arial, sans-serif", italic: bool = False) -> None:
    style = ' font-style="italic"' if italic else ""
    parts.append(
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill}"{style}>{escape(text)}</text>'
    )


def _render_svg_scene(scene: Scene) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{scene.width}" height="{scene.height}" viewBox="0 0 {scene.width} {scene.height}" role="img" aria-label="{escape(scene.title)}">',
        _svg_marker_defs(),
        f'<rect width="{scene.width}" height="{scene.height}" fill="#F9FBFD"/>',
    ]
    _svg_text(parts, 30, 38, scene.title, 26, "#1E324A", weight=700)
    _svg_text(parts, 30, 68, scene.subtitle, 15, "#52677F")

    for panel in scene.panels:
        parts.append(
            f'<rect x="{panel.x:.1f}" y="{panel.y:.1f}" width="{panel.w:.1f}" height="{panel.h:.1f}" rx="9" fill="{panel.fill}" stroke="{panel.stroke}" stroke-width="1.5"/>'
        )
        _svg_text(parts, panel.x + 18, panel.y + 29, panel.title, 18, "#283D55", weight=700)

    for edge in scene.edges:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in edge.points)
        dash = ' stroke-dasharray="8 6"' if edge.dashed else ""
        marker_start = ' marker-start="url(#diamond)"' if edge.kind == "composition" else ""
        marker_end = ' marker-end="url(#triangle)"' if edge.kind == "generalization" else (' marker-end="url(#arrow)"' if edge.kind == "association" else "")
        color = "#354B64" if edge.kind == "generalization" else "#62778F"
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"{dash}{marker_start}{marker_end}/>'
        )
        if edge.label:
            x, y = edge.label_pos or _longest_segment_label(edge.points)
            width = max(40, len(edge.label) * 6.4 + 10)
            parts.append(f'<rect x="{x - width / 2:.1f}" y="{y - 12:.1f}" width="{width:.1f}" height="18" rx="3" fill="#F9FBFD" fill-opacity="0.96"/>')
            _svg_text(parts, x, y + 1, edge.label, 11, "#3F556D", anchor="middle")

    for note in scene.notes:
        parts.append(
            f'<rect x="{note.x:.1f}" y="{note.y:.1f}" width="{note.w:.1f}" height="{note.h:.1f}" rx="7" fill="{note.fill}" stroke="{note.stroke}" stroke-width="1.5"/>'
        )
        _svg_text(parts, note.x + 14, note.y + 24, note.title, 15, "#293E56", weight=700)
        for index, line in enumerate(note.lines):
            _svg_text(parts, note.x + 14, note.y + 49 + index * 22, line, 12, "#425970")

    for box in scene.boxes:
        parts.append(
            f'<g><rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" rx="7" fill="{box.fill}" stroke="{box.stroke}" stroke-width="2"/>'
        )
        _svg_text(parts, box.x + 11, box.y + 18, _package_label(box.package), 10, "#60758B")
        if box.stereotype:
            stereo = f"«{box.stereotype}»"
            _svg_text(parts, box.x + box.w - 11, box.y + 18, stereo, 9, "#766A50", anchor="end")
        _svg_text(parts, box.x + box.w / 2, box.y + 43, box.title, 16, "#20354D", weight=700, anchor="middle")
        parts.append(f'<line x1="{box.x:.1f}" y1="{box.y + 58:.1f}" x2="{box.x + box.w:.1f}" y2="{box.y + 58:.1f}" stroke="{box.stroke}" stroke-width="1" opacity="0.5"/>')
        for index, line in enumerate(box.lines):
            _svg_text(parts, box.x + 11, box.y + 78 + index * 19, line, 11, "#334A62", family="Consolas, monospace")
        parts.append("</g>")

    if scene.ledger_top is not None:
        top = scene.ledger_top
        parts.append(f'<line x1="34" y1="{top}" x2="{scene.width - 34}" y2="{top}" stroke="#C5D2DF"/>')
        _svg_text(parts, 34, top + 31, "Relationship ledger", 18, "#263B53", weight=700)
        _svg_text(parts, 34, top + 54, "[Diagram] drawn edge · [View] included in the exact model · [Inheritance] in class headers", 12, "#60758B")
        columns = 3 if scene.width >= 2100 else 2
        rows_per_column = max(1, math.ceil(len(scene.ledger_entries) / columns))
        column_width = (scene.width - 68) / columns
        for index, entry in enumerate(scene.ledger_entries):
            column = index // rows_per_column
            row = index % rows_per_column
            x = 34 + column * column_width
            y = top + 82 + row * 23
            short = entry if len(entry) <= 92 else entry[:89] + "…"
            _svg_text(parts, x, y, short, 11, "#3F566E", family="Consolas, monospace")

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _font(size: int, *, bold: bool = False, italic: bool = False, mono: bool = False):
    from PIL import ImageFont

    if mono:
        candidates = ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/lucon.ttf"]
    elif bold and italic:
        candidates = ["C:/Windows/Fonts/arialbi.ttf"]
    elif bold:
        candidates = ["C:/Windows/Fonts/arialbd.ttf"]
    elif italic:
        candidates = ["C:/Windows/Fonts/ariali.ttf"]
    else:
        candidates = ["C:/Windows/Fonts/arial.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_dashed(draw: Any, points: list[Point], fill: str, width: int) -> None:
    for first, second in zip(points, points[1:]):
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = max(1.0, math.hypot(dx, dy))
        cursor = 0.0
        while cursor < length:
            finish = min(length, cursor + 8)
            draw.line(
                (
                    (first[0] + dx * cursor / length, first[1] + dy * cursor / length),
                    (first[0] + dx * finish / length, first[1] + dy * finish / length),
                ),
                fill=fill,
                width=width,
            )
            cursor += 14


def _last_segment(points: list[Point]) -> tuple[Point, Point]:
    for first, second in reversed(list(zip(points, points[1:]))):
        if first != second:
            return first, second
    return points[0], points[-1]


def _first_segment(points: list[Point]) -> tuple[Point, Point]:
    for first, second in zip(points, points[1:]):
        if first != second:
            return first, second
    return points[0], points[-1]


def _arrow_polygon(end: Point, start: Point, length: float = 10, half: float = 5) -> list[Point]:
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    base = (end[0] - math.cos(angle) * length, end[1] - math.sin(angle) * length)
    normal = (-math.sin(angle), math.cos(angle))
    return [end, (base[0] + normal[0] * half, base[1] + normal[1] * half), (base[0] - normal[0] * half, base[1] - normal[1] * half)]


def _diamond_polygon(start: Point, end: Point) -> list[Point]:
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    along = (math.cos(angle), math.sin(angle))
    normal = (-along[1], along[0])
    center = (start[0] + along[0] * 7, start[1] + along[1] * 7)
    return [
        start,
        (center[0] + normal[0] * 5, center[1] + normal[1] * 5),
        (start[0] + along[0] * 14, start[1] + along[1] * 14),
        (center[0] - normal[0] * 5, center[1] - normal[1] * 5),
    ]


def _render_png_scene(scene: Scene, path: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (scene.width, scene.height), "#F9FBFD")
    draw = ImageDraw.Draw(image)
    title_font = _font(26, bold=True)
    subtitle_font = _font(15)
    panel_font = _font(18, bold=True)
    node_title_font = _font(16, bold=True)
    small_font = _font(11)
    tiny_font = _font(10)
    attr_font = _font(11, mono=True)
    note_title_font = _font(15, bold=True)
    ledger_title_font = _font(18, bold=True)

    draw.text((30, 14), scene.title, font=title_font, fill="#1E324A")
    draw.text((30, 52), scene.subtitle, font=subtitle_font, fill="#52677F")

    for panel in scene.panels:
        draw.rounded_rectangle((panel.x, panel.y, panel.x + panel.w, panel.y + panel.h), radius=9, fill=panel.fill, outline=panel.stroke, width=2)
        draw.text((panel.x + 18, panel.y + 9), panel.title, font=panel_font, fill="#283D55")

    for edge in scene.edges:
        color = "#354B64" if edge.kind == "generalization" else "#62778F"
        if edge.dashed:
            _draw_dashed(draw, edge.points, color, 2)
        else:
            draw.line(edge.points, fill=color, width=2, joint="curve")
        first, second = _first_segment(edge.points)
        before, end = _last_segment(edge.points)
        if edge.kind == "composition":
            draw.polygon(_diamond_polygon(first, second), fill="#263A52")
        elif edge.kind == "generalization":
            draw.polygon(_arrow_polygon(end, before, 13, 7), fill="#FFFFFF", outline="#354B64")
        else:
            draw.polygon(_arrow_polygon(end, before), fill="#62778F")
        if edge.label:
            x, y = edge.label_pos or _longest_segment_label(edge.points)
            bbox = draw.textbbox((0, 0), edge.label, font=small_font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rounded_rectangle((x - tw / 2 - 4, y - th + 1, x + tw / 2 + 4, y + 5), radius=3, fill="#F9FBFD")
            draw.text((x - tw / 2, y - th), edge.label, font=small_font, fill="#3F556D")

    for note in scene.notes:
        draw.rounded_rectangle((note.x, note.y, note.x + note.w, note.y + note.h), radius=7, fill=note.fill, outline=note.stroke, width=2)
        draw.text((note.x + 14, note.y + 8), note.title, font=note_title_font, fill="#293E56")
        for index, line in enumerate(note.lines):
            draw.text((note.x + 14, note.y + 34 + index * 22), line, font=small_font, fill="#425970")

    for box in scene.boxes:
        draw.rounded_rectangle((box.x, box.y, box.x + box.w, box.y + box.h), radius=7, fill=box.fill, outline=box.stroke, width=2)
        draw.text((box.x + 11, box.y + 6), _package_label(box.package), font=tiny_font, fill="#60758B")
        if box.stereotype:
            stereo = f"«{box.stereotype}»"
            bbox = draw.textbbox((0, 0), stereo, font=tiny_font)
            draw.text((box.x + box.w - 11 - (bbox[2] - bbox[0]), box.y + 6), stereo, font=tiny_font, fill="#766A50")
        bbox = draw.textbbox((0, 0), box.title, font=node_title_font)
        draw.text((box.x + (box.w - (bbox[2] - bbox[0])) / 2, box.y + 27), box.title, font=node_title_font, fill="#20354D")
        draw.line((box.x, box.y + 58, box.x + box.w, box.y + 58), fill=box.stroke, width=1)
        for index, line in enumerate(box.lines):
            draw.text((box.x + 11, box.y + 68 + index * 19), line, font=attr_font, fill="#334A62")

    if scene.ledger_top is not None:
        top = scene.ledger_top
        draw.line((34, top, scene.width - 34, top), fill="#C5D2DF", width=1)
        draw.text((34, top + 10), "Relationship ledger", font=ledger_title_font, fill="#263B53")
        draw.text((34, top + 38), "[Diagram] drawn edge · [View] included in the exact model · [Inheritance] in class headers", font=small_font, fill="#60758B")
        columns = 3 if scene.width >= 2100 else 2
        rows_per_column = max(1, math.ceil(len(scene.ledger_entries) / columns))
        column_width = (scene.width - 68) / columns
        for index, entry in enumerate(scene.ledger_entries):
            column = index // rows_per_column
            row = index % rows_per_column
            x = 34 + column * column_width
            y = top + 65 + row * 23
            short = entry if len(entry) <= 92 else entry[:89] + "…"
            draw.text((x, y), short, font=attr_font, fill="#3F566E")

    image.save(path, format="PNG", optimize=False, compress_level=9)


def render_svg(model: dict[str, Any], view: dict[str, Any]) -> str:
    return _render_svg_scene(build_scene(model, view))


def render_png(model: dict[str, Any], view: dict[str, Any], path: Path) -> None:
    _render_png_scene(build_scene(model, view), path)


def render_mermaid(model: dict[str, Any], view: dict[str, Any]) -> str:
    elements = _all_elements(model)
    if view.get("kind") == "overview":
        lines = [
            "flowchart TB",
            "  %% The SVG/PNG files are the presentation-authoritative layout.",
            f"  %% {view['title']}",
            "  DFM[\"DynamicFunctionalModel «Context»\\nrequirementsModel [1] · verificationValidation [1] · assertion [*]\"]",
            "  subgraph A[\"A · EAST-ADL Requirements / UseCases\"]",
            "    direction LR",
            "    RM[\"RequirementsModel\"] -->|\"requirement [*]\"| REQ[\"Requirement\\n/text [0..1] inherited\"]",
            "    RM -->|\"useCase [*]\"| UC[\"UseCase\\n/text [0..1] inherited\"]",
            "    SAT[\"Satisfy\\nXOR supplier roles\\nsatisfiedBy excludes Requirement/Container\"] -->|\"satisfiedRequirement [*]\"| REQ",
            "    SAT -->|\"satisfiedUseCase [*]\"| UC",
            "    ACT[\"Actor\"] --- AP[\"ActorParticipation\"] --> UC",
            "    UC -->|\"extensionPoint [*]\"| EP[\"ExtensionPoint\\n/name [0..1] inherited\"]",
            "    UC -->|\"include [*]\"| INC[\"Include\"]",
            "    UC -->|\"extend [*]\"| EXT[\"Extend\"]",
            "    EXT -->|\"extensionLocation [1..*]\"| EP",
            "    CE[\"ConditionalExtend\"] -.->|\"specializes\"| EXT",
            "    CE -->|\"condition [1]\"| COND",
            "    UCS[\"UseCaseScenarioSpecification\"] -->|\"useCase [1]\"| UC",
            "  end",
            "  subgraph B[\"B · Scenario Layer\"]",
            "    direction LR",
            "    SC[\"Scenario\"] -->|\"step [1..*]\"| SS[\"ScenarioStep\"]",
            "    SC -->|\"stepRelation [*]\"| SR[\"StepRelation\"]",
            "    SC -->|\"parallelGroup [*]\"| PG[\"ParallelGroup\"]",
            "    SR -->|\"sourceStep [1]\"| SS",
            "    SR -->|\"targetStep [1]\"| SS",
            "    PG -->|\"memberStep [2..*]\"| SS",
            "    SS -->|\"triggeredBy [*]\"| SE[\"ScenarioEvent\"]",
            "    SS -->|\"guard [0..1]\"| COND[\"ScenarioCondition\"]",
            "    SS -->|\"resultingAssertion [*]\"| ASSERT[\"Assertion «abstract»\\nsubject [1] · expression [1] · severity [0..1]\"]",
            "    STATE[\"StateAssertion\"] -.->|\"specializes\"| ASSERT",
            "    SS -->|\"capabilityUse [*]\"| CU[\"CapabilityUse\"]",
            "    SR -->|\"probability [0..1]\"| PV[\"ProbabilityValue\"]",
            "  end",
            "  subgraph C[\"C · Capability / Runtime Bridge\"]",
            "    direction LR",
            "    AG[\"Agent\"] -->|\"providedCapability [*]\"| CAP[\"Capability\"]",
            "    ENT[\"Entity\"] -->|\"providedCapability [*]\"| CAP",
            "    CU -->|\"type [1]\"| CAP",
            "    CU -->|\"provider [0..1] core / [1] executable\"| ENT",
            "    CU -->|\"target [*]\"| ID[\"Identifiable\"]",
            "    CAP -->|\"effect [1..*]\"| EFF[\"Effect\"]",
            "    EFF -->|\"specifiedBy [1..*]\"| ASSERT",
            "    RB[\"RuntimeBinding\"] -->|\"capability [1]\"| CAP",
            "    RB -->|\"runtimeAction [1..*] {ordered}\"| RA[\"RuntimeAction\"]",
            "    CBB[\"CapabilityBehaviorBinding\"] -->|\"capability [1]\"| CAP",
            "    CBB -->|\"functionBehavior [1]\"| FB[\"FunctionBehavior\"]",
            "  end",
            "  subgraph V[\"V&V · kompakter Nachweis\"]",
            "    direction LR",
            "    VT[\"RuntimeValidationTarget <: VVTarget\\nplatform [1] · runtimeBinding [*]\"] <-->|\"vvTarget [*]\"| VC[\"ValidationCase <: VVCase\\nvvSubject [*]\"]",
            "    VC -->|\"vvProcedure [*] {ordered}\"| VP[\"RuntimeValidationProcedure <: VVProcedure\"]",
            "    VP -->|\"vvIntendedOutcome [*]\"| VIO[\"VVIntendedOutcome\"]",
            "    VC -->|\"vvLog [*]\"| VL[\"RuntimeValidationLog <: VVLog\"] -->|\"vvActualOutcome [*]\"| VAO[\"RuntimeActualOutcome <: VVActualOutcome\"]",
            "    VAO -->|\"result [1..*]\"| AR[\"AssertionResult\\nverdict · observedValue · evidenceRef · timestamp\"]",
            "    SAO[\"StateAssertionOutcome <: AssertionOutcome\"] -->|\"assertion [1..*]\"| ASSERT",
            "    VCB[\"ValidationCaseUseCaseBinding\"] -->|\"validationCase [1]\"| VC",
            "    VCB -->|\"useCase [1]\"| UC",
            "  end",
            "  DFM --> RM",
            "  DFM --> SC",
            "  DFM --> CAP",
            "  UCS -->|\"scenario [1]\"| SC",
            "  VAO -.->|\"intendedOutcome [0..1]\"| VIO",
        ]
        return "\n".join(lines) + "\n"

    lines = [
        "classDiagram",
        "  direction TB",
        "  %% SVG/PNG define the presentation-authoritative orthogonal layout.",
        f"  %% {view['title']}",
    ]
    for qualified_name in _members(view):
        item = elements[qualified_name]
        class_id = qualified_name.replace("::", "_").replace("-", "_")
        lines.append(f"  class {class_id} {{")
        if item.get("abstract"):
            lines.append("    <<abstract>>")
        elif item.get("element_kind") == "datatype":
            lines.append("    <<datatype>>")
        elif item.get("optional"):
            lines.append("    <<optional>>")
        else:
            lines.append(f"    <<{_package_label(item['package'])}>>")
        for attr in item.get("attributes", []):
            slash = "/" if attr.get("derived") else ""
            ordered = " {ordered}" if attr.get("ordered") else ""
            lines.append(f"    +{slash}{attr['name']} : {_simple(attr['type'])} [{attr['multiplicity']}]{ordered}")
        lines.append("  }")
    for derived, base in generalizations_for_view(model, view):
        lines.append(f"  {base.replace('::', '_')} <|-- {derived.replace('::', '_')}")
    for item in diagram_associations(model, view):
        source = item["source"].replace("::", "_")
        target = item["target"].replace("::", "_")
        if item["composition"]:
            connector = "*--" if item["owner"] == "source" else "--*"
        elif item.get("stereotype") == "instanceRef":
            connector = "..>"
        else:
            connector = "-->"
        label = _association_label(item)
        lines.append(f'  {source} "{item["source_multiplicity"]}" {connector} "{item["target_multiplicity"]}" {target} : {label}')
    return "\n".join(lines) + "\n"


__all__ = [
    "associations_for_view",
    "build_scene",
    "diagram_associations",
    "generalizations_for_view",
    "render_mermaid",
    "render_png",
    "render_svg",
]
