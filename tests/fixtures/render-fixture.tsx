import { Circuit } from "@tscircuit/core"
import type { ReactElement } from "react"
import type {
  ReturnCurrentCircuitJson,
  SimulationReturnCurrentExcitation,
} from "lib/types"

/** Circuit geometry is always rendered from TSX. Only the proposed excitation
 * records are temporarily injected, until @tscircuit/core can emit them.
 */
export async function renderFixture(
  element: ReactElement,
  currents: readonly number[] = [1],
): Promise<ReturnCurrentCircuitJson> {
  const circuit = new Circuit()
  circuit.add(element)
  await circuit.renderUntilSettled()
  const circuitJson = circuit.getCircuitJson()
  const ground = circuitJson.find(
    (element) => element.type === "source_net" && element.name === "GND",
  )
  if (!ground || ground.type !== "source_net")
    throw new Error("Fixture needs a GND net")
  const signals = circuitJson.filter((element) => element.type === "pcb_trace")
  if (signals.length !== currents.length)
    throw new Error(
      `Expected ${currents.length} signal traces, rendered ${signals.length}`,
    )
  const excitations: SimulationReturnCurrentExcitation[] = signals.map(
    (signal, signalIndex) => {
      const first = signal.route[0]
      const last = signal.route[signal.route.length - 1]
      if (first.route_type !== "wire" || last.route_type !== "wire")
        throw new Error("Fixture traces need wire endpoints")
      return {
        type: "simulation_return_current_excitation",
        simulation_return_current_excitation_id: `simulation_return_current_excitation_${signalIndex}`,
        pcb_trace_id: signal.pcb_trace_id,
        ground_source_net_id: ground.source_net_id,
        current: currents[signalIndex],
        return_source: { x: last.x, y: last.y },
        return_sink: { x: first.x, y: first.y },
      }
    },
  )
  return [...circuitJson, ...excitations]
}
