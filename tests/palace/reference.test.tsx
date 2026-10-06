import { expect, test } from "bun:test"
import { createHash } from "node:crypto"
import {
  createPalaceModel,
  comparePalaceReference,
  comparePalaceRuns,
  renderPalaceReferenceSvg,
  simulateReturnCurrent,
  validatePalaceReference,
} from "lib/index"
import type { PalaceReference } from "lib/index"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

const exampleRoot = `${import.meta.dir}/../../examples/palace`

test("TSX slot circuit matches Palace evidence and preserves complex currents", async () => {
  const circuitJson = await renderFixture(<SlotBoard />, [1, 1, 1])
  const reference: PalaceReference = await Bun.file(
    `${exampleRoot}/ground-slot-1mhz/reference.json`,
  ).json()
  validatePalaceReference(reference)
  expect(reference.columns).toBe(200)
  expect(reference.rows).toBe(200)
  expect(reference.cellWidth).toBe(0.2)
  const recordedCircuitText = await Bun.file(
    `${exampleRoot}/ground-slot-1mhz/circuit.json`,
  ).text()
  expect(createHash("sha256").update(recordedCircuitText).digest("hex")).toBe(
    reference.provenance.circuitSha256,
  )
  const recordedCircuit = JSON.parse(recordedCircuitText)
  const model = createPalaceModel({ circuitJson, frequencyHz: 1e6 })
  const recordedModel = createPalaceModel({
    circuitJson: recordedCircuit,
    frequencyHz: 1e6,
  })
  expect(model.geometry).toEqual(recordedModel.geometry)
  expect(model.topPads).toEqual(recordedModel.topPads)
  const result = simulateReturnCurrent({
    circuitJson,
    cellSize: reference.cellWidth,
    contactRadius: 0.6,
  })
  const comparison = comparePalaceReference(result, { reference })
  expect(comparison.frequencyHz).toBe(1e6)
  expect(comparison.approximationFrequencyModel).toBe("none")
  expect(comparison.relativeComplexL2Error).toBeGreaterThan(
    comparison.relativeRealL2Error,
  )
  expect(comparison.comparedSamples).toBeGreaterThan(5000)
  for (const current of reference.sourceCurrents) {
    expect(current.real).toBeCloseTo(1, 10)
    expect(current.imag).toBeCloseTo(0, 10)
  }
  expect(
    reference.samples.some(
      (sample) => Math.abs(sample.sheetCurrentXImag) > 0.01,
    ),
  ).toBe(true)
  expect(() =>
    comparePalaceReference(result, {
      reference: { ...reference, copperThickness: 0.07 },
    }),
  ).toThrow("identical")
  expect(() =>
    comparePalaceReference(result, {
      reference: { ...reference, samples: [...reference.samples].reverse() },
    }),
  ).toThrow("coordinates")
  expect(() =>
    validatePalaceReference({
      ...reference,
      samples: [...reference.samples, reference.samples[0]],
    }),
  ).toThrow("Duplicate")
  expect(() =>
    comparePalaceReference(result, {
      reference: {
        ...reference,
        provenance: { ...reference.provenance, geometrySignature: "[]" },
      },
    }),
  ).toThrow("geometry")
  for (const phaseDegrees of [0, 90]) {
    const svg = renderPalaceReferenceSvg(result, {
      reference,
      phaseDegrees,
      width: 900,
      height: 1000,
      maxCurrentDensity: 50,
      vectorSpacing: Math.max(1, Math.round(1.5 / reference.cellWidth)),
    })
    expect(svg).toContain("f = 1 MHz")
    expect(svg).toContain("peak phasors")
    await expect(svg).toMatchSvgSnapshot(
      import.meta.path,
      `palace-slot-phase-${phaseDegrees}`,
    )
  }
})

test("straight TSX circuit matches Palace units and return polarity", async () => {
  const circuitJson = await renderFixture(<StraightBoard />)
  const reference: PalaceReference = await Bun.file(
    `${exampleRoot}/straight-1mhz/reference.json`,
  ).json()
  const recordedCircuitText = await Bun.file(
    `${exampleRoot}/straight-1mhz/circuit.json`,
  ).text()
  expect(createHash("sha256").update(recordedCircuitText).digest("hex")).toBe(
    reference.provenance.circuitSha256,
  )
  const recordedCircuit = JSON.parse(recordedCircuitText)
  const model = createPalaceModel({ circuitJson, frequencyHz: 1e6 })
  const recordedModel = createPalaceModel({
    circuitJson: recordedCircuit,
    frequencyHz: 1e6,
  })
  expect(model.geometry).toEqual(recordedModel.geometry)
  expect(model.topPads).toEqual(recordedModel.topPads)
  const result = simulateReturnCurrent({
    circuitJson,
    cellSize: reference.cellWidth,
    contactRadius: 0.6,
  })
  expect(
    comparePalaceReference(result, { reference }).rmsSheetCurrentErrorAmpsPerMm,
  ).toBeGreaterThan(0)
  const centralSamples = reference.samples.filter(
    (sample) => Math.abs(sample.x) < 4,
  )
  // Cross-section flux averaged over 8 mm, with the reference grid midpoint quadrature.
  // Allows finite FEM/grid error; this is separate from approximation accuracy.
  const meanReturnFluxAmps =
    centralSamples.reduce(
      (sum, sample) => sum + sample.sheetCurrentXReal * reference.cellHeight,
      0,
    ) / new Set(centralSamples.map((sample) => sample.x)).size
  expect(meanReturnFluxAmps).toBeCloseTo(-1, 1)
  expect(reference.loadCurrents[0].real).toBeCloseTo(1, 2)
})

test("Palace refinement is reported without relabelling it ground truth", async () => {
  const coarse: PalaceReference = await Bun.file(
    `${exampleRoot}/ground-slot-coarse-1mhz/reference.json`,
  ).json()
  const fine: PalaceReference = await Bun.file(
    `${exampleRoot}/ground-slot-1mhz/reference.json`,
  ).json()
  const refinement = comparePalaceRuns(coarse, fine)
  expect(refinement.relativeComplexL2Change).toBeGreaterThan(0)
  expect(comparePalaceRuns(fine, fine).relativeComplexL2Change).toBe(0)
  expect(() =>
    comparePalaceRuns(coarse, { ...fine, frequencyHz: 1e5 }),
  ).toThrow("same circuit")
  const report = await Bun.file(`${exampleRoot}/refinement.json`).json()
  expect(report.isGroundTruth).toBe(false)
  expect(report.fluxCheck.specification.expectedRealAmps).toBe(-3)
  expect(report.fluxCheck.relativeComplexBalanceError).toBeLessThan(0.05)
})

test("100 kHz Palace evidence is frequency-labelled and changes the field", async () => {
  const circuitJson = await renderFixture(<SlotBoard />, [1, 1, 1])
  const reference: PalaceReference = await Bun.file(
    `${exampleRoot}/ground-slot-100khz/reference.json`,
  ).json()
  const oneMhz: PalaceReference = await Bun.file(
    `${exampleRoot}/ground-slot-order1-1mhz/reference.json`,
  ).json()
  expect(reference.provenance.meshSha256).toBe(oneMhz.provenance.meshSha256)
  const result = simulateReturnCurrent({
    circuitJson,
    cellSize: reference.cellWidth,
    contactRadius: 0.6,
  })
  const comparison = comparePalaceReference(result, { reference })
  expect(comparison.frequencyHz).toBe(1e5)
  expect(
    reference.samples.some(
      (sample, index) =>
        Math.abs(
          sample.sheetCurrentXImag - oneMhz.samples[index].sheetCurrentXImag,
        ) > 0.01,
    ),
  ).toBe(true)
  const svg = renderPalaceReferenceSvg(result, {
    reference,
    width: 900,
    height: 1000,
    maxCurrentDensity: 50,
    vectorSpacing: Math.max(1, Math.round(1.5 / reference.cellWidth)),
  })
  expect(svg).toContain("f = 0.1 MHz")
  await expect(svg).toMatchSvgSnapshot(import.meta.path, "palace-slot-100khz")
})
