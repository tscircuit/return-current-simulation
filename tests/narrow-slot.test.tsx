import { expect, test } from "bun:test"
import { renderReturnCurrentSvg, simulateReturnCurrent } from "lib/index"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("a ground slot narrower than the mesh cannot short through graph edges", async () => {
  const circuitJson = await renderFixture(<StraightBoard narrowSlot />)
  const result = simulateReturnCurrent({ circuitJson, cellSize: 0.5 })
  const crossings = result.edges.filter(
    (edge) =>
      edge.axis === "x" &&
      result.nodes[edge.startNode].x < 0 &&
      result.nodes[edge.endNode].x > 0,
  )
  expect(crossings.every((edge) => result.nodes[edge.startNode].y > 8)).toBe(
    true,
  )
  expect(
    crossings.reduce((current, edge) => current + edge.current, 0),
  ).toBeCloseTo(-1, 6)
  await expect(
    renderReturnCurrentSvg(result, {
      title: "A 0.04 mm ground slot blocks a 0.5 mm mesh edge",
      vectorSpacing: 3,
    }),
  ).toMatchSvgSnapshot(import.meta.path)
})
