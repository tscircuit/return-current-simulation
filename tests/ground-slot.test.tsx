import { expect, test } from "bun:test"
import { renderReturnCurrentSvg, simulateReturnCurrent } from "lib/index"
import { SlotBoard, slotRoutes } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("three top signals return around the bottom-ground slot", async () => {
  const circuitJson = await renderFixture(<SlotBoard />, [1, 1, 1])
  const result = simulateReturnCurrent({
    circuitJson,
    cellSize: 0.4,
    contactRadius: 0.6,
  })
  for (const [signalIndex, signal] of result.geometry.signals.entries()) {
    const wires = signal.route.filter(
      (routePoint) => routePoint.route_type === "wire",
    )
    const emittedPoints = wires
      .filter(
        (point, routeIndex) =>
          routeIndex === 0 ||
          point.x !== wires[routeIndex - 1].x ||
          point.y !== wires[routeIndex - 1].y,
      )
      .map((point) => ({ x: point.x, y: point.y }))
    expect(emittedPoints).toEqual(slotRoutes[signalIndex])
  }
  // Every return ampere must cross the narrow bridge above the slot.
  const bridgeEdges = result.edges.filter(
    (edge) =>
      edge.axis === "x" &&
      result.nodes[edge.startNode].x < -4.5 &&
      result.nodes[edge.endNode].x > -4.5,
  )
  expect(bridgeEdges.length).toBeGreaterThan(0)
  expect(
    bridgeEdges.every((edge) => result.nodes[edge.startNode].y >= 19),
  ).toBe(true)
  expect(
    bridgeEdges.reduce((current, edge) => current + edge.current, 0),
  ).toBeCloseTo(-3, 6)
  const divergence = new Float64Array(result.nodes.length)
  for (const edge of result.edges) {
    divergence[edge.startNode] += edge.current
    divergence[edge.endNode] -= edge.current
  }
  expect(
    Math.max(
      ...result.nodes.map((node, nodeIndex) =>
        Math.abs(divergence[nodeIndex] - node.injection),
      ),
    ),
  ).toBeLessThan(1e-7)
  expect(
    result.nodes.some((node) => node.x > -6 && node.x < -3 && node.y < 19),
  ).toBe(false)
  await expect(
    renderReturnCurrentSvg(result, {
      title: "Three signals across a ground-plane slot",
      maxCurrentDensity: 50,
      vectorSpacing: 3,
    }),
  ).toMatchSvgSnapshot(import.meta.path)
})
