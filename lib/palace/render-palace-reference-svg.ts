import { palaceGeometrySignature } from "./geometry-signature"
import { renderCurrentFieldSvg } from "../render-return-current-svg"
import type { RenderOptions, SimulationResult } from "../types"
import type { PalaceReference } from "./types"
import { validatePalaceReference } from "./validate-reference"

export function renderPalaceReferenceSvg(
  result: SimulationResult,
  options: RenderOptions & {
    reference: PalaceReference
    phaseDegrees?: number
  },
): string {
  const { reference } = options
  validatePalaceReference(reference)
  if (
    palaceGeometrySignature(result.geometry) !==
    reference.provenance.geometrySignature
  )
    throw new Error(
      "Palace reference geometry differs from the simulation geometry",
    )
  if (
    reference.layerSeparation !== result.layerSeparation ||
    reference.samples.length !== result.nodes.length ||
    reference.columns !== result.columns ||
    reference.rows !== result.rows ||
    reference.cellWidth !== result.cellWidth ||
    reference.cellHeight !== result.cellHeight ||
    reference.copperThickness !== result.copperThickness
  )
    throw new Error("Palace rendering requires the matching simulation grid")
  if (
    reference.sourceCurrents.length !== result.geometry.excitations.length ||
    reference.sourceCurrents.some(
      (current, index) =>
        Math.abs(current.real - result.geometry.excitations[index].current) >
          1e-8 || Math.abs(current.imag) > 1e-8,
    )
  )
    throw new Error("Palace rendering requires matching source currents")
  const phaseDegrees = options.phaseDegrees ?? 0
  if (!Number.isFinite(phaseDegrees))
    throw new Error("phaseDegrees must be finite")
  const phase = (phaseDegrees * Math.PI) / 180
  const nodes = reference.samples.map((sample, index) => {
    const node = result.nodes[index]
    if (Math.hypot(node.x - sample.x, node.y - sample.y) > 1e-8)
      throw new Error(
        "Palace sample coordinates differ from the rendering grid",
      )
    return {
      ...node,
      sheetCurrentX:
        sample.sheetCurrentXReal * Math.cos(phase) -
        sample.sheetCurrentXImag * Math.sin(phase),
      sheetCurrentY:
        sample.sheetCurrentYReal * Math.cos(phase) -
        sample.sheetCurrentYImag * Math.sin(phase),
      currentDensity:
        Math.hypot(
          sample.sheetCurrentXReal,
          sample.sheetCurrentYReal,
          sample.sheetCurrentXImag,
          sample.sheetCurrentYImag,
        ) / reference.copperThickness,
    }
  })
  return renderCurrentFieldSvg(
    {
      ...result,
      nodes,
      diagnostics: {
        converged: true,
        maxCurrentDensity: Math.max(
          ...nodes.map((node) => node.currentDensity),
        ),
      },
    },
    {
      ...options,
      title: options.title ?? "Palace ground-plane return current",
      description:
        "Palace driven Maxwell reference. Colors show magnitude of the complex conduction-current vector averaged through copper thickness. Arrows show the real instantaneous field at the selected phase. Copper is an explicitly meshed conductive volume.",
      subtitle: `Palace ${reference.solverVersion} · f = ${reference.frequencyHz / 1e6} MHz · |K|/t (A/mm²) · peak phasors`,
      gridLabel: "sample grid",
      footer: `FEM order ${reference.femOrder} · conductive copper volumes · arrows at ${phaseDegrees}° · air/substrate domain · source currents normalized`,
    },
  )
}
