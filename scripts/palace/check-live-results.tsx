import { comparePalaceRuns } from "lib/palace/compare-palace-runs"
import type { PalaceReference } from "lib/palace/types"
import { palaceGeometrySignature } from "lib/palace/geometry-signature"
import { createPalaceModel } from "lib/palace/create-palace-model"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

const destination = process.argv[2] ?? "work/palace"
for (const [name, element, currents] of [
  ["straight-1mhz", <StraightBoard />, [1]],
  ["ground-slot-1mhz", <SlotBoard />, [1, 1, 1]],
] as const) {
  const circuitJson = await renderFixture(element, currents)
  const reference: PalaceReference = await Bun.file(
    `${destination}/${name}/reference.json`,
  ).json()
  const recorded: PalaceReference = await Bun.file(
    `examples/palace/${name}/reference.json`,
  ).json()
  const model = createPalaceModel({ circuitJson, frequencyHz: 1e6 })
  if (
    reference.provenance.geometrySignature !==
    palaceGeometrySignature(model.geometry)
  )
    throw new Error(`${name}: fresh Palace geometry does not match TSX`)
  const change = comparePalaceRuns(recorded, reference).relativeComplexL2Change
  if (change > 0.3)
    throw new Error(
      `${name}: fresh Palace field differs by ${(100 * change).toFixed(1)}%; inspect raw fields before updating evidence`,
    )
  const flux = await Bun.file(`${destination}/${name}/flux-check.json`).json()
  if (
    flux.provenance.meshSha256 !== reference.provenance.meshSha256 ||
    flux.provenance.modelSha256 !== reference.provenance.modelSha256
  )
    throw new Error(`${name}: flux check does not belong to this Palace run`)
  const balanceError = flux.relativeComplexBalanceError
  if (!Number.isFinite(balanceError) || balanceError > 0.05)
    throw new Error(
      `${name}: dense return-current balance error ${(100 * balanceError).toFixed(1)}% exceeds 5%`,
    )
  console.log({
    name,
    relativeFieldChange: change,
    returnFluxAmps: { real: flux.meanRealAmps, imag: flux.meanImagAmps },
    relativeBalanceError: balanceError,
  })
}
