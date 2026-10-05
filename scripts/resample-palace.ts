import { resolve } from "node:path"
import { parseArgs } from "node:util"
import type { PalaceModel } from "lib/palace/types"
import { runCommand } from "./palace/run-command"
import { writeComparison } from "./palace/write-comparison"
import { writeSampleGrid } from "./palace/write-sample-grid"

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  allowPositionals: true,
  options: {
    "cell-size": { type: "string" },
    python: { type: "string" },
  },
})
if (positionals.length !== 1)
  throw new Error(
    "Usage: bun run resample:palace <completed-case-directory> [--cell-size 0.2 --python /path/to/python]",
  )
const destination = resolve(positionals[0])
const model: PalaceModel = await Bun.file(`${destination}/model.json`).json()
await writeSampleGrid({
  destination,
  geometry: model.geometry,
  cellSize: values["cell-size"] ? Number(values["cell-size"]) : undefined,
})
await runCommand({
  command: [
    values.python ?? process.env.PALACE_PYTHON ?? "python3",
    resolve(import.meta.dir, "../lib/palace/python/sample.py"),
    destination,
  ],
  cwd: destination,
  logPath: `${destination}/sample.log`,
})
await writeComparison(destination)
console.log(`Resampled ${model.frequencyHz} Hz Palace field at ${destination}`)
