import { parseArgs } from "node:util"
import { parseReturnCurrentCircuitJson } from "lib/parse-circuit-json"
import { runPalaceCase } from "./palace/run-case"
import { writeComparison } from "./palace/write-comparison"

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  allowPositionals: true,
  options: {
    "frequency-hz": { type: "string" },
    "mesh-size": { type: "string" },
    "cell-size": { type: "string" },
    "air-padding": { type: "string" },
    order: { type: "string" },
    processes: { type: "string" },
    python: { type: "string" },
    "palace-bin": { type: "string" },
  },
})
if (positionals.length !== 2 || !values["frequency-hz"])
  throw new Error(
    "Usage: bun run palace <circuit.json> <output-directory> --frequency-hz 1000000 [--mesh-size 2 --cell-size 0.2 --air-padding 6 --order 2 --processes 4 --python /path/to/python --palace-bin /path/to/palace]",
  )
const order = values.order ? Number(values.order) : 2
if (order !== 1 && order !== 2) throw new Error("order must be 1 or 2")
const circuitJson = parseReturnCurrentCircuitJson(
  await Bun.file(positionals[0]).json(),
)
await runPalaceCase({
  circuitJson,
  destination: positionals[1],
  frequencyHz: Number(values["frequency-hz"]),
  meshSize: values["mesh-size"] ? Number(values["mesh-size"]) : 2,
  cellSize: values["cell-size"] ? Number(values["cell-size"]) : undefined,
  airPadding: values["air-padding"] ? Number(values["air-padding"]) : 6,
  order,
  processes: values.processes ? Number(values.processes) : undefined,
  python: values.python,
  palaceBin: values["palace-bin"],
})
await writeComparison(positionals[1])
