import {
  MultilayerBoard,
  fourLayerStackup,
} from "tests/fixtures/MultilayerBoard"
import { Circuit } from "@tscircuit/core"
import { mkdtemp, readFile, writeFile, rm, stat } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { strict as assert } from "node:assert"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { ExplicitPortBoard } from "tests/fixtures/ExplicitPortBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

const repository = process.cwd()
const consumer = await mkdtemp(
  join(tmpdir(), "simulate-return-current-package-"),
)
async function run(command: string[], cwd = consumer) {
  const child = Bun.spawn(command, { cwd, stdout: "pipe", stderr: "pipe" })
  const [stdout, stderr, status] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ])
  if (status !== 0)
    throw new Error(`${command[0]} failed (${status}): ${stdout}\n${stderr}`)
  return stdout
}

try {
  const packed = JSON.parse(
    await run(
      [
        "npm",
        "pack",
        "--ignore-scripts",
        "--json",
        "--pack-destination",
        consumer,
        "--cache",
        join(consumer, "cache"),
      ],
      repository,
    ),
  )[0]
  assert.equal(packed.name, "simulate-return-current")
  assert(
    packed.files.some((file: { path: string }) => file.path === "dist/cli.js"),
  )
  for (const asset of ["mesh.py", "sample.py", "requirements.txt"])
    assert(
      packed.files.some(
        (file: { path: string }) => file.path === `dist/python/${asset}`,
      ),
    )
  assert(
    packed.files.every(
      (file: { path: string }) =>
        file.path.startsWith("dist/") ||
        ["README.md", "LICENSE", "package.json"].includes(file.path),
    ),
  )
  await writeFile(
    join(consumer, "package.json"),
    JSON.stringify({ private: true, type: "module" }),
  )
  await run([
    "npm",
    "install",
    join(consumer, packed.filename),
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    "--cache",
    join(consumer, "cache"),
  ])
  const bin = join(consumer, "node_modules/.bin/simulate-return-current")
  assert((await run([bin, "--help"])).includes("R1.pin1"))
  assert.equal((await run([bin, "--version"])).trim(), packed.version)
  const circuitJson = (await renderFixture(<StraightBoard />)).filter(
    (element) => element.type !== "simulation_return_current_excitation",
  )
  await writeFile(join(consumer, "board.json"), JSON.stringify(circuitJson))
  const common = [
    "board.json",
    "--source",
    "SIG_S.pin1",
    "--load",
    "SIG_L.SIGNAL",
    "--ground",
    "GND",
    "--current",
    "250mA",
  ]
  const listed = JSON.parse(await run([bin, "ports", "board.json"]))
  assert(listed.ports[0].aliases.includes("SIG_S.pin1"))
  await run([
    bin,
    ...common,
    "--frequency-hz",
    "1000000",
    "--output",
    "prepared",
    "--cell-size",
    "0.05",
    "--prepare-only",
  ])
  const model = JSON.parse(
    await readFile(join(consumer, "prepared/model.json"), "utf8"),
  )
  assert.equal(model.frequencyHz, 1e6)
  assert.equal(model.geometry.excitations[0].current, 0.25)
  const grid = JSON.parse(
    await readFile(join(consumer, "prepared/sample-grid.json"), "utf8"),
  )
  assert.equal(grid.columns, 600)
  assert.equal(grid.rows, 400)
  const explicit = (await renderFixture(<ExplicitPortBoard />)).filter(
    (element) => element.type !== "simulation_return_current_excitation",
  )
  await writeFile(join(consumer, "explicit.json"), JSON.stringify(explicit))
  await writeFile(
    join(consumer, "ports.json"),
    JSON.stringify([
      {
        source: "U1.OUT",
        sourceReference: "U1.GND",
        load: "U2.IN",
        loadReference: "U2.GND",
        current: "5mA",
        sourceImpedance: "25ohm",
        loadImpedance: "100ohm",
      },
    ]),
  )
  await run([
    bin,
    "explicit.json",
    "--ports-file",
    "ports.json",
    "--ground",
    "GND",
    "--frequency-hz",
    "1000000",
    "--prepare-only",
    "--output",
    "explicit-prepared",
  ])
  const explicitModel = JSON.parse(
    await readFile(join(consumer, "explicit-prepared/model.json"), "utf8"),
  )
  assert.equal(explicitModel.geometry.excitations[0].current, 0.005)
  assert.deepEqual(
    explicitModel.ports.map((port: { resistance: number }) => port.resistance),
    [25, 100],
  )
  assert.equal(explicitModel.groundVias.length, 2)
  const layeredCircuit = new Circuit()
  layeredCircuit.add(<MultilayerBoard innerPlane />)
  await layeredCircuit.renderUntilSettled()
  await writeFile(
    join(consumer, "multilayer.json"),
    JSON.stringify(layeredCircuit.getCircuitJson()),
  )
  await writeFile(
    join(consumer, "stackup.json"),
    JSON.stringify(fourLayerStackup),
  )
  await run([
    bin,
    "multilayer.json",
    "--stackup-file",
    "stackup.json",
    "--sample-layer",
    "inner2",
    "--ports-file",
    "ports.json",
    "--ground",
    "GND",
    "--frequency-hz",
    "1000000",
    "--prepare-only",
    "--output",
    "multilayer-prepared",
  ])
  const multilayer = JSON.parse(
    await readFile(join(consumer, "multilayer-prepared/model.json"), "utf8"),
  )
  assert.equal(multilayer.multilayer.sampleLayer, "inner2")
  assert.equal(multilayer.multilayer.audit.vias, 4)
  assert.equal(multilayer.multilayer.stackup.copperLayers.length, 4)
  assert(
    (
      await stat(
        join(
          consumer,
          "node_modules/simulate-return-current/dist/python/mesh_multilayer.py",
        ),
      )
    ).size > 1000,
  )
  await run([
    bin,
    ...common,
    "--solver",
    "approximation",
    "--output",
    "preview",
  ])
  assert((await stat(join(consumer, "preview/approximation.png"))).size > 1000)
  const circuitResult = JSON.parse(
    await readFile(join(consumer, "preview/circuit-result.json"), "utf8"),
  )
  assert(
    circuitResult.some(
      (element: { type: string }) =>
        element.type === "simulation_pcb_return_current_result",
    ),
  )
  assert(
    circuitResult.some(
      (element: { type: string; field_asset?: { url: string } }) =>
        element.type === "simulation_pcb_return_current_field" &&
        element.field_asset?.url.startsWith("data:application/gzip;base64,"),
    ),
  )
  await writeFile(
    join(consumer, "import.mjs"),
    `
import { readFileSync } from "node:fs";
import { parseReturnCurrentCircuitJson, withNamedExcitations, simulateReturnCurrent, renderReturnCurrentSvg, createReturnCurrentExperiment, selectReturnCurrentExperiment } from "simulate-return-current";
import { exportReturnCurrentCircuitJson } from "simulate-return-current/circuit-json";
import { preparePalaceSimulation } from "simulate-return-current/palace";
const input = parseReturnCurrentCircuitJson(JSON.parse(readFileSync("board.json", "utf8")));
const ports = [{ source: "SIG_S.pin1", load: "SIG_L.SIGNAL", current: 0.25 }];
const circuitJson = withNamedExcitations({ circuitJson: input, ports, groundNet: "GND" });
if (!renderReturnCurrentSvg(simulateReturnCurrent({ circuitJson })).includes("<svg")) throw new Error("Missing SVG");
await preparePalaceSimulation({ circuitJson: input, ports, groundNet: "GND", frequencyHz: 1e6, outputDirectory: "library-prepared" });
const definitions = createReturnCurrentExperiment({ circuitJson: input, ports, groundNet: "GND", experimentId: "simulation_experiment_smoke" });
const selected = selectReturnCurrentExperiment({ circuitJson: definitions });
const result = exportReturnCurrentCircuitJson({ circuitJson: definitions, experimentId: selected.experiment.simulation_experiment_id, simulation: simulateReturnCurrent({ circuitJson: selected.solverCircuitJson, excitations: selected.excitations }) });
if (!result.some((element) => element.type === "simulation_pcb_return_current_field")) throw new Error("Missing official Circuit JSON field");
`,
  )
  await run(["node", "import.mjs"])
  await writeFile(
    join(consumer, "types.mts"),
    `
import { parseReturnCurrentCircuitJson, withNamedExcitations } from "simulate-return-current";
import { runPalaceSimulation } from "simulate-return-current/palace";
const circuitJson = parseReturnCurrentCircuitJson([]);
const ports = [{ source: "R1.pin1", load: "U1.VDDIO1", current: 1 }];
withNamedExcitations({ circuitJson, ports, groundNet: "GND" });
runPalaceSimulation({ circuitJson, ports, groundNet: "GND", frequencyHz: 1e6, outputDirectory: "out" });
// @ts-expect-error Frequency is required.
runPalaceSimulation({ circuitJson, ports, groundNet: "GND", outputDirectory: "out" });
withNamedExcitations({ circuitJson, ports: [{ source: "R1.pin1", sourceReference: "R1.GND", load: "U1.pin1", loadReference: "U1.GND", current: "5mA", sourceImpedance: "50ohm", loadImpedance: 100 }], groundNet: "GND" });
// @ts-expect-error Peak current must be a number or string with units.
withNamedExcitations({ circuitJson, ports: [{ source: "R1.pin1", load: "U1.pin1", current: true }], groundNet: "GND" });
`,
  )
  await run([
    "node",
    resolve(consumer, "node_modules/typescript/bin/tsc"),
    "types.mts",
    "--noEmit",
    "--strict",
    "--skipLibCheck",
    "--module",
    "NodeNext",
    "--moduleResolution",
    "NodeNext",
    "--target",
    "ES2022",
  ])
  console.log(
    `Package smoke passed: ${packed.name}@${packed.version}; installed Node CLI, library, NodeNext declarations, named ports, 0.05 mm preparation, PNG, bundled Python assets`,
  )
} finally {
  await rm(consumer, { recursive: true, force: true })
}
