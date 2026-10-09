import type { Point } from "circuit-json"
import type { SimulationGeometry } from "../types"
import { canonicalJson } from "./canonical-json"

function coordinate(number: number): string {
  return (Math.abs(number) < 0.5e-9 ? 0 : number).toFixed(9)
}

function point(point: Point): string[] {
  return [coordinate(point.x), coordinate(point.y)]
}

/** Canonical sampling geometry, including the full layered physical model when present. */
export function palaceGeometrySignature(geometry: SimulationGeometry): string {
  return JSON.stringify([
    geometry.boardOutline.map(point),
    geometry.groundRegions.map((region) => [
      region.outer.map(point),
      [...region.holes, ...(region.maskCutouts ?? [])].map((hole) =>
        hole.map(point),
      ),
    ]),
    geometry.cutouts.map((outline) => outline.map(point)),
    geometry.signals.map((signal) =>
      signal.route
        .filter((route) => route.route_type === "wire")
        .map((route) => [
          ...point(route),
          coordinate(route.width),
          route.layer,
        ]),
    ),
    ...(geometry.physicalModelSignature
      ? [canonicalJson(JSON.parse(geometry.physicalModelSignature))]
      : []),
    geometry.excitations.map((excitation) => [
      coordinate(excitation.current),
      point(excitation.return_source),
      point(excitation.return_sink),
      ...(excitation.source_port || excitation.load_port
        ? [
            [
              excitation.source_port?.reference_layer ?? "bottom",
              coordinate(excitation.source_port?.resistance ?? 50),
              excitation.load_port?.reference_layer ?? "bottom",
              coordinate(excitation.load_port?.resistance ?? 50),
            ],
          ]
        : []),
    ]),
  ])
}

/** Accept archived signatures at the same precision as newly generated models. */
export function matchingGeometrySignatures(a: string, b: string): boolean {
  const normalize = (signature: string) => {
    const values = JSON.parse(signature)
    if (values.length === 6 && typeof values[4] === "string")
      values[4] = canonicalJson(JSON.parse(values[4]))
    return canonicalJson(values)
  }
  try {
    return normalize(a) === normalize(b)
  } catch {
    return false
  }
}
