import { expect, test } from "bun:test"
import { createHash } from "node:crypto"
import {
  comparePalaceReference,
  createPalaceModel,
  renderPalaceReferenceSvg,
  simulateReturnCurrent,
  validatePalaceReference,
} from "lib/index"
import { isCopper } from "lib/geometry"
import type { PalaceReference } from "lib/index"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("TSX widens the slot-tip clearance to 4 mm with a fresh 1 MHz Palace solve", async () => {
  const circuitJson = await renderFixture(<SlotBoard topGap={4} />, [1, 1, 1])
  const root = `${import.meta.dir}/../../examples/palace/ground-slot-wide-gap-1mhz`
  const reference: PalaceReference = await Bun.file(
    `${root}/reference.json`,
  ).json()
  validatePalaceReference(reference)
  const recordedCircuit = await Bun.file(`${root}/circuit.json`).text()
  expect(createHash("sha256").update(recordedCircuit).digest("hex")).toBe(
    reference.provenance.circuitSha256,
  )
  const narrow: PalaceReference = await Bun.file(
    `${import.meta.dir}/../../examples/palace/ground-slot-1mhz/reference.json`,
  ).json()
  expect(reference.provenance.meshSha256).not.toBe(narrow.provenance.meshSha256)
  const model = createPalaceModel({ circuitJson, frequencyHz: 1e6 })
  expect(isCopper({ x: -4.5, y: 16.1 }, model.geometry)).toBe(true)
  expect(isCopper({ x: -4.5, y: 15.9 }, model.geometry)).toBe(false)
  expect(Math.max(...model.geometry.boardOutline.map((point) => point.y))).toBe(
    20,
  )
  expect(reference.frequencyHz).toBe(1e6)
  expect(reference.columns).toBe(200)
  expect(reference.rows).toBe(200)
  const result = simulateReturnCurrent({
    circuitJson,
    cellSize: reference.cellWidth,
    contactRadius: 0.6,
  })
  expect(
    comparePalaceReference(result, { reference }).comparedSamples,
  ).toBeGreaterThan(30_000)
  expect(() => comparePalaceReference(result, { reference: narrow })).toThrow(
    "geometry",
  )
  const flux = await Bun.file(`${root}/flux-check.json`).json()
  expect(flux.specification.yMin).toBe(16)
  expect(flux.specification.yMax).toBe(20)
  expect(flux.provenance.meshSha256).toBe(reference.provenance.meshSha256)
  expect(flux.relativeComplexBalanceError).toBeLessThan(0.05)
  for (const phaseDegrees of [0, 90])
    await expect(
      renderPalaceReferenceSvg(result, {
        reference,
        title: "Palace: 4 mm clearance above the slot",
        phaseDegrees,
        width: 900,
        height: 1000,
        maxCurrentDensity: 50,
        vectorSpacing: Math.round(1.5 / reference.cellWidth),
      }),
    ).toMatchSvgSnapshot(import.meta.path, `wide-gap-phase-${phaseDegrees}`)
})
