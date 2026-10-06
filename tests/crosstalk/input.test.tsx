import { expect, test } from "bun:test"
import { analyzeCrosstalk } from "../../lib"
import { readEndpointModel } from "../../lib/crosstalk/spice-testbench"
import { renderCoupledLines } from "../fixtures/CoupledLines"

test("actual TSX without physical stackup produces an actionable result", async () => {
  const json = await renderCoupledLines({ physicalData: false })
  const before = JSON.stringify(json)
  const result = await analyzeCrosstalk(json)
  expect(result.getString()).toMatchSnapshot()
  expect(result.getReport().status).toBe("missing_data")
  expect(result.getReport().numerical).toBeUndefined()
  expect(JSON.stringify(json)).toBe(before)
})

test("rendered SPICE pin mappings preserve the pulse and finite driver/load models", async () => {
  const json = await renderCoupledLines()
  const records = json.filter((e) => e.type === "simulation_spice_subcircuit")
  const models = records.map((record) => {
    const port = record.spice_pin_to_source_port_map.signal
    return readEndpointModel(record, port)
  })
  expect(models).toMatchSnapshot()
  expect(
    json.some((e) => e.type === "simulation_transient_voltage_graph"),
  ).toBe(false)
})

test("unsupported SPICE directives are rejected before native execution", async () => {
  const json = await renderCoupledLines()
  const record = json.find((e) => e.type === "simulation_spice_subcircuit")!
  if (record.type !== "simulation_spice_subcircuit")
    throw new Error("Missing model")
  const adversarial = {
    ...record,
    subcircuit_source: record.subcircuit_source.replace(
      ".ends",
      ".include untrusted.cir\n.ends",
    ),
  }
  expect(() =>
    readEndpointModel(adversarial, record.spice_pin_to_source_port_map.signal),
  ).toThrow("Unsupported SPICE")
})
