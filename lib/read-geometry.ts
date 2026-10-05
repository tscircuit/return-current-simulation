import type { PcbCopperPour, Point } from "circuit-json"
import {
  cutoutOutline,
  flattenRing,
  isCopper,
  rectangleOutline,
  segmentInCopper,
} from "./geometry"
import type {
  CopperRegion,
  SimulationGeometry,
  SimulationOptions,
} from "./types"

function pourRegion(pour: PcbCopperPour): CopperRegion {
  if (pour.shape === "rect") return { outer: rectangleOutline(pour), holes: [] }
  if (pour.shape === "polygon") return { outer: pour.points, holes: [] }
  return {
    outer: flattenRing(pour.brep_shape.outer_ring.vertices),
    holes: pour.brep_shape.inner_rings.map((ring) =>
      flattenRing(ring.vertices),
    ),
  }
}

export function positiveFinite(number: number, label: string): number {
  if (!Number.isFinite(number) || number <= 0)
    throw new Error(`${label} must be finite and greater than zero`)
  return number
}

function validateOutline(outline: Point[]): void {
  if (
    outline.length < 3 ||
    outline.some(
      (point) => !Number.isFinite(point.x) || !Number.isFinite(point.y),
    )
  )
    throw new Error(
      "Copper and board polygons need at least three finite points",
    )
}

export function readGeometry(options: SimulationOptions): SimulationGeometry {
  const boards = options.circuitJson.filter(
    (element) => element.type === "pcb_board",
  )
  if (boards.length !== 1) throw new Error("Exactly one PCB board is required")
  const board = boards[0]
  if (board.num_layers !== 2)
    throw new Error(
      "Return-current simulation currently requires a two-layer board",
    )
  if (
    options.circuitJson.some(
      (element) =>
        element.type === "pcb_hole" ||
        element.type === "pcb_plated_hole" ||
        element.type === "pcb_via",
    )
  )
    throw new Error(
      "Drilled holes and vias are not supported yet; represent voids with PCB cutouts and model return contacts explicitly",
    )
  const boardOutline = board.outline?.length
    ? board.outline
    : rectangleOutline({
        center: board.center,
        width: positiveFinite(board.width ?? 0, "Board width"),
        height: positiveFinite(board.height ?? 0, "Board height"),
      })
  const excitations =
    options.excitations ??
    options.circuitJson.filter(
      (element) => element.type === "simulation_return_current_excitation",
    )
  if (!excitations.length)
    throw new Error(
      "Specify return-current excitations with signal current and return contacts",
    )
  const groundNetIds = new Set(
    excitations.map((excitation) => excitation.ground_source_net_id),
  )
  if (groundNetIds.size !== 1)
    throw new Error("All excitations must share one ground net")
  const pours = options.circuitJson.filter(
    (element): element is PcbCopperPour =>
      element.type === "pcb_copper_pour" &&
      element.layer === "bottom" &&
      groundNetIds.has(element.source_net_id ?? ""),
  )
  const groundPlanes = options.circuitJson.filter(
    (element) =>
      element.type === "pcb_ground_plane" &&
      groundNetIds.has(element.source_net_id),
  )
  const groundPlaneIds = new Set(
    groundPlanes.flatMap((element) =>
      element.type === "pcb_ground_plane" ? [element.pcb_ground_plane_id] : [],
    ),
  )
  const planeRegions = options.circuitJson.filter(
    (element) =>
      element.type === "pcb_ground_plane_region" &&
      element.layer === "bottom" &&
      groundPlaneIds.has(element.pcb_ground_plane_id),
  )
  const groundRegions = [
    ...pours.map(pourRegion),
    ...planeRegions.flatMap((region) =>
      region.type === "pcb_ground_plane_region"
        ? [{ outer: region.points, holes: [] }]
        : [],
    ),
  ]
  if (!groundRegions.length)
    throw new Error(
      "The selected ground net needs a bottom-layer copper pour or ground-plane region",
    )
  const cutouts = options.circuitJson
    .filter((element) => element.type === "pcb_cutout")
    .map(cutoutOutline)
  for (const outline of [
    boardOutline,
    ...cutouts,
    ...groundRegions.flatMap((region) => [region.outer, ...region.holes]),
  ])
    validateOutline(outline)
  const geometry: SimulationGeometry = {
    board,
    boardOutline,
    groundRegions,
    cutouts,
    signals: [],
    segments: [],
    excitations,
  }
  for (const excitation of excitations) {
    if (!Number.isFinite(excitation.current))
      throw new Error("Excitation current must be finite (amperes)")
    for (const contact of [excitation.return_source, excitation.return_sink]) {
      if (
        !Number.isFinite(contact.x) ||
        !Number.isFinite(contact.y) ||
        !isCopper(contact, geometry)
      )
        throw new Error(
          "Each return contact must lie on the selected ground copper",
        )
    }
    const signal = options.circuitJson.find(
      (element) =>
        element.type === "pcb_trace" &&
        element.pcb_trace_id === excitation.pcb_trace_id,
    )
    if (!signal || signal.type !== "pcb_trace")
      throw new Error("An excitation references a missing signal trace")
    if (signal.route.length < 2)
      throw new Error("Each signal trace needs at least two route points")
    const wires = signal.route.map((routePoint) => {
      if (routePoint.route_type !== "wire" || routePoint.layer !== "top")
        throw new Error(
          "Only continuous top-layer wire routes are supported; split routes at vias or pads",
        )
      if (!Number.isFinite(routePoint.x) || !Number.isFinite(routePoint.y))
        throw new Error("Signal coordinates must be finite")
      positiveFinite(routePoint.width, "Signal width")
      return routePoint
    })
    geometry.signals.push(signal)
    for (let routeIndex = 1; routeIndex < wires.length; routeIndex++) {
      const start = wires[routeIndex - 1]
      const end = wires[routeIndex]
      if (start.x === end.x && start.y === end.y) continue
      const boardMaterial = {
        ...geometry,
        groundRegions: [{ outer: boardOutline, holes: [] }],
      }
      if (!segmentInCopper({ start, end }, boardMaterial))
        throw new Error(
          "A top-layer signal leaves the board or crosses a physical PCB cutout",
        )
      geometry.segments.push({
        start,
        end,
        width: start.width,
        current: excitation.current,
      })
    }
  }
  if (!geometry.segments.length)
    throw new Error("Signal traces must contain a segment of nonzero length")
  return geometry
}
