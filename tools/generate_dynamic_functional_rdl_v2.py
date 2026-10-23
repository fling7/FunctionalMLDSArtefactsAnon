from __future__ import annotations

"""Deterministically generate all Dynamic Functional RDL V2 artifacts."""

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any, Iterable

try:
    from dynamic_functional_rdl_v2_model import MODEL
    from dynamic_functional_rdl_v2_diagrams import (
        render_mermaid as render_v2_mermaid,
        render_png as render_v2_png,
        render_svg as render_v2_svg,
    )
except ImportError:  # Supports ``python -m tools.generate_dynamic_functional_rdl_v2``.
    from tools.dynamic_functional_rdl_v2_model import MODEL
    from tools.dynamic_functional_rdl_v2_diagrams import (
        render_mermaid as render_v2_mermaid,
        render_png as render_v2_png,
        render_svg as render_v2_svg,
    )


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "metamodel_v2" / "generated"
MODEL_FILENAME = "dynamic_functional_rdl_v2.model.json"
SPEC_FILENAME = "dynamic_functional_rdl_v2_specification.md"
MANIFEST_FILENAME = "generation_manifest.sha256.json"


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def identifier(qualified_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", qualified_name)


def simple_name(qualified_name: str) -> str:
    return qualified_name.rsplit("::", 1)[-1]


def package_label(package: str) -> str:
    return package.replace("EAST-ADL::", "EA::").replace("RCM::V2::", "DF::")


def all_elements() -> dict[str, dict[str, Any]]:
    result = dict(MODEL["classes"])
    for name, datatype in MODEL["datatypes"].items():
        copy = dict(datatype)
        copy["element_kind"] = "datatype"
        result[name] = copy
    return result


def validate_model() -> list[str]:
    """Validate the canonical descriptor before producing any artifact."""

    errors: list[str] = []
    packages = MODEL["packages"]
    elements = all_elements()
    enums = MODEL["enums"]
    primitives = MODEL["primitives"]

    expected_keys = {
        "metadata",
        "packages",
        "primitives",
        "enums",
        "datatypes",
        "classes",
        "associations",
        "invariants",
        "invariant_index",
        "views",
        "compatibility_contract",
        "annex_mappings",
    }
    missing_keys = expected_keys - MODEL.keys()
    if missing_keys:
        errors.append(f"MODEL is missing keys: {sorted(missing_keys)}")

    for package_name, package in packages.items():
        for imported in package.get("imports", []):
            if imported not in packages:
                errors.append(f"Package {package_name} imports unknown package {imported}")
        if package_name.startswith("EAST-ADL::"):
            forbidden = [item for item in package.get("imports", []) if item.startswith("RCM::")]
            if forbidden:
                errors.append(f"EAST-ADL package {package_name} imports RCM packages: {forbidden}")

    core_imports = packages["RCM::V2::Core"]["imports"]
    for optional_package in (
        "RCM::V2::AnnexCBridge",
        "RCM::V2::FeatureBridge",
        "RCM::V2::AgentKnowledge",
    ):
        if optional_package in core_imports:
            errors.append(f"Core must not import optional package {optional_package}")

    allowed_types = set(primitives) | set(elements) | set(enums)

    def referenced_package(type_name: str) -> str | None:
        if type_name in elements:
            return elements[type_name]["package"]
        if type_name in enums:
            return enums[type_name]["package"]
        return None

    def require_import(owner_package: str, target_package: str | None, context: str) -> None:
        if target_package and target_package != owner_package and target_package not in packages[owner_package].get("imports", []):
            errors.append(f"{context}: package {owner_package} does not declare import {target_package}")

    for qualified_name, element in elements.items():
        expected_name = f"{element['package']}::{element['name']}"
        if qualified_name != expected_name:
            errors.append(f"Element key {qualified_name} does not match {expected_name}")
        if element["package"] not in packages:
            errors.append(f"Element {qualified_name} uses unknown package {element['package']}")
        for base in element.get("bases", []):
            if base not in elements:
                errors.append(f"Element {qualified_name} has unknown base {base}")
            else:
                require_import(element["package"], elements[base]["package"], f"Base of {qualified_name}")
        attribute_names: set[str] = set()
        for item in element.get("attributes", []):
            if item["name"] in attribute_names:
                errors.append(f"Element {qualified_name} repeats attribute {item['name']}")
            attribute_names.add(item["name"])
            if item["type"] not in allowed_types:
                errors.append(f"Attribute {qualified_name}.{item['name']} has unknown type {item['type']}")
            else:
                require_import(element["package"], referenced_package(item["type"]), f"Attribute {qualified_name}.{item['name']}")

    for qualified_name, enum in enums.items():
        if qualified_name != f"{enum['package']}::{enum['name']}":
            errors.append(f"Enum key {qualified_name} does not match its descriptor")
        if enum["package"] not in packages:
            errors.append(f"Enum {qualified_name} uses unknown package {enum['package']}")
        if not enum.get("literals") or len(enum["literals"]) != len(set(enum["literals"])):
            errors.append(f"Enum {qualified_name} has no literals or duplicate literals")

    association_ids: set[str] = set()
    for item in MODEL["associations"]:
        if item["id"] in association_ids:
            errors.append(f"Duplicate association id {item['id']}")
        association_ids.add(item["id"])
        if item["package"] not in packages:
            errors.append(f"Association {item['id']} uses unknown package {item['package']}")
        for endpoint in ("source", "target"):
            if item[endpoint] not in elements:
                errors.append(f"Association {item['id']} has unknown {endpoint} {item[endpoint]}")
            else:
                require_import(item["package"], elements[item[endpoint]]["package"], f"Association {item['id']}")
        if item["composition"] and item["owner"] not in {"source", "target"}:
            errors.append(f"Composition {item['id']} has no valid owner")
        if not item["composition"] and item["owner"] is not None:
            errors.append(f"Non-composition {item['id']} unexpectedly has owner {item['owner']}")

    invariant_ids = [item["id"] for item in MODEL["invariants"]]
    if len(invariant_ids) != len(set(invariant_ids)):
        errors.append("Invariant ids are not unique")
    if invariant_ids != MODEL["invariant_index"]:
        errors.append("invariant_index is not synchronized with invariants")
    expected_invariant_ids = [f"INV-{number:03d}" for number in range(1, len(invariant_ids) + 1)]
    if invariant_ids != expected_invariant_ids:
        errors.append("Invariant ids must be contiguous and ordered")

    for view_name, view in MODEL["views"].items():
        seen: set[str] = set()
        for row in view["rows"]:
            for item in row:
                if item not in elements:
                    errors.append(f"View {view_name} references unknown element {item}")
                if item in seen:
                    errors.append(f"View {view_name} repeats element {item}")
                seen.add(item)
        if not seen:
            errors.append(f"View {view_name} is empty")
        for association_id in view.get("diagram_association_ids", []):
            if association_id not in association_ids:
                errors.append(f"View {view_name} selects unknown association {association_id}")
                continue
            association = next(item for item in MODEL["associations"] if item["id"] == association_id)
            if association["source"] not in seen or association["target"] not in seen:
                errors.append(
                    f"View {view_name} selects association {association_id} whose endpoints are not both members"
                )

    required_chain = MODEL["compatibility_contract"]["required_chain"]
    if required_chain != ["ScenarioStep", "CapabilityUse", "Capability", "RuntimeBinding", "RuntimeAction"]:
        errors.append("Compatibility capability/runtime chain is incomplete or reordered")

    return errors


def view_members(view: dict[str, Any]) -> list[str]:
    return [item for row in view["rows"] for item in row]


def view_associations(view: dict[str, Any]) -> list[dict[str, Any]]:
    members = set(view_members(view))
    return [item for item in MODEL["associations"] if item["source"] in members and item["target"] in members]


def view_generalizations(view: dict[str, Any]) -> list[tuple[str, str]]:
    elements = all_elements()
    members = set(view_members(view))
    result: list[tuple[str, str]] = []
    for derived in view_members(view):
        for base in elements[derived].get("bases", []):
            if base in members:
                result.append((derived, base))
    return result


def mermaid_for_view(view: dict[str, Any]) -> str:
    elements = all_elements()
    lines = [
        "classDiagram",
        "  direction TB",
        f"  %% {view['title']}",
        f"  %% {view['description']}",
    ]
    for qualified_name in view_members(view):
        item = elements[qualified_name]
        class_id = identifier(qualified_name)
        lines.append(f"  class {class_id} {{")
        if item.get("abstract"):
            lines.append("    <<abstract>>")
        if item.get("element_kind") == "datatype":
            lines.append("    <<datatype>>")
        elif item.get("optional"):
            lines.append("    <<optional>>")
        else:
            lines.append(f"    <<{package_label(item['package'])}>>")
        for attr in item.get("attributes", []):
            slash = "/" if attr.get("derived") else ""
            ordered = " {ordered}" if attr.get("ordered") else ""
            default = f" = {str(attr['default']).lower()}" if "default" in attr else ""
            lines.append(
                f"    +{slash}{attr['name']} : {simple_name(attr['type'])}{default} [{attr['multiplicity']}]{ordered}"
            )
        lines.append("  }")
        lines.append(f"  note for {class_id} \"{qualified_name}\"")

    for derived, base in view_generalizations(view):
        lines.append(f"  {identifier(base)} <|-- {identifier(derived)}")

    for item in view_associations(view):
        source = identifier(item["source"])
        target = identifier(item["target"])
        if item["composition"]:
            connector = "*--" if item["owner"] == "source" else "--*"
        elif item.get("stereotype") == "instanceRef":
            connector = "..>"
        else:
            connector = "-->"
        extras: list[str] = []
        if item.get("stereotype"):
            extras.append(f"«{item['stereotype']}»")
        if item.get("ordered"):
            extras.append("{ordered}")
        label = item["target_role"]
        if extras:
            label += " " + " ".join(extras)
        lines.append(
            f'  {source} "{item["source_multiplicity"]}" {connector} "{item["target_multiplicity"]}" {target} : {label}'
        )
    return "\n".join(lines) + "\n"


def node_style(item: dict[str, Any]) -> tuple[str, str]:
    package = item["package"]
    if package == "RCM::V2::Core":
        return "#EAF8EF", "#27734D"
    if package.startswith("RCM::") or "AnnexC" in package or item.get("optional"):
        return "#FFF6DE", "#9A6A17"
    return "#EEF5FF", "#315C96"


def wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    result: list[str] = []
    current: list[str] = []
    for word in words:
        proposed = " ".join([*current, word])
        if current and len(proposed) > max_chars:
            result.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        result.append(" ".join(current))
    return result or [""]


def display_attributes(item: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for attr in item.get("attributes", []):
        slash = "/" if attr.get("derived") else ""
        ordered = " {ordered}" if attr.get("ordered") else ""
        default = f"={str(attr['default']).lower()} " if "default" in attr else ""
        value = f"+ {slash}{attr['name']}: {simple_name(attr['type'])} {default}[{attr['multiplicity']}]{ordered}"
        if len(value) > 48:
            value = value[:45] + "…"
        result.append(value)
    if item.get("element_kind") == "datatype" and "min" in item:
        result.append(f"{{range [{item['min']}, {item['max']}]}}")
    return result


def compute_layout(view: dict[str, Any]) -> tuple[dict[str, dict[str, float]], int, int, int]:
    elements = all_elements()
    card_width = 310
    horizontal_gap = 34
    left_margin = 48
    top_margin = 130
    row_gap = 92
    max_columns = max(len(row) for row in view["rows"])
    width = max(1280, left_margin * 2 + max_columns * card_width + (max_columns - 1) * horizontal_gap)
    y = top_margin
    positions: dict[str, dict[str, float]] = {}
    for row in view["rows"]:
        heights = [112 + 19 * len(display_attributes(elements[item])) for item in row]
        row_height = max(heights)
        row_width = len(row) * card_width + (len(row) - 1) * horizontal_gap
        x = (width - row_width) / 2
        for item, card_height in zip(row, heights):
            positions[item] = {"x": x, "y": y, "w": card_width, "h": card_height}
            x += card_width + horizontal_gap
        y += row_height + row_gap

    relation_count = len(view_associations(view))
    relation_columns = 2 if width >= 1600 else 1
    relation_rows = math.ceil(relation_count / relation_columns)
    relation_top = int(y + 20)
    height = relation_top + 96 + relation_rows * 23 + 48
    return positions, width, height, relation_top


def edge_anchors(
    source_box: dict[str, float], target_box: dict[str, float]
) -> tuple[tuple[float, float], tuple[float, float]]:
    sx = source_box["x"] + source_box["w"] / 2
    sy = source_box["y"] + source_box["h"] / 2
    tx = target_box["x"] + target_box["w"] / 2
    ty = target_box["y"] + target_box["h"] / 2
    dx = tx - sx
    dy = ty - sy
    if abs(dy) >= abs(dx) * 0.55:
        start = (sx, source_box["y"] + (source_box["h"] if dy >= 0 else 0))
        end = (tx, target_box["y"] + (0 if dy >= 0 else target_box["h"]))
    else:
        start = (source_box["x"] + (source_box["w"] if dx >= 0 else 0), sy)
        end = (target_box["x"] + (0 if dx >= 0 else target_box["w"]), ty)
    return start, end


def svg_for_view(view: dict[str, Any]) -> str:
    elements = all_elements()
    positions, width, height, relation_top = compute_layout(view)
    associations = view_associations(view)
    generalizations = view_generalizations(view)
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(view["title"])}">',
        "<defs>",
        '<marker id="triangle" markerWidth="13" markerHeight="13" refX="11" refY="6.5" orient="auto"><path d="M 0 0 L 12 6.5 L 0 13 z" fill="#FFFFFF" stroke="#3F5067" stroke-width="1.5"/></marker>',
        '<marker id="arrow" markerWidth="11" markerHeight="11" refX="10" refY="5.5" orient="auto"><path d="M 0 0 L 10 5.5 L 0 11 z" fill="#61738A"/></marker>',
        '<marker id="diamond" markerWidth="14" markerHeight="10" refX="2" refY="5" orient="auto"><path d="M 1 5 L 6 1 L 11 5 L 6 9 z" fill="#263A52"/></marker>',
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="#FAFCFF"/>',
        f'<text x="48" y="48" font-family="Arial" font-size="25" font-weight="700" fill="#1F324A">{escape(view["title"])}</text>',
        f'<text x="48" y="78" font-family="Arial" font-size="15" fill="#53677F">{escape(view["description"])}</text>',
        '<text x="48" y="105" font-family="Arial" font-size="12" fill="#738399">Dreieck: Generalisierung · Raute: Komposition · gestrichelt: optional/instanceRef</text>',
    ]

    # Edges are drawn before cards so cards remain legible.
    for derived, base in generalizations:
        start, end = edge_anchors(positions[derived], positions[base])
        parts.append(
            f'<path d="M {start[0]:.1f} {start[1]:.1f} L {end[0]:.1f} {end[1]:.1f}" fill="none" stroke="#3F5067" stroke-width="2" marker-end="url(#triangle)"/>'
        )
    for item in associations:
        start, end = edge_anchors(positions[item["source"]], positions[item["target"]])
        dash = ' stroke-dasharray="7 6"' if item.get("optional") or item.get("stereotype") == "instanceRef" else ""
        marker_start = ' marker-start="url(#diamond)"' if item["composition"] and item["owner"] == "source" else ""
        if item["composition"]:
            marker_end = ' marker-end="url(#diamond)"' if item["owner"] == "target" else ""
        else:
            marker_end = ' marker-end="url(#arrow)"'
        parts.append(
            f'<path d="M {start[0]:.1f} {start[1]:.1f} L {end[0]:.1f} {end[1]:.1f}" fill="none" stroke="#687B92" stroke-width="1.5"{dash}{marker_start}{marker_end}/>'
        )
        mx = (start[0] + end[0]) / 2
        my = (start[1] + end[1]) / 2 - 5
        label = f'{item["target_role"]} [{item["target_multiplicity"]}]'
        parts.append(
            f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" font-family="Arial" font-size="11" fill="#43566E" style="paint-order:stroke;stroke:#FAFCFF;stroke-width:4px;stroke-linejoin:round">{escape(label)}</text>'
        )

    for qualified_name in view_members(view):
        item = elements[qualified_name]
        box = positions[qualified_name]
        fill, stroke = node_style(item)
        parts.append(
            f'<g><rect x="{box["x"]:.1f}" y="{box["y"]:.1f}" width="{box["w"]:.1f}" height="{box["h"]:.1f}" rx="7" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{box["x"] + 13:.1f}" y="{box["y"] + 20:.1f}" font-family="Arial" font-size="11" fill="#5B6F84">{escape(package_label(item["package"]))}</text>'
        )
        stereotypes: list[str] = []
        if item.get("abstract"):
            stereotypes.append("abstract")
        stereotypes.extend(item.get("stereotypes", []))
        if item.get("element_kind") == "datatype":
            stereotypes.append("datatype")
        if item.get("optional"):
            stereotypes.append("optional")
        if stereotypes:
            parts.append(
                f'<text x="{box["x"] + box["w"] - 13:.1f}" y="{box["y"] + 20:.1f}" text-anchor="end" font-family="Arial" font-size="10" fill="#7D6B46">«{escape(", ".join(stereotypes))}»</text>'
            )
        font_style = ' font-style="italic"' if item.get("abstract") else ""
        parts.append(
            f'<text x="{box["x"] + box["w"] / 2:.1f}" y="{box["y"] + 48:.1f}" text-anchor="middle" font-family="Arial" font-size="17" font-weight="700"{font_style} fill="#20344B">{escape(item["name"])}</text>'
        )
        parts.append(
            f'<line x1="{box["x"]:.1f}" y1="{box["y"] + 62:.1f}" x2="{box["x"] + box["w"]:.1f}" y2="{box["y"] + 62:.1f}" stroke="{stroke}" stroke-width="1" opacity="0.55"/>'
        )
        attr_y = box["y"] + 83
        attrs = display_attributes(item)
        if not attrs:
            parts.append(
                f'<text x="{box["x"] + 13:.1f}" y="{attr_y:.1f}" font-family="Arial" font-size="12" fill="#708195">(keine lokalen Attribute)</text>'
            )
        for attr in attrs:
            parts.append(
                f'<text x="{box["x"] + 13:.1f}" y="{attr_y:.1f}" font-family="Consolas, monospace" font-size="12" fill="#31475E">{escape(attr)}</text>'
            )
            attr_y += 19
        parts.append("</g>")

    parts.extend(
        [
            f'<line x1="48" y1="{relation_top}" x2="{width - 48}" y2="{relation_top}" stroke="#C7D3E0"/>',
            f'<text x="48" y="{relation_top + 31}" font-family="Arial" font-size="18" font-weight="700" fill="#263A52">Assoziationen dieser Sicht</text>',
        ]
    )
    columns = 2 if width >= 1600 else 1
    column_width = (width - 96) / columns
    rows_per_column = math.ceil(len(associations) / columns) if associations else 0
    for index, item in enumerate(associations):
        column = index // rows_per_column if rows_per_column else 0
        row = index % rows_per_column if rows_per_column else 0
        x = 48 + column * column_width
        y = relation_top + 61 + row * 23
        symbol = "◆" if item["composition"] else "→"
        optional = " optional" if item.get("optional") else ""
        ordered = " {ordered}" if item.get("ordered") else ""
        label = (
            f'{symbol} {simple_name(item["source"])}.{item["target_role"]} '
            f'[{item["target_multiplicity"]}]{ordered}{optional} → {simple_name(item["target"])}'
        )
        if len(label) > 92:
            label = label[:89] + "…"
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="Consolas, monospace" font-size="12" fill="#425970">{escape(label)}</text>'
        )
    if not associations:
        parts.append(
            f'<text x="48" y="{relation_top + 61}" font-family="Arial" font-size="12" fill="#708195">Keine lokalen Assoziationen in dieser Sicht.</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_png(view: dict[str, Any], path: Path) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("PNG generation requires Pillow") from exc

    elements = all_elements()
    positions, width, height, relation_top = compute_layout(view)
    associations = view_associations(view)
    generalizations = view_generalizations(view)

    def font(size: int, *, bold: bool = False, italic: bool = False, mono: bool = False):
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
                pass
        return ImageFont.load_default()

    title_font = font(25, bold=True)
    subtitle_font = font(15)
    small_font = font(11)
    node_title_font = font(17, bold=True)
    node_title_italic_font = font(17, bold=True, italic=True)
    attr_font = font(12, mono=True)
    relation_title_font = font(18, bold=True)
    relation_font = font(12, mono=True)

    image = Image.new("RGB", (width, height), "#FAFCFF")
    draw = ImageDraw.Draw(image)
    draw.text((48, 24), view["title"], font=title_font, fill="#1F324A")
    draw.text((48, 59), view["description"], font=subtitle_font, fill="#53677F")
    draw.text((48, 89), "Dreieck: Generalisierung · Raute: Komposition · gestrichelt: optional/instanceRef", font=small_font, fill="#738399")

    def dashed_line(start: tuple[float, float], end: tuple[float, float], fill: str, line_width: int) -> None:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = max(math.hypot(dx, dy), 1)
        cursor = 0.0
        while cursor < length:
            finish = min(cursor + 8, length)
            draw.line(
                (
                    (start[0] + dx * cursor / length, start[1] + dy * cursor / length),
                    (start[0] + dx * finish / length, start[1] + dy * finish / length),
                ),
                fill=fill,
                width=line_width,
            )
            cursor += 14

    def triangle(end: tuple[float, float], start: tuple[float, float]) -> None:
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        length = 13
        half = 7
        base = (end[0] - math.cos(angle) * length, end[1] - math.sin(angle) * length)
        normal = (-math.sin(angle), math.cos(angle))
        points = [end, (base[0] + normal[0] * half, base[1] + normal[1] * half), (base[0] - normal[0] * half, base[1] - normal[1] * half)]
        draw.polygon(points, fill="#FFFFFF", outline="#3F5067")

    def arrow(end: tuple[float, float], start: tuple[float, float], fill: str = "#687B92") -> None:
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        length = 10
        half = 5
        base = (end[0] - math.cos(angle) * length, end[1] - math.sin(angle) * length)
        normal = (-math.sin(angle), math.cos(angle))
        draw.polygon([end, (base[0] + normal[0] * half, base[1] + normal[1] * half), (base[0] - normal[0] * half, base[1] - normal[1] * half)], fill=fill)

    def diamond(start: tuple[float, float], end: tuple[float, float]) -> None:
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        along = (math.cos(angle), math.sin(angle))
        normal = (-along[1], along[0])
        center = (start[0] + along[0] * 7, start[1] + along[1] * 7)
        points = [
            start,
            (center[0] + normal[0] * 5, center[1] + normal[1] * 5),
            (start[0] + along[0] * 14, start[1] + along[1] * 14),
            (center[0] - normal[0] * 5, center[1] - normal[1] * 5),
        ]
        draw.polygon(points, fill="#263A52")

    for derived, base in generalizations:
        start, end = edge_anchors(positions[derived], positions[base])
        draw.line((start, end), fill="#3F5067", width=2)
        triangle(end, start)
    for item in associations:
        start, end = edge_anchors(positions[item["source"]], positions[item["target"]])
        if item.get("optional") or item.get("stereotype") == "instanceRef":
            dashed_line(start, end, "#687B92", 2)
        else:
            draw.line((start, end), fill="#687B92", width=2)
        if item["composition"] and item["owner"] == "source":
            diamond(start, end)
        else:
            arrow(end, start)
        label = f'{item["target_role"]} [{item["target_multiplicity"]}]'
        bbox = draw.textbbox((0, 0), label, font=small_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        mx = (start[0] + end[0]) / 2
        my = (start[1] + end[1]) / 2 - text_height - 3
        draw.rounded_rectangle((mx - text_width / 2 - 3, my - 1, mx + text_width / 2 + 3, my + text_height + 2), radius=2, fill="#FAFCFF")
        draw.text((mx - text_width / 2, my), label, font=small_font, fill="#43566E")

    for qualified_name in view_members(view):
        item = elements[qualified_name]
        box = positions[qualified_name]
        fill, stroke = node_style(item)
        coords = (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
        draw.rounded_rectangle(coords, radius=7, fill=fill, outline=stroke, width=2)
        draw.text((box["x"] + 13, box["y"] + 8), package_label(item["package"]), font=small_font, fill="#5B6F84")
        stereotypes: list[str] = []
        if item.get("abstract"):
            stereotypes.append("abstract")
        stereotypes.extend(item.get("stereotypes", []))
        if item.get("element_kind") == "datatype":
            stereotypes.append("datatype")
        if item.get("optional"):
            stereotypes.append("optional")
        if stereotypes:
            stereo = f"«{', '.join(stereotypes)}»"
            bbox = draw.textbbox((0, 0), stereo, font=small_font)
            draw.text((box["x"] + box["w"] - 13 - (bbox[2] - bbox[0]), box["y"] + 8), stereo, font=small_font, fill="#7D6B46")
        title_font_for_item = node_title_italic_font if item.get("abstract") else node_title_font
        bbox = draw.textbbox((0, 0), item["name"], font=title_font_for_item)
        draw.text((box["x"] + (box["w"] - (bbox[2] - bbox[0])) / 2, box["y"] + 30), item["name"], font=title_font_for_item, fill="#20344B")
        draw.line((box["x"], box["y"] + 62, box["x"] + box["w"], box["y"] + 62), fill=stroke, width=1)
        attrs = display_attributes(item)
        if not attrs:
            draw.text((box["x"] + 13, box["y"] + 72), "(keine lokalen Attribute)", font=attr_font, fill="#708195")
        for index, attr in enumerate(attrs):
            draw.text((box["x"] + 13, box["y"] + 72 + index * 19), attr, font=attr_font, fill="#31475E")

    draw.line((48, relation_top, width - 48, relation_top), fill="#C7D3E0", width=1)
    draw.text((48, relation_top + 11), "Assoziationen dieser Sicht", font=relation_title_font, fill="#263A52")
    columns = 2 if width >= 1600 else 1
    column_width = (width - 96) / columns
    rows_per_column = math.ceil(len(associations) / columns) if associations else 0
    for index, item in enumerate(associations):
        column = index // rows_per_column if rows_per_column else 0
        row = index % rows_per_column if rows_per_column else 0
        x = 48 + column * column_width
        y = relation_top + 50 + row * 23
        symbol = "◆" if item["composition"] else "→"
        optional = " optional" if item.get("optional") else ""
        ordered = " {ordered}" if item.get("ordered") else ""
        label = f'{symbol} {simple_name(item["source"])}.{item["target_role"]} [{item["target_multiplicity"]}]{ordered}{optional} → {simple_name(item["target"])}'
        if len(label) > 92:
            label = label[:89] + "…"
        draw.text((x, y), label, font=relation_font, fill="#425970")
    if not associations:
        draw.text((48, relation_top + 50), "Keine lokalen Assoziationen in dieser Sicht.", font=relation_font, fill="#708195")
    image.save(path, format="PNG", optimize=False, compress_level=9)


def markdown_cell(value: Any) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text


def attributes_markdown(item: dict[str, Any]) -> str:
    values: list[str] = []
    for attr in item.get("attributes", []):
        slash = "/" if attr.get("derived") else ""
        ordered = " {ordered}" if attr.get("ordered") else ""
        default = f" = `{str(attr['default']).lower()}`" if "default" in attr else ""
        values.append(f"`{slash}{attr['name']}: {simple_name(attr['type'])} [{attr['multiplicity']}]{ordered}`{default}")
    if item.get("element_kind") == "datatype" and "min" in item:
        values.append(f"range `[{item['min']}, {item['max']}]`")
    return "<br>".join(values) if values else "—"


def specification_markdown() -> str:
    metadata = MODEL["metadata"]
    by_package: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for qualified_name, item in all_elements().items():
        by_package[item["package"]].append((qualified_name, item))
    lines = [
        f"# {metadata['name']} – Metamodel specification", "",
        f"Model version: `{metadata['model_version']}`  ",
        f"Namespace: `{metadata['namespace']}`  ",
        f"Status: `{metadata['status']}`  ",
        f"EAST-ADL reference: V{metadata['east_adl_version']}  ",
        f"Canonical source: `{metadata['canonical_source']}`", "",
        "## 1. Scope and conformance", "",
        "The blue EAST-ADL metaclasses form a selected, unchanged slice of EAST-ADL V2.1.12. An omitted class is outside this slice, not a change to EAST-ADL. All project-specific classes and relationships belong to `RCM::V2`.", "",
        "Dependencies are one-way: RCM imports EAST-ADL. No imported EAST-ADL metaclass gains a project-specific property, mandatory association or reverse dependency. Annex C, Feature Mapping and AgentKnowledge are optional modules; Annex C is preliminary in V2.1.12.", "",
        "Native V2 instances are consumed by the backend and authoring pipeline. The executable routing profile adds Gate 0 publication verification (INV-075–081). The v0.5 compatibility projection remains available. Runtime pin, digest and fingerprint state are not new metamodel classes.", "",
        "## 2. Packages", "", "| Package | Kind | Normative | Imports | Purpose |", "| --- | --- | --- | --- | --- |",
    ]
    for package_name, package in MODEL["packages"].items():
        imports = ", ".join(f"`{item}`" for item in package.get("imports", [])) or "—"
        normative = "yes" if package.get("normative") else "no"
        if package.get("preliminary"):
            normative += "; preliminary"
        lines.append(f"| `{package_name}` | {package['kind']} | {normative} | {imports} | {markdown_cell(package['description'])} |")
    lines.extend(["", "## 3. Enumerations", "", "| Enumeration | Literals | Source |", "| --- | --- | --- |"])
    for qualified_name, enum in MODEL["enums"].items():
        literals = ", ".join(f"`{item}`" for item in enum["literals"])
        lines.append(f"| `{qualified_name}` | {literals} | {enum.get('east_adl_source', 'RCM V2')} |")
    lines.extend(["", "## 4. Classes and datatypes", ""])
    for package_name in MODEL["packages"]:
        package_items = sorted(by_package.get(package_name, []), key=lambda pair: pair[1]["name"])
        if not package_items:
            continue
        lines.extend([f"### {package_name}", "", "| Element | Bases | Locally defined attributes | Description | EAST-ADL source |", "| --- | --- | --- | --- | --- |"])
        for qualified_name, item in package_items:
            bases = ", ".join(f"`{base}`" for base in item.get("bases", [])) or "—"
            flags = [flag for flag in ("abstract" if item.get("abstract") else "", "datatype" if item.get("element_kind") == "datatype" else "", "optional" if item.get("optional") else "") if flag]
            suffix = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"| `{item['name']}`{suffix} | {bases} | {attributes_markdown(item)} | {markdown_cell(item['description'])} | {item.get('east_adl_source', 'RCM V2')} |")
        lines.append("")
    lines.extend(["## 5. Associations", "", "Multiplicity belongs to the referenced end. `{ordered}` denotes semantic collection order; `{composite}` denotes exactly one composition owner.", "", "| ID | Package | Source | Target/role | Multiplicities | Properties |", "| --- | --- | --- | --- | --- | --- |"])
    for item in MODEL["associations"]:
        properties = []
        if item["composition"]:
            properties.append(f"composite; owner={item['owner']}")
        if item["ordered"]:
            properties.append("ordered")
        if item.get("stereotype"):
            properties.append(f"«{item['stereotype']}»")
        if item.get("optional"):
            properties.append("optional module")
        lines.append(f"| `{item['id']}` | `{item['package']}` | `{simple_name(item['source'])}.{item['source_role']}` | `{simple_name(item['target'])}.{item['target_role']}` | `{item['source_multiplicity']} → {item['target_multiplicity']}` | {', '.join(properties) or '—'} |")
    lines.extend(["", "## 6. Numbered invariants", "", "This list is canonical. Diagrams, tests and compatibility evidence reference these IDs. A declaration is not proof of enforcement: consult the generated `docs/INVARIANT_TRACEABILITY.md` registry. The executable routing profile is opt-in in the validator; the original structural baseline remains separable.", "", "| ID | Profile | Severity | Scope | Check expression | Meaning |", "| --- | --- | --- | --- | --- | --- |"])
    for item in MODEL["invariants"]:
        lines.append(f"| **{item['id']}** | `{item['profile']}` | `{item['severity']}` | `{item['scope']}` | `{markdown_cell(item['expression'])}` | {markdown_cell(item['text'])} |")
    contract = MODEL["compatibility_contract"]
    lines.extend(["", "## 7. Lossless v0.5 compatibility view", "", f"The technical view is `{contract['projection_name']}`. {contract['canonical_v2_independence']}", "", "Projection laws:", ""])
    lines.extend(f"- `{law}`" for law in contract["laws"])
    lines.extend(["", "The ledger preserves:", ""])
    lines.extend(f"- {item}" for item in contract["ledger_preserves"])
    lines.extend(["", "Required domain-to-runtime chain:", "", "```text", " -> ".join(contract["required_chain"]), "```", "", f"Forbidden shortcut: `{contract['forbidden_shortcut']}`.", "",
        "`CapabilityUse.provider` has core multiplicity `[0..1]` because legacy v0.5 data cannot always identify a unique provider. The executable authoring profile requires exactly one provider through INV-065; it must perform the owning ScenarioStep and provide the capability type. `CapabilityUse.target [*]` names affected identifiable objects without repurposing parameters.", "",
        "`Assertion` generalizes testable state, event, output, grounding and relation statements. `StateAssertion` remains a losslessly projectable specialization. Effects use `specifiedBy: Assertion [1..*]`; the legacy field name `evidencedBy` exists only in the v0.5 projection.", "",
        "`StepRelation` is the only control-flow authority. `Scenario.step` is containment and `stepNumber` is display data. Probabilities are allowed only on alternative/exception edges; a fully annotated mutually exclusive branch sums to one. Incompatible legacy values remain unchanged in the projection ledger.", "",
        "## 8. Verification and validation", "",
        "`DynamicFunctionalModel` owns exactly one unchanged `VerificationValidation` container, which owns VVCase, VVTarget and Verify instances. `ValidationCase` is composed only through `VerificationValidation.vvCase`. `RuntimeActualOutcome` belongs only to a RuntimeValidationLog/VVLog.", "",
        "`VVCase.vvSubject` names the primary subject under test. `VVTarget.element` names elements realized by the test environment. The roles are distinct but may happen to reference the same elements.", "",
        "`RuntimeValidationTarget` specifies `platform [1]`, optional `environmentRef` and configured `runtimeBinding [*]`; these bindings also appear in inherited `VVTarget.element`. RCM subjects may be ScenarioStep, Capability, RuntimeBinding and Entity without modifying the EAST-ADL association.", "",
        "`RuntimeActualOutcome` contains at least one structured AssertionResult. Each result references exactly one Assertion and records a verdict, optional typed observation, evidence reference and timestamp. Legacy `ValidationCase.level` is preserved in the compatibility ledger; it cannot be inferred from `abstractVVCase`.", "",
        "## 9. Optional Annex C mapping", "",
        "Annex C is preliminary in EAST-ADL V2.1.12. These mappings are semantic options, not core validity requirements.", "", "| RCM source | Annex C target | Mapping kind | Status |", "| --- | --- | --- | --- |"])
    for item in MODEL["annex_mappings"]:
        lines.append(f"| `{item['source']}` | `{item['target']}` | {item['kind']} | {item['status']} |")
    lines.extend(["", "Annex C TransitionEvent specializes EAElement and BehaviorConstraintParameter, not Timing::Event. Its connection is only `TransitionEvent.occurredExecutionEvent: Timing::Event [*]`.", "", "## 10. Generated views", "", "Every view is generated from the same model as Mermaid, SVG and PNG. The compact A/B/C overview and seven detailed views provide class and relationship coverage. Separate publication-size routing slices are generated by `tools/generate_routing_figures.py`.", "", "| Prefix | Title | Purpose |", "| --- | --- | --- |"])
    for view_name, view in MODEL["views"].items():
        lines.append(f"| `{view_name}` | {view['title']} | {view['description']} |")
    lines.extend(["", "## 11. Reproducibility", "", "The generator checks references, package dependencies, unique association/invariant IDs, gapless invariant numbering and view members before writing. JSON keys are sorted and artifacts contain no generation timestamps. `generation_manifest.sha256.json` records hashes for every managed output.", ""])
    return "\n".join(lines)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def managed_file_names() -> set[str]:
    names = {MODEL_FILENAME, SPEC_FILENAME, MANIFEST_FILENAME}
    for view_name in MODEL["views"]:
        names.update({f"{view_name}.mmd", f"{view_name}.svg", f"{view_name}.png"})
    return names


def generate() -> dict[str, Any]:
    errors = validate_model()
    if errors:
        raise ValueError("Canonical model validation failed:\n- " + "\n- ".join(errors))

    OUT.mkdir(parents=True, exist_ok=True)
    expected = managed_file_names()
    old_manifest_path = OUT / MANIFEST_FILENAME
    if old_manifest_path.exists():
        try:
            old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
            old_managed = set(old_manifest.get("managed_files", []))
        except (json.JSONDecodeError, OSError):
            old_managed = set()
        for stale_name in sorted(old_managed - expected):
            stale_path = (OUT / stale_name).resolve()
            if stale_path.parent == OUT.resolve() and stale_path.is_file():
                stale_path.unlink()

    write_text(OUT / MODEL_FILENAME, stable_json(MODEL))
    write_text(OUT / SPEC_FILENAME, specification_markdown())

    for view_name, view in MODEL["views"].items():
        write_text(OUT / f"{view_name}.mmd", render_v2_mermaid(MODEL, view))
        write_text(OUT / f"{view_name}.svg", render_v2_svg(MODEL, view))
        render_v2_png(MODEL, view, OUT / f"{view_name}.png")

    artifact_names = sorted(expected - {MANIFEST_FILENAME})
    artifact_entries = [
        {
            "path": name,
            "bytes": (OUT / name).stat().st_size,
            "sha256": sha256_file(OUT / name),
        }
        for name in artifact_names
    ]
    source_files = [
        ROOT / "tools" / "dynamic_functional_rdl_v2_model.py",
        ROOT / "tools" / "generate_dynamic_functional_rdl_v2.py",
        ROOT / "tools" / "dynamic_functional_rdl_v2_diagrams.py",
    ]
    manifest = {
        "format": "RCM-V2-deterministic-generation-manifest/1",
        "model_version": MODEL["metadata"]["model_version"],
        "managed_files": sorted(expected),
        "source_files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in source_files
        ],
        "artifacts": artifact_entries,
        "artifact_set_sha256": sha256_bytes(stable_json(artifact_entries).encode("utf-8")),
    }
    write_text(old_manifest_path, stable_json(manifest))
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate the canonical descriptor without writing artifacts.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    errors = validate_model()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if args.check:
        print(
            f"OK: {len(MODEL['classes'])} classes, {len(MODEL['datatypes'])} datatypes, "
            f"{len(MODEL['associations'])} associations, {len(MODEL['invariants'])} invariants, "
            f"{len(MODEL['views'])} views"
        )
        return 0
    manifest = generate()
    print(
        f"Generated {len(manifest['artifacts']) + 1} deterministic artifacts in {OUT} "
        f"(set {manifest['artifact_set_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
