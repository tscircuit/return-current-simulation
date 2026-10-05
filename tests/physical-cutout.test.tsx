import { expect, test } from "bun:test"
import { renderReturnCurrentSvg, simulateReturnCurrent } from "lib/index"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("a physical PCB cutout removes ground and the top trace routes around it", async () => {
  const result = simulateReturnCurrent({
    circuitJson: await renderFixture(<StraightBoard physicalCutout />),
    cellSize: 0.4,
  })
  expect(result.geometry.cutouts).toHaveLength(1)
  expect(
    result.nodes.some((node) => Math.abs(node.x) < 2 && Math.abs(node.y) < 3),
  ).toBe(false)
  expect(result.diagnostics.maxConservationError).toBeLessThan(1e-7)
  await expect(
    renderReturnCurrentSvg(result, {
      title: "Physical cutout: both layers route around removed PCB material",
      vectorSpacing: 3,
    }),
  ).toMatchSvgSnapshot(import.meta.path)
})
