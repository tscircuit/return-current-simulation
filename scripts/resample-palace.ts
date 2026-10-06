import { resolve } from "node:path"
import { cpus, platform, arch } from "node:os"
import { parseArgs } from "node:util"
import { positiveFinite } from "lib/read-geometry"
import type { PalaceModel } from "lib/palace/types"
import { runCommand } from "./palace/run-command"
import { writeComparison } from "./palace/write-comparison"
import { writeSampleGrid } from "./palace/write-sample-grid"
import { writePalaceImage } from "./palace/write-palace-image"

const { values, positionals } = parseArgs({
  args: process.argv.slice(2),
  allowPositionals: true,
  options: {
    "cell-size": { type: "string" },
    python: { type: "string" },
    "palace-only": { type: "boolean", default: false },
    "image-size": { type: "string" },
  },
})
if (positionals.length !== 1)
  throw new Error(
    "Usage: bun run resample:palace <completed-case-directory> [--cell-size 0.2 --python /path/to/python --palace-only --image-size 2000]",
  )
const started = performance.now()
const startedAt = new Date().toISOString()
const imageSize = positiveFinite(
  Number(values["image-size"] ?? 1100),
  "image-size",
)
if (!Number.isInteger(imageSize) || imageSize < 300 || imageSize > 8192)
  throw new Error("image-size must be an integer between 300 and 8192")
if (values["image-size"] && !values["palace-only"])
  throw new Error("image-size requires --palace-only")
const destination = resolve(positionals[0])
const model: PalaceModel = await Bun.file(`${destination}/model.json`).json()
const gridStarted = performance.now()
const grid = await writeSampleGrid({
  destination,
  geometry: model.geometry,
  cellSize: values["cell-size"] ? Number(values["cell-size"]) : undefined,
})
const gridSeconds = (performance.now() - gridStarted) / 1000
if (grid.columns * grid.rows > 100_000 && !values["palace-only"])
  throw new Error(
    "Grids above 100,000 cells require --palace-only; the approximation graph has a separate limit",
  )
const sampleStarted = performance.now()
await runCommand({
  command: [
    values.python ?? process.env.PALACE_PYTHON ?? "python3",
    resolve(import.meta.dir, "../lib/palace/python/sample.py"),
    destination,
  ],
  cwd: destination,
  logPath: `${destination}/sample.log`,
})
const sampleSeconds = (performance.now() - sampleStarted) / 1000
const exportStarted = performance.now()
const image = values["palace-only"]
  ? await writePalaceImage(destination, imageSize)
  : undefined
if (!values["palace-only"]) await writeComparison(destination)
const exportSeconds = (performance.now() - exportStarted) / 1000
const timing = {
  startedAt,
  completedAt: new Date().toISOString(),
  frequencyHz: model.frequencyHz,
  ...grid,
  reusedCompletedFemSolve: true,
  approximationCompared: !values["palace-only"],
  gridSeconds,
  sampleSeconds,
  exportSeconds,
  totalSeconds: (performance.now() - started) / 1000,
  image,
  environment: {
    platform: platform(),
    architecture: arch(),
    cpuModel: cpus()[0]?.model,
    bunVersion: Bun.version,
  },
}
await Bun.write(
  `${destination}/resample-timing.json`,
  JSON.stringify(timing, null, 2),
)
console.log(JSON.stringify(timing, null, 2))
console.log(`Resampled ${model.frequencyHz} Hz Palace field at ${destination}`)
