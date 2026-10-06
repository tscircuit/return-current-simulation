import type { SimulationSpiceSubcircuit } from "circuit-json"

interface Part {
  kind: string
  a: string
  b: string
  value: string
}

const scalar = (text: string) => {
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text))
    throw new Error(
      "Use finite numeric SI values in the supported SPICE subset",
    )
  const value = Number(text)
  if (!Number.isFinite(value)) throw new Error("SPICE value must be finite")
  return value
}

/** Closed numeric R/C/independent-voltage subset. No user SPICE is executed. */
export function readEndpointModel(
  record: SimulationSpiceSubcircuit,
  endpointPortId: string,
) {
  const rows = record.subcircuit_source
    .replace(/\r/g, "")
    .replace(/\n\s*\+/g, " ")
    .split("\n")
    .map((row) => row.trim())
    .filter((row) => row && !row.startsWith("*"))
  const header = rows.shift()?.split(/\s+/)
  if (
    !header ||
    header[0].toLowerCase() !== ".subckt" ||
    header.length !== 4 ||
    !/^\.ends(?:\s+\w+)?$/i.test(rows.pop() ?? "")
  )
    throw new Error(
      "Initial backend supports one self-contained two-pin SPICE subcircuit",
    )
  const [signal, reference] = header
    .slice(2)
    .sort((a, b) =>
      record.spice_pin_to_source_port_map[a] === endpointPortId ? -1 : 1,
    )
  if (record.spice_pin_to_source_port_map[signal] !== endpointPortId)
    throw new Error("SPICE pin mapping does not resolve the trace endpoint")
  const referencePortId = record.spice_pin_to_source_port_map[reference]
  if (!referencePortId)
    throw new Error("SPICE reference pin mapping is missing")
  const parts: Part[] = rows.map((row) => {
    const match = row.match(/^([RCV]\w*)\s+(\w+)\s+(\w+)\s+(.+)$/i)
    if (!match)
      throw new Error(
        "Unsupported SPICE element or directive: " + row.slice(0, 80),
      )
    return {
      kind: match[1][0].toUpperCase(),
      a: match[2],
      b: match[3],
      value: match[4],
    }
  })
  if (parts.length < 2 || parts.length > 3)
    throw new Error(
      "Expected one voltage source and series R, or bias source with receiver R/C",
    )
  const voltage = parts.find((part) => part.kind === "V")
  const resistor = parts.find((part) => part.kind === "R")
  const capacitor = parts.find((part) => part.kind === "C")
  if (!voltage || !resistor || voltage.b !== reference)
    throw new Error(
      "Expected one voltage source referenced to the mapped reference pin",
    )
  if (!parts.every((p) => p === voltage || p === resistor || p === capacitor))
    throw new Error("Duplicate SPICE element types are unsupported")
  if (
    !(
      (resistor.a === signal && resistor.b === voltage.a) ||
      (resistor.b === signal && resistor.a === voltage.a)
    ) ||
    voltage.a === signal ||
    voltage.a === reference
  )
    throw new Error(
      "Resistor must connect the endpoint pin to the independent source",
    )
  const resistance = scalar(resistor.value)
  if (resistance <= 0) throw new Error("Endpoint resistance must be positive")
  if (capacitor) {
    if (
      !(
        (capacitor.a === signal && capacitor.b === reference) ||
        (capacitor.b === signal && capacitor.a === reference)
      )
    )
      throw new Error("Receiver capacitance must connect signal to reference")
    const capacitance = scalar(capacitor.value)
    if (capacitance <= 0)
      throw new Error("Receiver capacitance must be positive")
    return {
      kind: "receiver" as const,
      referencePortId,
      resistance,
      capacitance,
      voltage: scalar(voltage.value),
    }
  }
  const match = voltage.value.match(/^PWL\s*\((.*)\)$/i)
  const values = match
    ? match[1].trim().split(/\s+/).map(scalar)
    : [0, scalar(voltage.value)]
  if (values.length < 2 || values.length % 2)
    throw new Error("PWL requires complete time/voltage pairs")
  const waveform: [number, number][] = []
  for (let i = 0; i < values.length; i += 2) {
    if (values[i] < 0 || (i > 0 && values[i] <= values[i - 2]))
      throw new Error("PWL times must be nonnegative and strictly increasing")
    waveform.push([values[i], values[i + 1]])
  }
  if (waveform[0][0] !== 0)
    throw new Error(
      "PWL must explicitly supply its initial voltage at time zero",
    )
  return { kind: "driver" as const, referencePortId, resistance, waveform }
}
