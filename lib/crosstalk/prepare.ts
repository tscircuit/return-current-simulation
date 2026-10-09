import type { AnyCircuitElement, PcbPort, PcbTrace } from "circuit-json"
import { portNetIds } from "../port-connectivity"
import { readEndpointModel } from "./spice-testbench"
import type { CrosstalkModel, CrosstalkReport, LineTestbench } from "./types"

class Problem extends Error {
  constructor(
    readonly status: "missing_data" | "unsupported",
    readonly code: string,
    message: string,
    readonly ids: string[] = [],
  ) {
    super(message)
  }
}
function missing(code: string, message: string, ids: string[] = []): never {
  throw new Problem("missing_data", code, message, ids)
}
function unsupported(message: string, ids: string[] = []): never {
  throw new Problem("unsupported", "unsupported_model", message, ids)
}
const positive = (value: unknown, name: string): number => {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0)
    return missing("missing_physical_data", "Supply a positive finite " + name)
  return value
}
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return missing(
      "missing_stackup",
      "Supply pcb_board.stackup with explicit physical layer data",
    )
  return value as Record<string, unknown>
}
const layerName = (value: unknown) =>
  typeof value === "string" ? value : object(value).name
const close = (a: number, b: number) => Math.abs(a - b) < 1e-7

export const crosstalkAssumptions = [
  "Uniform two-line quasi-TEM approximation; not arbitrary-board SI or DDR qualification.",
  "Supplied Er and explicit zero loss datum are held constant for this transient; no broadband laminate model is inferred.",
  "Soldermask properties are unknown and its effect is omitted; no assertion that the actual board is uncoated.",
  "Reference plane is idealized as infinite and nonmagnetic; finite edges, ground resistance, launches, pads and vias are omitted.",
  "Supplied trace conductivity gives DC series R, split at the line ends; skin effect and roughness are omitted.",
]

/** Geometry and endpoint models are read without modifying the rendered input. */
export function prepareCrosstalk(
  circuitJson: readonly AnyCircuitElement[],
): CrosstalkReport {
  try {
    if (
      !Array.isArray(circuitJson as unknown) ||
      circuitJson.some((e) => !e || typeof e.type !== "string")
    )
      unsupported("Expected an array of Circuit JSON records")
    const boards = circuitJson.filter((e) => e.type === "pcb_board")
    if (boards.length !== 1)
      unsupported("Initial backend requires exactly one PCB board")
    const board = boards[0]
    const stackup = object(
      (board as typeof board & { stackup?: unknown }).stackup,
    )
    if (!["specified", "assumed"].includes(String(stackup.source)))
      missing(
        "missing_stackup_source",
        "Stackup source must explicitly be specified or assumed",
      )
    const layers = stackup.layers
    if (!Array.isArray(layers) || layers.length !== 3 || board.num_layers !== 2)
      unsupported(
        "Initial backend supports top copper / one dielectric / bottom copper on a two-layer board",
      )
    const [top, dielectric, bottom] = layers.map(object)
    if (
      top.type !== "copper" ||
      layerName(top.layer) !== "top" ||
      dielectric.type !== "dielectric" ||
      bottom.type !== "copper" ||
      layerName(bottom.layer) !== "bottom"
    )
      unsupported("Expected ordered top copper, dielectric and bottom copper")
    const thicknessMm = positive(top.thickness_mm, "top copper thickness_mm")
    const heightMm = positive(
      dielectric.thickness_mm,
      "dielectric thickness_mm",
    )
    const bottomThickness = positive(
      bottom.thickness_mm,
      "bottom copper thickness_mm",
    )
    const conductivity = positive(
      top.conductivity_s_per_m,
      "top copper conductivity_s_per_m",
    )
    positive(bottom.conductivity_s_per_m, "bottom copper conductivity_s_per_m")
    if (
      board.thickness !== undefined &&
      !close(board.thickness, thicknessMm + heightMm + bottomThickness)
    )
      unsupported(
        "pcb_board.thickness must agree with the physical stackup, including both copper foils",
      )
    const relativePermittivity = positive(
      dielectric.dielectric_constant,
      "dielectric_constant",
    )
    const referenceFrequencyHz = positive(
      dielectric.dielectric_constant_frequency_hz,
      "dielectric_constant_frequency_hz",
    )
    const lossFrequency = positive(
      dielectric.dielectric_loss_tangent_frequency_hz,
      "dielectric_loss_tangent_frequency_hz",
    )
    if (dielectric.dielectric_loss_tangent === undefined)
      missing(
        "missing_dielectric_loss",
        "Supply dielectric loss data; omission cannot become zero loss",
      )
    if (dielectric.dielectric_loss_tangent !== 0)
      unsupported(
        "Initial transient model requires explicitly supplied zero dielectric loss; nonzero loss is not implemented",
      )
    if (!close(referenceFrequencyHz / lossFrequency, 1))
      unsupported(
        "Er and loss reference frequencies differ; this initial model has no conversion policy",
      )
    if (
      circuitJson.some((e) =>
        ["pcb_cutout", "pcb_via", "pcb_hole", "pcb_plated_hole"].includes(
          e.type,
        ),
      )
    )
      unsupported(
        "Board cutouts, holes and vias are outside the initial uniform-line model",
      )
    const traces = circuitJson.filter((e) => e.type === "pcb_trace")
    if (traces.length !== 2)
      unsupported("Initial backend requires exactly two routed PCB traces")
    const ports = circuitJson.filter((e) => e.type === "pcb_port")
    const routes = traces.map((trace) => {
      if (
        trace.route.length < 2 ||
        trace.route.some(
          (p) =>
            p.route_type !== "wire" ||
            layerName(p.layer) !== "top" ||
            p.start_width !== undefined ||
            p.end_width !== undefined ||
            !Number.isFinite(p.x) ||
            !Number.isFinite(p.y),
        )
      )
        unsupported(
          "Each trace must have a finite, untapered top-layer wire route",
          [trace.pcb_trace_id],
        )
      const wire = trace.route as Extract<
        PcbTrace["route"][number],
        { route_type: "wire" }
      >[]
      const first = wire[0],
        last = wire[wire.length - 1]
      const width = positive(first.width, "trace width")
      const length = Math.hypot(last.x - first.x, last.y - first.y)
      if (length <= 0)
        unsupported("Trace length must be positive", [trace.pcb_trace_id])
      const dx = (last.x - first.x) / length,
        dy = (last.y - first.y) / length
      let previous = -1e-7
      for (const point of wire) {
        const along = (point.x - first.x) * dx + (point.y - first.y) * dy
        if (
          !close((point.x - first.x) * dy - (point.y - first.y) * dx, 0) ||
          along < previous ||
          !close(point.width, width)
        )
          unsupported(
            "Trace bends, backtracking and width changes are unsupported",
            [trace.pcb_trace_id],
          )
        previous = along
      }
      const endpoint = (point: typeof first, id?: string): PcbPort => {
        const matches = ports.filter(
          (p) =>
            (!id || p.pcb_port_id === id) &&
            close(p.x, point.x) &&
            close(p.y, point.y) &&
            p.layers.some((l) => layerName(l) === "top"),
        )
        if (matches.length !== 1)
          missing(
            "missing_endpoint",
            "Trace endpoint must resolve to exactly one PCB/source port",
            [trace.pcb_trace_id],
          )
        return matches[0]
      }
      const endpoints = [
        endpoint(first, first.start_pcb_port_id),
        endpoint(last, last.end_pcb_port_id),
      ]
      const connection = circuitJson.find(
        (e) =>
          e.type === "source_trace" &&
          e.source_trace_id === trace.source_trace_id,
      )
      if (
        connection?.type !== "source_trace" ||
        connection.connected_source_port_ids.length !== 2 ||
        !endpoints.every((p) =>
          connection.connected_source_port_ids.includes(p.source_port_id),
        )
      )
        unsupported(
          "Each routed trace must correspond to one unbranched two-port source connection",
          [trace.pcb_trace_id],
        )
      return { trace, first, last, width, length, dx, dy, endpoints }
    })
    const [a, b] = routes
    if (
      !close(a.width, b.width) ||
      !close(a.length, b.length) ||
      !close(a.dx, b.dx) ||
      !close(a.dy, b.dy) ||
      !close((b.first.x - a.first.x) * a.dx + (b.first.y - a.first.y) * a.dy, 0)
    )
      unsupported(
        "Traces must be equal-width, parallel, coextensive and routed in the same direction",
      )
    const gapMm =
      Math.abs(
        (b.first.x - a.first.x) * a.dy - (b.first.y - a.first.y) * a.dx,
      ) - a.width
    if (gapMm <= 0) unsupported("The two traces overlap or touch")
    const groundIds = new Set(
      circuitJson
        .filter((e) => e.type === "source_net")
        .filter((e) => e.is_ground)
        .map((e) => e.source_net_id),
    )
    const isGroundPort = (id: string) =>
      portNetIds([...circuitJson], id).some((net) => groundIds.has(net))
    const pours = circuitJson
      .filter((e) => e.type === "pcb_copper_pour")
      .filter(
        (e) =>
          layerName(e.layer) === "bottom" &&
          e.source_net_id &&
          groundIds.has(e.source_net_id),
      )
    if (circuitJson.filter((e) => e.type === "pcb_copper_pour").length !== 1)
      unsupported(
        "Initial model requires one reference pour and no additional copper pours",
      )
    const bounds = (pour: (typeof pours)[number]) => {
      if (
        pour.shape === "rect" &&
        (!pour.rotation || close(pour.rotation % 180, 0))
      )
        return [
          pour.center.x - pour.width / 2,
          pour.center.x + pour.width / 2,
          pour.center.y - pour.height / 2,
          pour.center.y + pour.height / 2,
        ]
      const points =
        pour.shape === "polygon"
          ? pour.points
          : pour.shape === "brep" && pour.brep_shape.inner_rings.length === 0
            ? pour.brep_shape.outer_ring.vertices
            : []
      if (
        points.some(
          (p) =>
            !Number.isFinite(p.x) ||
            !Number.isFinite(p.y) ||
            ("bulge" in p && p.bulge !== undefined && p.bulge !== 0),
        )
      )
        unsupported(
          "Reference plane requires finite straight edges; curved BRep edges are unsupported",
        )
      if (points.length !== 4)
        unsupported(
          "Initial reference plane must be one axis-aligned rectangle",
        )
      const xs = [...new Set(points.map((p) => p.x))],
        ys = [...new Set(points.map((p) => p.y))]
      if (xs.length !== 2 || ys.length !== 2)
        unsupported(
          "Initial reference plane must be one axis-aligned rectangle",
        )
      if (
        points.some((p, i) => {
          const next = points[(i + 1) % 4]
          return (p.x === next.x) === (p.y === next.y)
        })
      )
        unsupported(
          "Reference polygon must be a closed rectangle without crossing edges",
        )
      return [
        Math.min(...xs),
        Math.max(...xs),
        Math.min(...ys),
        Math.max(...ys),
      ]
    }
    const reference = pours.find((pour) => {
      const [xmin, xmax, ymin, ymax] = bounds(pour)
      const margin = a.width / 2 + heightMm * 4
      return routes.every((r) =>
        [r.first, r.last].every(
          (p) =>
            p.x >= xmin + margin &&
            p.x <= xmax - margin &&
            p.y >= ymin + margin &&
            p.y <= ymax - margin,
        ),
      )
    })
    if (!reference)
      missing(
        "missing_reference_plane",
        "Supply one connected rectangular bottom GND pour covering both traces with margin",
      )
    const sourcePorts = circuitJson.filter((e) => e.type === "source_port")
    const models = circuitJson.filter(
      (e) => e.type === "simulation_spice_subcircuit",
    )
    const modelOwners = new Set(models.map((m) => m.source_component_id))
    if (
      circuitJson.some(
        (e) =>
          e.type === "source_component" &&
          !modelOwners.has(e.source_component_id),
      )
    )
      unsupported(
        "Additional components outside the four endpoint subcircuits are not modeled",
      )
    const endpointModel = (port: PcbPort) => {
      const sourcePort = sourcePorts.find(
        (p) => p.source_port_id === port.source_port_id,
      )
      const found = models.filter(
        (m) => m.source_component_id === sourcePort?.source_component_id,
      )
      if (found.length !== 1)
        missing(
          "missing_endpoint_model",
          "Supply one mapped SPICE driver or receiver model at each endpoint; pin flags and part numbers are insufficient",
          [port.source_port_id],
        )
      const parsed = readEndpointModel(found[0], port.source_port_id)
      if (!isGroundPort(parsed.referencePortId))
        missing(
          "missing_reference_connection",
          "Endpoint reference pin must connect to the declared ground net",
          [parsed.referencePortId],
        )
      return parsed
    }
    const lines = routes.map((route): LineTestbench => {
      const [near, far] = route.endpoints
      const driver = endpointModel(near),
        receiver = endpointModel(far)
      if (driver.kind !== "driver" || receiver.kind !== "receiver")
        unsupported(
          "Route must start at the supplied driver and end at the supplied R/C receiver",
        )
      const owner = sourcePorts.find(
        (p) => p.source_port_id === near.source_port_id,
      )?.source_component_id
      const component = circuitJson.find(
        (e) => e.type === "source_component" && e.source_component_id === owner,
      )
      return {
        traceId: route.trace.pcb_trace_id,
        name:
          component?.type === "source_component"
            ? component.name
            : route.trace.pcb_trace_id,
        nearPortId: near.source_port_id,
        farPortId: far.source_port_id,
        sourceResistance: driver.resistance,
        loadResistance: receiver.resistance,
        loadCapacitance: receiver.capacitance,
        loadVoltage: receiver.voltage,
        waveform: driver.waveform,
      }
    }) as [LineTestbench, LineTestbench]
    for (const key of [
      "sourceResistance",
      "loadResistance",
      "loadCapacitance",
      "loadVoltage",
    ] as const)
      if (lines[0][key] !== lines[1][key])
        unsupported(
          "Exact independent modes currently require equal source R, load R/C and termination bias",
        )
    if (
      models.length !== 4 ||
      circuitJson.some(
        (e) =>
          e.type === "simulation_voltage_source" ||
          e.type === "simulation_parameter_sweep",
      )
    )
      unsupported(
        "Initial backend supports only the four mapped endpoint subcircuits; additional sources or parameter sweeps are unsupported",
      )
    const experiments = circuitJson.filter(
      (e) => e.type === "simulation_experiment",
    )
    if (
      experiments.length !== 1 ||
      experiments[0].experiment_type !== "spice_transient_analysis"
    )
      missing(
        "missing_experiment",
        "Supply exactly one unambiguous transient experiment",
      )
    const stopSeconds =
      positive(experiments[0].end_time_ms, "simulation end_time_ms") * 1e-3
    if (experiments[0].start_time_ms && experiments[0].start_time_ms !== 0)
      unsupported("Initial analysis starts at time zero")
    if (
      stopSeconds > 1e-6 ||
      lines.some((line) => line.waveform.length > 10000)
    )
      unsupported(
        "Initial resource budget is at most 1 microsecond and 10000 PWL knots per source",
      )
    if (experiments[0].spice_options)
      unsupported(
        "User SPICE options are not yet supported; numerical refinement uses recorded internal settings",
      )
    const model: CrosstalkModel = {
      geometry: {
        widthMm: a.width,
        thicknessMm,
        heightMm,
        lengthMm: a.length,
        gapMm,
        referencePourId: reference.pcb_copper_pour_id,
        traceIds: traces.map((t) => t.pcb_trace_id),
      },
      material: {
        relativePermittivity,
        conductivity,
        referenceFrequencyHz,
        stackupSource: stackup.source as "specified" | "assumed",
      },
      stopSeconds,
      lines,
    }
    return {
      status: "complete",
      issues: [],
      assumptions: [...crosstalkAssumptions],
      model,
    }
  } catch (error) {
    const problem =
      error instanceof Problem
        ? error
        : new Problem(
            "unsupported",
            "unsupported_input",
            error instanceof Error ? error.message : String(error),
          )
    return {
      status: problem.status,
      issues: [
        {
          code: problem.code,
          message: problem.message,
          elementIds: problem.ids,
        },
      ],
      assumptions: [...crosstalkAssumptions],
    }
  }
}
