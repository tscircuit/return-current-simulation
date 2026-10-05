import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { createPalaceModel } from "lib/palace/create-palace-model"
import type { PalaceOptions } from "lib/palace/types"
import { runCommand } from "./run-command"
import { writeSampleGrid } from "./write-sample-grid"

// Community-built Palace v0.14.0; pinned by digest, not a moving image tag.
export const palaceImage =
  "benvial/palace@sha256:f0f3a3cbbdf1ee2d8f856ddbe1f5bf4628a92ee8ab87d1e27dc33402ad9c8dda"

export async function runPalaceCase(
  options: PalaceOptions & {
    destination: string
    python?: string
    palaceBin?: string
    cellSize?: number
    processes?: number
  },
): Promise<void> {
  const model = createPalaceModel(options)
  const processes =
    options.processes ?? Number(process.env.PALACE_PROCESSES ?? 1)
  if (!Number.isInteger(processes) || processes < 1)
    throw new Error("processes must be a positive integer")

  const destination = resolve(options.destination)
  await mkdir(destination, { recursive: true })
  await Bun.write(
    `${destination}/circuit.json`,
    JSON.stringify(options.circuitJson),
  )
  await Bun.write(`${destination}/model.json`, JSON.stringify(model, null, 2))
  await writeSampleGrid({
    destination,
    geometry: model.geometry,
    cellSize: options.cellSize,
  })
  const python = options.python ?? process.env.PALACE_PYTHON ?? "python3"
  const meshScript = resolve(import.meta.dir, "../../lib/palace/python/mesh.py")
  const sampleScript = resolve(
    import.meta.dir,
    "../../lib/palace/python/sample.py",
  )
  console.log(`Meshing ${destination}`)
  await runCommand({
    command: [python, meshScript, `${destination}/model.json`],
    cwd: destination,
    logPath: `${destination}/mesh.log`,
  })
  const palaceBin = options.palaceBin ?? process.env.PALACE_BIN
  const command = palaceBin
    ? [palaceBin, "-np", String(processes), "palace.json"]
    : [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        `${process.getuid?.() ?? 1000}:${process.getgid?.() ?? 1000}`,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--mount",
        `type=bind,src=${destination},dst=/case`,
        "--workdir",
        "/case",
        palaceImage,
        "palace",
        "-np",
        String(processes),
        "palace.json",
      ]
  console.log(`Running Palace at ${model.frequencyHz} Hz`)
  await runCommand({
    command,
    cwd: destination,
    logPath: `${destination}/palace.log`,
  })
  console.log("Sampling complex conduction current through ground copper")
  await runCommand({
    command: [python, sampleScript, destination],
    cwd: destination,
    logPath: `${destination}/sample.log`,
  })
}
