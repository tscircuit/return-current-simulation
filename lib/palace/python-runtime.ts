import { existsSync } from "node:fs"
import { mkdir } from "node:fs/promises"
import { resolve, join } from "node:path"
import { fileURLToPath } from "node:url"
import { runCommand } from "./run-command"

/** In source: lib/palace/python. In the published bundle: dist/python. */
export function palacePythonAsset(filename: string): string {
  return fileURLToPath(new URL(`./python/${filename}`, import.meta.url))
}

function venvPython(directory: string): string {
  return join(
    directory,
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  )
}

export function palacePython(explicit?: string): string {
  if (explicit || process.env.PALACE_PYTHON)
    return explicit ?? process.env.PALACE_PYTHON!
  const local = venvPython(resolve(".return-current-python"))
  return existsSync(local) ? local : "python3"
}

export async function setupPalacePython(
  options: { python?: string; directory?: string } = {},
): Promise<string> {
  const directory = resolve(options.directory ?? ".return-current-python")
  await mkdir(directory, { recursive: true })
  await runCommand({
    command: [options.python ?? "python3", "-m", "venv", directory],
    cwd: directory,
    logPath: join(directory, "venv.log"),
  })
  const python = venvPython(directory)
  await runCommand({
    command: [
      python,
      "-m",
      "pip",
      "install",
      "-r",
      palacePythonAsset("requirements.txt"),
    ],
    cwd: directory,
    logPath: join(directory, "install.log"),
  })
  return python
}
