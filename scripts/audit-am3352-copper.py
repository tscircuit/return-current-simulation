"""Reproduce the AM3352 copper audit and plot geometry, not EM current density.
Requires the mesher's Python environment plus matplotlib (plotting only).
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch, PathPatch, Rectangle
from matplotlib.path import Path as PlotPath
import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib/palace/python"))
from mesh_multilayer import build_layer_copper, copper_overlaps, nonempty_polygons


def draw_copper(axis, shape):
    for polygon in nonempty_polygons(shape):
        vertices, codes = [], []
        for ring in [polygon.exterior, *polygon.interiors]:
            coordinates = list(ring.coords)
            vertices.extend(coordinates)
            codes.extend([PlotPath.MOVETO, *([PlotPath.LINETO] * (len(coordinates) - 2)), PlotPath.CLOSEPOLY])
        axis.add_patch(PathPatch(PlotPath(vertices, codes), facecolor="#0891b2", edgecolor="none", rasterized=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    model_bytes = args.model.read_bytes()
    model = json.loads(model_bytes)
    board, copper = build_layer_copper(model)
    overlaps = copper_overlaps(copper)
    corrected_seconds = time.monotonic() - started
    _, old_copper = build_layer_copper(model, trace_caps="square")
    layer, nets = "inner1", ["source_net_23", "source_net_80"]
    corrected = [copper[layer][net] for net in nets]
    old = [old_copper[layer][net] for net in nets]
    old_overlap = old[0].intersection(old[1])
    clearance = corrected[0].distance(corrected[1])
    report = {
        "board": "astra/am3352-sbc", "version": "0.1.19",
        "modelSha256": hashlib.sha256(model_bytes).hexdigest(),
        "valid": not overlaps, "seconds": corrected_seconds,
        "traceEndCaps": "round", "circleSides": 32,
        "checkedLayers": list(copper), "overlaps": overlaps,
        "reportedPair": {"layer": layer, "nets": nets, "netNames": ["MMC0_DAT3", "VIN_5V"],
                         "squareCapOverlapAreaMm2": old_overlap.area,
                         "roundCapOverlapAreaMm2": corrected[0].intersection(corrected[1]).area,
                         "roundCapMinimumClearanceMm": clearance},
        "heatmap": {"quantity": "number of distinct copper nets at each cell center",
                    "cellSizeMm": 0.005, "frequencyApplicable": False, "emSolvePerformed": False},
    }
    (args.output / "geometry-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    fig, axes = plt.subplots(1, 3, figsize=(15, 6.2),
                             gridspec_kw={"width_ratios": [1.1, 1, 1]})
    fig.subplots_adjust(left=0.055, right=0.985, top=0.80, bottom=0.24, wspace=0.32)
    fig.suptitle("AM3352 inner1 copper: square segment ends caused a false overlap", fontsize=16)
    overview = axes[0]
    draw_copper(overview, unary_union(list(copper[layer].values())))
    xmin, ymin, xmax, ymax = board.bounds
    overview.set(xlim=(xmin, xmax), ylim=(ymin, ymax), title="Corrected layer overview · 0 overlaps")
    overview.add_patch(Rectangle((-19.65, 11.0), 1.55, 1.85, fill=False, edgecolor="#ef4444", linewidth=1.5))
    overview.annotate("Zoom", (-18.8, 12.5), (-8, 24), arrowprops={"arrowstyle": "->", "color": "#ef4444"})
    bounds = (-19.65, -18.1, 11.0, 12.85)
    pitch = 0.005
    xs = np.arange(bounds[0] + pitch / 2, bounds[1], pitch)
    ys = np.arange(bounds[2] + pitch / 2, bounds[3], pitch)
    xx, yy = np.meshgrid(xs, ys)
    colors = ListedColormap(["#f1f5f9", "#0891b2", "#ef4444"])
    for axis, shapes, title in zip(axes[1:], [old, corrected],
                                   [f"Before: square ends\n{old_overlap.area:.6f} mm² false overlap",
                                    f"After: round ends\n0 mm² overlap · {clearance:.3f} mm minimum clearance"]):
        occupancy = sum(contains_xy(shape, xx, yy).astype(np.uint8) for shape in shapes)
        axis.imshow(occupancy, origin="lower", extent=bounds, interpolation="nearest",
                    cmap=colors, norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5], 3))
        for shape, color in zip(shapes, ["#1d4ed8", "#b45309"]):
            for polygon in nonempty_polygons(shape.intersection(Polygon.from_bounds(bounds[0], bounds[2], bounds[1], bounds[3]))):
                axis.plot(*polygon.exterior.xy, color=color, linewidth=0.8)
        axis.set_title(title, fontsize=11)
        axis.annotate("MMC0_DAT3 via", (-18.7, 12.5), (-19.55, 12.73), fontsize=9,
                      arrowprops={"arrowstyle": "->", "color": "#1d4ed8"})
        axis.text(-19.55, 11.15, "VIN_5V · changing trace width", color="#92400e", fontsize=9)
    a, b = nearest_points(*corrected)
    axes[2].plot([a.x, b.x], [a.y, b.y], color="#111827", linewidth=1.4)
    for axis in axes:
        axis.set_aspect("equal")
        axis.set_xlabel("x (mm)")
        axis.set_ylabel("y (mm)")
    fig.legend(handles=[Patch(color=colors(i), label=label) for i, label in enumerate(
        ["0 nets: no copper", "1 net: copper", "2 nets: overlap"])],
        loc="lower center", bbox_to_anchor=(0.5, 0.015), ncol=3, frameon=False)
    fig.text(0.5, 0.11, "Copper occupancy at 0.005 mm cells; areas and clearance use polygon geometry. Frequency does not apply. This is not an EM current-density result.",
             ha="center", fontsize=9, color="#475569")
    for extension in ["svg", "png"]:
        fig.savefig(args.output / f"inner1-copper-heatmap.{extension}", dpi=180)
    plt.close(fig)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
