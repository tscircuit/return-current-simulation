import { palaceGeometrySignature } from "./geometry-signature"
import { segmentInCopper } from "../geometry"
import type { SimulationResult } from "../types"
import type { PalaceReference } from "./types"
import { validatePalaceReference } from "./validate-reference"

/** Compares the fixed-current approximation with a frequency-dependent phasor.
 * No fit, global phase rotation, or peak normalization is applied to the fields.
 */
export function comparePalaceReference(
  result: SimulationResult,
  options: {
    reference: PalaceReference
    edgeExclusionMm?: number
    contactExclusionMm?: number
  },
) {
  const { reference } = options
  validatePalaceReference(reference)
  if (
    palaceGeometrySignature(result.geometry) !==
    reference.provenance.geometrySignature
  )
    throw new Error(
      "Palace reference geometry differs from the simulation geometry",
    )
  const edgeExclusionMm = options.edgeExclusionMm ?? 0.5
  const contactExclusionMm = options.contactExclusionMm ?? 1
  if (
    ![edgeExclusionMm, contactExclusionMm].every(
      (number) => Number.isFinite(number) && number >= 0,
    )
  )
    throw new Error("Exclusion distances must be finite and nonnegative")
  if (
    result.copperThickness !== reference.copperThickness ||
    result.layerSeparation !== reference.layerSeparation ||
    result.cellWidth !== reference.cellWidth ||
    result.cellHeight !== reference.cellHeight ||
    result.columns !== reference.columns ||
    result.rows !== reference.rows ||
    result.nodes.length !== reference.samples.length
  )
    throw new Error(
      "Palace and approximation must use identical thickness and sample grids",
    )
  if (reference.sourceCurrents.length !== result.geometry.excitations.length)
    throw new Error("Palace and approximation source counts differ")
  for (const [index, current] of reference.sourceCurrents.entries())
    if (
      Math.abs(current.real - result.geometry.excitations[index].current) >
        1e-8 ||
      Math.abs(current.imag) > 1e-8
    )
      throw new Error("Palace and approximation source currents differ")
  let comparedSamples = 0
  let complexSquaredError = 0
  let realSquaredError = 0
  let magnitudeSquaredError = 0
  let referenceSquaredNorm = 0
  let maxAbsoluteDensityError = 0
  const contacts = result.geometry.excitations.flatMap((excitation) => [
    excitation.return_source,
    excitation.return_sink,
  ])
  for (const [index, sample] of reference.samples.entries()) {
    const node = result.nodes[index]
    if (Math.hypot(node.x - sample.x, node.y - sample.y) > 1e-8)
      throw new Error(
        "Palace sample ordering/coordinates differ from the approximation",
      )
    if (
      contacts.some(
        (contact) =>
          Math.hypot(contact.x - node.x, contact.y - node.y) <
          contactExclusionMm,
      )
    )
      continue
    if (
      [
        { x: node.x - edgeExclusionMm, y: node.y },
        { x: node.x + edgeExclusionMm, y: node.y },
        { x: node.x, y: node.y - edgeExclusionMm },
        { x: node.x, y: node.y + edgeExclusionMm },
      ].some((end) => !segmentInCopper({ start: node, end }, result.geometry))
    )
      continue
    const realError =
      (node.sheetCurrentX - sample.sheetCurrentXReal) ** 2 +
      (node.sheetCurrentY - sample.sheetCurrentYReal) ** 2
    const imagNorm =
      sample.sheetCurrentXImag ** 2 + sample.sheetCurrentYImag ** 2
    const norm =
      sample.sheetCurrentXReal ** 2 + sample.sheetCurrentYReal ** 2 + imagNorm
    const magnitudeError =
      Math.hypot(node.sheetCurrentX, node.sheetCurrentY) - Math.sqrt(norm)
    complexSquaredError += realError + imagNorm
    realSquaredError += realError
    magnitudeSquaredError += magnitudeError ** 2
    referenceSquaredNorm += norm
    maxAbsoluteDensityError = Math.max(
      maxAbsoluteDensityError,
      Math.abs(magnitudeError) / reference.copperThickness,
    )
    comparedSamples++
  }
  if (!comparedSamples || !referenceSquaredNorm)
    throw new Error(
      "Comparison needs nonzero reference fields away from excluded contacts and edges",
    )
  return {
    referenceSolver: `Palace ${reference.solverVersion}`,
    frequencyHz: reference.frequencyHz,
    approximationFrequencyModel: "none" as const,
    comparedSamples,
    excludedSamples: reference.samples.length - comparedSamples,
    edgeExclusionMm,
    contactExclusionMm,
    relativeComplexL2Error: Math.sqrt(
      complexSquaredError / referenceSquaredNorm,
    ),
    relativeRealL2Error: Math.sqrt(realSquaredError / referenceSquaredNorm),
    relativeMagnitudeL2Error: Math.sqrt(
      magnitudeSquaredError / referenceSquaredNorm,
    ),
    rmsSheetCurrentErrorAmpsPerMm: Math.sqrt(
      complexSquaredError / comparedSamples,
    ),
    maxAbsoluteEquivalentDensityErrorAmpsPerMm2: maxAbsoluteDensityError,
  }
}
