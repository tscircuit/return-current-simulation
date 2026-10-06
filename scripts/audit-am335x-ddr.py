"""Independent PCB geometry checks against TI SPRS717L Table 7-69.

This is not an EM extraction, impedance calculation, or timing signoff.
Input is rendered circuit-json; no board-specific measured lengths are embedded.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union


def route_measurement(circuit, name):
    sources = [
        x for x in circuit if x["type"] == "source_trace" and x.get("name") == name
    ]
    if len(sources) != 1:
        raise ValueError(f"{name}: expected one named source trace")
    source = sources[0]
    traces = [
        x
        for x in circuit
        if x["type"] == "pcb_trace"
        and x.get("source_trace_id") == source["source_trace_id"]
    ]
    if len(traces) != 1:
        raise ValueError(f"{name}: expected one complete ordered PCB route")
    pins = source["connected_source_port_ids"]
    if len(pins) != 2:
        raise ValueError(f"{name}: expected two terminals")
    pads = []
    for pin in pins:
        matches = [
            x
            for x in circuit
            if x["type"] == "pcb_port" and x.get("source_port_id") == pin
        ]
        if len(matches) != 1:
            raise ValueError(f"{name}: ambiguous or missing PCB port")
        pads.append(matches[0])
    route = traces[0]["route"]
    endpoints = [route[0], route[-1]]
    if not all(
        any(math.hypot(p["x"] - q["x"], p["y"] - q["y"]) < 1e-5 for q in endpoints)
        for p in pads
    ):
        raise ValueError(f"{name}: route endpoints do not match terminals")
    segments, layers, length = [], {}, 0.0
    for a, b in zip(route, route[1:]):
        distance = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
        if not math.isfinite(distance):
            raise ValueError(f"{name}: nonfinite route")
        if a["route_type"] != "wire" or b["route_type"] != "wire":
            if distance > 1e-5:
                raise ValueError(f"{name}: displaced via or unsupported route element")
            continue
        if a["layer"] != b["layer"]:
            raise ValueError(f"{name}: missing via at layer change")
        if distance < 1e-10:
            continue
        segment = {
            "layer": a["layer"],
            "start": [a["x"], a["y"]],
            "end": [b["x"], b["y"]],
            "widthMm": a["width"],
        }
        segments.append(segment)
        layers[a["layer"]] = layers.get(a["layer"], 0.0) + distance
        length += distance
    return {
        "signal": name,
        "pcbTraceId": traces[0]["pcb_trace_id"],
        "wireLengthMm": length,
        "padManhattanMm": abs(pads[0]["x"] - pads[1]["x"])
        + abs(pads[0]["y"] - pads[1]["y"]),
        "layerLengthsMm": layers,
        "viaCount": sum(p["route_type"] == "via" for p in route),
        "segments": segments,
    }


def reference_pours(circuit, layer, names):
    net_ids = {
        x["source_net_id"]
        for x in circuit
        if x["type"] == "source_net" and x["name"] in names
    }
    if len(net_ids) != len(names):
        raise ValueError(f"Unknown reference nets: {names}")
    shapes = []
    for pour in circuit:
        if (
            pour["type"] != "pcb_copper_pour"
            or pour["layer"] != layer
            or pour.get("source_net_id") not in net_ids
        ):
            continue
        if pour["shape"] != "brep":
            raise ValueError("Reference check requires rendered brep pours")
        shape = pour["brep_shape"]
        vertices = lambda ring: [(p["x"], p["y"]) for p in ring["vertices"]]
        polygon = Polygon(
            vertices(shape["outer_ring"]),
            [vertices(r) for r in shape.get("inner_rings", [])],
        )
        if not polygon.is_valid:
            raise ValueError(f"Invalid reference pour: {pour['pcb_copper_pour_id']}")
        shapes.append(polygon)
    if not shapes:
        raise ValueError(f"No rendered reference pours on {layer}")
    return unary_union(shapes)


def audit(circuit, lanes, references):
    measurements, groups = [], []
    for lane in lanes:
        data_names = [f"DDR_D{8 * lane + bit}" for bit in range(8)] + [f"DDR_DQM{lane}"]
        data = [route_measurement(circuit, n) for n in data_names]
        pair = [
            route_measurement(circuit, n) for n in [f"DDR_DQS{lane}", f"DDR_DQSn{lane}"]
        ]
        all_members = data + pair
        # DQLM is placement-derived, not the longest routed length. The ceiling
        # below is checked on DQ/DM; DQS is checked against DQ for skew separately.
        ceiling = max(m["padManhattanMm"] for m in data)
        data_lengths = [m["wireLengthMm"] for m in data]
        all_lengths = [m["wireLengthMm"] for m in all_members]
        pair_skew = abs(pair[0]["wireLengthMm"] - pair[1]["wireLengthMm"])
        pair_layers = [set(m["layerLengthsMm"]) - {"top", "bottom"} for m in pair]
        groups.append(
            {
                "byte": lane,
                "dqlmMm": ceiling,
                "dqMinLengthMm": min(data_lengths),
                "dqMaxLengthMm": max(data_lengths),
                "dataLengthPass": max(data_lengths) <= ceiling + 1e-7,
                "dqAndDqsSkewMm": max(all_lengths) - min(all_lengths),
                "byteSkewPass": max(all_lengths) - min(all_lengths) <= 0.635 + 1e-7,
                "dqsPairSkewMm": pair_skew,
                "pairSkewPass": pair_skew <= 0.127 + 1e-7,
                "sameInnerCarrier": pair_layers[0] == pair_layers[1]
                and len(pair_layers[0]) == 1,
            }
        )
        measurements.extend(all_members)
    projection = []
    shapes = {}
    for signal_layer, reference_layer, nets in references:
        plane = reference_pours(circuit, reference_layer, nets)
        shapes[signal_layer] = plane
        for m in measurements:
            selected = [s for s in m["segments"] if s["layer"] == signal_layer]
            total = sum(LineString([s["start"], s["end"]]).length for s in selected)
            gaps = [
                LineString([s["start"], s["end"]]).difference(plane) for s in selected
            ]
            projection.append(
                {
                    "signal": m["signal"],
                    "signalLayer": signal_layer,
                    "referenceLayer": reference_layer,
                    "referenceNets": nets,
                    "carrierLengthMm": total,
                    "centerlineOutsidePourMm": sum(g.length for g in gaps),
                }
            )
    result = {
        "status": "geometry-only; EM/eye signoff unavailable",
        "ruleSource": "https://www.ti.com/lit/ds/symlink/am3352.pdf",
        "ruleRevision": "SPRS717L",
        "ruleTable": "7-69",
        "groups": groups,
        "geometricLengthAndSkewPass": all(
            g["dataLengthPass"] and g["byteSkewPass"] and g["pairSkewPass"]
            for g in groups
        ),
        "measurements": measurements,
        "referencePourProjection": projection,
        "limitations": [
            "XY pad-to-pad copper lengths exclude vertical/package flight time.",
            "Projection uses rendered pour polygons and their holes, not traces, pads, barrels or electrical connectivity.",
            "Copper under a trace does not prove an AC return path; power references need decoupling and stitching.",
            "No impedance, coupled S-parameters, crosstalk, jitter, BER or receiver timing signoff is inferred.",
        ],
    }
    return result, shapes


def line_parts(shape):
    if shape.is_empty:
        return []
    if shape.geom_type == "LineString":
        return [shape]
    return (
        [p for g in shape.geoms for p in line_parts(g)]
        if hasattr(shape, "geoms")
        else []
    )


def plot(result, shapes, out):
    os.environ.setdefault("MPLCONFIGDIR", str(Path("work/matplotlib").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch

    fig, axes = plt.subplots(2, 2, figsize=(14, 11), layout="constrained")
    for ax, (layer, plane) in zip(axes[0], shapes.items()):
        polygons = [plane] if plane.geom_type == "Polygon" else list(plane.geoms)
        for polygon in polygons:
            # Opposite winding of holes retains actual voids in the plot.
            from shapely.geometry.polygon import orient

            polygon = orient(polygon, sign=1)
            path = MPath.make_compound_path(
                *[MPath(list(r.coords)) for r in [polygon.exterior, *polygon.interiors]]
            )
            ax.add_patch(
                PathPatch(path, facecolor="#d8e8f1", edgecolor="#aac4d2", lw=0.25)
            )
        xy = []
        for m in result["measurements"]:
            for s in m["segments"]:
                if s["layer"] != layer:
                    continue
                xy.extend([s["start"], s["end"]])
                line = LineString([s["start"], s["end"]])
                for piece in line_parts(line.intersection(plane)):
                    ax.plot(
                        *piece.xy,
                        color="#173d5f" if "DQS" in m["signal"] else "#71858c",
                        lw=1 if "DQS" in m["signal"] else 0.5,
                    )
                for piece in line_parts(line.difference(plane)):
                    ax.plot(*piece.xy, color="#d72c30", lw=1.2)
        ax.set_xlim(min(x for x, y in xy) - 2, max(x for x, y in xy) + 2)
        ax.set_ylim(min(y for x, y in xy) - 2, max(y for x, y in xy) + 2)
        ax.set_aspect("equal")
        mapping = next(
            r for r in result["referencePourProjection"] if r["signalLayer"] == layer
        )
        ax.set_title(
            f"{layer} traces over {mapping['referenceLayer']} {'/'.join(mapping['referenceNets'])} pours\nRed = centerline outside selected pours"
        )
        ax.set_xlabel("x (mm)")
        ax.set_ylabel("y (mm)")
    for ax, group in zip(axes[1], result["groups"]):
        lane = group["byte"]
        members = [
            m
            for m in result["measurements"]
            if m["signal"]
            in [f"DDR_D{lane*8+b}" for b in range(8)]
            + [f"DDR_DQM{lane}", f"DDR_DQS{lane}", f"DDR_DQSn{lane}"]
        ]
        ax.barh(
            [m["signal"].removeprefix("DDR_") for m in members],
            [m["wireLengthMm"] for m in members],
            color=[
                (
                    "#173d5f"
                    if "DQS" in m["signal"]
                    else "#d72c30" if m["wireLengthMm"] > group["dqlmMm"] else "#71858c"
                )
                for m in members
            ],
        )
        ax.axvline(
            group["dqlmMm"],
            color="black",
            ls="--",
            label=f"TI DQ/DM maximum: {group['dqlmMm']:.3f} mm",
        )
        ax.set_title(f"Byte {lane}: routed length versus placement-derived limit")
        ax.set_xlabel("XY pad-to-pad wire length (mm)")
        ax.legend(loc="lower right")
    fig.suptitle(
        "AM335x DDR routing audit — geometry evidence, not an eye/EM simulation",
        fontsize=16,
    )
    fig.savefig(out / "routing-audit.png", dpi=150)
    fig.savefig(out / "routing-audit.svg")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board")
    parser.add_argument("--lanes", default="0,1")
    parser.add_argument(
        "--reference",
        action="append",
        required=True,
        help="signal-layer:reference-layer:net1,net2; repeat for each carrier",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = Path(args.board).read_bytes()
    references = [
        (a, b, names.split(","))
        for a, b, names in [r.split(":") for r in args.reference]
    ]
    if len(references) != 2 or len({r[0] for r in references}) != 2:
        parser.error("Plot requires two distinct carrier/reference mappings")
    result, shapes = audit(
        json.loads(raw), [int(n) for n in args.lanes.split(",")], references
    )
    result["circuitJsonSha256"] = hashlib.sha256(raw).hexdigest()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    saved = {
        **result,
        "measurements": [
            {k: v for k, v in m.items() if k != "segments"}
            for m in result["measurements"]
        ],
    }
    (out / "routing-audit.json").write_text(json.dumps(saved, indent=2) + "\n")
    plot(result, shapes, out)
    print(json.dumps(result["groups"], indent=2))


if __name__ == "__main__":
    main()
