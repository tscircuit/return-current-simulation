import type { Point } from "circuit-json"
import type { SignalSegment } from "./types"

/** Ideal image sheet current from straight filaments above an infinite plane.
 * Integrates -I h dl / [2π (r²+h²)^(3/2)] along each segment analytically.
 * Returns board-space direction components in A/mm (+X right, +Y up).
 */
export function imageCurrentAt(
  point: Point,
  context: { segments: readonly SignalSegment[]; layerSeparation: number },
): Point {
  let x = 0
  let y = 0
  const h = context.layerSeparation
  for (const segment of context.segments) {
    const length = Math.hypot(
      segment.end.x - segment.start.x,
      segment.end.y - segment.start.y,
    )
    const tx = (segment.end.x - segment.start.x) / length
    const ty = (segment.end.y - segment.start.y) / length
    const projection =
      (point.x - segment.start.x) * tx + (point.y - segment.start.y) * ty
    const perpendicular =
      (point.y - segment.start.y) * tx - (point.x - segment.start.x) * ty
    const squaredDistance = h * h + perpendicular * perpendicular
    const farEnd = length - projection
    const integral =
      (farEnd / Math.sqrt(squaredDistance + farEnd * farEnd) +
        projection / Math.sqrt(squaredDistance + projection * projection)) /
      squaredDistance
    const amplitude = (-segment.current * h * integral) / (2 * Math.PI)
    x += amplitude * tx
    y += amplitude * ty
  }
  return { x, y }
}
