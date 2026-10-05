import { SlotBoard } from "tests/fixtures/SlotBoard"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"
import { runPalaceCase } from "./palace/run-case"
import { writeComparison } from "./palace/write-comparison"

const destination = process.argv[2] ?? "work/palace"
for (const [name, element, currents] of [
  ["straight-1mhz", <StraightBoard />, [1]],
  ["ground-slot-1mhz", <SlotBoard />, [1, 1, 1]],
  ["unbroken-ground-1mhz", <SlotBoard unbrokenGround />, [1, 1, 1]],
] as const) {
  const circuitJson = await renderFixture(element, currents)
  const folder = `${destination}/${name}`
  await runPalaceCase({
    circuitJson,
    frequencyHz: 1e6,
    meshSize: 2,
    airPadding: 6,
    order: 2,
    destination: folder,
  })
  await writeComparison(folder)
}
