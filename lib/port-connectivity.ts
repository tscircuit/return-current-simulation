import type { ReturnCurrentCircuitJson } from "./types"

/** Use source connectivity, never a pin label or geometric proximity, to identify nets. */
export function portNetIds(
  circuitJson: ReturnCurrentCircuitJson,
  sourcePortId: string,
): string[] {
  const ports = new Set([sourcePortId])
  const nets = new Set<string>()
  const pending = circuitJson.filter(
    (element) => element.type === "source_trace",
  )
  let changed = true
  while (changed) {
    changed = false
    for (const trace of pending) {
      if (
        !trace.connected_source_port_ids.some((id) => ports.has(id)) &&
        !trace.connected_source_net_ids.some((id) => nets.has(id))
      )
        continue
      for (const id of trace.connected_source_port_ids)
        if (!ports.has(id)) {
          ports.add(id)
          changed = true
        }
      for (const id of trace.connected_source_net_ids)
        if (!nets.has(id)) {
          nets.add(id)
          changed = true
        }
    }
  }
  return [...nets]
}
