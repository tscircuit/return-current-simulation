"""Canonical physical-input provenance; no NumPy/VTK runtime is needed."""

import hashlib
import json
import math


def canonical_json(value, digits=12):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Non-finite provenance value")
        if value == 0:
            return "0"
        mantissa, exponent = format(value, f".{digits - 1}e").split("e")
        return f"{mantissa}e{int(exponent):+d}"
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(item, digits) for item in value) + "]"
    return "{" + ",".join(
        json.dumps(key, ensure_ascii=False) + ":" + canonical_json(
            json.loads(value[key]) if key == "physicalModelSignature" and isinstance(value[key], str) else value[key], digits
        ) for key in sorted(value)
    ) + "}"


def input_manifest(circuit, model):
    inputs = [e for e in circuit if not e["type"].startswith("simulation_")]
    inputs.extend(model["geometry"]["excitations"])
    return {
        "schemaVersion": 1,
        "numericPrecision": "model_12_input_17_significant_digits",
        "circuitSha256": hashlib.sha256(canonical_json(inputs, 17).encode()).hexdigest(),
        "modelSha256": hashlib.sha256(canonical_json(model).encode()).hexdigest(),
    }


def validate_inputs(case, model):
    manifest = input_manifest(json.loads((case / "circuit.json").read_text()), model)
    saved = case / "input-manifest.json"
    if saved.exists():
        recorded = json.loads(saved.read_text())
        if any(recorded.get(key) != value for key, value in manifest.items()):
            raise ValueError("Palace physical inputs changed after preparation")
        for filename, key in [("circuit.json", "circuitFileSha256"), ("model.json", "modelFileSha256"), ("mesh.msh", "meshSha256")]:
            if key in recorded and recorded[key] != hashlib.sha256((case / filename).read_bytes()).hexdigest():
                raise ValueError(f"Palace {filename} changed after preparation/meshing")
    elif (case / "reference.json").exists():
        previous = json.loads((case / "reference.json").read_text())["provenance"]
        for filename, key in [("circuit.json", "circuitSha256"), ("model.json", "modelSha256"), ("mesh.msh", "meshSha256")]:
            if previous[key] != hashlib.sha256((case / filename).read_bytes()).hexdigest():
                raise ValueError(f"Legacy Palace {filename} changed since its verified solve")
    return manifest


def coordinate(number):
    return f"{0 if abs(number) < 0.5e-9 else number:.9f}"


def point(position):
    return [coordinate(position["x"]), coordinate(position["y"])]


def geometry_signature(geometry):
    signature = [
        [point(position) for position in geometry["boardOutline"]],
        [
            [
                [point(position) for position in region["outer"]],
                [[point(position) for position in hole] for hole in [*region["holes"], *region.get("maskCutouts", [])]],
            ]
            for region in geometry["groundRegions"]
        ],
        [[point(position) for position in outline] for outline in geometry["cutouts"]],
        [
            [
                [*point(route), coordinate(route["width"]), route["layer"]]
                for route in signal["route"]
                if route["route_type"] == "wire"
            ]
            for signal in geometry["signals"]
        ],
        *([canonical_json(json.loads(geometry["physicalModelSignature"]))] if geometry.get("physicalModelSignature") else []),
        [
            [
                coordinate(excitation["current"]),
                point(excitation["return_source"]),
                point(excitation["return_sink"]),
                *([[excitation.get("source_port", {}).get("reference_layer", "bottom"), coordinate(excitation.get("source_port", {}).get("resistance", 50)), excitation.get("load_port", {}).get("reference_layer", "bottom"), coordinate(excitation.get("load_port", {}).get("resistance", 50))]] if excitation.get("source_port") or excitation.get("load_port") else []),
            ]
            for excitation in geometry["excitations"]
        ],
    ]
    return json.dumps(signature, separators=(",", ":"))

