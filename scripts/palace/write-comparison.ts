import { Resvg } from "@resvg/resvg-js"
import { comparePalaceReference } from "lib/palace/compare-palace-reference"
import { renderPalaceReferenceSvg } from "lib/palace/render-palace-reference-svg"
import type { PalaceReference, PalaceModel } from "lib/palace/types"
import { renderReturnCurrentSvg } from "lib/render-return-current-svg"
import { simulateReturnCurrent } from "lib/simulate-return-current"
import type { ReturnCurrentCircuitJson } from "lib/types"

export async function writeComparison(destination: string): Promise<void> {
  const circuitJson: ReturnCurrentCircuitJson = await Bun.file(
    `${destination}/circuit.json`,
  ).json()
  const model: PalaceModel = await Bun.file(`${destination}/model.json`).json()
  const reference: PalaceReference = await Bun.file(
    `${destination}/reference.json`,
  ).json()
  const result = simulateReturnCurrent({
    circuitJson,
    layerSeparation: model.layerSeparation,
    copperThickness: model.copperThickness,
    cellSize: reference.cellWidth,
    contactRadius: 0.6,
  })
  const comparison = comparePalaceReference(result, { reference })
  await Bun.write(
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
    await Bun.write(`${destination}/${solver}.svg`, svg)
    await Bun.write(
      `${destination}/${solver}.png`,
      new Resvg(svg).render().asPng(),
    )
  }
  console.log(comparison)
}
