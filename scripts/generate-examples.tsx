import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { Resvg } from "@resvg/resvg-js"
import { renderReturnCurrentSvg, simulateReturnCurrent } from "lib/index"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

const destination = resolve(process.argv[2] ?? "examples")
await mkdir(destination, { recursive: true })
for (const unbrokenGround of [false, true]) {
  const name = unbrokenGround ? "unbroken-ground" : "ground-slot"
  const circuitJson = await renderFixture(
    <SlotBoard unbrokenGround={unbrokenGround} />,
    [1, 1, 1],
  )
  const result = simulateReturnCurrent({
    circuitJson,
    cellSize: 0.25,
    layerSeparation: 0.8,
    contactRadius: 0.6,
  })
  const svg = renderReturnCurrentSvg(result, {
    title: unbrokenGround
      ? "Unbroken ground plane"
      : "Return current around a ground-plane slot",
    maxCurrentDensity: 50,
    vectorSpacing: 4,
  })
  await Bun.write(
    `${destination}/${name}.circuit.json`,
    JSON.stringify(circuitJson, null, 2),
  )
  await Bun.write(`${destination}/${name}.svg`, svg)
  await Bun.write(`${destination}/${name}.png`, new Resvg(svg).render().asPng())
  await Bun.write(
    `${destination}/${name}.diagnostics.json`,
    JSON.stringify(result.diagnostics, null, 2),
  )
  console.log(name, result.diagnostics)
}
