import type { PalaceReference } from "./types"
import { validatePalaceReference } from "./validate-reference"

/** A numerical refinement check, not proof that the physical model is correct. */
export function comparePalaceRuns(
  coarse: PalaceReference,
  fine: PalaceReference,
) {
  validatePalaceReference(coarse)
  validatePalaceReference(fine)
  if (
    coarse.frequencyHz !== fine.frequencyHz ||
    coarse.copperThickness !== fine.copperThickness ||
    coarse.samples.length !== fine.samples.length ||
    coarse.provenance.geometrySignature !== fine.provenance.geometrySignature
  )
    throw new Error(
      "Refinement requires the same circuit, frequency and sampling positions",
    )
  let errorSquared = 0
  let fineNormSquared = 0
  for (const [index, sample] of fine.samples.entries()) {
    const coarseSample = coarse.samples[index]
    if (Math.hypot(sample.x - coarseSample.x, sample.y - coarseSample.y) > 1e-8)
      throw new Error("Refinement sample positions differ")
    for (const component of [
      "sheetCurrentXReal",
      "sheetCurrentYReal",
      "sheetCurrentXImag",
      "sheetCurrentYImag",
    ] as const) {
      errorSquared += (coarseSample[component] - sample[component]) ** 2
      fineNormSquared += sample[component] ** 2
    }
  }
  if (!fineNormSquared)
    throw new Error("Refinement requires a nonzero reference field")
  return {
    frequencyHz: fine.frequencyHz,
    coarseFemOrder: coarse.femOrder,
    fineFemOrder: fine.femOrder,
    samples: fine.samples.length,
    relativeComplexL2Change: Math.sqrt(errorSquared / fineNormSquared),
    coarseMeshSha256: coarse.provenance.meshSha256,
    fineMeshSha256: fine.provenance.meshSha256,
  }
}
