import { expect, test } from "bun:test"
import { createPalaceModel } from "lib/palace/create-palace-model"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("Palace uses the TSX circuit geometry and explicit frequency/materials", async () => {
  const circuitJson = await renderFixture(<SlotBoard />, [1, 1, 1])
  const model = createPalaceModel({ circuitJson, frequencyHz: 1e6 })
  expect(model.frequencyHz).toBe(1e6)
  expect(model.copperModel).toBe("volumetric_copper")
  expect(model.geometry.signals).toHaveLength(3)
  expect(model.topPads).toHaveLength(6)
  expect(model.layerSeparation).toBe(0.8)
  expect(model.geometry.groundRegions[0].outer).toContainEqual({ x: -6, y: 19 })
  expect(() =>
    createPalaceModel({ circuitJson, frequencyHz: Number.NaN }),
  ).toThrow("frequencyHz")
  expect(() => createPalaceModel({ circuitJson, frequencyHz: 1e9 })).toThrow(
    "skin depth",
  )
  const excitations = model.geometry.excitations.map((excitation) => ({
    ...excitation,
    return_sink: {
      x: excitation.return_sink.x + 1,
      y: excitation.return_sink.y,
    },
  }))
  expect(() =>
    createPalaceModel({ circuitJson, excitations, frequencyHz: 1e6 }),
  ).toThrow("directly below")
})
