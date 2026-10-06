import { expect, test } from "bun:test"
import { createHash } from "node:crypto"
import { createPalaceModel, renderPalaceModelSvg } from "lib/index"
import type { PalaceReference } from "lib/index"
import { multilayerModel } from "tests/fixtures/renderMultilayerBoard"
import { fourLayerStackup } from "tests/fixtures/MultilayerBoard"

test("TSX multilayer fields match completed Palace solves and render the selected foil", async () => {
  const { circuitJson, model } = await multilayerModel()
  const bottomModel = createPalaceModel({
    circuitJson,
    stackup: fourLayerStackup,
    sampleLayer: "bottom",
    frequencyHz: 1e6,
    order: 1,
    meshSize: 2,
    airPadding: 2,
  })
  const references: PalaceReference[] = []
  for (const [layer, layerModel] of [
    ["inner2", model],
    ["bottom", bottomModel],
  ] as const) {
    const root = `${import.meta.dir}/../../examples/palace/multilayer-${layer}-1mhz`
    const reference: PalaceReference = await Bun.file(
      `${root}/reference.json`,
    ).json()
    references.push(reference)
    for (const [file, hash] of [
      ["circuit.json", reference.provenance.circuitSha256],
      ["model.json", reference.provenance.modelSha256],
    ] as const)
      expect(
        createHash("sha256")
          .update(await Bun.file(`${root}/${file}`).text())
          .digest("hex"),
      ).toBe(hash)
    expect(reference.sampleLayer).toBe(layer)
    expect(reference.sourceCurrents[0].real).toBeCloseTo(0.005, 12)
    expect(reference.sourceCurrents[0].imag).toBeCloseTo(0, 12)
    expect(
      Math.abs(reference.loadCurrents[0].real - 0.005) / 0.005,
    ).toBeLessThan(0.02)
    const middleReturn = reference.samples
      .filter((p) => Math.abs(p.x) < 0.2)
      .reduce((sum, p) => sum + p.sheetCurrentXReal, 0)
    expect(middleReturn).toBeLessThan(0)
    const svg = renderPalaceModelSvg(layerModel, {
      reference,
      maxCurrentDensity: 0.2,
      title: `Four-layer board: ${layer} return at 1 MHz`,
      vectorSpacing: 5,
    })
    expect(svg).toContain(`layer = ${layer}`)
    expect(svg).toContain("f = 1 MHz")
    await expect(svg).toMatchSvgSnapshot(
      import.meta.path,
      `multilayer-${layer}-1mhz`,
    )
  }
  // Selecting a different foil does not change physical conductor geometry.
  expect(model.multilayer!.copper).toEqual(bottomModel.multilayer!.copper)
  expect(model.multilayer!.barrels).toEqual(bottomModel.multilayer!.barrels)
  expect(references[0].copperThickness).toBeCloseTo(0.015, 12)
  expect(references[1].copperThickness).toBeCloseTo(0.035, 12)
  expect(() =>
    renderPalaceModelSvg(model, { reference: references[1] }),
  ).toThrow("differs")
})
