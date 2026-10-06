import { expect, test } from "bun:test"
import {
  withNamedExcitations,
  listCircuitPorts,
  createPalaceModel,
} from "lib/index"
import { NamedPortBoard } from "tests/fixtures/NamedPortBoard"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("TSX refdes/pin aliases select source/load, peak current and ground without injecting metadata", async () => {
  for (const reverse of [false, true]) {
    const original = (
      await renderFixture(<NamedPortBoard reverse={reverse} />)
    ).filter(
      (element) => element.type !== "simulation_return_current_excitation",
    )
    const saved = JSON.stringify(original)
    const ports = listCircuitPorts(original)
    expect(ports[0].aliases).toContain("R1.pin1")
    expect(ports[1].aliases).toContain("U1.VDDIO1")
    const circuitJson = withNamedExcitations({
      circuitJson: original,
      groundNet: "GND",
      ports: [{ source: "R1.pin1", load: "U1.VDDIO1", current: 0.25 }],
    })
    const model = createPalaceModel({ circuitJson, frequencyHz: 1e6 })
    expect(model.frequencyHz).toBe(1e6)
    expect(model.geometry.excitations[0].current).toBe(0.25)
    expect(model.geometry.excitations[0].return_sink).toEqual({ x: -12, y: 0 })
    expect(model.geometry.excitations[0].return_source).toEqual({ x: 12, y: 0 })
    expect(model.geometry.signals[0].route[0]).toMatchObject({
      route_type: "wire",
      x: -12,
    })
    expect(model.geometry.signals[0].route.at(-1)).toMatchObject({
      route_type: "wire",
      x: 12,
    })
    expect(JSON.stringify(original)).toBe(saved)
    const negative = withNamedExcitations({
      circuitJson: original,
      groundNet: "GND",
      ports: [{ source: "R1.OUT", load: "U1.pin1", current: -0.5 }],
    })
    expect(
      createPalaceModel({ circuitJson: negative, frequencyHz: 1e6 }).geometry
        .segments[0].current,
    ).toBe(-0.5)
  }
})

test("all three TSX signals can be selected with explicit ports and independent currents", async () => {
  const input = await renderFixture(<SlotBoard topGap={4} />, [1, 1, 1])
  const circuitJson = withNamedExcitations({
    circuitJson: input,
    groundNet: "GND",
    ports: [1, 2, 3].map((index) => ({
      source: `SIG${index}_S.pin1`,
      load: `SIG${index}_L.SIGNAL`,
      current: `${index * 100}mA`,
      sourceImpedance: index * 10,
      loadImpedance: `${index * 100}ohm`,
    })),
  })
  expect(
    createPalaceModel({
      circuitJson,
      frequencyHz: 1e6,
    }).geometry.excitations.map((excitation) => excitation.current),
  ).toEqual([0.1, 0.2, 0.3])
  expect(
    createPalaceModel({ circuitJson, frequencyHz: 1e6 }).ports?.map(
      (port) => port.resistance,
    ),
  ).toEqual([10, 100, 20, 200, 30, 300])
  expect(
    circuitJson.filter(
      (element) => element.type === "simulation_return_current_excitation",
    ),
  ).toHaveLength(3)
})

test("named selection rejects missing/ambiguous pins, duplicate traces and unsupported connections", async () => {
  const circuitJson = await renderFixture(<NamedPortBoard />)
  const port = { source: "R1.pin1", load: "U1.VDDIO1", current: 1 }
  const select = (source = circuitJson, ports = [port], groundNet = "GND") =>
    withNamedExcitations({ circuitJson: source, ports, groundNet })
  expect(() => select(circuitJson, [{ ...port, load: "U1.BAD" }])).toThrow(
    "missing",
  )
  expect(() => select(circuitJson, [{ ...port, source: "R2.pin1" }])).toThrow(
    "missing",
  )
  expect(() => select(circuitJson, [{ ...port, source: "R1" }])).toThrow(
    "refdes.pin",
  )
  expect(() => select(circuitJson, [{ ...port, current: Number.NaN }])).toThrow(
    "current",
  )
  expect(() => select(circuitJson, [{ ...port, source: port.load }])).toThrow(
    "different ports",
  )
  expect(() => select(circuitJson, [port, port])).toThrow("more than once")
  expect(() => select(circuitJson, [port], "MISSING")).toThrow("Ground net")
  const component = circuitJson.find(
    (element) => element.type === "source_component" && element.name === "R1",
  )!
  expect(() => select([...circuitJson, component])).toThrow("ambiguous")
  const pcbPort = circuitJson.find((element) => element.type === "pcb_port")!
  expect(() => select([...circuitJson, pcbPort])).toThrow("exactly one PCB")
  expect(() =>
    select(circuitJson.filter((element) => element.type !== "pcb_trace")),
  ).toThrow("continuous PCB trace")
  const disconnected = circuitJson.map((element) =>
    element.type === "pcb_trace"
      ? {
          ...element,
          route: element.route.map((point, index) =>
            index === 0 && point.route_type === "wire"
              ? { ...point, start_pcb_port_id: "pcb_port_wrong" }
              : point,
          ),
        }
      : element,
  )
  expect(() => select(disconnected)).toThrow("continuous PCB trace")
})
