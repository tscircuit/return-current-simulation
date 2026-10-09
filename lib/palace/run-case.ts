import { palacePython, palacePythonAsset } from "./python-runtime"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { resolve } from "node:path"
import { createPalaceModel } from "./create-palace-model"
import type { PalaceOptions } from "./types"
import { runCommand } from "./run-command"
import { writeSampleGrid } from "./write-sample-grid"
import { palaceInputManifest, sha256 } from "./input-provenance"

// Community-built Palace v0.14.0; pinned by digest, not a moving image tag.
export const palaceImage =
  "benvial/palace@sha256:f0f3a3cbbdf1ee2d8f856ddbe1f5bf4628a92ee8ab87d1e27dc33402ad9c8dda"

export type PalaceCaseOptions = PalaceOptions & {
  destination: string
  python?: string
  palaceBin?: string
  cellSize?: number
  processes?: number
}

export async function preparePalaceCase(options: PalaceCaseOptions) {
  const model = createPalaceModel(options)
  const processes =
    options.processes ?? Number(process.env.PALACE_PROCESSES ?? 1)
  if (!Number.isInteger(processes) || processes < 1)
    throw new Error("processes must be a positive integer")

  const destination = resolve(options.destination)
  await mkdir(destination, { recursive: true })
  await writeFile(
    `${destination}/circuit.json`,
    JSON.stringify(options.circuitJson),
  )
  await writeFile(`${destination}/model.json`, JSON.stringify(model, null, 2))
  await writeFile(
    `${destination}/input-manifest.json`,
    JSON.stringify(
      {
        ...palaceInputManifest(options.circuitJson, model),
        circuitFileSha256: sha256(JSON.stringify(options.circuitJson)),
        modelFileSha256: sha256(JSON.stringify(model, null, 2)),
      },
      null,
      2,
    ),
  )
  if (model.multilayer)
    await writeFile(
      `${destination}/model-audit.json`,
      JSON.stringify(model.multilayer.audit, null, 2),
    )
  const grid = await writeSampleGrid({
    destination,
    geometry: model.geometry,
    cellSize: options.cellSize,
  })
  return { model, destination, processes, grid }
}

export async function runPalaceCase(options: PalaceCaseOptions): Promise<void> {
  const { model, destination, processes } = await preparePalaceCase(options)
  const python = palacePython(options.python)
  const meshScript = palacePythonAsset("mesh.py")
  const sampleScript = palacePythonAsset("sample.py")
  console.log(`Meshing ${destination}`)
  await runCommand({
    command: [python, meshScript, `${destination}/model.json`],
    cwd: destination,
    logPath: `${destination}/mesh.log`,
  })
  const manifest = JSON.parse(
    await readFile(`${destination}/input-manifest.json`, "utf8"),
  )
  manifest.meshSha256 = sha256(await readFile(`${destination}/mesh.msh`))
  await writeFile(
    `${destination}/input-manifest.json`,
    JSON.stringify(manifest, null, 2),
  )
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
