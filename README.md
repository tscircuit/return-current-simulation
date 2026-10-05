# Return-current simulation

Generate PCB return-current images from **tscircuit circuit-json**. Use Palace EM
for a simulation at a specified frequency, or the TypeScript approximation for a
quick preview. The current model supports a two-layer PCB with top signal traces
and bottom ground copper.

![Palace return current at 1 MHz, 0.05 mm sample spacing](examples/palace/ground-slot-wide-gap-005mm-1mhz/palace.png)

## Install in a tscircuit project

```sh
bun add github:tscircuit/return-current-simulation
```

The package exposes TypeScript directly; no package build step is needed. The
library's approximation and SVG renderer run without Python or Docker. Palace
simulations use the repository's scripts and require the setup below.

## 1. Get circuit-json from your board

If you already have an exported circuit-json **array**, use that file and continue
to the next step. To export a TSX board with `@tscircuit/core`, create
`export-circuit.tsx` in your project:

```tsx
import { Circuit } from "@tscircuit/core"
import { MyBoard } from "./MyBoard"

const circuit = new Circuit()
circuit.add(<MyBoard />)
await circuit.renderUntilSettled()
await Bun.write(
  "board.circuit.json",
  JSON.stringify(circuit.getCircuitJson(), null, 2),
)
```

```sh
bun run export-circuit.tsx
```

Your board needs these elements in its circuit-json:

| Element | Requirement |
| --- | --- |
| `pcb_board` | Exactly one board with `num_layers: 2`. |
| `pcb_trace` | Each excited signal is a continuous top-layer wire route. |
| Ground copper | Bottom `pcb_copper_pour`, or `pcb_ground_plane` with bottom `pcb_ground_plane_region` polygons, on the selected ground net. |
| Excitations | Signal current and the ground return contacts, added in the next step. |

In TSX, declare your ground net and bottom copper pour inside your two-layer
`<board>`:

```tsx
<net name="GND" />
<copperpour layer="bottom" connectsTo="net.GND" />
```

The simulator uses the copper geometry emitted by core. Declaring a net named
`GND` alone does not create a ground plane. Represent a ground-plane slot with a
pour outline or hole; use `<cutout>` when the substrate is also removed. A signal
may cross a slot in ground copper, but must route around a physical PCB cutout.

## 2. Specify signal current and return contacts

Circuit-json routing does not specify the current to simulate. Add one
`simulation_return_current_excitation` record for each signal you want to excite.
All records must select the same ground net. If your JSON already includes these
records, skip this step.

Create `prepare-return-current.ts` in your project. Replace `pcb_trace_0` with the
ID of the signal trace in your exported JSON, and set its current in amperes:

```ts
import {
  parseReturnCurrentCircuitJson,
  type SimulationReturnCurrentExcitation,
} from "@tscircuit/return-current-simulation"

const circuitJson = parseReturnCurrentCircuitJson(
  await Bun.file("board.circuit.json").json(),
)
const trace = circuitJson.find(
  (element) => element.type === "pcb_trace" && element.pcb_trace_id === "pcb_trace_0",
)
const ground = circuitJson.find(
  (element) => element.type === "source_net" && element.name === "GND",
)
if (!trace || trace.type !== "pcb_trace") throw new Error("Select a PCB trace")
if (!ground || ground.type !== "source_net") throw new Error("GND net is missing")
const first = trace.route[0]
const last = trace.route.at(-1)
if (!first || !last || first.route_type !== "wire" || last.route_type !== "wire")
  throw new Error("Signal needs wire endpoints")

const excitation: SimulationReturnCurrentExcitation = {
  type: "simulation_return_current_excitation",
  simulation_return_current_excitation_id: "simulation_return_current_excitation_0",
  pcb_trace_id: trace.pcb_trace_id,
  ground_source_net_id: ground.source_net_id,
  current: 1,
  return_source: { x: last.x, y: last.y },
  return_sink: { x: first.x, y: first.y },
}
await Bun.write(
  "board.return-current.json",
  JSON.stringify([...circuitJson, excitation], null, 2),
)
```

```sh
bun run prepare-return-current.ts
```

Positive signal current follows the trace's ordered route. Its ground return
enters at the load-side `return_source` and leaves at the driver-side
`return_sink`. Coordinates are millimetres in circuit world space: +X right,
+Y up. Both contacts must lie on connected ground copper. Palace requires them
directly below the trace endpoints, as in this example.

For multiple signals, append multiple records with unique IDs and the desired
current for each. Palace interprets the signed currents as **in-phase peak phasor
amplitudes**; `current: 1` means 1 A peak, not RMS. The temporary element is
proposed in [circuit-json PR #870](https://github.com/tscircuit/circuit-json/pull/870).
Until core emits it, add these records yourself. The library also accepts an
`excitations` option to supply them without modifying your circuit-json.

## 3. Run Palace and generate an image

Clone this repository for the CLI scripts. Install **Bun**, **Python 3.12**, and
either **Docker** or a native **Palace v0.14.0** installation. On Debian/Ubuntu,
Gmsh also needs `libglu1-mesa` (`sudo apt-get install libglu1-mesa`).

```sh
git clone https://github.com/tscircuit/return-current-simulation
cd return-current-simulation
bun install
python3 -m venv work/palace-python
work/palace-python/bin/pip install -r lib/palace/python/requirements.txt
export PALACE_PYTHON="$PWD/work/palace-python/bin/python"
```

With Docker running, simulate your prepared JSON at **1 MHz**:

```sh
bun run palace /path/to/my-project/board.return-current.json work/my-board \
  --frequency-hz 1000000 --mesh-size 2 --cell-size 0.2 \
  --air-padding 6 --order 2 --processes 4
```

For a native installation, set `PALACE_BIN=/path/to/palace-v0.14.0/bin/palace`
before running that command. The Docker fallback uses a community-built v0.14.0
image [pinned by digest](scripts/palace/run-case.ts).

| CLI option | Meaning | Default |
| --- | --- | --- |
| `--frequency-hz` | Frequency in Hz. | Required |
| `--mesh-size` | Target FEM mesh size in mm. | `2` |
| `--order` | FEM polynomial order, `1` or `2`. | `2` |
| `--cell-size` | Target image sample spacing in mm. | `0.2` |
| `--air-padding` | Air-domain padding in mm. | `6` |
| `--processes` | MPI process count. | `PALACE_PROCESSES`, otherwise `1` |
| `--python` | Python executable with Gmsh/VTK installed. | `PALACE_PYTHON`, otherwise `python3` |
| `--palace-bin` | Native Palace executable. | `PALACE_BIN`, otherwise Docker |

Frequency has no default. The physical defaults are board thickness for
signal/ground separation (0.8 mm if missing), 0.035 mm copper, conductivity
5.8 × 10⁷ S/m, substrate relative permittivity 4.3, loss tangent 0.02, and 50 Ω
source/load ports. To set other material or stackup values, use `PalaceOptions`
with [`runPalaceCase`](scripts/palace/run-case.ts) from a script in this checkout.

The command also generates an approximation comparison, so its image grid must
stay within **100,000 candidate cells**. Increase `--cell-size` for larger boards.
Use the next step for a finer Palace-only image.

Open `work/my-board/palace.png` or `palace.svg`. The case directory also contains:

| Output | Contents |
| --- | --- |
| `circuit.json`, `model.json`, `palace.json` | Input circuit, physical model and solver configuration. |
| `mesh.msh`, `palace.log`, `postpro/` | FEM mesh, solver log, port data and raw ParaView fields. |
| `reference.json` | Sample positions and complex sheet-current components in A/mm. |
| `normalization.json` | Source/load currents and source-basis normalization. |
| `comparison.json`, `approximation.svg`, `approximation.png` | Differences from the TypeScript approximation and its image. |

Keep the raw `postpro/` fields to resample later. Heatmap colors show the magnitude
of thickness-averaged conduction-current density in **A/mm²**. Arrows show the
instantaneous current at the selected phase; sources are normalized to the
currents you supplied.

## 4. Generate a higher-resolution image

Resample a completed case without rerunning the EM solve:

```sh
bun run resample:palace work/my-board \
  --cell-size 0.05 --palace-only --image-size 2000
```

This overwrites that case's sampled `reference.json` and Palace images, and writes
`resample-timing.json`. It evaluates the saved FEM fields at the new positions.
`--palace-only` skips the approximation and comparison; their previous outputs
are not regenerated. Palace sampling supports up to **1,000,000 candidate cells**.

On a 40 × 40 mm board, 0.05 mm spacing gives an **800 × 800** grid. `--image-size`
sets the square PNG size in pixels (default 1100). **Image sampling and FEM mesh
resolution are separate:** change `--mesh-size` or `--order` and rerun Palace to
refine the EM solve. Change frequency or geometry by starting a new solve too.

The included [4 mm-gap example](examples/palace/ground-slot-wide-gap-005mm-1mhz)
took 62.2 s to sample/export at 0.05 mm, reusing a completed 1 MHz FEM solve.
Its timing report includes hardware and stage measurements.

## Render saved Palace fields in TypeScript

Use the library to render `model.json` and `reference.json` from a completed case:

```ts
import {
  renderPalaceModelSvg,
  type PalaceModel,
  type PalaceReference,
} from "@tscircuit/return-current-simulation"

const model: PalaceModel = await Bun.file("work/my-board/model.json").json()
const reference: PalaceReference = await Bun.file("work/my-board/reference.json").json()
const svg = renderPalaceModelSvg(model, {
  reference,
  phaseDegrees: 0,
  maxCurrentDensity: 50,
  vectorSpacing: Math.max(1, Math.round(1 / reference.cellWidth)),
  width: 2000,
  height: 2000,
})
await Bun.write("return-current.svg", svg)
```

`phaseDegrees` changes arrows; the complex-magnitude heatmap remains the same.
`maxCurrentDensity` fixes the linear color scale in A/mm². Other render options
include `hideVectors`, `hideTraces`, `title`, `width` and `height`. SVG rendering
needs no browser or native dependency.

## Quick TypeScript approximation

For a preview without Palace, use the prepared circuit-json in your project:

```ts
import {
  parseReturnCurrentCircuitJson,
  simulateReturnCurrent,
  renderReturnCurrentSvg,
} from "@tscircuit/return-current-simulation"

const circuitJson = parseReturnCurrentCircuitJson(
  await Bun.file("board.return-current.json").json(),
)
const result = simulateReturnCurrent({
  circuitJson,
  cellSize: 0.5,
  layerSeparation: 0.8,
  copperThickness: 0.035,
  contactRadius: 0.6,
})
await Bun.write("preview.svg", renderReturnCurrentSvg(result, {
  maxCurrentDensity: 50,
}))
```

This approximation is frequency-independent. It conserves current but does not
solve Maxwell's equations. Its grid is limited to 100,000 candidate cells.
`cellSize`, separation, copper thickness and contact radius are in millimetres.
Separation defaults to board thickness; copper thickness defaults to 0.035 mm.
The repository can also export its PNG:

```sh
bun run render /path/to/my-project/board.return-current.json preview.png 0.5
```

To compare against Palace, pass a matching approximation result to
`comparePalaceReference(result, { reference })`. Use the reference's cell spacing,
copper thickness, layer separation and source currents. The comparison requires
identical sample positions; it reports complex-vector, real-vector and magnitude
L2 differences. It is available only at grids supported by the approximation.

## Supported boards and common input errors

- **Missing excitations:** add signal current and return-contact records; current
  is not inferred from component values or routing.
- **Missing bottom ground copper:** add a bottom pour/plane region on the same
  `source_net_id` used by the excitations.
- **Contacts outside copper or on disconnected regions:** adjust contacts or the
  ground geometry. Palace contacts must be directly below signal endpoints.
- **Unsupported geometry:** the current model rejects vias, drilled/plated holes,
  multi-layer boards, and routes that change layers. Palace supports rectangular
  top SMT pads. Simplify the board to the supported two-layer geometry first.
- **High-frequency thickness error:** the current Palace volume mesher requires
  copper thickness no greater than skin depth; it is not yet a resolved
  high-frequency skin-effect model.

Palace provides an independent EM comparison. Establish accuracy by checking
mesh refinement and air-domain size; a finer image grid alone does not establish
convergence. The checked-in [Palace examples](examples/palace) include solver
logs, provenance and current-balance evidence.

## Try the examples or contribute

```sh
bun install
bun run start                 # Cosmos viewer and Palace comparison
bun run generate:examples     # TSX-derived approximation examples
bun run generate:palace:wide-gap work/palace/ground-slot-wide-gap-1mhz
bun test
bun run typecheck
bun run format:check
```

The Palace generator needs the Python/Palace setup above. Numerical fixtures and
visual snapshots start from TSX rendered by `@tscircuit/core`; excitation records
are appended until core supports them. See
[`SlotBoard`](tests/fixtures/SlotBoard.tsx) and the
[`fixture helper`](tests/fixtures/render-fixture.tsx) for working examples.
