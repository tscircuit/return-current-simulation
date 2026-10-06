import { join, resolve } from "node:path"
import {
  MultilayerBoard,
  fourLayerStackup,
} from "tests/fixtures/MultilayerBoard"
import { parseCopperLayer } from "lib/palace/stackup"
import { Circuit } from "@tscircuit/core"
import { runPalaceSimulation } from "lib/palace"

const circuit = new Circuit()
circuit.add(<MultilayerBoard innerPlane />)
await circuit.renderUntilSettled()
const outputDirectory = resolve(process.argv[2] ?? "work/multilayer-1mhz")
await runPalaceSimulation({
  circuitJson: circuit.getCircuitJson(),
  stackup: fourLayerStackup,
  sampleLayer: parseCopperLayer(process.argv[3] ?? "inner2"),
  frequencyHz: 1e6,
  groundNet: "GND",
  ports: [
    {
      source: "U1.OUT",
      sourceReference: "U1.GND",
      load: "U2.IN",
      loadReference: "U2.GND",
      current: "5mA",
      sourceImpedance: 25,
      loadImpedance: 100,
    },
  ],
  order: 1,
  meshSize: 2,
  airPadding: 2,
  cellSize: 0.05,
  processes: 2,
  python: process.env.PALACE_PYTHON,
  outputDirectory,
})
console.log(`Saved ${join(outputDirectory, "palace.png")}`)
