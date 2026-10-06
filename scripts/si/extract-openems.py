"""openEMS differential two-port extraction from actual layered circuit copper."""

import argparse, json, time, os, hashlib
from pathlib import Path
import numpy as np

# openEMS 0.0.35 Python bindings predate NumPy's alias removal.
np.float = float
np.int = int
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from CSXCAD.SmoothMeshLines import SmoothMeshLines
from shapely.geometry import shape, Polygon, box

p = argparse.ArgumentParser()
p.add_argument("--lane", type=int, default=0)
p.add_argument("--excite", type=int, default=1)
p.add_argument("--cell", type=float, default=0.1)
p.add_argument("--margin", type=float, default=2)
p.add_argument("--max-ns", type=float, default=1.5)
p.add_argument("--out", required=True)
p.add_argument("--setup-only", action="store_true")
p.add_argument("--postprocess-only", action="store_true")
p.add_argument("--threads", type=int, default=5)
p.add_argument("--board", required=True)
p.add_argument("--model", required=True)
p.add_argument("--copper", required=True)
p.add_argument("--compact-copper", required=True)
a = p.parse_args()
started = time.monotonic()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
c = json.load(open(a.board))
m = json.load(open(a.model))
cu = json.load(open(a.copper))
expected = {
    "top": (1.4942, 1.5292),
    "inner1": (1.3796, 1.3948),
    "inner2": (0.0994, 0.1146),
    "bottom": (-0.035, 0),
}
for foil in m["multilayer"]["stackup"]["copperLayers"]:
    assert foil["name"] in expected and np.allclose(
        [foil["zMin"], foil["zMax"]], expected[foil["name"]], atol=1e-6
    ), "This experimental adapter requires the documented AM3352 stackup"
source = {e.get("name"): e for e in c if e["type"] == "source_trace" and e.get("name")}
routes = []
term = []
for name in [f"DDR_DQS{a.lane}", f"DDR_DQSn{a.lane}"]:
    s = source[name]
    r = next(
        e
        for e in c
        if e["type"] == "pcb_trace" and e.get("source_trace_id") == s["source_trace_id"]
    )
    routes.append(r)
    ports = [
        next(e for e in c if e["type"] == "pcb_port" and e.get("source_port_id") == i)
        for i in s["connected_source_port_ids"]
    ]
    term.append(ports)
xy = np.array([[r["x"], r["y"]] for route in routes for r in route["route"]])
bounds = [
    xy[:, 0].min() - a.margin,
    xy[:, 1].min() - a.margin,
    xy[:, 0].max() + a.margin,
    xy[:, 1].max() + a.margin,
]
FDTD = openEMS(NrTS=1000000, EndCriteria=1e-5)
FDTD.SetMaxTime(a.max_ns * 1e-9)
FDTD.SetGaussExcite(0, 5e9)
FDTD.SetBoundaryCond(["PML_8"] * 6)
CSX = ContinuousStructure()
FDTD.SetCSX(CSX)
grid = CSX.GetGrid()
grid.SetDeltaUnit(1e-3)
for d, lo, hi, limit in [
    ("x", bounds[0], bounds[2], 56),
    ("y", bounds[1], bounds[3], 46),
]:
    lo = np.floor(lo / a.cell) * a.cell
    hi = np.ceil(hi / a.cell) * a.cell
    fine = np.arange(lo, hi + a.cell / 2, a.cell)
    v = np.r_[-limit, fine, limit]
    lines = SmoothMeshLines(v, 1.0, 1.35)
    grid.SetLines(d, lines)
# Conductive foils at their faces toward the DDR near references. Thin-sheet
# approximation: preserves the 0.0994 mm outer dielectric gaps, with no Cu volume.
zfoil = {"bottom": 0.0, "inner2": 0.0994, "inner1": 1.3948, "top": 1.4942}
z = [
    -8,
    -4,
    -2,
    -1,
    -0.5,
    -0.25,
    -0.1,
    0,
    0.0497,
    0.0994,
    0.15,
    0.25,
    0.45,
    0.7,
    1.0,
    1.2,
    1.3,
    1.3948,
    1.4445,
    1.4942,
    1.5692,
    1.6442,
    1.75,
    2,
    2.5,
    3.5,
    5.5,
    9.5,
]
grid.SetLines("z", SmoothMeshLines(z, 1, 1.35))
for i, (lo, hi, er) in enumerate(
    [(0, 0.0994, 4.1), (0.0994, 1.3948, 4.42), (1.3948, 1.4942, 4.1)]
):
    dielectric = CSX.AddMaterial(f"dielectric_{i}", epsilon=er)
    dielectric.AddBox([-50, -40, lo], [50, 40, hi], priority=1)
# All exported copper is retained, including reference voids, neighboring traces
# and pads. Sorting nested polygons lets metal islands inside pour holes win.
counts = {}
compact = json.load(open(a.compact_copper))
for layer in zfoil:
    if compact is not None:
        metal = CSX.AddMetal("copper_" + layer)
        for pts in compact[layer]:
            metal.AddPolygon(
                np.array(pts).T, norm_dir="z", elevation=zfoil[layer], priority=100
            )
        counts[layer] = len(compact[layer])
        continue
    geom = shape(cu[layer])
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    polys.sort(key=lambda x: -x.area)
    metal = CSX.AddMetal("copper_" + layer)
    void = CSX.AddMaterial(
        "foil_void_" + layer, epsilon=4.1 if layer in ["inner1", "inner2"] else 1
    )
    for i, poly in enumerate(polys):
        priority = 100 + 2 * i
        metal.AddPolygon(
            np.array(poly.exterior.coords).T[:, :-1],
            norm_dir="z",
            elevation=zfoil[layer],
            priority=priority,
        )
        for h in poly.interiors:
            void.AddPolygon(
                np.array(h.coords).T[:, :-1],
                norm_dir="z",
                elevation=zfoil[layer],
                priority=priority + 1,
            )
    counts[layer] = len(polys)
via_metal = CSX.AddMetal("via_barrels_outer_surface")
for barrel in m["multilayer"]["barrels"]:
    h = Polygon([(q["x"], q["y"]) for q in barrel["hole"]])
    x, y = h.centroid.coords[0]
    radius = (h.bounds[2] - h.bounds[0]) / 2 + barrel["platingThickness"]
    # Solid PEC exterior approximates a hollow high-conductivity barrel; no
    # artificial connection beyond the exported physical layer span.
    lo = max(0, barrel["zMin"])
    hi = min(1.4942, barrel["zMax"])
    if lo < hi:
        via_metal.AddCylinder([x, y, lo], [x, y, hi], radius=radius, priority=50)
launch = CSX.AddMetal("differential_port_launch_posts")
ports = []
contacts = []
for j in range(2):
    pos = np.array([[term[k][j]["x"], term[k][j]["y"]] for k in range(2)])
    pos = np.round(pos / a.cell) * a.cell
    for x, y in pos:
        launch.AddCylinder([x, y, 1.4942], [x, y, 1.6442], radius=0.1, priority=100000)
    direction = int(np.argmax(np.abs(pos[0] - pos[1])))
    start = np.r_[pos[1], 1.6442]
    stop = np.r_[pos[0], 1.6442]
    other = 1 - direction
    start[other] -= 0.1
    stop[other] += 0.1
    port = FDTD.AddLumpedPort(
        j + 1,
        100,
        start,
        stop,
        ["x", "y"][direction],
        excite=1 if a.excite == j + 1 else 0,
        priority=100001,
    )
    ports.append(port)
    contacts.append(
        {
            "positive": pos[0].tolist(),
            "negative": pos[1].tolist(),
            "axis": ["x", "y"][direction],
            "leadHeightMm": 0.15,
            "portWidthMm": 0.2,
        }
    )
CSX.Write2XML(str(out / "model.xml"))
meta = {
    "solver": "openEMS 0.0.35",
    "lane": a.lane,
    "excitedPort": a.excite,
    "cellMm": a.cell,
    "fineMarginMm": a.margin,
    "fineBoundsMm": bounds,
    "maxTimeNs": a.max_ns,
    "endCriteria": 1e-5,
    "gridCells": [len(grid.GetLines(d)) - 1 for d in ["x", "y", "z"]],
    "foilPolygons": counts,
    "contacts": contacts,
    "dielectricLoss": "omitted",
    "copperLoss": "PEC for initial routing extraction",
    "input": {
        "circuitJson": "AM3352 release 0.1.19",
        "copper": "round-capped rendered full-board copper with holes",
        "sha256": {
            k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
            for k, v in {
                "circuitJson": a.board,
                "model": a.model,
                "compactCopper": a.compact_copper,
            }.items()
        },
    },
    "limitations": [
        "Thin conductive foil placement, solid high-conductivity via exterior approximation",
        "Fine DDR region with graded coarser mesh outside; compare mesh and margin refinement",
        "Differential two-terminal ports, balanced excitation; no common-mode I/O or active aggressors in this extraction",
        "0.15 mm matched launch posts; not exact IC packaging",
        "Energy decay and mesh/time convergence must be assessed separately from reaching the requested finite record",
    ],
}
(out / "extraction.json").write_text(json.dumps(meta, indent=2))
print(json.dumps(meta), flush=True)
if not a.postprocess_only:
    FDTD.Run(
        str(out),
        cleanup=False,
        setup_only=a.setup_only,
        verbose=1,
        numThreads=a.threads,
    )
if not a.setup_only:
    freq = np.linspace(1e6, 5e9, 1001)
    for port in ports:
        port.CalcPort(str(out), freq)
    inc = ports[a.excite - 1].uf_inc
    rows = np.column_stack(
        [
            freq,
            *[
                x
                for port in ports
                for x in [(port.uf_ref / inc).real, (port.uf_ref / inc).imag]
            ],
        ]
    )
    np.savetxt(
        out / "s-column.csv",
        rows,
        delimiter=",",
        header="frequency_hz,s1_real,s1_imag,s2_real,s2_imag",
        comments="",
    )
    meta["wallSeconds"] = time.monotonic() - started
    meta["actualTimeNs"] = float(ports[0].u_data.ui_time[0][-1]) * 1e9
    meta["sourceIncidentMinAbs"] = float(np.min(np.abs(inc)))
    meta["solverCompleted"] = not a.postprocess_only
    meta["recordLengthIsEnergyConvergence"] = False
    (out / "extraction.json").write_text(json.dumps(meta, indent=2))
    print("COMPLETE", json.dumps(meta), flush=True)
