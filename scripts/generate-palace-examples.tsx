import { SlotBoard } from "tests/fixtures/SlotBoard"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"
import { runPalaceCase } from "./palace/run-case"
import { writeComparison } from "./palace/write-comparison"
import { writeFluxCheck } from "./palace/write-flux-check"

const destination = process.argv[2] ?? "work/palace"
for (const [name, element, currents, frequencyHz, order] of [
  ["straight-1mhz", <StraightBoard />, [1], 1e6, 2],
  ["ground-slot-1mhz", <SlotBoard />, [1, 1, 1], 1e6, 2],
  ["unbroken-ground-1mhz", <SlotBoard unbrokenGround />, [1, 1, 1], 1e6, 2],
  ["ground-slot-100khz", <SlotBoard />, [1, 1, 1], 1e5, 1],
  ["ground-slot-order1-1mhz", <SlotBoard />, [1, 1, 1], 1e6, 1],
  ["ground-slot-coarse-1mhz", <SlotBoard />, [1, 1, 1], 1e6, 1],
] as const) {
  const circuitJson = await renderFixture(element, currents)
  const folder = `${destination}/${name}`
  await runPalaceCase({
    circuitJson,
    frequencyHz,
    meshSize: name.includes("coarse") ? 3 : 2,
    airPadding: 6,
    order,
    destination: folder,
  })
  await writeComparison(folder)
  if (name === "straight-1mhz" || name === "ground-slot-1mhz")
    await writeFluxCheck({
      destination: folder,
      xColumns:
        name === "straight-1mhz"
          ? [-3, -1, 1, 3]
          : [-5.75, -5.25, -4.75, -4.25, -3.75, -3.25],
      yMin: name === "straight-1mhz" ? -10 : 19,
      yMax: name === "straight-1mhz" ? 10 : 20,
      rows: name === "straight-1mhz" ? 400 : 80,
      expectedRealAmps: name === "straight-1mhz" ? -1 : -3,
    })
}
