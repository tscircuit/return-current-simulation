import { expect, test } from "bun:test"
import { ReturnCurrentSolver, simulateReturnCurrent } from "lib/index"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("unphysical and incomplete inputs fail explicitly", async () => {
  const circuitJson = await renderFixture(<StraightBoard />)
  const disconnected = await renderFixture(<StraightBoard splitGround />)
  expect(() => simulateReturnCurrent({ circuitJson: disconnected })).toThrow(
    "disconnected copper",
  )
  expect(() =>
    simulateReturnCurrent({
      circuitJson: circuitJson.filter(
        (element) => element.type !== "simulation_return_current_excitation",
      ),
    }),
  ).toThrow("excitations")
  expect(() =>
    simulateReturnCurrent({
      circuitJson: circuitJson.filter(
        (element) => element.type !== "pcb_copper_pour",
      ),
    }),
  ).toThrow("bottom-layer copper pour")
  for (const cellSize of [0, -1, Infinity, NaN, 0.00001])
    expect(() => simulateReturnCurrent({ circuitJson, cellSize })).toThrow()
  const solver = new ReturnCurrentSolver({ circuitJson, maxIterations: 1 })
  expect(() => solver.getOutput()).toThrow("not converged")
  solver.solve()
  expect(solver.failed).toBe(true)
  expect(() => solver.getOutput()).toThrow("ran out of iterations")
  const stepped = new ReturnCurrentSolver({ circuitJson, cellSize: 1 })
  while (!stepped.solved && !stepped.failed) stepped.step()
  expect(stepped.getOutput().diagnostics.maxConservationError).toBeLessThan(
    1e-7,
  )
})
