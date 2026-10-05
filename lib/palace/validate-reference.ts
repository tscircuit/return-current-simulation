import type { PalaceReference } from "./types"

export function validatePalaceReference(reference: PalaceReference): void {
  if (
    (reference.femOrder !== 1 && reference.femOrder !== 2) ||
    reference.schemaVersion !== 1 ||
    reference.solver !== "palace" ||
    reference.copperModel !== "volumetric_copper"
  )
    throw new Error("Unsupported Palace reference")
  if (
    ![
      reference.frequencyHz,
      reference.copperThickness,
      reference.layerSeparation,
      reference.cellWidth,
      reference.cellHeight,
      reference.normalizationConditionNumber,
      reference.electricFieldScaleVoltsPerMeter,
    ].every((number) => Number.isFinite(number) && number > 0)
  )
    throw new Error(
      "Palace reference needs finite positive frequency, thickness, cell sizes and normalization condition",
    )
  if (
    ![reference.columns, reference.rows].every(
      (number) => Number.isInteger(number) && number > 0,
    ) ||
    !reference.samples.length
  )
    throw new Error("Palace reference needs a nonempty grid")
  if (
    typeof reference.provenance.geometrySignature !== "string" ||
    !reference.provenance.geometrySignature.length
  )
    throw new Error("Palace reference needs a physical geometry signature")
  const locations = new Set<string>()
  for (const sample of reference.samples) {
    if (
      ![
        sample.x,
        sample.y,
        sample.sheetCurrentXReal,
        sample.sheetCurrentYReal,
        sample.sheetCurrentXImag,
        sample.sheetCurrentYImag,
      ].every(Number.isFinite)
    )
      throw new Error("Non-finite Palace sample")
    const location = `${sample.x},${sample.y}`
    if (locations.has(location))
      throw new Error("Duplicate Palace sample position")
    locations.add(location)
  }
  for (const current of [
    ...reference.sourceCurrents,
    ...reference.loadCurrents,
  ])
    if (![current.real, current.imag].every(Number.isFinite))
      throw new Error("Non-finite Palace port current")
}
