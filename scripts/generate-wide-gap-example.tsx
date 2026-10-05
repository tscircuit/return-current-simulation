import { SlotBoard } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"
import { runPalaceCase } from "./palace/run-case"
import { writeComparison } from "./palace/write-comparison"
import { writeFluxCheck } from "./palace/write-flux-check"
import { exportEvidence } from "./palace/export-evidence"

const destination = process.argv[2] ?? "work/palace/ground-slot-wide-gap-1mhz"
const circuitJson = await renderFixture(<SlotBoard topGap={4} />, [1, 1, 1])
await runPalaceCase({
  circuitJson,
  frequencyHz: 1e6,
  meshSize: 2,
  airPadding: 6,
  order: 2,
  cellSize: 0.2,
  destination,
  processes: Number(process.env.PALACE_PROCESSES ?? 4),
})
await writeComparison(destination)
await writeFluxCheck({
  destination,
  xColumns: [-5.75, -5.25, -4.75, -4.25, -3.75, -3.25],
  yMin: 16,
  yMax: 20,
  rows: 320,
  expectedRealAmps: -3,
})
await exportEvidence({
  source: destination,
  destination: "examples/palace/ground-slot-wide-gap-1mhz",
  rawOutputCommand:
    "bun run generate:palace:wide-gap work/palace/ground-slot-wide-gap-1mhz",
})
