# simulate-return-current

Generate return-current SVG/PNG images from **tscircuit circuit-json** with
**Palace EM**. Select the signal's source/load pins, ground net, peak current and
frequency explicitly.

![1 MHz Palace return current](examples/palace/ground-slot-wide-gap-005mm-1mhz/palace.png)

## CLI

Requires **Node.js 20.11+**. Install globally or run with `npx`:

```sh
npm install -g simulate-return-current
simulate-return-current --help
# Or: npx simulate-return-current --help
```

For Palace, also install **Python 3.12** and run Docker, or provide native
**Palace v0.14.0** with `--palace-bin /path/to/palace`. Install the Python
dependencies into a local environment using the bundled setup command:

```sh
simulate-return-current setup --python python3
```

This creates `.return-current-python/` in the current directory, which subsequent
runs detect automatically. On Debian/Ubuntu, Gmsh needs `libglu1-mesa` too.
Use `--python /path/to/venv/bin/python` or `PALACE_PYTHON` for an existing
environment. The Docker fallback is a community-built image pinned by digest.

### Use your circuit-json

Export the circuit-json array from your tscircuit board with
`circuit.getCircuitJson()` after `await circuit.renderUntilSettled()`. Save that
array as `board.json`; signal traces and bottom ground copper must already be
rendered. Inspect available pin names and aliases:

```sh
simulate-return-current ports board.json
```

Run a **1 MHz**, **1 A peak** excitation from `R1.pin1` to `U1.VDDIO1`, referenced
to the bottom copper on `GND`:

```sh
simulate-return-current board.json \
  --source R1.pin1 --load U1.VDDIO1 --ground GND \
  --current 1 --frequency-hz 1000000 \
  --output return-current --cell-size 0.05 --image-size 2000
```

Open `return-current/palace.png` or `palace.svg`. The case also saves the resolved
`excitation-ports.json`, input circuit, model, mesh, solver logs, raw ParaView
fields, complex sampled currents and `run-timing.json`.

**Frequency comes from `--frequency-hz`, not from circuit-json or the pin name.**
`--source` names the driver terminal; `--load` names the receiving terminal.
`--current` is the signed peak current at that frequency, not RMS. Named pins
resolve through source components/ports to PCB ports and the connecting trace;
you do not need to look up `pcb_trace_id` or manually inject excitation records.

Each signal endpoint is paired with the **ground plane directly beneath it**.
`--ground` selects that plane's net by name or `source_net_id`; it does not select
a separate ground-pad terminal. Palace uses 50 Ω source/load ports and normalizes
the source current to your requested amplitude. This simulates PCB geometry at
one frequency; it does not infer a voltage source or solve the components as a
SPICE circuit.

For multiple signals, repeat `--excitation source,load,current` instead of
`--source/--load/--current`. They share the specified frequency and ground net,
with signed, in-phase peak currents:

```sh
simulate-return-current board.json --ground GND --frequency-hz 1000000 \
  --excitation R1.pin1,U1.VDDIO1,1 \
  --excitation R2.pin1,U2.IN,0.5 --output return-current
```

Use `--prepare-only` to inspect the resolved ports, model and sample grid before
running an EM solve. For JSON that already contains
`simulation_return_current_excitation` records, explicitly use
`--use-circuit-excitations` with `--frequency-hz` instead of naming pins.

### Resolution and resampling

`--cell-size` sets image sample spacing in mm (Palace default 0.2). On a 40 mm
square board, 0.05 mm gives **800 × 800** sample cells. `--image-size` sets square
SVG/PNG dimensions in pixels (default 1100).

To resample a completed case without rerunning Palace:

```sh
simulate-return-current resample return-current --cell-size 0.05 --image-size 2000
```

Keep the case's raw `postpro/` fields. Resampling overwrites its sampled reference
and images and writes `resample-timing.json`. It evaluates the saved FEM fields
at new positions; **image sampling does not refine the EM mesh**. Change
`--mesh-size` (default 2 mm), `--order` (default 2), or `--air-padding` (default
6 mm) and start a new solve to change the numerical model. Frequency and geometry
changes also need a new solve. Use `--processes` for MPI parallelism.

Colors show the complex magnitude of thickness-averaged conduction-current
density in A/mm²; arrows show the instantaneous field at phase 0°. Palace sample
grids allow up to 1,000,000 candidate cells. The included
[0.05 mm example](examples/palace/ground-slot-wide-gap-005mm-1mhz) records export
timings and the original solve's provenance.

### Quick approximation

For a preview without Python or Docker, select the TypeScript approximation:

```sh
simulate-return-current board.json --solver approximation \
  --source R1.pin1 --load U1.VDDIO1 --ground GND --current 1 \
  --cell-size 0.5 --output preview
```

Open `preview/approximation.png`. This model is **frequency-independent**;
`--frequency-hz` is rejected for it. Its grid is limited to 100,000 candidate
cells. Use Palace for the frequency-dependent simulation.

## Library

`circuitJson` can be the array from `circuit.getCircuitJson()`. Validate JSON
loaded from a file with the root export `parseReturnCurrentCircuitJson`.

```ts
import { runPalaceSimulation } from "simulate-return-current/palace"

const result = await runPalaceSimulation({
  circuitJson,
  frequencyHz: 1e6,
  groundNet: "GND",
  ports: [{ source: "R1.pin1", load: "U1.VDDIO1", current: 1 }],
  outputDirectory: "return-current",
})
console.log(result.pngPath)
```

The Node-only `/palace` entry also exports `preparePalaceSimulation`,
`resamplePalaceCase` and `setupPalacePython`. The root entry exports
`withNamedExcitations`, `simulateReturnCurrent` (the approximation),
`renderReturnCurrentSvg`, `renderPalaceModelSvg` and the comparison helpers.
Use `renderPalaceModelSvg(model, { reference, phaseDegrees: 90 })` to render saved
Palace fields at a different arrow phase.

## Supported inputs

The current model needs one **two-layer** board, continuous **top-layer** wire
traces, and **bottom ground copper** on the selected net. Each source/load pair
must be the endpoints of one PCB trace. Branched/component-spanning paths, vias,
drilled/plated holes and multi-layer routing are not supported. Pin/refdes
selectors must be unambiguous. Palace supports rectangular top SMT pads.

Ground copper comes from bottom `pcb_copper_pour` records or
`pcb_ground_plane`/`pcb_ground_plane_region` records. Declaring `GND` alone does
not create copper. A ground-plane slot removes copper; a physical PCB cutout
also removes substrate, so signals must route around it.

Physical defaults: board thickness for signal/ground separation (0.8 mm when
missing), 0.035 mm copper, 5.8 × 10⁷ S/m conductivity, substrate relative
permittivity 4.3, and loss tangent 0.02. The library's `PalaceSimulationOptions`
allows material and stackup overrides. The current volume mesher requires foil
thickness no greater than skin depth. Check mesh refinement and air-domain size
before treating Palace results as an accuracy reference.

## Develop and publish

```sh
bun install
bun test
bun run typecheck
bun run format:check
bun run build
bun run smoke:package
bun run start                 # Cosmos viewer
npm pack                     # npm tarball, including CLI and Python assets
```

Like `tscircuit/check-shorts`, the package ships built ESM and TypeScript
declarations. Tests generate circuit-json from TSX. The package smoke check
installs a tarball into a clean project and exercises its Node CLI and library.

The **Publish to npm** workflow runs manually from `main`, validates the package,
and publishes it with provenance. Repository metadata targets
`tscircuit/simulate-return-current`; rename the repository before the first
provenance release. The first release needs the repository's
`NPM_TOKEN` secret; later releases can use npm trusted publishing configured for
the repository and `publish-npm.yml`. Bump `package.json` before subsequent
releases. You can also run `npm publish --access public` after authenticating.
