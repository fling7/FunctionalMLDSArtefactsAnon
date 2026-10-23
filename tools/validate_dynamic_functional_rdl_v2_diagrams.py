from __future__ import annotations

"""Deterministic geometry and format QA for the generated V2 diagrams."""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image

from dynamic_functional_rdl_v2_diagrams import Edge, Scene, build_scene
from dynamic_functional_rdl_v2_model import MODEL


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENERATED = ROOT / "output" / "metamodel_v2" / "generated"
DEFAULT_REPORT = ROOT / "output" / "metamodel_v2" / "evidence" / "diagram_geometry_qa.json"
EPSILON = 0.1


def _segments(edge: Edge) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return list(zip(edge.points, edge.points[1:]))


def _orientation(segment: tuple[tuple[float, float], tuple[float, float]]) -> str:
    (x1, y1), (x2, y2) = segment
    if abs(y1 - y2) <= EPSILON:
        return "horizontal"
    if abs(x1 - x2) <= EPSILON:
        return "vertical"
    return "diagonal"


def _strict_between(value: float, first: float, second: float) -> bool:
    low, high = sorted((first, second))
    return low + EPSILON < value < high - EPSILON


def _proper_crossing(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float] | None:
    first_orientation = _orientation(first)
    second_orientation = _orientation(second)
    if {first_orientation, second_orientation} != {"horizontal", "vertical"}:
        return None
    horizontal = first if first_orientation == "horizontal" else second
    vertical = second if second_orientation == "vertical" else first
    (hx1, hy), (hx2, _) = horizontal
    (vx, vy1), (_, vy2) = vertical
    if _strict_between(vx, hx1, hx2) and _strict_between(hy, vy1, vy2):
        return (vx, hy)
    return None


def _overlap_length(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    orientation = _orientation(first)
    if orientation != _orientation(second) or orientation == "diagonal":
        return 0.0
    if orientation == "horizontal":
        if abs(first[0][1] - second[0][1]) > EPSILON:
            return 0.0
        first_range = sorted((first[0][0], first[1][0]))
        second_range = sorted((second[0][0], second[1][0]))
    else:
        if abs(first[0][0] - second[0][0]) > EPSILON:
            return 0.0
        first_range = sorted((first[0][1], first[1][1]))
        second_range = sorted((second[0][1], second[1][1]))
    return max(0.0, min(first_range[1], second_range[1]) - max(first_range[0], second_range[0]))


def _segment_hits_box_interior(
    segment: tuple[tuple[float, float], tuple[float, float]],
    box: Any,
) -> bool:
    (x1, y1), (x2, y2) = segment
    left, right = box.x + 1.0, box.x + box.w - 1.0
    top, bottom = box.y + 1.0, box.y + box.h - 1.0
    orientation = _orientation(segment)
    if orientation == "horizontal":
        return top < y1 < bottom and min(x1, x2) < right and max(x1, x2) > left
    if orientation == "vertical":
        return left < x1 < right and min(y1, y2) < bottom and max(y1, y2) > top
    # Conservative bounding-box fallback; diagonal segments fail separately as well.
    return min(x1, x2) < right and max(x1, x2) > left and min(y1, y2) < bottom and max(y1, y2) > top


def _rectangles_overlap(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> bool:
    return (
        min(first[2], second[2]) - max(first[0], second[0]) > EPSILON
        and min(first[3], second[3]) - max(first[1], second[1]) > EPSILON
    )


def _edge_name(edge: Edge, index: int) -> str:
    return edge.label or f"unlabeled-edge-{index + 1}"


def _scene_geometry(scene: Scene) -> dict[str, Any]:
    diagonal_segments: list[dict[str, Any]] = []
    foreign_card_hits: list[dict[str, Any]] = []
    proper_crossings: list[dict[str, Any]] = []
    overlapping_segments: list[dict[str, Any]] = []
    label_card_overlaps: list[dict[str, Any]] = []

    for edge_index, edge in enumerate(scene.edges):
        for segment_index, segment in enumerate(_segments(edge)):
            if _orientation(segment) == "diagonal":
                diagonal_segments.append({
                    "edge": _edge_name(edge, edge_index),
                    "segment": segment_index + 1,
                    "points": segment,
                })
            for box in scene.boxes:
                if _segment_hits_box_interior(segment, box):
                    foreign_card_hits.append({
                        "edge": _edge_name(edge, edge_index),
                        "segment": segment_index + 1,
                        "card": box.title,
                    })

    for first_index, first_edge in enumerate(scene.edges):
        for second_index in range(first_index + 1, len(scene.edges)):
            second_edge = scene.edges[second_index]
            seen_crossings: set[tuple[float, float]] = set()
            for first_segment in _segments(first_edge):
                for second_segment in _segments(second_edge):
                    crossing = _proper_crossing(first_segment, second_segment)
                    if crossing and crossing not in seen_crossings:
                        seen_crossings.add(crossing)
                        proper_crossings.append({
                            "edge_a": _edge_name(first_edge, first_index),
                            "edge_b": _edge_name(second_edge, second_index),
                            "at": crossing,
                        })
                    overlap = _overlap_length(first_segment, second_segment)
                    if overlap > EPSILON:
                        overlapping_segments.append({
                            "edge_a": _edge_name(first_edge, first_index),
                            "edge_b": _edge_name(second_edge, second_index),
                            "length": round(overlap, 3),
                        })

    for edge_index, edge in enumerate(scene.edges):
        if not edge.label or edge.label_pos is None:
            continue
        x, y = edge.label_pos
        width = max(40.0, len(edge.label) * 6.4 + 10.0)
        label_rect = (x - width / 2.0, y - 12.0, x + width / 2.0, y + 6.0)
        for box in scene.boxes:
            card_rect = (box.x + 1.0, box.y + 1.0, box.x + box.w - 1.0, box.y + box.h - 1.0)
            if _rectangles_overlap(label_rect, card_rect):
                label_card_overlaps.append({"edge": _edge_name(edge, edge_index), "card": box.title})

    counts = {
        "diagonal_segments": len(diagonal_segments),
        "foreign_card_hits": len(foreign_card_hits),
        "proper_crossings": len(proper_crossings),
        "overlapping_segments": len(overlapping_segments),
        "label_card_overlaps": len(label_card_overlaps),
    }
    return {
        "edge_count": len(scene.edges),
        "counts": counts,
        "incidents": {
            "diagonal_segments": diagonal_segments,
            "foreign_card_hits": foreign_card_hits,
            "proper_crossings": proper_crossings,
            "overlapping_segments": overlapping_segments,
            "label_card_overlaps": label_card_overlaps,
        },
        "status": "PASS" if all(value == 0 for value in counts.values()) else "FAIL",
    }


def _format_checks(generated: Path, view_name: str, scene: Scene) -> dict[str, Any]:
    png_path = generated / f"{view_name}.png"
    svg_path = generated / f"{view_name}.svg"
    mmd_path = generated / f"{view_name}.mmd"
    with Image.open(png_path) as image:
        png_size = list(image.size)
    root = ET.parse(svg_path).getroot()
    svg_width = int(float(root.attrib["width"]))
    svg_height = int(float(root.attrib["height"]))
    mermaid = mmd_path.read_text(encoding="utf-8")
    expected = [scene.width, scene.height]
    checks = {
        "png_dimensions_match_scene": png_size == expected,
        "svg_dimensions_match_scene": [svg_width, svg_height] == expected,
        "svg_is_xml": root.tag.endswith("svg"),
        "mermaid_has_no_note_for": "note for" not in mermaid.lower(),
        "overview_mermaid_contains_model_nodes": view_name != "dynamic_functional_rdl_v2_metamodel" or (
            "subgraph A" in mermaid and "ScenarioStep" in mermaid and "RuntimeBinding" in mermaid
        ),
    }
    return {
        "png_dimensions": png_size,
        "svg_dimensions": [svg_width, svg_height],
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def validate(generated: Path) -> dict[str, Any]:
    views: dict[str, Any] = {}
    for view_name, view in MODEL["views"].items():
        scene = build_scene(MODEL, view)
        geometry = _scene_geometry(scene)
        formats = _format_checks(generated, view_name, scene)
        views[view_name] = {
            "title": view["title"],
            "geometry": geometry,
            "formats": formats,
            "status": "PASS" if geometry["status"] == formats["status"] == "PASS" else "FAIL",
        }
    totals = {
        metric: sum(item["geometry"]["counts"][metric] for item in views.values())
        for metric in (
            "diagonal_segments",
            "foreign_card_hits",
            "proper_crossings",
            "overlapping_segments",
            "label_card_overlaps",
        )
    }
    return {
        "model_version": MODEL["metadata"]["model_version"],
        "view_count": len(views),
        "acceptance_thresholds": {metric: 0 for metric in totals},
        "totals": totals,
        "views": views,
        "status": "PASS" if all(item["status"] == "PASS" for item in views.values()) else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, default=DEFAULT_GENERATED)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = validate(args.generated.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Diagram geometry QA: {report['status']} "
        f"({report['view_count']} views; totals={report['totals']})"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
