import argparse, json, numpy as np, time
from shapely.geometry import shape, box, Point
from shapely.prepared import prep
from CSXCAD import ContinuousStructure

parser = argparse.ArgumentParser(
    description="Convert copper to tiled compound contours; verify native point-in-polygon parity."
)
parser.add_argument("copper")
parser.add_argument("--out", required=True)
args = parser.parse_args()
cu = json.load(open(args.copper))
c = ContinuousStructure()
result = {}
coverage = {}
rng = np.random.default_rng(91)
for layer, gjson in cu.items():
    g = shape(gjson)
    polys = []
    tiled_area = 0.0
    for x in range(
        int(np.floor(g.bounds[0] / 4) * 4), int(np.ceil(g.bounds[2] / 4) * 4), 4
    ):
        for y in range(
            int(np.floor(g.bounds[1] / 4) * 4), int(np.ceil(g.bounds[3] / 4) * 4), 4
        ):
            cut = g.intersection(box(x, y, x + 4, y + 4))
            if cut.is_empty:
                continue
            tiled_area += cut.area
            parts = (
                [cut]
                if cut.geom_type == "Polygon"
                else [v for v in cut.geoms if v.geom_type == "Polygon"]
            )
            anchor = [x - 0.0011371, y - 0.0021983]
            v = [anchor]
            for part in parts:
                for ring in [part.exterior, *part.interiors]:
                    v.extend(list(ring.coords))
                    v.append(anchor)
            if len(v) < 5:
                continue
            p = c.AddMetal(f"{layer}_{x}_{y}").AddPolygon(
                np.array(v).T, norm_dir="z", elevation=0
            )
            c.Update()
            expected = prep(cut)
            for xy in rng.uniform([x, y], [x + 4, y + 4], size=(30, 2)):
                assert bool(p.IsInside([*xy, 0])) == expected.covers(Point(xy)), (
                    layer,
                    xy,
                )
            polys.append(v)
    assert abs(tiled_area - g.area) <= 1e-6, "Tiling omitted copper"
    coverage[layer] = {
        "inputAreaMm2": g.area,
        "tiledAreaMm2": tiled_area,
        "inputBoundsMm": list(g.bounds),
        "nativeContourChecksPassed": True,
    }
    result[layer] = polys
    print(layer, len(polys), sum(map(len, polys)), flush=True)
json.dump(result, open(args.out, "w"))
from pathlib import Path

Path(args.out).with_suffix(".provenance.json").write_text(
    json.dumps(coverage, indent=2)
)
print("VALIDATED", flush=True)
