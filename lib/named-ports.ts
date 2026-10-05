import type { PcbPort, PcbTrace, SourcePort } from "circuit-json"
import type {
  ReturnCurrentCircuitJson,
  SimulationReturnCurrentExcitation,
} from "./types"

export interface NamedExcitation {
  /** Signal driver, e.g. R1.pin1. */
  source: string
  /** Signal load, e.g. U1.VDDIO1. */
  load: string
  /** Signed, in-phase peak current in amperes. No amplitude is inferred. */
  current: number
}

function aliases(port: SourcePort): string[] {
  return [
    ...new Set([
      port.name,
      ...(port.port_hints ?? []),
      ...(port.pin_number === undefined
        ? []
        : [`pin${port.pin_number}`, String(port.pin_number)]),
    ]),
  ]
}

/** List circuit-json pin names/aliases and their PCB locations. */
export function listCircuitPorts(circuitJson: ReturnCurrentCircuitJson) {
  return circuitJson.flatMap((port) => {
    if (port.type !== "source_port") return []
    const component = circuitJson.find(
      (element) =>
        element.type === "source_component" &&
        element.source_component_id === port.source_component_id,
    )
    if (!component || component.type !== "source_component") return []
    return circuitJson.flatMap((pcb) =>
      pcb.type === "pcb_port" && pcb.source_port_id === port.source_port_id
        ? [
            {
              selector: `${component.name}.${port.name}`,
              aliases: aliases(port).map(
                (alias) => `${component.name}.${alias}`,
              ),
              sourcePortId: port.source_port_id,
              pcbPortId: pcb.pcb_port_id,
              x: pcb.x,
              y: pcb.y,
              layers: pcb.layers,
            },
          ]
        : [],
    )
  })
}

function resolvePort(
  circuitJson: ReturnCurrentCircuitJson,
  selector: string,
): { source: SourcePort; pcb: PcbPort } {
  const match = /^([^\.\s]+)\.([^\.\s]+)$/.exec(selector)
  if (!match)
    throw new Error(
      `Port "${selector}" must use refdes.pin syntax, e.g. R1.pin1 or U1.VDDIO1`,
    )
  const components = circuitJson.filter(
    (element) =>
      element.type === "source_component" && element.name === match[1],
  )
  if (components.length !== 1 || components[0].type !== "source_component")
    throw new Error(
      `Component "${match[1]}" is ${components.length ? "ambiguous" : "missing"}`,
    )
  const componentId = components[0].source_component_id
  const ports = circuitJson.filter(
    (element): element is SourcePort =>
      element.type === "source_port" &&
      element.source_component_id === componentId &&
      aliases(element).includes(match[2]),
  )
  if (ports.length !== 1)
    throw new Error(
      `Port "${selector}" is ${ports.length ? "ambiguous" : "missing"}; use the ports command to inspect selectors`,
    )
  const pcbPorts = circuitJson.filter(
    (element): element is PcbPort =>
      element.type === "pcb_port" &&
      element.source_port_id === ports[0].source_port_id,
  )
  if (pcbPorts.length !== 1)
    throw new Error(`Port "${selector}" needs exactly one PCB port location`)
  if (!pcbPorts[0].layers.includes("top"))
    throw new Error(`Port "${selector}" must be on the top layer`)
  return { source: ports[0], pcb: pcbPorts[0] }
}

function endpointMatches(
  circuitJson: ReturnCurrentCircuitJson,
  trace: PcbTrace,
  endpoint: PcbTrace["route"][number],
  port: ReturnType<typeof resolvePort>,
): boolean {
  if (
    endpoint.route_type !== "wire" ||
    Math.hypot(endpoint.x - port.pcb.x, endpoint.y - port.pcb.y) > 1e-6
  )
    return false
  const ids = [endpoint.start_pcb_port_id, endpoint.end_pcb_port_id].filter(
    Boolean,
  )
  if (ids.length) return ids.includes(port.pcb.pcb_port_id)
  const sourceTrace = circuitJson.find(
    (element) =>
      element.type === "source_trace" &&
      element.source_trace_id === trace.source_trace_id,
  )
  return (
    sourceTrace?.type === "source_trace" &&
    sourceTrace.connected_source_port_ids.includes(port.source.source_port_id)
  )
}

/** Resolve named signal ports to one continuous trace per excitation.
 * Ground contacts are the plane directly beneath the source/load endpoints.
 * Traces are oriented driver → load; existing excitation records are replaced.
 */
export function withNamedExcitations(options: {
  circuitJson: ReturnCurrentCircuitJson
  groundNet: string
  ports: readonly NamedExcitation[]
}): ReturnCurrentCircuitJson {
  if (!options.ports.length)
    throw new Error("Specify at least one source/load/current excitation")
  const nets = options.circuitJson.filter(
    (element) =>
      element.type === "source_net" &&
      (element.name === options.groundNet ||
        element.source_net_id === options.groundNet),
  )
  if (nets.length !== 1 || nets[0].type !== "source_net")
    throw new Error(
      `Ground net "${options.groundNet}" is ${nets.length ? "ambiguous" : "missing"}`,
    )
  const groundId = nets[0].source_net_id
  const oriented = new Map<string, PcbTrace>()
  const excitations: SimulationReturnCurrentExcitation[] = []
  for (const [index, excitation] of options.ports.entries()) {
    if (!Number.isFinite(excitation.current))
      throw new Error("Named excitation current must be finite (peak amperes)")
    const source = resolvePort(options.circuitJson, excitation.source)
    const load = resolvePort(options.circuitJson, excitation.load)
    if (source.pcb.pcb_port_id === load.pcb.pcb_port_id)
      throw new Error("Source and load must be different ports")
    const candidates = options.circuitJson.flatMap((element) => {
      if (element.type !== "pcb_trace" || element.route.length < 2) return []
      const first = element.route[0]
      const last = element.route[element.route.length - 1]
      const forward =
        endpointMatches(options.circuitJson, element, first, source) &&
        endpointMatches(options.circuitJson, element, last, load)
      const reverse =
        endpointMatches(options.circuitJson, element, last, source) &&
        endpointMatches(options.circuitJson, element, first, load)
      return forward || reverse ? [{ trace: element, reverse }] : []
    })
    if (candidates.length !== 1)
      throw new Error(
        `"${excitation.source}" → "${excitation.load}" needs exactly one continuous PCB trace; found ${candidates.length}. Branched nets, vias and component-spanning paths are not supported`,
      )
    const { trace, reverse } = candidates[0]
    if (
      trace.route.some(
        (point) => point.route_type !== "wire" || point.layer !== "top",
      )
    )
      throw new Error(
        "Named excitation requires a continuous top-layer wire trace without vias",
      )
    if (oriented.has(trace.pcb_trace_id))
      throw new Error(`Trace ${trace.pcb_trace_id} is selected more than once`)
    const route = reverse
      ? trace.route
          .map((point, routeIndex) => {
            if (point.route_type !== "wire") return point
            const previous = trace.route[Math.max(0, routeIndex - 1)]
            return {
              ...point,
              width:
                previous.route_type === "wire" ? previous.width : point.width,
              start_pcb_port_id: point.end_pcb_port_id,
              end_pcb_port_id: point.start_pcb_port_id,
            }
          })
          .reverse()
      : trace.route
    oriented.set(trace.pcb_trace_id, { ...trace, route })
    excitations.push({
      type: "simulation_return_current_excitation",
      simulation_return_current_excitation_id: `simulation_return_current_excitation_${index}`,
      pcb_trace_id: trace.pcb_trace_id,
      ground_source_net_id: groundId,
      current: excitation.current,
      return_source: { x: load.pcb.x, y: load.pcb.y },
      return_sink: { x: source.pcb.x, y: source.pcb.y },
    })
  }
  return [
    ...options.circuitJson
      .filter(
        (element) => element.type !== "simulation_return_current_excitation",
      )
      .map((element) =>
        element.type === "pcb_trace"
          ? (oriented.get(element.pcb_trace_id) ?? element)
          : element,
      ),
    ...excitations,
  ]
}
