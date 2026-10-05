import { writeFile } from "node:fs/promises"
import { resolve, join } from "node:path"
import { cpus, platform, arch } from "node:os"
import { readJson } from "./read-json"
import { palacePython, palacePythonAsset } from "./python-runtime"
import { runCommand } from "./run-command"
import { writeSampleGrid } from "./write-sample-grid"
import { writePalaceImage } from "./write-palace-image"
import { writeComparison } from "./write-comparison"
import { imageDimension } from "./run-simulation"
import type { PalaceModel } from "./types"

export async function resamplePalaceCase(options: {
  outputDirectory: string
  cellSize?: number
  imageSize?: number
  python?: string
  compareApproximation?: boolean
}) {
  const started = performance.now()
  const startedAt = new Date().toISOString()
  const imageSize = imageDimension(options.imageSize)
  if (options.compareApproximation && options.imageSize !== undefined)
    throw new Error("imageSize is configurable only for Palace-only resampling")
  const destination = resolve(options.outputDirectory)
  const model = await readJson<PalaceModel>(join(destination, "model.json"))
  const gridStarted = performance.now()
  const grid = await writeSampleGrid({
    destination,
    geometry: model.geometry,
    cellSize: options.cellSize,
  })
  const gridSeconds = (performance.now() - gridStarted) / 1000
  if (grid.columns * grid.rows > 100_000 && options.compareApproximation)
    throw new Error(
      "Approximation comparison is limited to 100,000 candidate cells",
    )
  const sampleStarted = performance.now()
  await runCommand({
    command: [
      palacePython(options.python),
      palacePythonAsset("sample.py"),
      destination,
    ],
    cwd: destination,
    logPath: join(destination, "sample.log"),
  })
  const sampleSeconds = (performance.now() - sampleStarted) / 1000
  const exportStarted = performance.now()
  if (options.compareApproximation) await writeComparison(destination)
  const image = options.compareApproximation
    ? undefined
    : await writePalaceImage(destination, imageSize)
  const timing = {
    startedAt,
    completedAt: new Date().toISOString(),
    frequencyHz: model.frequencyHz,
    ...grid,
    reusedCompletedFemSolve: true,
    approximationCompared: Boolean(options.compareApproximation),
    gridSeconds,
    sampleSeconds,
    exportSeconds: (performance.now() - exportStarted) / 1000,
    totalSeconds: (performance.now() - started) / 1000,
    image,
    environment: {
      platform: platform(),
      architecture: arch(),
      cpuModel: cpus()[0]?.model,
      nodeVersion: process.version,
    },
  }
  await writeFile(
    join(destination, "resample-timing.json"),
    JSON.stringify(timing, null, 2),
  )
  return timing
}
