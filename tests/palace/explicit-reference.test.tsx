import { expect, test } from "bun:test"
import { Circuit } from "@tscircuit/core"
import { createHash } from "node:crypto"
import { ExplicitPortBoard } from "tests/fixtures/ExplicitPortBoard"
import {
  withNamedExcitations,
  createPalaceModel,
  renderPalaceModelSvg,
} from "lib/index"
import type { PalaceReference } from "lib/index"

test("TSX two-terminal ports match a completed Palace solve, return polarity and visual snapshot", async () => {
  const circuit = new Circuit()
  circuit.add(<ExplicitPortBoard />)
  await circuit.renderUntilSettled()
  const input = withNamedExcitations({
    circuitJson: circuit.getCircuitJson(),
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
  const model = createPalaceModel({
    circuitJson: input,
    frequencyHz: 1e6,
    order: 1,
    meshSize: 2,
    airPadding: 2,
  })
  const root = `${import.meta.dir}/../../examples/palace/explicit-ports-1mhz`
  const reference: PalaceReference = await Bun.file(
    `${root}/reference.json`,
  ).json()
  for (const [file, hash] of [
    ["circuit.json", reference.provenance.circuitSha256],
    ["model.json", reference.provenance.modelSha256],
  ] as const)
    expect(
      createHash("sha256")
        .update(await Bun.file(`${root}/${file}`).text())
        .digest("hex"),
    ).toBe(hash)
  expect(reference.sourceCurrents[0].real).toBeCloseTo(0.005, 12)
  expect(reference.sourceCurrents[0].imag).toBeCloseTo(0, 12)
  expect(reference.loadCurrents[0].real).toBeCloseTo(0.005, 6)
  expect(
    reference.samples
      .filter(
        (sample) => Math.abs(sample.x) < 0.5 && Math.abs(sample.y - 1.5) < 0.5,
      )
      .reduce((sum, sample) => sum + sample.sheetCurrentXReal, 0),
  ).toBeLessThan(0)
  const svg = renderPalaceModelSvg(model, {
    reference,
    maxCurrentDensity: 0.2,
    title: "Two-terminal ports: 5 mA at 1 MHz",
    vectorSpacing: 5,
  })
  expect(svg).toContain("S1+")
  expect(svg).toContain("S1−")
  expect(svg).toContain("f = 1 MHz")
  await expect(svg).toMatchSvgSnapshot(import.meta.path, "explicit-ports-1mhz")
})
