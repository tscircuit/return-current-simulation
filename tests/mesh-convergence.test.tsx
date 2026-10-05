import { expect, test } from "bun:test"
import { simulateReturnCurrent } from "lib/index"
import { Signal } from "tests/fixtures/Signal"
import { renderFixture } from "tests/fixtures/render-fixture"
import type { SimulationResult } from "lib/types"

function infiniteLineProfileError(result: SimulationResult): number {
  const nodes = result.nodes.filter(
    (node) => Math.abs(node.x) < 0.8 && Math.abs(node.y) < 3,
  )
  // Independent closed form: Kx(y) = -I h / [π(h² + y²)].
  return (
    nodes.reduce(
      (error, node) =>
        error +
        Math.abs(
          node.sheetCurrentX + 0.8 / (Math.PI * (0.64 + node.y * node.y)),
        ),
      0,
    ) / nodes.length
  )
}

test("mesh refinement approaches the infinite straight-line image-current solution", async () => {
  const circuitJson = await renderFixture(
    <board width={60} height={40} layers={2} thickness={0.8} schematicDisabled>
      <net name="GND" />
      <Signal
        name="SIG"
        route={[
          { x: -27, y: 0 },
          { x: 27, y: 0 },
        ]}
      />
      <copperpour layer="bottom" connectsTo="net.GND" boardEdgeMargin={0} />
    </board>,
  )
  const meshes = [0.8, 0.4, 0.2].map((cellSize) =>
    simulateReturnCurrent({ circuitJson, cellSize, contactRadius: 0.9 }),
  )
  const errors = meshes.map(infiniteLineProfileError)
  expect(errors[1]).toBeLessThan(errors[0])
  expect(errors[2]).toBeLessThan(errors[0])
  expect(errors[2]).toBeLessThan(errors[1])
  expect(errors[2]).toBeLessThan(0.001)
  for (const mesh of meshes) {
    const sectionCurrent = mesh.edges
      .filter(
        (edge) =>
          edge.axis === "x" &&
          mesh.nodes[edge.startNode].x < 0 &&
          mesh.nodes[edge.endNode].x >= 0,
      )
      .reduce((current, edge) => current + edge.current, 0)
    expect(sectionCurrent).toBeCloseTo(-1, 6)
  }
})
