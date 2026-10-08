import {
  simulation_experiment,
  simulation_return_current_excitation,
  type SimulationExperiment,
  type SimulationReturnCurrentExcitation as OfficialExcitation,
  type SimulationReturnCurrentContact,
  type PcbTrace,
} from "circuit-json"
import { withNamedExcitations, type NamedExcitation } from "./named-ports"
import type { ReturnCurrentCircuitJson } from "./types"
import type { CopperLayer } from "./palace/stackup"
import { pourRegion } from "./read-geometry"
import { pointInPolygon } from "./geometry"
import { portNetIds } from "./port-connectivity"
import { normalizeLayeredRoute } from "./palace/normalize-layered-route"

const id = (prefix: string) => `${prefix}_${globalThis.crypto.randomUUID()}`

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
