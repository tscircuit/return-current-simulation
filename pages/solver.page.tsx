import { GenericSolverDebugger } from "@tscircuit/solver-utils/react"
import { ReturnCurrentSolver } from "lib/index"
import circuitJson from "../examples/ground-slot.circuit.json"
import type { ReturnCurrentCircuitJson } from "lib/types"

export default (
  <GenericSolverDebugger
    createSolver={() =>
      new ReturnCurrentSolver({
        circuitJson: circuitJson as ReturnCurrentCircuitJson,
        cellSize: 0.8,
        contactRadius: 0.8,
      })
    }
  />
)
