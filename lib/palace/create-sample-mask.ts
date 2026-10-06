import type { Point } from "circuit-json"
import { pointInPolygon } from "../geometry"
import type { SimulationGeometry } from "../types"

function boundedPolygon(outline: readonly Point[]) {
  return {
    outline,
    minX: Math.min(...outline.map((p) => p.x)),
    maxX: Math.max(...outline.map((p) => p.x)),
    minY: Math.min(...outline.map((p) => p.y)),
    maxY: Math.max(...outline.map((p) => p.y)),
  }
}

function contains(point: Point, polygon: ReturnType<typeof boundedPolygon>) {
  return (
    point.x >= polygon.minX - 1e-9 &&
    point.x <= polygon.maxX + 1e-9 &&
    point.y >= polygon.minY - 1e-9 &&
    point.y <= polygon.maxY + 1e-9 &&
    pointInPolygon(point, polygon.outline)
  )
}

/** Cache bounds for this immutable sampling operation; avoid scanning every
 * drill's vertices at every image pixel on a board with hundreds of vias. */
export function createSampleMask(geometry: SimulationGeometry) {
  const board = boundedPolygon(geometry.boardOutline)
  const cutouts = geometry.cutouts.map(boundedPolygon)
  const regions = geometry.groundRegions.map((r) => ({
    outer: boundedPolygon(r.outer),
    holes: [...r.holes, ...(r.maskCutouts ?? [])].map(boundedPolygon),
  }))
  return (point: Point) =>
    contains(point, board) &&
    !cutouts.some((cutout) => contains(point, cutout)) &&
    regions.some(
      (r) =>
        contains(point, r.outer) &&
        !r.holes.some((hole) => contains(point, hole)),
    )
}
