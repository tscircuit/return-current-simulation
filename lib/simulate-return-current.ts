import { ReturnCurrentSolver } from "./ReturnCurrentSolver"
import type { SimulationOptions, SimulationResult } from "./types"

export function simulateReturnCurrent(
  options: SimulationOptions,
): SimulationResult {
  const solver = new ReturnCurrentSolver(options)
  solver.solve()
  return solver.getOutput()
}
