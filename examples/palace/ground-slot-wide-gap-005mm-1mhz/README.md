# 0.05 mm Palace field sampling

![1 MHz Palace return current, 0.05 mm cells and 4 mm top clearance](palace.png)

The 40 × 40 mm board uses an **800 × 800** image grid, with **596,800 copper
samples**, and a **2000 × 2000** PNG. The signal frequency is **1 MHz**, with
three simultaneous in-phase 1 A peak sources and **4 mm** clearance above the
slot. Input geometry comes from `<SlotBoard topGap={4} />` rendered by
`@tscircuit/core`; its circuit/model/mesh hashes match the existing wider-gap case.

Measured once on the cloud Linux x64 environment, AMD EPYC 9V74, with a
four-core CPU quota and 16 GiB memory limit:

| Stage | Wall time |
| --- | ---: |
| Generate XY sample grid | 0.205 s |
| Read/probe Palace fields, integrate thickness, normalize and write JSON | 58.632 s |
| Read sampled field JSON | 0.240 s |
| Validate/render/write SVG | 2.108 s |
| Rasterize/write PNG | 0.921 s |
| Script total | 62.106 s |
| Process total including Bun startup | **62.200 s** |

This is a resampling/export benchmark using a **completed FEM solve**. Palace
was not rerun. The original second-order EM solve took **1157.501 s
(19 min 17.5 s)**, excluding mesh generation and field sampling. Resampling does
not refine the 232,635-tetrahedron FEM mesh or establish mesh convergence. The
sampler evaluates the original saved 3D fields at the new positions; it does not
interpolate the earlier PNG or sampled JSON. VTK probing uses one thread.
Runtime varies with hardware, cache state and other work in the shared environment.

`resample-timing.json` contains the stage timings, grid dimensions and provenance.
`process-timing.json` independently records process elapsed and CPU times. Its
maximum child RSS is about **1.08 GiB**; this is not an aggregate process-tree peak.
`run.json` records source hashes, output sizes and SHA-256 digests. The 120.7 MB
sampled JSON, 22.2 MB grid and 17.3 MB SVG stay under ignored `work/`; the PNG is
checked in here. The earlier 0.2 mm reference remains the interactive comparison.

To regenerate the TSX input and obtain raw Palace fields, then sample them:

```sh
export PALACE_PYTHON=/path/to/python-with-vtk-and-gmsh
bun run generate:palace:wide-gap work/palace/ground-slot-wide-gap-1mhz
bun run resample:palace work/palace/ground-slot-wide-gap-1mhz \
  --cell-size 0.05 --palace-only --image-size 2000
```

If a completed wider-gap case already has its raw `postpro/paraview` fields,
only the second command is necessary. `--palace-only` skips the older
approximation and its comparison; its graph retains a 100,000-cell limit.
