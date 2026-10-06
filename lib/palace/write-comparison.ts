import { readJson } from "./read-json"
import { writeFile } from "node:fs/promises"
import { Resvg } from "@resvg/resvg-js"
import { comparePalaceReference } from "./compare-palace-reference"
import { renderPalaceReferenceSvg } from "./render-palace-reference-svg"
import type { PalaceReference, PalaceModel } from "./types"
import { renderReturnCurrentSvg } from "../render-return-current-svg"
import { simulateReturnCurrent } from "../simulate-return-current"
import type { ReturnCurrentCircuitJson } from "../types"

export async function writeComparison(destination: string): Promise<void> {
  const circuitJson: ReturnCurrentCircuitJson = await readJson(
    `${destination}/circuit.json`,
  )
  const model: PalaceModel = await readJson(`${destination}/model.json`)
  const reference: PalaceReference = await readJson(
    `${destination}/reference.json`,
  )
  const result = simulateReturnCurrent({
    circuitJson,
    layerSeparation: model.layerSeparation,
    copperThickness: model.copperThickness,
    cellSize: reference.cellWidth,
    contactRadius: 0.6,
  })
  const comparison = comparePalaceReference(result, { reference })
  await writeFile(
    `${destination}/comparison.json`,
    JSON.stringify(comparison, null, 2),
  )
  for (const solver of ["palace", "approximation"]) {
    const options = {
      title:
        solver === "palace"
          ? "Palace: ground-plane return current"
          : "Approximation: ground-plane return current",
      maxCurrentDensity: 50,
      vectorSpacing: Math.max(1, Math.round(1 / reference.cellWidth)),
      width: 1100,
      height: 1100,
    }
    const svg =
      solver === "palace"
        ? renderPalaceReferenceSvg(result, { ...options, reference })
        : renderReturnCurrentSvg(result, options)
    await writeFile(`${destination}/${solver}.svg`, svg)
    await writeFile(
      `${destination}/${solver}.png`,
      new Resvg(svg).render().asPng(),
    )
  }
  console.log(comparison)
}
