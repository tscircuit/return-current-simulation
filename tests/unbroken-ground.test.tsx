import { expect, test } from "bun:test"
import { renderReturnCurrentSvg, simulateReturnCurrent } from "lib/index"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("an unbroken reference plane removes slot-tip current crowding", async () => {
  const slotted = simulateReturnCurrent({
    circuitJson: await renderFixture(<SlotBoard />, [1, 1, 1]),
    cellSize: 0.4,
    contactRadius: 0.6,
  })
  const intact = simulateReturnCurrent({
    circuitJson: await renderFixture(<SlotBoard unbrokenGround />, [1, 1, 1]),
    cellSize: 0.4,
    contactRadius: 0.6,
  })
  expect(slotted.diagnostics.maxCurrentDensity).toBeGreaterThan(
    intact.diagnostics.maxCurrentDensity * 3,
  )
  expect(intact.diagnostics.maxConservationError).toBeLessThan(1e-7)
  await expect(
    renderReturnCurrentSvg(intact, {
      title: "The same signals over unbroken ground",
      maxCurrentDensity: 50,
      vectorSpacing: 3,
    }),
  ).toMatchSvgSnapshot(import.meta.path)
})
