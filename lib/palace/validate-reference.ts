import type { PalaceReference } from "./types"

export function validatePalaceReference(reference: PalaceReference): void {
  if (
    (reference.femOrder !== 1 && reference.femOrder !== 2) ||
    reference.schemaVersion !== 1 ||
    reference.solver !== "palace" ||
    !["volumetric_copper", "surface_impedance_copper"].includes(
      reference.copperModel,
    ) ||
    (reference.sampleLayer !== undefined &&
      !/^(top|bottom|inner[1-8])$/.test(reference.sampleLayer))
  )
    throw new Error("Unsupported Palace reference")
  if (
    reference.copperModel === "surface_impedance_copper" &&
    (reference.samplingMethod !== "sum_foil_face_surface_currents" ||
      !Number.isFinite(reference.surfaceCurrentScaleAmpsPerMm) ||
      reference.surfaceCurrentScaleAmpsPerMm! <= 0)
  )
    throw new Error(
      "Surface impedance reference must identify its face-current sampling and finite positive A/mm scale",
    )
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
