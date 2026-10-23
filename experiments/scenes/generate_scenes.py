"""Deterministic synthetic source rooms; no LLM outputs or participant data."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.case_study_pipeline.rdl_ingestion import normalize_scene

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = {
    "astronomy_gallery": ["telescope", "star_map", "planet_model", "meteorite_display", "orbit_simulator", "spectroscope"],
    "botanical_center": ["seed_display", "leaf_model", "soil_station", "plant_case", "root_diagram", "pollination_model"],
    "maritime_museum": ["ship_model", "navigation_chart", "anchor_display", "compass_case", "sail_diagram", "buoy_model"],
    "energy_exhibition": ["solar_panel_model", "turbine_model", "battery_case", "grid_diagram", "insulation_sample", "generator_display"],
    "archaeology_gallery": ["pottery_display", "tool_case", "excavation_model", "mosaic_panel", "dating_station", "settlement_map"],
    "music_workshop": ["string_instrument", "percussion_station", "wind_instrument", "score_display", "sound_panel", "rhythm_console"],
    "transport_center": ["rail_model", "bicycle_display", "signal_station", "bridge_model", "route_map", "wheel_display"],
    "materials_lab": ["metal_sample", "polymer_sample", "ceramic_case", "fiber_display", "crystal_model", "strength_station"],
    "ocean_discovery": ["coral_model", "current_diagram", "shell_case", "submersible_model", "plankton_display", "depth_station"],
    "robotics_showroom": ["gripper_display", "sensor_station", "mobile_robot_model", "joint_model", "control_console", "assembly_display"],
    "geology_gallery": ["rock_case", "fault_model", "volcano_model", "mineral_display", "erosion_station", "strata_panel"],
    "food_science_center": ["grain_display", "fermentation_model", "nutrition_panel", "preservation_station", "milling_model", "supply_map"],
}
SIZES = (15, 24, 40, 80)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

def make_scene(domain: str, count: int, seed: int, *, scene_id: str | None = None) -> dict:
    if domain not in DOMAINS or not 1 <= count <= 1000:
        raise ValueError("Unknown domain or unsupported scene size.")
    rng = random.Random(seed)
    columns = max(3, math.ceil(math.sqrt(count)))
    rows = math.ceil(count / columns)
    spacing = 2.8
    width, depth = round((columns + 2) * spacing, 2), round((rows + 2) * spacing, 2)
    labels = list(DOMAINS[domain])
    rng.shuffle(labels)
    objects = []
    for index in range(count):
        kind = labels[index % len(labels)]
        height = round(rng.uniform(0.7, 1.5), 2)
        objects.append({"objectId": f"object_{index+1:03d}", "objectType": kind,
                        "position": {"x": round((index % columns - (columns-1)/2)*spacing, 2), "y": height/2,
                                     "z": round((index // columns - (rows-1)/2)*spacing, 2)},
                        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                        "dimensions": {"width": 0.8, "height": height, "depth": 0.8},
                        "group": f"collection_{index % 3 + 1}", "children": [],
                        "specification": f"Synthetic {domain.replace('_',' ')} object: {kind.replace('_',' ')}. "
                                         f"Display {index+1} explains a distinct example in collection {index%3+1}. "
                                         "A freestanding educational display with a clearly visible label; no real person or institution."})
    scene = {"scene": {"sceneName": scene_id or f"{domain}_{count}_{seed}", "environment": {
        "type": "indoor", "dimensions": {"width": width, "height": 4.0, "depth": depth},
        "lighting": [{"lightType": "ambient", "intensity": 0.7, "color": "#FFFFFF"}], "background": "#ECECEC"},
        "objectGroups": {f"collection_{i}": {"color": color} for i,color in enumerate(("#7A9DB2","#B2A37A","#8BAE8B"),1)},
        "objects": objects}}
    validate_source(scene)
    return scene

def validate_source(scene: dict) -> dict:
    normalized, report = normalize_scene(scene)
    if report["status"] != "valid":
        raise ValueError("Source scene failed packet ingestion validation.")
    objects = scene["scene"]["objects"]
    ids = [o["objectId"] for o in objects]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source object identifier.")
    bounds = normalized["room_bounds"]
    for obj in objects:
        p, d = obj["position"], obj["dimensions"]
        if not (bounds["min_x"] <= p["x"]-d["width"]/2 < p["x"]+d["width"]/2 <= bounds["max_x"]
                and bounds["min_z"] <= p["z"]-d["depth"]/2 < p["z"]+d["depth"]/2 <= bounds["max_z"]):
            raise ValueError("Object lies outside room bounds.")
    for i,left in enumerate(objects):
        for right in objects[i+1:]:
            if abs(left["position"]["x"]-right["position"]["x"]) < (left["dimensions"]["width"]+right["dimensions"]["width"])/2 and abs(left["position"]["z"]-right["position"]["z"]) < (left["dimensions"]["depth"]+right["dimensions"]["depth"])/2:
                raise ValueError("Object footprints overlap.")
    return {"status": "valid", "object_count": len(objects), "group_count": len(scene["scene"]["objectGroups"]),
            "geometry": "nonoverlapping axis-aligned footprints inside room; open grid aisles"}

def generate(output_root: Path = ROOT/"experiments/scenes/sources") -> dict:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    rows=[]
    for size_index,size in enumerate(SIZES):
        for domain_index,domain in enumerate(DOMAINS):
            number=size_index*len(DOMAINS)+domain_index+1
            scene_id=f"scene_{number:03d}_{domain}"
            seed=2026101500+number
            payload=make_scene(domain,size,seed,scene_id=scene_id)
            path=output_root/(scene_id+".json")
            text=canonical(payload)
            if path.exists() and path.read_text(encoding="utf-8") != text:
                raise FileExistsError("Source scene differs from existing frozen file.")
            path.write_text(text,encoding="utf-8",newline="\n")
            rows.append({"scene_id":scene_id,"domain":domain,"object_count":size,"seed":seed,
                         "split":"dev" if number<=3 else "evaluation",
                         "path":path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
                         "sha256":hashlib.sha256(text.encode()).hexdigest(),"validation":validate_source(payload),
                         "provenance":"deterministic_synthetic_generator"})
    report={"schema":"synthetic_source_corpus_v1","scenes":rows,
            "counts":{"total":len(rows),"domains":len(DOMAINS),"dev":sum(r["split"]=="dev" for r in rows),
                      "evaluation":sum(r["split"]=="evaluation" for r in rows),"llm_written":0},
            "size_range":[min(r["object_count"] for r in rows),max(r["object_count"] for r in rows)],
            "limitations":"Geometry follows one open-grid family. Domain labels and object vocabularies vary; these are not deployment samples."}
    (output_root/"manifest.json").write_text(canonical(report),encoding="utf-8",newline="\n")
    return report

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-root",type=Path,default=ROOT/"experiments/scenes/sources")
    args=parser.parse_args()
    print(json.dumps(generate(args.output_root)["counts"]))

