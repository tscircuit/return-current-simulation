import {
  any_circuit_element,
  current,
  getZodPrefixedIdWithDefault,
  point,
} from "circuit-json"
import { z } from "zod"
import type {
  ReturnCurrentCircuitJson,
  SimulationReturnCurrentExcitation,
} from "./types"

/** Mirrors the proposed circuit-json schema until it is released upstream. */
const excitationSchema = z.object({
  type: z.literal("simulation_return_current_excitation"),
  simulation_return_current_excitation_id: getZodPrefixedIdWithDefault(
    "simulation_return_current_excitation",
  ),
  pcb_trace_id: z.string(),
  ground_source_net_id: z.string(),
  current: current.pipe(z.number().finite()),
  return_source: point.refine(
    (contact) => Number.isFinite(contact.x) && Number.isFinite(contact.y),
  ),
  return_sink: point.refine(
    (contact) => Number.isFinite(contact.x) && Number.isFinite(contact.y),
  ),
})

/** Some released core versions emit numeric display offsets despite the
 * circuit-json string type. Normalize those display labels at the boundary.
 */
function normalizeDisplayOffsets(
  element: Record<string, unknown>,
): Record<string, unknown> {
  if (element.type !== "pcb_component" && element.type !== "pcb_board")
    return element
  return {
    ...element,
    display_offset_x:
      typeof element.display_offset_x === "number"
        ? String(element.display_offset_x)
        : element.display_offset_x,
    display_offset_y:
      typeof element.display_offset_y === "number"
        ? String(element.display_offset_y)
        : element.display_offset_y,
  }
}

/** Validate external JSON and normalize circuit-json units before simulation. */
export function parseReturnCurrentCircuitJson(
  input: unknown,
): ReturnCurrentCircuitJson {
  const elements = z
    .array(z.object({ type: z.string() }).passthrough())
    .parse(input)
  return elements.map((element) => {
    if (element.type !== "simulation_return_current_excitation")
      return any_circuit_element.parse(normalizeDisplayOffsets(element))
    const excitation: SimulationReturnCurrentExcitation =
      excitationSchema.parse(element)
    return excitation
  })
}
