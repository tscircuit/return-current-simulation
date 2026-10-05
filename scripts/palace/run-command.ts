import { open } from "node:fs/promises"

export async function runCommand(options: {
  command: string[]
  cwd: string
  logPath: string
}): Promise<void> {
  const log = await open(options.logPath, "w")
  try {
    const process = Bun.spawn(options.command, {
      cwd: options.cwd,
      stdout: log.fd,
      stderr: log.fd,
    })
    const status = await process.exited
    if (status !== 0)
      throw new Error(
        `${options.command[0]} exited with ${status}; see ${options.logPath}`,
      )
  } finally {
    await log.close()
  }
}
