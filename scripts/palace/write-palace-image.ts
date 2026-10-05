import { Resvg } from "@resvg/resvg-js"
import { renderPalaceModelSvg } from "lib/palace/render-palace-reference-svg"
import type { PalaceModel, PalaceReference } from "lib/palace/types"

/** Export sampled Palace fields without constructing the approximation graph. */
export async function writePalaceImage(destination: string, imageSize = 1100) {
  const readStarted = performance.now()
  const model: PalaceModel = await Bun.file(`${destination}/model.json`).json()
  const reference: PalaceReference = await Bun.file(
    `${destination}/reference.json`,
  ).json()
  const readSeconds = (performance.now() - readStarted) / 1000
  const svgStarted = performance.now()
  const svg = renderPalaceModelSvg(model, {
    reference,
    title: "Palace: ground-plane return current",
    maxCurrentDensity: 50,
    vectorSpacing: Math.max(1, Math.round(1 / reference.cellWidth)),
    width: imageSize,
    height: imageSize,
  })
  await Bun.write(`${destination}/palace.svg`, svg)
  const svgSeconds = (performance.now() - svgStarted) / 1000
  const pngStarted = performance.now()
  await Bun.write(`${destination}/palace.png`, new Resvg(svg).render().asPng())
  const pngSeconds = (performance.now() - pngStarted) / 1000
  return {
    readSeconds,
    svgSeconds,
    pngSeconds,
    imageSize,
    provenance: reference.provenance,
    solverVersion: reference.solverVersion,
    femOrder: reference.femOrder,
    sourceCurrents: reference.sourceCurrents,
  }
}
