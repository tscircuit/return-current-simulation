import { rectangleOutline } from "../geometry"
import { positiveFinite, readGeometry } from "../read-geometry"
import type { PalaceModel, PalaceOptions } from "./types"

export function createPalaceModel(options: PalaceOptions): PalaceModel {
  const frequencyHz = positiveFinite(options.frequencyHz, "frequencyHz")
  const geometry = readGeometry(options)
  const layerSeparation = positiveFinite(
    options.layerSeparation ?? geometry.board.thickness ?? 0.8,
    "layerSeparation",
  )
  const copperThickness = positiveFinite(
    options.copperThickness ?? 0.035,
    "copperThickness",
  )
  const copperConductivity = positiveFinite(
    options.copperConductivity ?? 5.8e7,
    "copperConductivity",
  )
  const skinDepthMm =
    1000 /
    Math.sqrt(Math.PI * frequencyHz * 4e-7 * Math.PI * copperConductivity)
  if (copperThickness > skinDepthMm)
    throw new Error(
      "The current volume mesher requires copper thickness <= skin depth; refine copper through its thickness before using higher frequencies",
    )
  for (const [index, signal] of geometry.signals.entries()) {
    const first = signal.route[0]
    const last = signal.route.at(-1)
    const excitation = geometry.excitations[index]
    if (
      !last ||
      first.route_type !== "wire" ||
      last.route_type !== "wire" ||
      Math.hypot(
        first.x - excitation.return_sink.x,
        first.y - excitation.return_sink.y,
      ) > 1e-6 ||
      Math.hypot(
        last.x - excitation.return_source.x,
        last.y - excitation.return_source.y,
      ) > 1e-6
    )
      throw new Error(
        "Palace vertical ports require return contacts directly below signal endpoints",
      )
  }
  const topPads = options.circuitJson.flatMap((element) => {
    if (element.type !== "pcb_smtpad" || element.layer !== "top") return []
    if (element.shape !== "rect")
      throw new Error("Palace currently supports rectangular top SMT pads")
    return [
      rectangleOutline({
        center: { x: element.x, y: element.y },
        width: element.width,
        height: element.height,
      }),
    ]
  })
  const substrateLossTangent = options.substrateLossTangent ?? 0.02
  if (!Number.isFinite(substrateLossTangent) || substrateLossTangent < 0)
    throw new Error("substrateLossTangent must be finite and nonnegative")
  const order = options.order ?? 2
  if (order !== 1 && order !== 2) throw new Error("order must be 1 or 2")
  return {
    schemaVersion: 1,
    geometry,
    topPads,
    frequencyHz,
    layerSeparation,
    copperThickness,
    copperConductivity,
    substratePermittivity: positiveFinite(
      options.substratePermittivity ?? 4.3,
      "substratePermittivity",
    ),
    substrateLossTangent,
    portResistance: positiveFinite(
      options.portResistance ?? 50,
      "portResistance",
    ),
    portWidth: positiveFinite(options.portWidth ?? 0.18, "portWidth"),
    meshSize: positiveFinite(options.meshSize ?? 1, "meshSize"),
    airPadding: positiveFinite(options.airPadding ?? 10, "airPadding"),
    order,
    copperModel: "volumetric_copper",
  }
}
