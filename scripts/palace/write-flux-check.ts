import { resolve } from "node:path"
import { runCommand } from "./run-command"

export async function writeFluxCheck(options: {
  destination: string
  xColumns: number[]
  yMin: number
  yMax: number
  rows: number
  expectedRealAmps: number
}) {
  const destination = resolve(options.destination)
  const { destination: _, ...specification } = options
  const path = `${destination}/flux-specification.json`
  await Bun.write(path, JSON.stringify(specification, null, 2))
  await runCommand({
    command: [
      process.env.PALACE_PYTHON ?? "python3",
      resolve(import.meta.dir, "../../lib/palace/python/flux.py"),
      destination,
      path,
    ],
    cwd: destination,
    logPath: `${destination}/flux.log`,
  })
}
