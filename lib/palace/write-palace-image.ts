import { readJson } from "./read-json"
import { writeFile } from "node:fs/promises"
import { Resvg } from "@resvg/resvg-js"
import { renderPalaceModelSvg } from "./render-palace-reference-svg"
import type { PalaceModel, PalaceReference } from "./types"
import { validatePalaceCaseInputs } from "./input-provenance"

/** Export sampled Palace fields without constructing the approximation graph. */
export async function writePalaceImage(destination: string, imageSize = 1100) {
  const readStarted = performance.now()
  const model: PalaceModel = await readJson(`${destination}/model.json`)
  const reference: PalaceReference = await readJson(
    `${destination}/reference.json`,
  )
  await validatePalaceCaseInputs(reference, destination)
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
  await writeFile(`${destination}/palace.svg`, svg)
  const svgSeconds = (performance.now() - svgStarted) / 1000
  const pngStarted = performance.now()
  await writeFile(`${destination}/palace.png`, new Resvg(svg).render().asPng())
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
