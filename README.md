# Return-current simulation

Use **Palace EM** to solve a two-layer PCB at an explicit frequency, then compare
its complex return-current field with the original image-current approximation.
Both accept circuit-json; every example and visual snapshot starts from TSX
rendered by `@tscircuit/core`.

![Palace return-current reference at 1 MHz, 4 mm clearance, 0.05 mm cells](examples/palace/ground-slot-wide-gap-005mm-1mhz/palace.png)

The Palace fixture has three top traces, a slot in the bottom ground copper,
0.8 mm of FR4, and 35 µm copper. FR4 remains under signals crossing the slot.
The displayed example leaves **4 mm** between the slot tip and the board top
edge, compared with 1 mm in the original reference. The Cosmos comparison
defaults to 4 mm and lets you switch to the 1 mm case.
A physical PCB cutout removes the substrate too; signals must route around it.
Palace models the copper as **3D conductive volumes**, not PEC or a custom field
algorithm. The fields use 1 MHz and three simultaneous, in-phase 1 A peak source
currents, with 50 Ω source/load ports. These assumptions are not known for the
supplied screenshot, so visual similarity alone cannot validate either model.

The original approximation **does not model frequency**. It is experimental and
its current-conservation residual is not an electromagnetic accuracy check. Its
snapshots now state this explicitly.

## Run Palace

Requires Bun, Python 3.12, Gmsh's `libGLU`, and either Docker or Palace v0.14.0.
The Docker fallback is a **community-built** v0.14.0 binary pinned by digest;
it is not an AWS-published container. See the pinned image and upstream source in
[`scripts/palace/run-case.ts`](scripts/palace/run-case.ts).

```sh
bun install
python3 -m venv work/palace-python
work/palace-python/bin/pip install -r lib/palace/python/requirements.txt
export PALACE_PYTHON="$PWD/work/palace-python/bin/python"
# Optional native installation instead of Docker:
# export PALACE_BIN=/path/to/palace-v0.14.0/bin/palace
bun run palace examples/ground-slot.circuit.json work/palace-slot \
  --frequency-hz 1000000 --mesh-size 2 --cell-size 0.2 --air-padding 6 --order 2 --processes 4
```

Palace images default to 0.2 mm sample spacing: **200 × 200** for the 40 mm
slot board, with 37,075 points inside ground copper. `--cell-size` controls
this image grid; `--mesh-size` and `--order` control the independent FEM mesh.
To resample an existing completed solve without rerunning Palace:

```sh
bun run resample:palace work/palace-slot --cell-size 0.2
```

This reads the saved ParaView fields, samples the requested positions, and
regenerates the comparison and SVG/PNG images. The mesh, frequency, physical
model and port normalization remain the same.

For **0.05 mm cells** on the 40 mm board (800 × 800), export Palace directly:

```sh
bun run resample:palace work/palace/ground-slot-wide-gap-1mhz \
  --cell-size 0.05 --palace-only --image-size 2000
```

The 4 mm clearance variant has **596,800 copper samples**. The sampler evaluates
the saved FEM fields at each new position and integrates five points through the
copper thickness; it does not upscale a previous image. This changes image
sampling, not the tetrahedral FEM resolution. Palace sampling supports up to
1,000,000 candidate cells; the approximation retains its separate 100,000-cell
limit, so larger exports require `--palace-only`. This flag skips the approximation
and numerical comparison. `resample-timing.json` reports grid creation, VTK field
sampling/normalization/serialization, and image-export wall times. The PNG defaults
to 1100 pixels; `--image-size 2000` exports a 2000 × 2000 PNG.

The measured image and timing evidence are in
[`ground-slot-wide-gap-005mm-1mhz`](examples/palace/ground-slot-wide-gap-005mm-1mhz).
The dense sampled JSON and SVG remain in `work/` rather than making the repository
and browser viewer load hundreds of thousands of samples. The interactive
comparison continues to use the 0.2 mm grid.

To generate input circuit-json from TSX and run the example suite:

```sh
bun run generate:palace work/palace
bun run generate:palace:wide-gap work/palace/ground-slot-wide-gap-1mhz
```

Each run saves the input circuit, mesher model, Gmsh mesh, Palace configuration,
solver log, port CSVs, raw ParaView fields, complex sampled currents, numerical
comparison, and SVG/PNG images. Outputs are under `work/`; curated evidence is
checked into [`examples/palace`](examples/palace). The manual **Palace reference**
CI workflow uploads raw meshes and ParaView output as artifacts, then checks
fresh field changes and independently sampled return-current balance.

`frequencyHz` is required; the CLI has no frequency default. Other explicit
options include conductivity, copper thickness, FR4 permittivity/loss tangent,
port resistance, signal/ground separation, mesh size, air padding, and FEM order.
Use `--processes` (or `PALACE_PROCESSES`) for MPI parallelism.
Ports currently require ground contacts directly beneath trace endpoints and
rectangular top SMT pads. Unsupported geometries fail instead of disappearing.
The volume mesher currently requires foil thickness no larger than skin depth;
there is no claim of a resolved high-frequency skin-effect benchmark.

## Compare numerical fields

```ts
import {
  comparePalaceReference,
  renderPalaceReferenceSvg,
  simulateReturnCurrent,
} from "@tscircuit/return-current-simulation"
import type { PalaceReference } from "@tscircuit/return-current-simulation"

const reference: PalaceReference = await Bun.file("work/palace-slot/reference.json").json()
const result = simulateReturnCurrent({
  circuitJson,
  cellSize: reference.cellWidth,
  copperThickness: reference.copperThickness,
  layerSeparation: 0.8,
  contactRadius: 0.6,
})
console.log(comparePalaceReference(result, { reference }))
await Bun.write("palace.svg", renderPalaceReferenceSvg(result, {
  reference,
  phaseDegrees: 0,
  maxCurrentDensity: 50,
}))
```

To render Palace alone, use `renderPalaceModelSvg(model, { reference, ...options })`
with the saved `PalaceModel`; no approximation solve is required.

The comparison requires identical sampling positions, source currents and foil
thickness. It reports complex-vector, real-vector and magnitude L2 differences,
with contact/edge exclusions recorded. It does not fit amplitudes, rotate phase,
or equate its error to a conservation residual. The heatmap shows the complex
norm of thickness-averaged conduction current in A/mm²; arrows show an
instantaneous field at the selected phase. Raw sheet-current phasors are A/mm.

Palace's RF `port-I.csv` reports termination current. Net driven current entering
the PCB is **2 I_inc − I_termination**. The importer solves the full source-current
matrix, including coupling, to normalize simultaneous 1 A excitations. Load
currents are reported separately and are not forced to equal the source current.

**Version-specific units:** Palace v0.14.0's ParaView fields are nondimensional.
The importer uses `E_SI = E_VTU × sqrt(Z0)/Lc`, then `J = conductivity × E_SI`,
and integrates five Gauss points through the bottom copper. CSV port currents
are already amperes. `Lc` is fixed explicitly in newly generated configurations;
older case files derive the upstream default from the air-domain bounds. Other
Palace versions are rejected until their output units are audited. See upstream
[v0.14.0 units](https://github.com/awslabs/palace/blob/v0.14.0/palace/utils/units.hpp)
and [postprocessing documentation](https://github.com/awslabs/palace/blob/v0.14.0/docs/src/guide/postprocessing.md).

The 100 kHz example is exploratory order-1 evidence. Its frequency comparison
uses the [matching order-1 1 MHz run](examples/palace/ground-slot-order1-1mhz),
with identical mesh hashes, rather than attributing a change in FEM order to
frequency. Use equal numerical refinement when comparing frequencies.

The 4 mm clearance is generated with `<SlotBoard topGap={4} />` and a fresh
second-order 1 MHz Palace solve; its fields are not reused from the 1 mm case.
The original 1 mm evidence and frequency/refinement comparisons are retained.

Palace is an independent **point of comparison**, not automatically ground truth.
The 4 mm case recovers 2.994 A of return current for three 1 A sources, with
0.40% complex balance error. Its mesh convergence has not been established.
The original 1 mm refinement report records field changes and bridge-current balance.
Dense cross-section quadrature recovers 0.996 A for the straight 1 A source
and 3.002 A through the slot bridge for three 1 A sources; complex balance errors
are 0.64% and 0.064%, respectively. The 0.2 mm image grid has five
rows across the 1 mm bridge and a 3.9% sampled complex balance error (the older
0.5 mm grid had two rows and 16.8% error). Flux checks retain separate 0.0125 mm
samples there. Current balance validates units and normalization; the 45.2%
coarse/fine field change evaluated on the denser grid still prevents treating this
mesh as converged ground truth.
Increase FEM order, refine the mesh, and enlarge the air domain before treating a
result as an accuracy reference. Contact footprints differ from the approximation's
distributed contacts, so those neighborhoods are excluded from the default metric.

## Library usage

Following the [handbook](https://github.com/tscircuit/handbook/blob/main/guides/bootstrapping-repos.md),
the package uses GitHub vanilla installation, a TypeScript entrypoint, no package
build step, and no lockfile.

```sh
bun add github:tscircuit/return-current-simulation
```

```ts
import {
  parseReturnCurrentCircuitJson,
  simulateReturnCurrent,
  renderReturnCurrentSvg,
} from "@tscircuit/return-current-simulation"

const circuitJson = parseReturnCurrentCircuitJson(
  await Bun.file("input.circuit.json").json(),
)
const result = simulateReturnCurrent({
  circuitJson,
  cellSize: 0.25, // mm
  layerSeparation: 0.8, // mm, signal-to-ground distance
  copperThickness: 0.035, // mm
  contactRadius: 0.6, // mm
})
await Bun.write("return-current.svg", renderReturnCurrentSvg(result))
```

Parsing validates external JSON and normalizes circuit-json units. Already
validated circuit-json can be passed directly. Results contain copper nodes,
signed edge currents in A, sheet-current components in A/mm, density in A/mm²,
and convergence/conservation diagnostics. Non-convergence throws.

SVG rendering requires no DOM, canvas, or native dependency. Render options
include `maxCurrentDensity` (a fixed **linear** color-scale maximum in A/mm²),
`hideVectors`, `hideTraces`, `vectorSpacing`, `width`, `height`, and `title`.
Without a fixed maximum, each image scales to its own peak.

For PNG export with the included script:

```sh
git clone https://github.com/tscircuit/return-current-simulation
cd return-current-simulation
bun install
bun run render examples/ground-slot.circuit.json return-current.png 0.25
```

## Excitations

Geometry does not determine signal current or spatial ground contacts. Include
one element per excited trace:

```json
{
  "type": "simulation_return_current_excitation",
  "simulation_return_current_excitation_id": "simulation_return_current_excitation_0",
  "pcb_trace_id": "pcb_trace_0",
  "ground_source_net_id": "source_net_0",
  "current": 1,
  "return_source": { "x": 12, "y": 0 },
  "return_sink": { "x": -12, "y": 0 }
}
```

Positive current follows the ordered signal route. Return current enters ground
at the load-side `return_source` and leaves at the driver-side `return_sink`.
Negative current reverses both fields. Contacts can be offset from trace
endpoints, but must lie on the selected ground copper and share a connected
region. Currents are signed instantaneous or in-phase amplitudes and superpose
linearly.

The element is proposed in [circuit-json PR #870](https://github.com/tscircuit/circuit-json/pull/870).
Until it is released and core emits it, this package exports the temporary type
and parser. The TSX fixture helper appends **only excitation records** after core
renders all geometry. `options.excitations` can supply or override the records
without editing circuit-json. Neither signal current nor a full ground plane is
silently inferred.

## Geometry and defaults

Supported geometry:

- One board with `num_layers: 2`, rectangular or polygon outline.
- Continuous top-layer `pcb_trace` wire routes; split at vias or pads.
- Bottom `pcb_copper_pour` rectangles, polygons, and BReps with inner holes.
  Circular BRep arcs are tessellated at at most 3° angular intervals.
- `pcb_ground_plane` with bottom-layer `pcb_ground_plane_region` polygons.
- Physical `pcb_cutout` rectangles (including rotation), circles, and polygons.

All excitations select one ground net. Path cutouts, rounded rectangular cutouts,
drilled holes, and vias are rejected explicitly because they are outside the
current model. Top traces cannot leave the board or cross a physical cutout.

Coordinates are circuit world millimetres, +X right and +Y up. Sheet-current
components are board-space directions. SVG coordinates are pixels, +Y down.

| Option | Default |
| --- | --- |
| `cellSize` | 0.5 mm |
| `layerSeparation` | `board.thickness` |
| `copperThickness` | 0.035 mm |
| `contactRadius` | `cellSize` |
| `tolerance` | 1e-8 relative L2 residual |
| `maxIterations` | 5000 |

Override spacing with the actual stackup distance. Contacts distribute current
uniformly among visible nodes inside their radius. A contact with no nodes fails
with a refinement hint. The mesh is limited to 100,000 candidate cells.

## Numerical model

For a signal filament at height h carrying current I, preferred image sheet
current on an infinite plane is

```text
K₀(r) = −I h / (2π) ∫ dl / (|r − r′|² + h²)^(3/2)
```

Straight segments are integrated analytically. Three-point Gaussian quadrature
integrates K₀ over mesh faces to obtain preferred edge currents F₀. The graph
projects those currents onto a conservative field:

```text
minimize  ½ Σ_edges (F − F₀)² / w
subject to  B F = b

F = F₀ + w Bᵀ φ
(B w Bᵀ) φ = b − B F₀
```

B is the outgoing-current incidence matrix, b the contact injections, and w the
face-length/cell-distance ratio. The correction φ is a Lagrange multiplier,
**not a predicted voltage**. Jacobi-preconditioned conjugate gradients fix one
gauge per connected region and check the recomputed residual before convergence.
Conservation diagnostics include every cell, including gauge cells.

Entire graph edges are tested against polygon intersections, so even a slot
narrower than the cell pitch cannot short the graph across the gap. Rendering
clips to actual copper. Partial boundary cells still use a cell-centre mask;
refine near narrow bridges, sharp corners, and curved boundaries.

This is a qualitative high-frequency return-path model, not a full Maxwell,
PEEC, or electromagnetic finite-element solution. It omits frequency-dependent
impedance, skin effect, dielectric losses, displacement current, waves, and
radiation. Signal width is drawn, while field calculations treat signals as
filaments. Density peaks are not validated thermal, EMC, or signal-integrity
predictions. Sharp-corner peaks depend on mesh pitch; contact peaks depend on
contact radius.

## Develop and reproduce

```sh
bun install
bun test
bun run typecheck
bun run format:check
bun run start
bun run build:site
bun run generate:examples
```

Cosmos includes an interactive `ground-slot` page, a `GenericSolverDebugger`
`solver` page, and a `hello-world` bootstrap page. Compare slotted and intact
planes on the same scale, vary current, toggle arrows, and download SVGs.
`ReturnCurrentSolver` extends `BaseSolver` with `step()`, `solve()`, `visualize()`,
and `getOutput()`.

All numerical fixtures generate geometry using **TSX and @tscircuit/core**.
Visual snapshots use `bun-match-svg`. Tests cover emitted trace coordinates,
bridge conservation, sub-cell slot isolation, physical cutouts, disconnected
copper, superposition, polarity, thickness units, zero current, JSON validation,
iteration failure, and mesh refinement against the independent straight-line
profile `Kx(y) = −I h / [π(h² + y²)]`.

Regenerate snapshots with `BUN_UPDATE_SNAPSHOTS=1 bun test`. The example generator
emits circuit-json, SVG, PNG, and diagnostics from the same TSX sources. The
paired examples use a fixed 50 A/mm² scale; the slotted example exceeds it at the
tip and saturates to red.
