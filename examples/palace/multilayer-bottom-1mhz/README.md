# Four-layer Palace example: bottom

Generated from [`MultilayerBoard.tsx`](../../../tests/fixtures/MultilayerBoard.tsx).
The top signal uses blind vias to reach inner1. Ground through vias connect
inner2 and bottom. The source/load ports use actual top ground pins and
25 Ω/100 Ω real terminations, with a prescribed 5 mA peak source at 1 MHz.

This is a completed Palace v0.14.0 driven Maxwell solve with volumetric copper,
three dielectric slabs (relative permittivity 4.1/4.42/4.1), FEM order 1,
2 mm mesh target and 2 mm air padding. All emitted copper is retained.
`mesh-summary.json` records 9,683 nodes and 53,228 tetrahedra.

The full run at **0.05 mm** sample pitch (160 × 120 candidates) took
**42.67 seconds** on the development machine, including meshing,
two-process Palace, sampling and default image export. `run-timing.json`
records that original run. This directory stores a subsequent **0.2 mm**
resampling (40 × 30 candidates, 1196 copper samples) for compact,
TSX-regenerated visual snapshots. The display scale is 0.2 A/mm².
`resample-timing.json` records reuse of the completed solve.

Reproduce from a checkout with Gmsh/VTK Python and Docker/native Palace:

```sh
PALACE_PYTHON=/path/to/venv/bin/python \
  bun scripts/generate-multilayer-example.tsx work/multilayer-bottom bottom
```

`reference.json` stores the complex through-thickness sheet current sampled
on **bottom** and the actual source/load currents, with circuit/model/mesh
hashes. `palace.log`, `palace.json`, `port-I.csv` and `normalization.json`
preserve solver configuration and source-normalization evidence.

**Not mesh-convergence certified.** Source current is normalized at the
port; that does not prove sampled plane current-density accuracy. These
completed solves are geometry/sampling regression examples, not calibrated
current-density limits or a certified multilayer ground truth. Quantitative
use requires mesh/order refinement and relevant component/package models.
