import { expect, test } from "bun:test"
import { simulateReturnCurrent } from "lib/index"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("signed current superposition and copper-thickness units", async () => {
  const circuitJson = await renderFixture(<StraightBoard />)
  const baseline = simulateReturnCurrent({ circuitJson, cellSize: 0.75 })
  const excitation = baseline.geometry.excitations[0]
  const reversed = simulateReturnCurrent({
    circuitJson,
    cellSize: 0.75,
    excitations: [{ ...excitation, current: -2 }],
  })
  const thinCopper = simulateReturnCurrent({
    circuitJson,
    cellSize: 0.75,
    copperThickness: baseline.copperThickness / 2,
  })
  const superposed = simulateReturnCurrent({
    circuitJson,
    cellSize: 0.75,
    excitations: [
      { ...excitation, current: 0.3 },
      { ...excitation, current: 0.7 },
    ],
  })
  for (let edgeIndex = 0; edgeIndex < baseline.edges.length; edgeIndex++) {
    expect(reversed.edges[edgeIndex].current).toBeCloseTo(
      -2 * baseline.edges[edgeIndex].current,
      7,
    )
    expect(thinCopper.edges[edgeIndex].current).toBeCloseTo(
      baseline.edges[edgeIndex].current,
      7,
    )
    expect(superposed.edges[edgeIndex].current).toBeCloseTo(
      baseline.edges[edgeIndex].current,
      7,
    )
  }
  for (let nodeIndex = 0; nodeIndex < baseline.nodes.length; nodeIndex++) {
    expect(thinCopper.nodes[nodeIndex].currentDensity).toBeCloseTo(
      2 * baseline.nodes[nodeIndex].currentDensity,
      7,
    )
    expect(reversed.nodes[nodeIndex].currentDensity).toBeCloseTo(
      2 * baseline.nodes[nodeIndex].currentDensity,
      7,
    )
  }
  const zero = simulateReturnCurrent({
    circuitJson,
    excitations: [{ ...excitation, current: 0 }],
  })
  expect(zero.diagnostics.maxCurrentDensity).toBe(0)
  expect(zero.diagnostics.maxConservationError).toBe(0)
})
