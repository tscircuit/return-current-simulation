import { spawn } from "node:child_process"
import { open } from "node:fs/promises"

export async function runCommand(options: {
  command: string[]
  cwd: string
  logPath: string
}): Promise<void> {
  const log = await open(options.logPath, "w")
  try {
    await new Promise<void>((resolve, reject) => {
      const child = spawn(options.command[0], options.command.slice(1), {
        cwd: options.cwd,
        stdio: ["ignore", log.fd, log.fd],
      })
      child.once("error", (error) =>
        reject(
          new Error(
            `Could not start ${options.command[0]}: ${error.message}; see ${options.logPath}`,
          ),
        ),
      )
      child.once("close", (status, signal) =>
        status === 0
          ? resolve()
          : reject(
              new Error(
                `${options.command[0]} exited with ${status ?? signal}; see ${options.logPath}`,
              ),
            ),
      )
    })
  } finally {
    await log.close()
  }
}
