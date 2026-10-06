import { Circuit } from "@tscircuit/core"
import {
  createPalaceModel,
  withNamedExcitations,
  parseReturnCurrentCircuitJson,
} from "lib/index"
import { MultilayerBoard, fourLayerStackup } from "./MultilayerBoard"

export async function multilayerCircuit(
  options: { referenceLayer?: "top" | "inner2" } = {},
) {
  const circuit = new Circuit()
  circuit.add(
    <MultilayerBoard innerPlane referenceLayer={options.referenceLayer} />,
  )
  await circuit.renderUntilSettled()
  return parseReturnCurrentCircuitJson(circuit.getCircuitJson())
}

export async function multilayerModel(
  options: { referenceLayer?: "top" | "inner2" } = {},
) {
  const circuitJson = withNamedExcitations({
    circuitJson: await multilayerCircuit(options),
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
  })
  return {
    circuitJson,
    model: createPalaceModel({
      circuitJson,
      stackup: fourLayerStackup,
      sampleLayer: "inner2",
      frequencyHz: 1e6,
      order: 1,
      meshSize: 2,
      airPadding: 2,
    }),
  }
}
