#!/usr/bin/env node
import { readFile, writeFile, mkdir } from "node:fs/promises"
import { resolve, join } from "node:path"
import { parseArgs } from "node:util"
import { Resvg } from "@resvg/resvg-js"
import {
  parseReturnCurrentCircuitJson,
  listCircuitPorts,
  withNamedExcitations,
  simulateReturnCurrent,
  renderReturnCurrentSvg,
} from "../lib/index"
import type { ReturnCurrentCircuitJson, NamedExcitation } from "../lib/index"
import {
  runPalaceSimulation,
  preparePalaceSimulation,
  resamplePalaceCase,
  setupPalacePython,
} from "../lib/palace"
import { imageDimension } from "../lib/palace/run-simulation"
import { positiveFinite } from "../lib/read-geometry"
import { version } from "../package.json"
import type { PalaceSimulationOptions } from "../lib/palace"

const help = `simulate-return-current — PCB return-current images from circuit-json

Usage:
  simulate-return-current board.json --source R1.pin1 --load U1.VDDIO1
    --ground GND --current 1 --frequency-hz 1000000 --output return-current
  simulate-return-current board.json --ground GND --frequency-hz 1000000
    --excitation R1.pin1,U1.VDDIO1,1 --excitation R2.pin1,U2.IN,0.5
  simulate-return-current ports board.json
  simulate-return-current setup [--python python3 --directory .return-current-python]
  simulate-return-current resample return-current --cell-size 0.05 --image-size 2000

Options:
  --source, --load <refdes.pin>   Driver/load terminals; pin names or aliases
  --ground <net>                Ground net name or source_net_id
  --current <A>                 Signed in-phase peak amperes, not RMS
  --excitation <source,load,A>   Repeat for multiple simultaneous excitations
  --frequency-hz <Hz>           Required for Palace; never inferred from routing
  --output, -o <directory>      Output case directory (default: return-current)
  --cell-size <mm>              Image sample pitch (Palace: 0.2; approximation: 0.5)
  --image-size <pixels>         Square SVG/PNG size (default: 1100)
  --mesh-size <mm>              FEM mesh target (default: 2)
  --order <1|2>                 FEM polynomial order (default: 2)
  --air-padding <mm>            Air domain padding (default: 6)
  --processes <count>           MPI processes (default: PALACE_PROCESSES or 1)
  --python <path>               Python with Gmsh/VTK; or PALACE_PYTHON
  --palace-bin <path>           Native Palace v0.14.0; or PALACE_BIN; otherwise Docker
  --prepare-only               Resolve ports/save inputs without running a solver
  --use-circuit-excitations     Explicitly use excitation records already in JSON
  --solver <palace|approximation> Default: palace; approximation has no frequency model
  --help, -h / --version, -v

Each signal port is paired with bottom ground directly beneath it. Source/load
must be endpoints of one continuous top-layer trace. No voltage source, signal
amplitude, component circuit or frequency is inferred from circuit-json.
Palace needs Python 3.12 with Gmsh/VTK and Docker or native Palace v0.14.0.
`

const definitions = {
  help: { type: "boolean", short: "h" },
  version: { type: "boolean", short: "v" },
  source: { type: "string" },
  load: { type: "string" },
  ground: { type: "string" },
  current: { type: "string" },
  excitation: { type: "string", multiple: true },
  "frequency-hz": { type: "string" },
  output: { type: "string", short: "o" },
  solver: { type: "string" },
  "cell-size": { type: "string" },
  "image-size": { type: "string" },
  "mesh-size": { type: "string" },
  order: { type: "string" },
  "air-padding": { type: "string" },
  processes: { type: "string" },
  python: { type: "string" },
  "palace-bin": { type: "string" },
  directory: { type: "string" },
  "prepare-only": { type: "boolean" },
  "use-circuit-excitations": { type: "boolean" },
} as const

async function inputCircuit(
  filename: string,
): Promise<ReturnCurrentCircuitJson> {
  return parseReturnCurrentCircuitJson(
    JSON.parse(await readFile(resolve(filename), "utf8")),
  )
}

async function main() {
  const { values, positionals } = parseArgs({
    options: definitions,
    allowPositionals: true,
  })
  if (values.version) {
    console.log(version)
    return
  }
  if (values.help || !positionals.length) {
    console.log(help)
    return
  }
  const number = (
    key: keyof typeof definitions,
    fallback?: number,
  ): number | undefined =>
    values[key] === undefined ? fallback : Number(values[key])
  const command = positionals[0]
  if (["setup", "ports", "resample"].includes(command)) {
    const allowed =
      command === "setup"
        ? ["python", "directory"]
        : command === "resample"
          ? ["python", "cell-size", "image-size"]
          : []
    for (const key of Object.keys(values))
      if (!allowed.includes(key))
        throw new Error(
          `--${key} is not supported by ${command}; change frequency or ports by starting a new simulation`,
        )
    if (command === "setup") {
      if (positionals.length !== 1)
        throw new Error(
          "Usage: simulate-return-current setup [--python python3 --directory .return-current-python]",
        )
      console.log(
        `Python ready: ${await setupPalacePython({ python: values.python, directory: values.directory })}`,
      )
      return
    }
    if (positionals.length !== 2)
      throw new Error(
        `Usage: simulate-return-current ${command} ${command === "ports" ? "board.json" : "case-directory"}`,
      )
    if (command === "ports") {
      const circuitJson = await inputCircuit(positionals[1])
      console.log(
        JSON.stringify(
          {
            ports: listCircuitPorts(circuitJson),
            nets: circuitJson.flatMap((element) =>
              element.type === "source_net"
                ? [{ name: element.name, sourceNetId: element.source_net_id }]
                : [],
            ),
          },
          null,
          2,
        ),
      )
    } else
      console.log(
        JSON.stringify(
          await resamplePalaceCase({
            outputDirectory: positionals[1],
            cellSize: number("cell-size"),
            imageSize: number("image-size"),
            python: values.python,
          }),
          null,
          2,
        ),
      )
    return
  }
  if (positionals.length !== 1)
    throw new Error(
      "Specify one circuit-json input file; use --output for the output directory",
    )
  if (values.directory) throw new Error("--directory is only used by setup")
  const solver = values.solver ?? "palace"
  if (solver !== "palace" && solver !== "approximation")
    throw new Error("solver must be palace or approximation")
  const frequencyHz =
    solver === "palace"
      ? positiveFinite(
          number("frequency-hz", Number.NaN)!,
          "frequencyHz (--frequency-hz)",
        )
      : undefined
  if (solver === "approximation" && values["frequency-hz"] !== undefined)
    throw new Error(
      "The approximation has no frequency model; use --solver palace to specify frequency",
    )
  const circuitJson = await inputCircuit(command)
  const namedFlags =
    values.source !== undefined ||
    values.load !== undefined ||
    values.current !== undefined ||
    values.ground !== undefined ||
    values.excitation !== undefined
  let ports: NamedExcitation[] | undefined
  if (values["use-circuit-excitations"]) {
    if (namedFlags)
      throw new Error("Choose named ports or --use-circuit-excitations")
    if (
      !circuitJson.some(
        (element) => element.type === "simulation_return_current_excitation",
      )
    )
      throw new Error(
        "Input JSON has no simulation_return_current_excitation records",
      )
  } else {
    if (!values.ground)
      throw new Error(
        "Specify --ground GND and named source/load/current, or --use-circuit-excitations",
      )
    if (values.excitation) {
      if (
        values.source !== undefined ||
        values.load !== undefined ||
        values.current !== undefined
      )
        throw new Error("Choose --excitation or --source/--load/--current")
      ports = values.excitation.map((value) => {
        const fields = value.split(",").map((field) => field.trim())
        if (fields.length !== 3 || fields.some((field) => !field))
          throw new Error(
            "Each --excitation must be source,load,current (e.g. R1.pin1,U1.VDDIO1,1)",
          )
        return {
          source: fields[0],
          load: fields[1],
          current: Number(fields[2]),
        }
      })
    } else {
      if (!values.source || !values.load || values.current === undefined)
        throw new Error(
          "Specify --source R1.pin1 --load U1.VDDIO1 --current 1 --ground GND",
        )
      ports = [
        {
          source: values.source,
          load: values.load,
          current: Number(values.current),
        },
      ]
    }
  }
  const outputDirectory = resolve(values.output ?? "return-current")
  const imageSize = imageDimension(number("image-size", 1100))
  if (solver === "approximation") {
    for (const flag of [
      "mesh-size",
      "order",
      "air-padding",
      "processes",
      "python",
      "palace-bin",
      "prepare-only",
    ] as const)
      if (values[flag] !== undefined)
        throw new Error(`--${flag} is a Palace option`)
    const input = ports
      ? withNamedExcitations({ circuitJson, ports, groundNet: values.ground! })
      : circuitJson
    const result = simulateReturnCurrent({
      circuitJson: input,
      cellSize: number("cell-size", 0.5),
    })
    const svg = renderReturnCurrentSvg(result, {
      width: imageSize,
      height: imageSize,
      maxCurrentDensity: 50,
      vectorSpacing: Math.max(1, Math.round(1 / result.cellWidth)),
    })
    await mkdir(outputDirectory, { recursive: true })
    await writeFile(
      join(outputDirectory, "circuit.json"),
      JSON.stringify(input),
    )
    await writeFile(join(outputDirectory, "approximation.svg"), svg)
    await writeFile(
      join(outputDirectory, "approximation.png"),
      new Resvg(svg).render().asPng(),
    )
    await writeFile(
      join(outputDirectory, "diagnostics.json"),
      JSON.stringify(
        {
          frequencyModel: "none",
          ports: ports ?? null,
          groundNet: values.ground ?? null,
          ...result.diagnostics,
        },
        null,
        2,
      ),
    )
    console.log(
      `Frequency-independent approximation: ${join(outputDirectory, "approximation.png")}`,
    )
    return
  }
  const order = number("order", 2)
  if (order !== 1 && order !== 2) throw new Error("order must be 1 or 2")
  const options: PalaceSimulationOptions = {
    circuitJson,
    ports,
    groundNet: values.ground,
    frequencyHz: frequencyHz!,
    outputDirectory,
    cellSize: number("cell-size", 0.2),
    imageSize,
    meshSize: number("mesh-size", 2),
    order,
    airPadding: number("air-padding", 6),
    processes: number("processes"),
    python: values.python,
    palaceBin: values["palace-bin"],
  }
  if (values["prepare-only"]) {
    const prepared = await preparePalaceSimulation(options)
    console.log(
      `Prepared ${prepared.model.frequencyHz} Hz Palace input at ${prepared.destination}; no EM solve performed`,
    )
  } else
    console.log(JSON.stringify(await runPalaceSimulation(options), null, 2))
}

main().catch((error: unknown) => {
  console.error(
    `simulate-return-current: ${error instanceof Error ? error.message : String(error)}`,
  )
  process.exitCode = 1
})
