# Return-current simulation

Simulate ground-plane return current from **circuit-json**, then generate SVG or
PNG current-density images with computed direction arrows and top-layer traces.
This is a conservative high-frequency image-current approximation for two-layer
PCBs.

![Return current around a bottom ground-plane slot](examples/ground-slot.svg)

The example follows the supplied reference: three top signals cross a long slot
in the **bottom copper**, with FR4 remaining under the top traces. A physical PCB
cutout removes both layers, so top traces must route around it. That case has a
separate [snapshot](tests/__snapshots__/physical-cutout.snap.svg).

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
