import { expect, test } from "bun:test"
import { Circuit } from "@tscircuit/core"
import {
  withNamedExcitations,
  createPalaceModel,
  parseReturnCurrentCircuitJson,
  simulateReturnCurrent,
} from "lib/index"
import { ExplicitPortBoard } from "tests/fixtures/ExplicitPortBoard"

export async function explicitBoard(
  options: Parameters<typeof ExplicitPortBoard>[0] = {},
) {
  const circuit = new Circuit()
  circuit.add(<ExplicitPortBoard {...options} />)
  await circuit.renderUntilSettled()
  return parseReturnCurrentCircuitJson(circuit.getCircuitJson())
}

const port = {
  source: "U1.OUT",
  sourceReference: "U1.GND",
  load: "U2.IN",
  loadReference: "U2.GND",
  current: "5mA",
  sourceImpedance: "25ohm",
  loadImpedance: "100ohm",
}

test("two-terminal ports resolve real TSX ground pads/vias and independent impedances", async () => {
  for (const referenceLayer of ["top", "bottom"] as const) {
    const original = await explicitBoard({ referenceLayer })
    const saved = JSON.stringify(original)
    const circuitJson = withNamedExcitations({
      circuitJson: original,
      groundNet: "GND",
      ports: [port],
    })
    const model = createPalaceModel({
      circuitJson: parseReturnCurrentCircuitJson(circuitJson),
      frequencyHz: 1e6,
    })
    expect(model.geometry.excitations[0].current).toBe(0.005)
    expect(model.ports?.map((port) => port.resistance)).toEqual([25, 100])
    expect(model.ports?.map((port) => port.referenceLayer)).toEqual([
      referenceLayer,
      referenceLayer,
    ])
    expect(model.ports?.[0].signal).toEqual({ x: -2, y: 0 })
    expect(model.ports?.[0].reference).toEqual({ x: -2, y: 1.5 })
    expect(model.groundVias).toHaveLength(referenceLayer === "top" ? 2 : 0)
    expect(model.topGroundPads).toHaveLength(referenceLayer === "top" ? 2 : 0)
    expect(model.geometry.cutouts).toHaveLength(
      referenceLayer === "top" ? 2 : 0,
    )
    expect(JSON.stringify(original)).toBe(saved)
    expect(() => simulateReturnCurrent({ circuitJson })).toThrow(
      "require Palace",
    )
  }
})

test("explicit references reject signal nets, missing ground copper connection and invalid impedance", async () => {
  const input = await explicitBoard()
  expect(() =>
    withNamedExcitations({
      circuitJson: input,
      groundNet: "GND",
      ports: [{ ...port, sourceReference: "U2.IN" }],
    }),
  ).toThrow("not connected")
  expect(() =>
    withNamedExcitations({
      circuitJson: input,
      groundNet: "GND",
      ports: [{ ...port, loadImpedance: "0ohm" }],
    }),
  ).toThrow("greater than zero")
  const noVias = withNamedExcitations({
    circuitJson: input.filter((element) => element.type !== "pcb_via"),
    groundNet: "GND",
    ports: [port],
  })
  expect(() =>
    createPalaceModel({ circuitJson: noVias, frequencyHz: 1e6 }),
  ).toThrow("real concentric ground via")
  const wrongVia = input.map((element) =>
    element.type === "pcb_via"
      ? { ...element, source_net_id: "wrong_net" }
      : element,
  )
  expect(() =>
    createPalaceModel({
      circuitJson: withNamedExcitations({
        circuitJson: wrongVia,
        groundNet: "GND",
        ports: [port],
      }),
      frequencyHz: 1e6,
    }),
  ).toThrow("ground vias")
  const mismatched = noVias.map((element) =>
    element.type === "simulation_return_current_excitation"
      ? {
          ...element,
          source_port: {
            ...element.source_port!,
            signal_pcb_port_id: "missing",
          },
        }
      : element,
  )
  expect(() =>
    createPalaceModel({ circuitJson: mismatched, frequencyHz: 1e6 }),
  ).toThrow("does not match")
})
