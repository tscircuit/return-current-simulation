import { expect, test } from "bun:test"
import { parseReturnCurrentCircuitJson, simulateReturnCurrent } from "lib/index"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("external circuit-json validates and normalizes excitation units", async () => {
  const circuitJson = await renderFixture(<StraightBoard />)
  const externalJson = circuitJson.map((element) =>
    element.type === "simulation_return_current_excitation"
      ? { ...element, current: "500mA", return_source: { x: "12mm", y: "0mm" } }
      : element,
  )
  const parsed = parseReturnCurrentCircuitJson(externalJson)
  const result = simulateReturnCurrent({ circuitJson: parsed, cellSize: 1 })
  expect(result.geometry.excitations[0].current).toBe(0.5)
  expect(result.geometry.excitations[0].return_source).toEqual({ x: 12, y: 0 })
  expect(() => parseReturnCurrentCircuitJson({ circuitJson })).toThrow()
  expect(() =>
    parseReturnCurrentCircuitJson([{ type: "unrecognized_element" }]),
  ).toThrow()
  expect(() =>
    parseReturnCurrentCircuitJson([
      { type: "simulation_return_current_excitation", current: "1A" },
    ]),
  ).toThrow()
})
