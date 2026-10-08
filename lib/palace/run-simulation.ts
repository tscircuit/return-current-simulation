import { writeFile } from "node:fs/promises"
import { resolve, join } from "node:path"
import { withNamedExcitations, type NamedExcitation } from "../named-ports"
import { preparePalaceCase, runPalaceCase } from "./run-case"
import { writePalaceImage } from "./write-palace-image"
import type { PalaceOptions } from "./types"
import { parseCurrentAmps, parseResistanceOhms } from "../electrical-units"
import { readJson } from "./read-json"
import type { PalaceModel } from "./types"

export interface PalaceSimulationOptions extends PalaceOptions {
  outputDirectory: string
  groundNet?: string
  ports?: readonly NamedExcitation[]
  cellSize?: number
  imageSize?: number
  python?: string
  palaceBin?: string
  processes?: number
}

export function imageDimension(size = 1100): number {
  if (!Number.isInteger(size) || size < 300 || size > 8192)
    throw new Error("imageSize must be an integer between 300 and 8192 pixels")
  return size
}

function caseOptions(options: PalaceSimulationOptions) {
  imageDimension(options.imageSize)
  if (options.ports && !options.groundNet)
    throw new Error("Named ports require groundNet")
  if (options.groundNet && !options.ports)
    throw new Error("groundNet requires named ports")
  if (options.ports && options.excitations)
    throw new Error("Choose named ports or explicit excitation records")
  const circuitJson = options.ports
    ? withNamedExcitations({
        circuitJson: options.circuitJson,
        ports: options.ports.map((port) => ({
          ...port,
          sourceImpedance: port.sourceImpedance ?? options.portResistance ?? 50,
          loadImpedance: port.loadImpedance ?? options.portResistance ?? 50,
        })),
        groundNet: options.groundNet!,
        referenceLayer: options.sampleLayer,
      })
    : options.excitations
      ? [
          ...options.circuitJson.filter(
            (element) =>
              element.type !== "simulation_return_current_excitation",
          ),
          ...options.excitations,
        ]
      : options.circuitJson
  return {
    ...options,
    circuitJson,
    excitations: undefined,
    destination: resolve(options.outputDirectory),
  }
}

async function writePortSpecification(
  options: PalaceSimulationOptions,
  destination: string,
) {
  const model: PalaceModel = await readJson(join(destination, "model.json"))
  await writeFile(
    join(destination, "excitation-ports.json"),
    JSON.stringify(
      {
        frequencyHz: options.frequencyHz,
        copperModel: model.copperModel,
        ...(model.surfaceImpedance
          ? { surfaceImpedance: model.surfaceImpedance }
          : {}),
        ports:
          options.ports?.map((port) => ({
            ...port,
            current: parseCurrentAmps(port.current),
            ...(port.sourceImpedance === undefined
              ? {}
              : { sourceImpedance: parseResistanceOhms(port.sourceImpedance) }),
            ...(port.loadImpedance === undefined
              ? {}
              : { loadImpedance: parseResistanceOhms(port.loadImpedance) }),
          })) ?? null,
        groundNet: options.groundNet ?? null,
        resolvedTerminals: model.ports,
        metadataSource: options.ports ? "named_ports" : "circuit_json",
        reference: model.ports?.some((port) => port.referencePcbPortId)
          ? "explicit reference pins; omitted references use plane beneath signal"
          : "ground plane directly beneath each signal endpoint",
        currentConvention: "signed in-phase peak amperes",
      },
      null,
      2,
    ),
  )
}

/** Resolve ports and validate/save the model without invoking an external solver. */
export async function preparePalaceSimulation(
  options: PalaceSimulationOptions,
) {
  const prepared = await preparePalaceCase(caseOptions(options))
  await writePortSpecification(options, prepared.destination)
  return prepared
}

/** Run Palace and export its sampled field directly; no approximation is run. */
export async function runPalaceSimulation(options: PalaceSimulationOptions) {
  const startedAt = new Date().toISOString()
  const started = performance.now()
  const resolved = caseOptions(options)
  await runPalaceCase(resolved)
  await writePortSpecification(options, resolved.destination)
  const image = await writePalaceImage(
    resolved.destination,
    imageDimension(options.imageSize),
  )
  const timing = {
    startedAt,
    completedAt: new Date().toISOString(),
    frequencyHz: options.frequencyHz,
    copperModel: options.copperModel ?? "volumetric_copper",
    totalSeconds: (performance.now() - started) / 1000,
    reusedCompletedFemSolve: false,
    image,
  }
  await writeFile(
    join(resolved.destination, "run-timing.json"),
    JSON.stringify(timing, null, 2),
  )
  return {
    outputDirectory: resolved.destination,
    referencePath: join(resolved.destination, "reference.json"),
    svgPath: join(resolved.destination, "palace.svg"),
    pngPath: join(resolved.destination, "palace.png"),
    timing,
  }
}
