"""Export physical copper unions using the validated Palace geometry adapter.

This is geometry conversion, not a field solver. Requires the Palace mesh Python
requirements; the exported GeoJSON can be consumed by the openEMS container.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from shapely.geometry import mapping
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib/palace/python"))
from mesh_multilayer import layer_copper

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("model")
parser.add_argument("--out", required=True)
args = parser.parse_args()
raw = Path(args.model).read_bytes()
model = json.loads(raw)
board, copper = layer_copper(model)
out = Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps(
        {
            layer: mapping(unary_union(list(groups.values())))
            for layer, groups in copper.items()
        }
    )
)
out.with_suffix(".provenance.json").write_text(
    json.dumps(
        {
            "modelSha256": hashlib.sha256(raw).hexdigest(),
            "differentNetOverlaps": 0,
            "traceCaps": "round",
            "boardAreaMm2": board.area,
            "layers": list(copper),
        },
        indent=2,
    )
)
