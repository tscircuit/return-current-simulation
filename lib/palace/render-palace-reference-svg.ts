import { palaceGeometrySignature } from "./geometry-signature"
import { renderCurrentFieldSvg } from "../render-return-current-svg"
import type { RenderOptions, SimulationResult } from "../types"
import type { PalaceModel, PalaceReference } from "./types"
import { validatePalaceReference } from "./validate-reference"

type PalaceRenderOptions = RenderOptions & {
  reference: PalaceReference
  phaseDegrees?: number
}

type PalaceRenderGrid = Pick<
  SimulationResult,
  | "geometry"
  | "nodes"
  | "columns"
  | "rows"
  | "cellWidth"
  | "cellHeight"
  | "bounds"
  | "copperThickness"
  | "layerSeparation"
>

/** Render the Palace model directly, without constructing an approximation solve. */
export function renderPalaceModelSvg(
  model: PalaceModel,
  options: PalaceRenderOptions,
): string {
  const { reference } = options
  validatePalaceReference(reference)
  if (
    reference.frequencyHz !== model.frequencyHz ||
    reference.femOrder !== model.order
  )
    throw new Error(
      "Palace model frequency or FEM order differs from reference",
    )
  const outline = model.geometry.boardOutline
  const bounds = {
    minX: Math.min(...outline.map((point) => point.x)),
    maxX: Math.max(...outline.map((point) => point.x)),
    minY: Math.min(...outline.map((point) => point.y)),
    maxY: Math.max(...outline.map((point) => point.y)),
  }
  if (
    Math.abs(
      reference.columns * reference.cellWidth - (bounds.maxX - bounds.minX),
    ) > 1e-8 ||
    Math.abs(
      reference.rows * reference.cellHeight - (bounds.maxY - bounds.minY),
    ) > 1e-8
  )
    throw new Error("Palace sample grid does not fit the model bounds")
  const nodes = reference.samples.map((sample) => {
    const column = Math.round(
      (sample.x - bounds.minX) / reference.cellWidth - 0.5,
    )
    const row = Math.round(
      (sample.y - bounds.minY) / reference.cellHeight - 0.5,
    )
    if (
      column < 0 ||
      column >= reference.columns ||
      row < 0 ||
      row >= reference.rows ||
      Math.abs(
        sample.x - (bounds.minX + (column + 0.5) * reference.cellWidth),
      ) > 1e-8 ||
      Math.abs(sample.y - (bounds.minY + (row + 0.5) * reference.cellHeight)) >
        1e-8
    )
      throw new Error("Palace sample is not at a grid cell center")
    return {
      x: sample.x,
      y: sample.y,
      column,
      row,
      injection: 0,
      sheetCurrentX: 0,
      sheetCurrentY: 0,
      currentDensity: 0,
    }
  })
  return renderPalaceReferenceSvg(
    {
      geometry: model.geometry,
      bounds,
      nodes,
      columns: reference.columns,
      rows: reference.rows,
      cellWidth: reference.cellWidth,
      cellHeight: reference.cellHeight,
      copperThickness: model.copperThickness,
      layerSeparation: model.layerSeparation,
    },
    options,
  )
}

export function renderPalaceReferenceSvg(
  result: PalaceRenderGrid,
  options: PalaceRenderOptions,
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
  let maxCurrentDensity = 0
  const nodes = reference.samples.map((sample, index) => {
    const node = result.nodes[index]
    if (Math.hypot(node.x - sample.x, node.y - sample.y) > 1e-8)
      throw new Error(
        "Palace sample coordinates differ from the rendering grid",
      )
    const currentDensity =
      Math.hypot(
        sample.sheetCurrentXReal,
        sample.sheetCurrentYReal,
        sample.sheetCurrentXImag,
        sample.sheetCurrentYImag,
      ) / reference.copperThickness
    maxCurrentDensity = Math.max(maxCurrentDensity, currentDensity)
    return {
      ...node,
      sheetCurrentX:
        sample.sheetCurrentXReal * Math.cos(phase) -
        sample.sheetCurrentXImag * Math.sin(phase),
      sheetCurrentY:
        sample.sheetCurrentYReal * Math.cos(phase) -
        sample.sheetCurrentYImag * Math.sin(phase),
      currentDensity,
    }
  })
  return renderCurrentFieldSvg(
    {
      ...result,
      nodes,
      diagnostics: {
        converged: true,
        maxCurrentDensity,
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
