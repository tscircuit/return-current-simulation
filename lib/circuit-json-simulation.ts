import { randomUUID } from "node:crypto"
import { gzipSync } from "node:zlib"
import { Resvg } from "@resvg/resvg-js"
import {
  simulation_experiment,
  simulation_return_current_excitation,
  simulation_pcb_return_current_result,
  simulation_pcb_return_current_field,
  simulation_pcb_return_current_heatmap,
  simulation_pcb_return_current_marker,
  getSimulationReturnCurrentGridJsonSchema,
  type SimulationExperiment,
  type SimulationReturnCurrentExcitation as OfficialExcitation,
  type SimulationReturnCurrentContact,
  type SimulationReturnCurrentGridJson,
  type SimulationPcbReturnCurrentField,
  type SimulationPcbReturnCurrentMarker,
  type PcbTrace,
} from "circuit-json"
import { withNamedExcitations, type NamedExcitation } from "./named-ports"
import type { ReturnCurrentCircuitJson, SimulationResult } from "./types"
import type { PalaceModel, PalaceReference } from "./palace/types"
import type { CopperLayer } from "./palace/stackup"
import { pourRegion, readGeometry } from "./read-geometry"
import { pointInPolygon } from "./geometry"
import { portNetIds } from "./port-connectivity"
import { validatePalaceReference } from "./palace/validate-reference"
import { currentColor } from "./current-color"
import { palaceGeometrySignature } from "./palace/geometry-signature"
import { createPalaceModel } from "./palace/create-palace-model"
import { createSampleMask } from "./palace/create-sample-mask"
import { normalizeLayeredRoute } from "./palace/normalize-layered-route"

function fabricationStackup(model: PalaceModel) {
  if (!model.multilayer) return undefined
  const stackup = model.multilayer.stackup
  return {
    nominalBoardThicknessMm: stackup.nominalBoardThicknessMm,
    layers: [
      ...stackup.copperLayers.map((foil) => ({
        z: foil.zMax,
        value: { name: foil.name, copperThicknessMm: foil.zMax - foil.zMin },
      })),
      ...stackup.dielectrics.map((d) => ({
        z: d.zMax,
        value: {
          material: d.material,
          dielectricThicknessMm: d.zMax - d.zMin,
          dielectricConstant: d.dielectricConstant,
          lossTangent: d.lossTangent,
        },
      })),
    ]
      .sort((a, b) => b.z - a.z)
      .map((l) => l.value),
  }
}

const id = (prefix: string) => `${prefix}_${randomUUID()}`

function assertUniqueIds(circuitJson: ReturnCurrentCircuitJson) {
  const ids = new Set<string>()
  for (const element of circuitJson) {
    const key = `${element.type}_id`
    const value = (element as unknown as Record<string, unknown>)[key]
    if (typeof value !== "string") continue
    if (ids.has(value)) throw new Error(`Duplicate circuit-json ID: ${value}`)
    ids.add(value)
  }
}

function pourContact(
  circuitJson: ReturnCurrentCircuitJson,
  point: { x: number; y: number },
  layer: CopperLayer,
  groundNetId: string,
): SimulationReturnCurrentContact {
  const pours = circuitJson.filter((e) => {
    if (
      e.type !== "pcb_copper_pour" ||
      e.layer !== layer ||
      e.source_net_id !== groundNetId
    )
      return false
    const region = pourRegion(e)
    return (
      pointInPolygon(point, region.outer) &&
      !region.holes.some((h) => pointInPolygon(point, h))
    )
  })
  if (!pours.length || pours[0].type !== "pcb_copper_pour")
    throw new Error(
      `Return contact at (${point.x}, ${point.y}) on ${layer} needs an identified ground PCB port, via, or copper pour; legacy ground-plane regions cannot identify a PR887 contact`,
    )
  // Overlapping pours on the same net are electrically the same conductor.
  return {
    ...point,
    layer,
    contact_type: "pcb_copper_pour",
    pcb_copper_pour_id: pours[0].pcb_copper_pour_id,
  }
}

/** Build official experiment/excitation definitions from existing named flags.
 * No frequency or electrical amplitude is guessed. A plane-beneath reference
 * is identified as a copper pour, never mislabeled as a PCB ground pad.
 */
export function createReturnCurrentExperiment(options: {
  circuitJson: ReturnCurrentCircuitJson
  ports: readonly NamedExcitation[]
  groundNet: string
  experimentId?: string
  name?: string
  referenceLayer?: CopperLayer
}): ReturnCurrentCircuitJson {
  assertUniqueIds(options.circuitJson)
  const experimentId = options.experimentId ?? id("simulation_experiment")
  if (
    options.circuitJson.some(
      (e) =>
        e.type === "simulation_experiment" &&
        e.simulation_experiment_id === experimentId,
    )
  )
    throw new Error(
      `Experiment ${experimentId} already exists; select it without named flags or choose a new ID`,
    )
  const generated = withNamedExcitations(options)
  const official = generated
    .filter((e) => e.type === "simulation_return_current_excitation")
    .map((e) => {
      const contact = (
        point: { x: number; y: number },
        terminal: typeof e.source_port,
      ): SimulationReturnCurrentContact =>
        terminal?.reference_pcb_port_id
          ? {
              ...point,
              layer: terminal.reference_layer,
              contact_type: "pcb_port",
              pcb_port_id: terminal.reference_pcb_port_id,
            }
          : pourContact(
              generated,
              point,
              terminal?.reference_layer ?? options.referenceLayer ?? "bottom",
              e.ground_source_net_id,
            )
      return simulation_return_current_excitation.parse({
        ...e,
        simulation_return_current_excitation_id: id(
          "simulation_return_current_excitation",
        ),
        simulation_experiment_id: experimentId,
        return_source: contact(e.return_source, e.load_port),
        return_sink: contact(e.return_sink, e.source_port),
      })
    })
  const experiment = simulation_experiment.parse({
    type: "simulation_experiment",
    simulation_experiment_id: experimentId,
    name: options.name ?? "PCB return current",
    experiment_type: "pcb_return_current",
  })
  // Keep the original PCB route ordering. The selected solver view is oriented
  // independently, so adding another experiment cannot invalidate old ones.
  return [...options.circuitJson, experiment, ...official]
}

function validateContact(
  circuitJson: ReturnCurrentCircuitJson,
  contact: SimulationReturnCurrentContact,
  groundId: string,
) {
  if (contact.contact_type === "pcb_port") {
    const port = circuitJson.find(
      (e) => e.type === "pcb_port" && e.pcb_port_id === contact.pcb_port_id,
    )
    if (
      !port ||
      port.type !== "pcb_port" ||
      !port.layers.includes(contact.layer) ||
      Math.hypot(port.x - contact.x, port.y - contact.y) > 1e-6
    )
      throw new Error(
        `Return PCB port ${contact.pcb_port_id} does not match contact location/layer`,
      )
    if (!portNetIds(circuitJson, port.source_port_id).includes(groundId))
      throw new Error(
        `Return PCB port ${contact.pcb_port_id} is not on the selected ground net`,
      )
  } else if (contact.contact_type === "pcb_via") {
    const via = circuitJson.find(
      (e) => e.type === "pcb_via" && e.pcb_via_id === contact.pcb_via_id,
    )
    if (
      !via ||
      via.type !== "pcb_via" ||
      !via.layers.includes(contact.layer) ||
      Math.hypot(via.x - contact.x, via.y - contact.y) > 1e-6
    )
      throw new Error(
        `Return PCB via ${contact.pcb_via_id} does not match contact location/layer`,
      )
    if (via.source_net_id !== groundId)
      throw new Error(
        `Return PCB via ${contact.pcb_via_id} needs explicit selected-ground ownership`,
      )
  } else {
    const pour = circuitJson.find(
      (e) =>
        e.type === "pcb_copper_pour" &&
        e.pcb_copper_pour_id === contact.pcb_copper_pour_id,
    )
    if (
      !pour ||
      pour.type !== "pcb_copper_pour" ||
      pour.layer !== contact.layer ||
      pour.source_net_id !== groundId
    )
      throw new Error(
        `Return copper pour ${contact.pcb_copper_pour_id} is missing or not on the selected ground/layer`,
      )
    const region = pourRegion(pour)
    if (
      !pointInPolygon(contact, region.outer) ||
      region.holes.some((h) => pointInPolygon(contact, h))
    )
      throw new Error(
        `Return contact is outside copper pour ${contact.pcb_copper_pour_id}`,
      )
  }
}

/** Select one pending (or rerunnable) official experiment, validating links. */
export function selectReturnCurrentExperiment(options: {
  circuitJson: ReturnCurrentCircuitJson
  experimentId?: string
}): {
  experiment: SimulationExperiment
  excitations: OfficialExcitation[]
  /** PCB unchanged except normalized routes oriented driver → load. */
  solverCircuitJson: ReturnCurrentCircuitJson
} {
  const { circuitJson } = options
  assertUniqueIds(circuitJson)
  if (circuitJson.filter((e) => e.type === "pcb_board").length !== 1)
    throw new Error("Exactly one PCB board is required")
  const experiments = circuitJson.filter(
    (e) =>
      e.type === "simulation_experiment" &&
      e.experiment_type === "pcb_return_current" &&
      (!options.experimentId ||
        e.simulation_experiment_id === options.experimentId),
  )
  if (
    experiments.length !== 1 ||
    experiments[0].type !== "simulation_experiment"
  )
    throw new Error(
      `Select exactly one pcb_return_current experiment with --experiment-id; found ${experiments.length}`,
    )
  const experiment = simulation_experiment.parse(experiments[0])
  const excitations = circuitJson
    .filter(
      (e) =>
        e.type === "simulation_return_current_excitation" &&
        e.simulation_experiment_id === experiment.simulation_experiment_id,
    )
    .map((e) => simulation_return_current_excitation.parse(e))
  if (!excitations.length)
    throw new Error(
      `Experiment ${experiment.simulation_experiment_id} has no excitations`,
    )
  if (new Set(excitations.map((e) => e.ground_source_net_id)).size !== 1)
    throw new Error("Selected excitations must share one ground net")
  if (
    new Set(excitations.map((e) => e.pcb_trace_id)).size !== excitations.length
  )
    throw new Error(
      "Selected excitations must reference distinct signal traces",
    )
  const oriented = new Map<string, PcbTrace>()
  for (const excitation of excitations) {
    const originalTrace = circuitJson.find(
      (e) =>
        e.type === "pcb_trace" && e.pcb_trace_id === excitation.pcb_trace_id,
    )
    if (!originalTrace || originalTrace.type !== "pcb_trace")
      throw new Error(`Missing signal trace ${excitation.pcb_trace_id}`)
    let trace = normalizeLayeredRoute(originalTrace)
    if (excitation.source_port) {
      const sourcePort = circuitJson.find(
        (e) =>
          e.type === "pcb_port" &&
          e.pcb_port_id === excitation.source_port!.signal_pcb_port_id,
      )
      const first = trace.route[0],
        last = trace.route.at(-1)
      if (
        sourcePort?.type === "pcb_port" &&
        last?.route_type === "wire" &&
        Math.hypot(sourcePort.x - last.x, sourcePort.y - last.y) < 1e-6 &&
        !(
          first?.route_type === "wire" &&
          Math.hypot(sourcePort.x - first.x, sourcePort.y - first.y) < 1e-6
        )
      )
        trace = {
          ...trace,
          route: trace.route
            .map((point, index) => {
              if (point.route_type === "via")
                return {
                  ...point,
                  from_layer: point.to_layer,
                  to_layer: point.from_layer,
                }
              if (point.route_type !== "wire") return point
              const previous = trace.route[Math.max(0, index - 1)]
              return {
                ...point,
                width:
                  previous.route_type === "wire" ? previous.width : point.width,
                start_pcb_port_id: point.end_pcb_port_id,
                end_pcb_port_id: point.start_pcb_port_id,
              }
            })
            .reverse(),
        }
    }
    oriented.set(trace.pcb_trace_id, trace)
    if (
      !circuitJson.some(
        (e) =>
          e.type === "source_net" &&
          e.source_net_id === excitation.ground_source_net_id,
      )
    )
      throw new Error(`Missing ground net ${excitation.ground_source_net_id}`)
    validateContact(
      circuitJson,
      excitation.return_source,
      excitation.ground_source_net_id,
    )
    validateContact(
      circuitJson,
      excitation.return_sink,
      excitation.ground_source_net_id,
    )
    for (const [terminal, contact, endpoint] of [
      [excitation.source_port, excitation.return_sink, trace.route[0]],
      [excitation.load_port, excitation.return_source, trace.route.at(-1)],
    ] as const) {
      if (!terminal) {
        if (contact.contact_type === "pcb_port" || contact.layer !== "bottom")
          throw new Error(
            "An identified return PCB port or non-bottom reference requires explicit source_port/load_port terminal metadata",
          )
        continue
      }
      if (
        contact.contact_type === "pcb_port" &&
        terminal.reference_pcb_port_id !== contact.pcb_port_id
      )
        throw new Error(
          "A PCB-port return contact requires its matching reference_pcb_port_id",
        )
      if (
        terminal.reference_layer !== contact.layer ||
        (terminal.reference_pcb_port_id !== undefined &&
          (contact.contact_type !== "pcb_port" ||
            terminal.reference_pcb_port_id !== contact.pcb_port_id))
      )
        throw new Error(
          "Terminal reference must match the identified return contact",
        )
      const port = circuitJson.find(
        (e) =>
          e.type === "pcb_port" &&
          e.pcb_port_id === terminal.signal_pcb_port_id,
      )
      if (
        !port ||
        port.type !== "pcb_port" ||
        endpoint?.route_type !== "wire" ||
        !port.layers.includes(endpoint.layer) ||
        Math.hypot(port.x - endpoint.x, port.y - endpoint.y) > 1e-6
      )
        throw new Error(
          "Signal terminal must match the source/load trace endpoint",
        )
      if (terminal.signal_pcb_port_id === terminal.reference_pcb_port_id)
        throw new Error(
          "Signal and reference terminals must be different ports",
        )
    }
    // Offset top-side via contacts cannot be represented by the existing
    // Palace terminal geometry without a real reference PCB port.
    if (
      [excitation.return_source, excitation.return_sink].some(
        (c) => c.contact_type === "pcb_via",
      )
    )
      throw new Error(
        "Via return contacts are not supported by the current solver adapter; use a PCB port or copper-pour contact",
      )
  }
  return {
    experiment,
    excitations,
    solverCircuitJson: circuitJson.map((e) =>
      e.type === "pcb_trace" ? (oriented.get(e.pcb_trace_id) ?? e) : e,
    ),
  }
}

function markersFor(
  circuitJson: ReturnCurrentCircuitJson,
  excitations: OfficialExcitation[],
  resultId: string,
): SimulationPcbReturnCurrentMarker[] {
  const markers: SimulationPcbReturnCurrentMarker[] = []
  const portMarker = (
    role: "signal_source" | "signal_load" | "return_source" | "return_sink",
    portId: string,
    layer: CopperLayer,
  ) => {
    markers.push(
      simulation_pcb_return_current_marker.parse({
        type: "simulation_pcb_return_current_marker",
        simulation_pcb_return_current_marker_id: id(
          "simulation_pcb_return_current_marker",
        ),
        simulation_pcb_return_current_result_id: resultId,
        role,
        target_type: "pcb_port",
        pcb_port_id: portId,
        layer,
        label: role.replaceAll("_", " "),
      }),
    )
  }
  for (const excitation of excitations) {
    const trace = circuitJson.find(
      (e): e is PcbTrace =>
        e.type === "pcb_trace" && e.pcb_trace_id === excitation.pcb_trace_id,
    )!
    for (const [role, terminal, endpoint] of [
      ["signal_source", excitation.source_port, trace.route[0]],
      ["signal_load", excitation.load_port, trace.route.at(-1)],
    ] as const)
      if (terminal && endpoint?.route_type === "wire")
        portMarker(
          role,
          terminal.signal_pcb_port_id,
          endpoint.layer as CopperLayer,
        )
    for (const [role, contact] of [
      ["return_source", excitation.return_source],
      ["return_sink", excitation.return_sink],
    ] as const)
      if (contact.contact_type === "pcb_port")
        portMarker(role, contact.pcb_port_id, contact.layer as CopperLayer)
    for (const point of trace.route) {
      if (point.route_type !== "via") continue
      const via = circuitJson.find(
        (e) =>
          e.type === "pcb_via" &&
          Math.hypot(e.x - point.x, e.y - point.y) < 1e-6 &&
          e.pcb_trace_id === trace.pcb_trace_id &&
          e.layers.includes(point.from_layer) &&
          e.layers.includes(point.to_layer),
      )
      if (!via || via.type !== "pcb_via") continue
      markers.push(
        simulation_pcb_return_current_marker.parse({
          type: "simulation_pcb_return_current_marker",
          simulation_pcb_return_current_marker_id: id(
            "simulation_pcb_return_current_marker",
          ),
          simulation_pcb_return_current_result_id: resultId,
          role: "signal_transition",
          target_type: "pcb_via",
          pcb_via_id: via.pcb_via_id,
          from_layer: point.from_layer,
          to_layer: point.to_layer,
          label: `signal via: ${point.from_layer} ↔ ${point.to_layer}`,
        }),
      )
    }
  }
  return markers
}

/** Export actual sampled values to official circuit-json, retaining every
 * original board/definition element. Reruns replace only results at this
 * experiment + frequency, and their field/heatmap/marker descendants.
 */
export function exportReturnCurrentCircuitJson(options: {
  circuitJson: ReturnCurrentCircuitJson
  experimentId: string
  resultId?: string
  simulation:
    | SimulationResult
    | { model: PalaceModel; reference: PalaceReference }
  fieldFormat?: "gzip" | "json"
}): ReturnCurrentCircuitJson {
  const selected = selectReturnCurrentExperiment(options)
  const backendExcitations =
    "reference" in options.simulation
      ? options.simulation.model.geometry.excitations
      : options.simulation.geometry.excitations
  if (
    backendExcitations.length !== selected.excitations.length ||
    backendExcitations.some(
      (e, i) =>
        JSON.stringify(simulation_return_current_excitation.parse(e)) !==
        JSON.stringify(selected.excitations[i]),
    )
  )
    throw new Error(
      "Result is stale: selected excitation current, contacts, or terminal metadata changed",
    )
  const resultId =
    options.resultId ?? id("simulation_pcb_return_current_result")
  const frequencyHz =
    "reference" in options.simulation
      ? options.simulation.reference.frequencyHz
      : undefined
  const oldIds = new Set(
    options.circuitJson.flatMap((e) =>
      e.type === "simulation_pcb_return_current_result" &&
      e.simulation_experiment_id === options.experimentId &&
      e.frequency_hz === frequencyHz
        ? [e.simulation_pcb_return_current_result_id]
        : [],
    ),
  )
  if (
    options.circuitJson.some(
      (e) =>
        e.type === "simulation_pcb_return_current_result" &&
        e.simulation_pcb_return_current_result_id === resultId &&
        !oldIds.has(resultId),
    )
  )
    throw new Error(
      `Result ID ${resultId} belongs to another experiment/frequency`,
    )
  const circuitJson = options.circuitJson.filter((e) =>
    e.type === "simulation_pcb_return_current_result"
      ? !oldIds.has(e.simulation_pcb_return_current_result_id)
      : "simulation_pcb_return_current_result_id" in e
        ? !oldIds.has(String(e.simulation_pcb_return_current_result_id))
        : true,
  )
  const board = circuitJson.find((e) => e.type === "pcb_board")!
  if (board.type !== "pcb_board") throw new Error("Missing PCB board")
  const fieldId = id("simulation_pcb_return_current_field")
  let grid: SimulationReturnCurrentGridJson
  let metadata: Omit<
    SimulationPcbReturnCurrentField,
    | "field_asset"
    | "type"
    | "simulation_pcb_return_current_field_id"
    | "simulation_pcb_return_current_result_id"
    | "data_format"
  >
  if ("reference" in options.simulation) {
    const { model, reference } = options.simulation
    validatePalaceReference(reference)
    if (reference.columns * reference.rows > 1_000_000)
      throw new Error("The result grid exceeds 1,000,000 cells")
    if (reference.frequencyHz !== model.frequencyHz)
      throw new Error("Palace model/reference frequencies differ")
    if (reference.copperThickness !== model.copperThickness)
      throw new Error("Palace model/reference copper thicknesses differ")
    if (
      model.geometry.excitations
        .map((e) => e.simulation_return_current_excitation_id)
        .join() !==
      selected.excitations
        .map((e) => e.simulation_return_current_excitation_id)
        .join()
    )
      throw new Error(
        "Palace model does not contain exactly the selected experiment excitations",
      )
    if (
      reference.provenance.geometrySignature !==
      palaceGeometrySignature(model.geometry)
    )
      throw new Error(
        "Palace reference provenance does not match its model geometry",
      )
    const expected = createPalaceModel({
      circuitJson: selected.solverCircuitJson,
      excitations: selected.excitations,
      frequencyHz: model.frequencyHz,
      stackup: fabricationStackup(model),
      sampleLayer: reference.sampleLayer ?? "bottom",
      viaClearance: model.multilayer?.viaClearance,
      ...(model.multilayer
        ? {}
        : {
            layerSeparation: model.layerSeparation,
            copperThickness: model.copperThickness,
          }),
      copperConductivity: model.copperConductivity,
      substratePermittivity: model.substratePermittivity,
      substrateLossTangent: model.substrateLossTangent,
      portResistance: model.portResistance,
      portWidth: model.portWidth,
      meshSize: model.meshSize,
      airPadding: model.airPadding,
      order: model.order,
    })
    if (
      palaceGeometrySignature(expected.geometry) !==
      palaceGeometrySignature(model.geometry)
    )
      throw new Error(
        "Palace result is stale: input geometry, current, contacts, or termination changed",
      )
    const minX = Math.min(...model.geometry.boardOutline.map((p) => p.x))
    const minY = Math.min(...model.geometry.boardOutline.map((p) => p.y))
    metadata = {
      layer: reference.sampleLayer ?? "bottom",
      source_net_id: selected.excitations[0].ground_source_net_id,
      field_type: "complex_phasor",
      min_x: minX,
      min_y: minY,
      columns: reference.columns,
      rows: reference.rows,
      cell_width: reference.cellWidth,
      cell_height: reference.cellHeight,
      copper_thickness: reference.copperThickness,
    }
    const blank = () =>
      Array<number | null>(reference.columns * reference.rows).fill(null)
    grid = {
      field_type: "complex_phasor",
      sheet_current_x_real: blank(),
      sheet_current_x_imag: blank(),
      sheet_current_y_real: blank(),
      sheet_current_y_imag: blank(),
    }
    const seen = new Set<number>()
    const containsCopper = createSampleMask(model.geometry)
    for (const sample of reference.samples) {
      const column = Math.round((sample.x - minX) / reference.cellWidth - 0.5)
      const row = Math.round((sample.y - minY) / reference.cellHeight - 0.5)
      if (
        column < 0 ||
        column >= reference.columns ||
        row < 0 ||
        row >= reference.rows ||
        Math.abs(sample.x - (minX + (column + 0.5) * reference.cellWidth)) >
          1e-6 ||
        Math.abs(sample.y - (minY + (row + 0.5) * reference.cellHeight)) > 1e-6
      )
        throw new Error("Palace sample is not aligned with its declared grid")
      const index = row * reference.columns + column
      if (!containsCopper(sample))
        throw new Error(
          "Palace sample lies outside the reference conductor mask",
        )
      if (seen.has(index)) throw new Error("Duplicate Palace grid cell")
      seen.add(index)
      grid.sheet_current_x_real[index] = sample.sheetCurrentXReal
      grid.sheet_current_x_imag[index] = sample.sheetCurrentXImag
      grid.sheet_current_y_real[index] = sample.sheetCurrentYReal
      grid.sheet_current_y_imag[index] = sample.sheetCurrentYImag
    }
    for (let row = 0; row < reference.rows; row++)
      for (let column = 0; column < reference.columns; column++)
        if (
          containsCopper({
            x: minX + (column + 0.5) * reference.cellWidth,
            y: minY + (row + 0.5) * reference.cellHeight,
          }) !== seen.has(row * reference.columns + column)
        )
          throw new Error(
            "Palace samples do not cover exactly the declared conductor mask",
          )
  } else {
    const result = options.simulation
    if (!result.diagnostics.converged)
      throw new Error("Cannot export an unconverged approximation")
    if (result.columns * result.rows > 1_000_000)
      throw new Error("The result grid exceeds 1,000,000 cells")
    if (
      result.geometry.excitations
        .map((e) => e.simulation_return_current_excitation_id)
        .join() !==
      selected.excitations
        .map((e) => e.simulation_return_current_excitation_id)
        .join()
    )
      throw new Error(
        "Approximation does not contain exactly the selected experiment excitations",
      )
    const expected = readGeometry({
      circuitJson: selected.solverCircuitJson,
      excitations: selected.excitations,
    })
    if (
      palaceGeometrySignature(expected) !==
      palaceGeometrySignature(result.geometry)
    )
      throw new Error(
        "Approximation result is stale: input geometry, current, contacts, or termination changed",
      )
    metadata = {
      layer: "bottom",
      source_net_id: selected.excitations[0].ground_source_net_id,
      field_type: "real",
      min_x: result.bounds.minX,
      min_y: result.bounds.minY,
      columns: result.columns,
      rows: result.rows,
      cell_width: result.cellWidth,
      cell_height: result.cellHeight,
      copper_thickness: result.copperThickness,
    }
    grid = {
      field_type: "real",
      sheet_current_x: Array<number | null>(result.columns * result.rows).fill(
        null,
      ),
      sheet_current_y: Array<number | null>(result.columns * result.rows).fill(
        null,
      ),
    }
    const seen = new Set<number>()
    for (const node of result.nodes) {
      const index = node.row * result.columns + node.column
      if (
        !Number.isInteger(node.column) ||
        !Number.isInteger(node.row) ||
        node.column < 0 ||
        node.column >= result.columns ||
        node.row < 0 ||
        node.row >= result.rows ||
        seen.has(index)
      )
        throw new Error("Invalid approximation grid node")
      seen.add(index)
      grid.sheet_current_x[index] = node.sheetCurrentX
      grid.sheet_current_y[index] = node.sheetCurrentY
    }
  }
  getSimulationReturnCurrentGridJsonSchema(metadata).parse(grid)
  const format = options.fieldFormat ?? "gzip"
  if (format !== "gzip" && format !== "json")
    throw new Error("fieldFormat must be gzip or json")
  const mime = format === "gzip" ? "application/gzip" : "application/json"
  const bytes = Buffer.from(JSON.stringify(grid))
  const assetBytes = format === "gzip" ? gzipSync(bytes) : bytes
  const field = simulation_pcb_return_current_field.parse({
    ...metadata,
    type: "simulation_pcb_return_current_field",
    simulation_pcb_return_current_field_id: fieldId,
    simulation_pcb_return_current_result_id: resultId,
    data_format: "simulation_return_current_grid_json_v1",
    field_asset: {
      project_relative_path: `simulation/${fieldId}.json${format === "gzip" ? ".gz" : ""}`,
      mimetype: mime,
      url: `data:${mime};base64,${assetBytes.toString("base64")}`,
    },
  })
  const maxX = metadata.min_x + metadata.columns * metadata.cell_width
  const maxY = metadata.min_y + metadata.rows * metadata.cell_height
  const magnitudes = Array.from(
    { length: metadata.columns * metadata.rows },
    (_, index) => {
      if (grid.field_type === "real")
        return grid.sheet_current_x[index] === null
          ? null
          : Math.hypot(
              grid.sheet_current_x[index]!,
              grid.sheet_current_y[index]!,
            ) / metadata.copper_thickness
      return grid.sheet_current_x_real[index] === null
        ? null
        : Math.hypot(
            grid.sheet_current_x_real[index]!,
            grid.sheet_current_x_imag[index]!,
            grid.sheet_current_y_real[index]!,
            grid.sheet_current_y_imag[index]!,
          ) / metadata.copper_thickness
    },
  )
  const maximum = magnitudes.reduce<number>(
    (max, value) => Math.max(max, value ?? 0),
    0,
  )
  const rectangles = magnitudes
    .flatMap((magnitude, index) =>
      magnitude === null
        ? []
        : [
            `<rect x="${index % metadata.columns}" y="${metadata.rows - 1 - Math.floor(index / metadata.columns)}" width="1" height="1" fill="${currentColor(maximum > 0 ? magnitude / maximum : 0)}"/>`,
          ],
    )
    .join("")
  // Raster is field-only, transparent in voids, with +Y-up grid reversed into
  // top-left image rows. Renderer can choose its own scale from the field data.
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${metadata.columns}" height="${metadata.rows}" viewBox="0 0 ${metadata.columns} ${metadata.rows}">${rectangles}</svg>`
  const png = new Resvg(svg).render().asPng()
  const heatmapId = id("simulation_pcb_return_current_heatmap")
  const heatmap = simulation_pcb_return_current_heatmap.parse({
    type: "simulation_pcb_return_current_heatmap",
    simulation_pcb_return_current_heatmap_id: heatmapId,
    simulation_pcb_return_current_result_id: resultId,
    layer: metadata.layer,
    source_net_id: metadata.source_net_id,
    min_x: metadata.min_x,
    min_y: metadata.min_y,
    max_x: maxX,
    max_y: maxY,
    image_asset: {
      project_relative_path: `simulation/${heatmapId}.png`,
      mimetype: "image/png",
      url: `data:image/png;base64,${Buffer.from(png).toString("base64")}`,
    },
  })
  const result = simulation_pcb_return_current_result.parse({
    type: "simulation_pcb_return_current_result",
    simulation_pcb_return_current_result_id: resultId,
    simulation_experiment_id: options.experimentId,
    pcb_board_id: board.pcb_board_id,
    simulation_return_current_excitation_ids: selected.excitations.map(
      (e) => e.simulation_return_current_excitation_id,
    ),
    ...(frequencyHz === undefined ? {} : { frequency_hz: frequencyHz }),
  })
  return [
    ...circuitJson,
    result,
    field,
    heatmap,
    ...markersFor(selected.solverCircuitJson, selected.excitations, resultId),
  ]
}
