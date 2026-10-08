#!/usr/bin/env node
import { readFile, writeFile, mkdir } from "node:fs/promises"
import { resolve, join } from "node:path"
import { parseArgs } from "node:util"
import { Resvg } from "@resvg/resvg-js"
import { z } from "zod"
import {
  parseReturnCurrentCircuitJson,
  listCircuitPorts,
  simulateReturnCurrent,
  renderReturnCurrentSvg,
  parseCurrentAmps,
  parseResistanceOhms,
  createReturnCurrentExperiment,
  selectReturnCurrentExperiment,
  exportReturnCurrentCircuitJson,
} from "../lib/index"
import type { ReturnCurrentCircuitJson, NamedExcitation } from "../lib/index"
import {
  runPalaceSimulation,
  preparePalaceSimulation,
  resamplePalaceCase,
  setupPalacePython,
} from "../lib/palace"
import {
  parseFabricationStackup,
  parseCopperLayer,
} from "../lib/palace/stackup"
import { imageDimension } from "../lib/palace/run-simulation"
import { positiveFinite } from "../lib/read-geometry"
import { version } from "../package.json"
import type { PalaceSimulationOptions } from "../lib/palace"
import type { PalaceModel, PalaceReference } from "../lib/palace/types"

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
  --source-reference <refdes.pin> Source reference terminal (default: plane beneath)
  --load-reference <refdes.pin>  Load reference terminal (default: plane beneath)
  --source-impedance <ohms>      Positive real source port resistance (default: 50)
  --load-impedance <ohms>        Positive real load resistance (default: 50)
  --ground <net>                Ground net name or source_net_id
  --current <A>                 Signed peak current: 5mA, 0.1A, 250uA or bare amperes
  --excitation <source,load,A>   Repeat; or source,sourceRef,load,loadRef,current
  --ports-file <json>           Array of named excitations, including per-port impedances
  --frequency-hz <Hz>           Required for Palace; never inferred from routing
  --output, -o <directory>      Output case directory (default: return-current)
  --cell-size <mm>              Image sample pitch (Palace: 0.2; approximation: 0.5)
  --image-size <pixels>         Square SVG/PNG size (default: 1100)
  --stackup-file <json>         Physical top-to-bottom stackup; required for multilayer
  --sample-layer <layer>        Reference copper to sample: top, inner1..inner8, bottom
  --via-clearance <mm>          Radial foreign-net antipad clearance (default: board or 0.2)
  --mesh-size <mm>              FEM mesh target (default: 2)
  --order <1|2>                 FEM polynomial order (default: 2)
  --air-padding <mm>            Air domain padding (default: 6)
  --processes <count>           MPI processes (default: PALACE_PROCESSES or 1)
  --python <path>               Python with Gmsh/VTK; or PALACE_PYTHON
  --palace-bin <path>           Native Palace v0.14.0; or PALACE_BIN; otherwise Docker
  --prepare-only               Resolve ports/save inputs without running a solver
  --use-circuit-excitations     Explicitly use excitation records already in JSON
  --experiment-id <id>          Select an existing PR887 experiment, or name a new one
  --experiment-name <name>      Name a new experiment created from named flags
  --result-json <path>          Full circuit-json result (default: output/circuit-result.json)
  --result-id <id>              Optional result ID; reruns replace same experiment/frequency
  --field-format <gzip|json>    Embedded field encoding (default: gzip)
  --solver <palace|approximation> Default: palace; approximation has no frequency model
  --help, -h / --version, -v

Omitted reference terminals use bottom ground directly beneath the signal.
Without a stackup, named top references require concentric ground vias. With a
stackup, references need real copper paths to the sampled layer. Source/load must be endpoints of one continuous trace. Multilayer routes need physical vias
and a fabrication stackup. The approximation remains two-layer only. No voltage source, signal
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
  "source-reference": { type: "string" },
  "load-reference": { type: "string" },
  "source-impedance": { type: "string" },
  "load-impedance": { type: "string" },
  "ports-file": { type: "string" },
  excitation: { type: "string", multiple: true },
  "frequency-hz": { type: "string" },
  output: { type: "string", short: "o" },
  solver: { type: "string" },
  "cell-size": { type: "string" },
  "image-size": { type: "string" },
  "stackup-file": { type: "string" },
  "sample-layer": { type: "string" },
  "via-clearance": { type: "string" },
  "mesh-size": { type: "string" },
  order: { type: "string" },
  "air-padding": { type: "string" },
  processes: { type: "string" },
  python: { type: "string" },
  "palace-bin": { type: "string" },
  directory: { type: "string" },
  "prepare-only": { type: "boolean" },
  "use-circuit-excitations": { type: "boolean" },
  "experiment-id": { type: "string" },
  "experiment-name": { type: "string" },
  "result-json": { type: "string" },
  "result-id": { type: "string" },
  "field-format": { type: "string" },
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
  let circuitJson = await inputCircuit(command)
  const namedFlags =
    values.source !== undefined ||
    values.load !== undefined ||
    values.current !== undefined ||
    values.ground !== undefined ||
    values.excitation !== undefined ||
    values["ports-file"] !== undefined ||
    values["source-reference"] !== undefined ||
    values["load-reference"] !== undefined ||
    values["source-impedance"] !== undefined ||
    values["load-impedance"] !== undefined
  let ports: NamedExcitation[] | undefined
  const officialInput =
    !namedFlags &&
    circuitJson.some(
      (e) =>
        e.type === "simulation_experiment" &&
        e.experiment_type === "pcb_return_current",
    )
  if (values["use-circuit-excitations"] || officialInput) {
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
    const advanced = {
      ...(values["source-reference"] === undefined
        ? {}
        : { sourceReference: values["source-reference"] }),
      ...(values["load-reference"] === undefined
        ? {}
        : { loadReference: values["load-reference"] }),
      ...(values["source-impedance"] === undefined
        ? {}
        : { sourceImpedance: parseResistanceOhms(values["source-impedance"]) }),
      ...(values["load-impedance"] === undefined
        ? {}
        : { loadImpedance: parseResistanceOhms(values["load-impedance"]) }),
    }
    if (values["ports-file"]) {
      if (
        values.excitation ||
        values.source ||
        values.load ||
        values.current !== undefined ||
        Object.keys(advanced).length
      )
        throw new Error(
          "Choose --ports-file or individual excitation/port flags",
        )
      const quantity = z.union([z.number(), z.string()])
      ports = z
        .array(
          z
            .object({
              source: z.string(),
              load: z.string(),
              current: quantity,
              sourceReference: z.string().optional(),
              loadReference: z.string().optional(),
              sourceImpedance: quantity.optional(),
              loadImpedance: quantity.optional(),
            })
            .strict(),
        )
        .min(1)
        .parse(
          JSON.parse(await readFile(resolve(values["ports-file"]), "utf8")),
        )
        .map((port) => ({
          ...port,
          current: parseCurrentAmps(port.current),
          ...(port.sourceImpedance === undefined
            ? {}
            : { sourceImpedance: parseResistanceOhms(port.sourceImpedance) }),
          ...(port.loadImpedance === undefined
            ? {}
            : { loadImpedance: parseResistanceOhms(port.loadImpedance) }),
        }))
    } else if (values.excitation) {
      if (
        values.source !== undefined ||
        values.load !== undefined ||
        values.current !== undefined
      )
        throw new Error("Choose --excitation or --source/--load/--current")
      ports = values.excitation.map((value) => {
        const fields = value.split(",").map((field) => field.trim())
        if (![3, 5].includes(fields.length) || fields.some((field) => !field))
          throw new Error(
            "Each --excitation must be source,load,current or source,sourceReference,load,loadReference,current",
          )
        if (values["source-reference"] || values["load-reference"])
          throw new Error(
            "Put reference pins inside each --excitation or use --ports-file",
          )
        return fields.length === 3
          ? {
              ...advanced,
              source: fields[0],
              load: fields[1],
              current: parseCurrentAmps(fields[2]),
            }
          : {
              ...advanced,
              source: fields[0],
              sourceReference: fields[1],
              load: fields[2],
              loadReference: fields[3],
              current: parseCurrentAmps(fields[4]),
            }
      })
    } else {
      if (!values.source || !values.load || values.current === undefined)
        throw new Error(
          "Specify --source R1.pin1 --load U1.VDDIO1 --current 1 --ground GND",
        )
      ports = [
        {
          ...advanced,
          source: values.source,
          load: values.load,
          current: parseCurrentAmps(values.current),
        },
      ]
    }
  }
  const outputDirectory = resolve(values.output ?? "return-current")
  const imageSize = imageDimension(number("image-size", 1100))
  const fieldFormat = values["field-format"] ?? "gzip"
  if (fieldFormat !== "gzip" && fieldFormat !== "json")
    throw new Error("--field-format must be gzip or json")
  if (ports)
    circuitJson = createReturnCurrentExperiment({
      circuitJson,
      ports,
      groundNet: values.ground!,
      experimentId: values["experiment-id"],
      name: values["experiment-name"],
      referenceLayer: values["sample-layer"]
        ? parseCopperLayer(values["sample-layer"])
        : undefined,
    })
  const createdExperimentId = ports
    ? circuitJson.findLast(
        (e) =>
          e.type === "simulation_experiment" &&
          e.experiment_type === "pcb_return_current",
      )
    : undefined
  const selected =
    ports || officialInput
      ? selectReturnCurrentExperiment({
          circuitJson,
          experimentId:
            values["experiment-id"] ??
            (createdExperimentId?.type === "simulation_experiment"
              ? createdExperimentId.simulation_experiment_id
              : undefined),
        })
      : undefined
  if (!ports && values["experiment-name"])
    throw new Error(
      "--experiment-name is only used when creating a new experiment from named flags",
    )
  if (
    !selected &&
    (values["experiment-id"] || values["result-json"] || values["result-id"])
  )
    throw new Error(
      "Circuit-json results require an official pcb_return_current experiment; use named flags to create one",
    )
  const resultPath = resolve(
    values["result-json"] ?? join(outputDirectory, "circuit-result.json"),
  )
  const saveResult = async (
    simulation: Parameters<
      typeof exportReturnCurrentCircuitJson
    >[0]["simulation"],
  ) => {
    if (!selected) return
    const result = exportReturnCurrentCircuitJson({
      circuitJson,
      experimentId: selected.experiment.simulation_experiment_id,
      resultId: values["result-id"],
      simulation,
      fieldFormat,
    })
    await mkdir(resolve(resultPath, ".."), { recursive: true })
    await writeFile(resultPath, JSON.stringify(result, null, 2))
    console.log(`Circuit-json simulation result: ${resultPath}`)
  }
  if (solver === "approximation") {
    if (
      ports?.some(
        (port) =>
          port.sourceReference ||
          port.loadReference ||
          port.sourceImpedance !== undefined ||
          port.loadImpedance !== undefined,
      ) ||
      (selected?.excitations ?? circuitJson).some(
        (element) =>
          element.type === "simulation_return_current_excitation" &&
          (element.source_port?.reference_pcb_port_id ||
            element.load_port?.reference_pcb_port_id ||
            (element.source_port && element.source_port.resistance !== 50) ||
            (element.load_port && element.load_port.resistance !== 50)),
      )
    )
      throw new Error(
        "Explicit reference terminals and impedances require --solver palace",
      )
    for (const flag of [
      "stackup-file",
      "sample-layer",
      "via-clearance",
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
    const input = selected?.solverCircuitJson ?? circuitJson
    const result = simulateReturnCurrent({
      circuitJson: input,
      excitations: selected?.excitations,
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
    await saveResult(result)
    return
  }
  const order = number("order", 2)
  if (order !== 1 && order !== 2) throw new Error("order must be 1 or 2")
  const options: PalaceSimulationOptions = {
    circuitJson: selected?.solverCircuitJson ?? circuitJson,
    stackup: values["stackup-file"]
      ? parseFabricationStackup(
          JSON.parse(await readFile(resolve(values["stackup-file"]), "utf8")),
        )
      : undefined,
    sampleLayer: values["sample-layer"]
      ? parseCopperLayer(values["sample-layer"])
      : undefined,
    viaClearance: number("via-clearance"),
    excitations: selected?.excitations,
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
    if (selected) {
      await writeFile(
        join(outputDirectory, "circuit-definition.json"),
        JSON.stringify(circuitJson, null, 2),
      )
      if (values["result-json"]) {
        await mkdir(resolve(resultPath, ".."), { recursive: true })
        await writeFile(resultPath, JSON.stringify(circuitJson, null, 2))
      }
    }
    console.log(
      `Prepared ${prepared.model.frequencyHz} Hz Palace input at ${prepared.destination}; no EM solve performed`,
    )
  } else {
    console.log(JSON.stringify(await runPalaceSimulation(options), null, 2))
    await saveResult({
      model: JSON.parse(
        await readFile(join(outputDirectory, "model.json"), "utf8"),
      ) as PalaceModel,
      reference: JSON.parse(
        await readFile(join(outputDirectory, "reference.json"), "utf8"),
      ) as PalaceReference,
    })
  }
}

main().catch((error: unknown) => {
  console.error(
    `simulate-return-current: ${error instanceof Error ? error.message : String(error)}`,
  )
  process.exitCode = 1
})
