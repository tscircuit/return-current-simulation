import type { Point } from "circuit-json"
import { isCopper, segmentInCopper } from "./geometry"
import { imageCurrentAt } from "./image-current"
import { positiveFinite, readGeometry } from "./read-geometry"
import type {
  CurrentEdge,
  CurrentNode,
  SimulationOptions,
  SimulationResult,
} from "./types"

export interface CurrentSystem {
  result: SimulationResult
  diagonal: Float64Array
  rightHandSide: Float64Array
  pinned: Uint8Array
  conductance: Float64Array
}

function labelCopperRegions(
  nodes: CurrentNode[],
  edges: CurrentEdge[],
): Int32Array {
  const neighbours: number[][] = nodes.map(() => [])
  for (const edge of edges) {
    neighbours[edge.startNode].push(edge.endNode)
    neighbours[edge.endNode].push(edge.startNode)
  }
  const labels = new Int32Array(nodes.length).fill(-1)
  let regionCount = 0
  for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
    if (labels[nodeIndex] >= 0) continue
    const queue = [nodeIndex]
    labels[nodeIndex] = regionCount
    for (let queueIndex = 0; queueIndex < queue.length; queueIndex++) {
      for (const neighbour of neighbours[queue[queueIndex]]) {
        if (labels[neighbour] >= 0) continue
        labels[neighbour] = regionCount
        queue.push(neighbour)
      }
    }
    regionCount++
  }
  return labels
}

function contactNodes(
  contact: Point,
  context: { result: SimulationResult; labels: Int32Array; radius: number },
): number[] {
  const candidates: number[] = []
  let nearestNode = -1
  let nearestDistance = Infinity
  for (
    let nodeIndex = 0;
    nodeIndex < context.result.nodes.length;
    nodeIndex++
  ) {
    const node = context.result.nodes[nodeIndex]
    const distance = Math.hypot(node.x - contact.x, node.y - contact.y)
    if (
      distance > context.radius ||
      !segmentInCopper({ start: contact, end: node }, context.result.geometry)
    )
      continue
    candidates.push(nodeIndex)
    if (distance < nearestDistance) {
      nearestDistance = distance
      nearestNode = nodeIndex
    }
  }
  if (nearestNode < 0)
    throw new Error(
      "A return contact has no copper mesh nodes within its radius; reduce cellSize or increase contactRadius",
    )
  return candidates.filter(
    (nodeIndex) => context.labels[nodeIndex] === context.labels[nearestNode],
  )
}

function preferredEdgeCurrent(
  edge: {
    start: CurrentNode
    end: CurrentNode
    axis: "x" | "y"
    faceLength: number
  },
  context: { result: SimulationResult },
): number {
  // Three-point Gaussian quadrature across the shared cell face.
  const fractions = [-Math.sqrt(3 / 5) / 2, 0, Math.sqrt(3 / 5) / 2]
  const weights = [5 / 18, 4 / 9, 5 / 18]
  let current = 0
  for (let sampleIndex = 0; sampleIndex < fractions.length; sampleIndex++) {
    const point = {
      x:
        (edge.start.x + edge.end.x) / 2 +
        (edge.axis === "y" ? fractions[sampleIndex] * edge.faceLength : 0),
      y:
        (edge.start.y + edge.end.y) / 2 +
        (edge.axis === "x" ? fractions[sampleIndex] * edge.faceLength : 0),
    }
    const sheetCurrent = imageCurrentAt(point, {
      segments: context.result.geometry.segments,
      layerSeparation: context.result.layerSeparation,
    })
    current += sheetCurrent[edge.axis] * edge.faceLength * weights[sampleIndex]
  }
  return current
}

export function createCurrentSystem(options: SimulationOptions): CurrentSystem {
  const geometry = readGeometry(options)
  const cellSize = positiveFinite(options.cellSize ?? 0.5, "cellSize")
  const layerSeparation = positiveFinite(
    options.layerSeparation ?? geometry.board.thickness,
    "layerSeparation",
  )
  const copperThickness = positiveFinite(
    options.copperThickness ?? 0.035,
    "copperThickness",
  )
  const contactRadius = positiveFinite(
    options.contactRadius ?? cellSize,
    "contactRadius",
  )
  const bounds = {
    minX: Math.min(...geometry.boardOutline.map((point) => point.x)),
    maxX: Math.max(...geometry.boardOutline.map((point) => point.x)),
    minY: Math.min(...geometry.boardOutline.map((point) => point.y)),
    maxY: Math.max(...geometry.boardOutline.map((point) => point.y)),
  }
  const columns = Math.max(2, Math.ceil((bounds.maxX - bounds.minX) / cellSize))
  const rows = Math.max(2, Math.ceil((bounds.maxY - bounds.minY) / cellSize))
  if (columns * rows > 100_000)
    throw new Error("The mesh exceeds 100,000 cells; increase cellSize")
  const cellWidth = positiveFinite(
    (bounds.maxX - bounds.minX) / columns,
    "Board X extent",
  )
  const cellHeight = positiveFinite(
    (bounds.maxY - bounds.minY) / rows,
    "Board Y extent",
  )
  const nodes: CurrentNode[] = []
  const gridNodes = new Int32Array(columns * rows).fill(-1)
  for (let row = 0; row < rows; row++) {
    for (let column = 0; column < columns; column++) {
      const point = {
        x: bounds.minX + (column + 0.5) * cellWidth,
        y: bounds.minY + (row + 0.5) * cellHeight,
      }
      if (!isCopper(point, geometry)) continue
      gridNodes[row * columns + column] = nodes.length
      nodes.push({
        ...point,
        column,
        row,
        injection: 0,
        sheetCurrentX: 0,
        sheetCurrentY: 0,
        currentDensity: 0,
      })
    }
  }
  if (!nodes.length)
    throw new Error("The mesh contains no ground copper; reduce cellSize")
  const result: SimulationResult = {
    geometry,
    nodes,
    edges: [],
    columns,
    rows,
    cellWidth,
    cellHeight,
    bounds,
    copperThickness,
    layerSeparation,
    diagnostics: {
      converged: false,
      iterations: 0,
      relativeResidual: Infinity,
      maxConservationError: Infinity,
      maxCurrentDensity: 0,
      connectedCopperRegions: 0,
    },
  }
  const conductanceList: number[] = []
  for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
    const node = nodes[nodeIndex]
    for (const axis of ["x", "y"] as const) {
      const neighbourColumn = node.column + (axis === "x" ? 1 : 0)
      const neighbourRow = node.row + (axis === "y" ? 1 : 0)
      if (neighbourColumn >= columns || neighbourRow >= rows) continue
      const neighbourIndex = gridNodes[neighbourRow * columns + neighbourColumn]
      if (
        neighbourIndex < 0 ||
        !segmentInCopper({ start: node, end: nodes[neighbourIndex] }, geometry)
      )
        continue
      const faceLength = axis === "x" ? cellHeight : cellWidth
      const preferredCurrent = preferredEdgeCurrent(
        { start: node, end: nodes[neighbourIndex], axis, faceLength },
        { result },
      )
      result.edges.push({
        startNode: nodeIndex,
        endNode: neighbourIndex,
        axis,
        preferredCurrent,
        current: preferredCurrent,
      })
      conductanceList.push(faceLength / (axis === "x" ? cellWidth : cellHeight))
    }
  }
  const labels = labelCopperRegions(nodes, result.edges)
  const pinned = new Uint8Array(nodes.length)
  const regionRoots = new Set<number>()
  for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
    if (regionRoots.has(labels[nodeIndex])) continue
    pinned[nodeIndex] = 1
    regionRoots.add(labels[nodeIndex])
  }
  result.diagnostics.connectedCopperRegions = regionRoots.size
  for (const excitation of geometry.excitations) {
    const sourceNodes = contactNodes(excitation.return_source, {
      result,
      labels,
      radius: contactRadius,
    })
    const sinkNodes = contactNodes(excitation.return_sink, {
      result,
      labels,
      radius: contactRadius,
    })
    if (
      excitation.current !== 0 &&
      labels[sourceNodes[0]] !== labels[sinkNodes[0]]
    )
      throw new Error(
        "The return contacts are on disconnected copper; there is no return-current path",
      )
    for (const nodeIndex of sourceNodes)
      nodes[nodeIndex].injection += excitation.current / sourceNodes.length
    for (const nodeIndex of sinkNodes)
      nodes[nodeIndex].injection -= excitation.current / sinkNodes.length
  }
  const diagonal = new Float64Array(nodes.length)
  const rightHandSide = Float64Array.from(nodes.map((node) => node.injection))
  const conductance = Float64Array.from(conductanceList)
  for (let edgeIndex = 0; edgeIndex < result.edges.length; edgeIndex++) {
    const edge = result.edges[edgeIndex]
    diagonal[edge.startNode] += conductance[edgeIndex]
    diagonal[edge.endNode] += conductance[edgeIndex]
    rightHandSide[edge.startNode] -= edge.preferredCurrent
    rightHandSide[edge.endNode] += edge.preferredCurrent
  }
  for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
    if (!pinned[nodeIndex]) continue
    diagonal[nodeIndex] = 1
    rightHandSide[nodeIndex] = 0
  }
  return { result, diagonal, rightHandSide, pinned, conductance }
}
