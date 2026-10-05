import type { CurrentSystem } from "./create-mesh"

export function dot(left: Float64Array, right: Float64Array): number {
  let product = 0
  for (let nodeIndex = 0; nodeIndex < left.length; nodeIndex++)
    product += left[nodeIndex] * right[nodeIndex]
  return product
}

export function applyLaplacian(
  potential: Float64Array,
  system: CurrentSystem,
): Float64Array {
  const applied = new Float64Array(potential.length)
  for (let edgeIndex = 0; edgeIndex < system.result.edges.length; edgeIndex++) {
    const edge = system.result.edges[edgeIndex]
    const difference =
      system.conductance[edgeIndex] *
      ((system.pinned[edge.startNode] ? 0 : potential[edge.startNode]) -
        (system.pinned[edge.endNode] ? 0 : potential[edge.endNode]))
    if (!system.pinned[edge.startNode]) applied[edge.startNode] += difference
    if (!system.pinned[edge.endNode]) applied[edge.endNode] -= difference
  }
  for (let nodeIndex = 0; nodeIndex < potential.length; nodeIndex++) {
    if (system.pinned[nodeIndex]) applied[nodeIndex] = potential[nodeIndex]
  }
  return applied
}

export function precondition(
  residual: Float64Array,
  system: CurrentSystem,
): Float64Array {
  return residual.map((error, nodeIndex) => error / system.diagonal[nodeIndex])
}

/** Reconstruct the conservative face currents and cell-centred sheet vectors. */
export function updateCurrentField(
  potential: Float64Array,
  system: CurrentSystem,
): void {
  const divergence = new Float64Array(potential.length)
  for (const node of system.result.nodes) {
    node.sheetCurrentX = 0
    node.sheetCurrentY = 0
  }
  for (let edgeIndex = 0; edgeIndex < system.result.edges.length; edgeIndex++) {
    const edge = system.result.edges[edgeIndex]
    edge.current =
      edge.preferredCurrent +
      system.conductance[edgeIndex] *
        (potential[edge.startNode] - potential[edge.endNode])
    divergence[edge.startNode] += edge.current
    divergence[edge.endNode] -= edge.current
    const sheetCurrent =
      edge.current /
      (edge.axis === "x" ? system.result.cellHeight : system.result.cellWidth)
    for (const nodeIndex of [edge.startNode, edge.endNode]) {
      const node = system.result.nodes[nodeIndex]
      // The missing boundary face has zero normal flux: divide by two even at boundaries.
      if (edge.axis === "x") node.sheetCurrentX += sheetCurrent / 2
      else node.sheetCurrentY += sheetCurrent / 2
    }
  }
  let maxConservationError = 0
  let maxCurrentDensity = 0
  for (let nodeIndex = 0; nodeIndex < potential.length; nodeIndex++) {
    const node = system.result.nodes[nodeIndex]
    node.currentDensity =
      Math.hypot(node.sheetCurrentX, node.sheetCurrentY) /
      system.result.copperThickness
    maxCurrentDensity = Math.max(maxCurrentDensity, node.currentDensity)
    maxConservationError = Math.max(
      maxConservationError,
      Math.abs(divergence[nodeIndex] - node.injection),
    )
  }
  Object.assign(system.result.diagnostics, {
    maxConservationError,
    maxCurrentDensity,
  })
}
