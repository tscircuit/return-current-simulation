import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { mkdtemp, readFile, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { promisify } from "node:util"
import type { AnyCircuitElement } from "circuit-json"
import { palacePythonAsset } from "../palace/python-runtime"
import { prepareCrosstalk } from "./prepare"
import type { CrosstalkReport } from "./types"

const execute = promisify(execFile)

const format = (report: CrosstalkReport) => {
  const lines = ["Crosstalk analysis: " + report.status.replaceAll("_", " ")]
  for (const issue of report.issues) lines.push(issue.message)
  if (report.numerical)
    lines.push(
      "Geometry-derived electrostatics and real ngspice transients completed within the uniform two-line model.",
    )
  lines.push(...report.assumptions)
  return lines.join("\n")
}

/** Public circuit input only. Runtime installation: CROSSTALK_PYTHON and CROSSTALK_NGSPICE. */
export async function analyzeCrosstalk(
  circuitJson: readonly AnyCircuitElement[],
) {
  const report = prepareCrosstalk(circuitJson)
  if (report.model) {
    const inputText = JSON.stringify(report.model)
    const hash = createHash("sha256").update(inputText).digest("hex")
    const directory = await mkdtemp(join(tmpdir(), "crosstalk-"))
    report.artifactDirectory = directory
    await writeFile(join(directory, "model.json"), inputText + "\n")
    const python = process.env.CROSSTALK_PYTHON ?? "python3"
    const ngspice = process.env.CROSSTALK_NGSPICE ?? "ngspice"
    try {
      const { stdout, stderr } = await execute(
        python,
        [
          palacePythonAsset("crosstalk.py"),
          join(directory, "model.json"),
          directory,
          ngspice,
        ],
        {
          timeout: 120000,
          maxBuffer: 1024 * 1024,
          env: {
            ...process.env,
            OPENBLAS_NUM_THREADS: "1",
            OMP_NUM_THREADS: "1",
            MPLCONFIGDIR: join(directory, "matplotlib"),
          },
        },
      )
      await writeFile(join(directory, "backend.log"), stdout + stderr)
      report.numerical = JSON.parse(
        await readFile(join(directory, "result.json"), "utf8"),
      )
      report.numerical!.svg = await readFile(
        join(directory, "transients.svg"),
        "utf8",
      )
      report.numerical!.provenance.inputModelSha256 = hash
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      await writeFile(join(directory, "backend-error.log"), reason)
      report.status = "failed"
      report.issues.push({
        code: "numerical_backend_failed",
        message:
          "Numerical backend did not complete: " +
          reason +
          "\nInstall ngspice and the pinned crosstalk-requirements.txt into CROSSTALK_PYTHON; CROSSTALK_NGSPICE selects its executable. Inspect saved logs and convergence checks.",
        elementIds: [],
      })
    }
  }
  return {
    getReport: () => report,
    getString: () => format(report),
    getIssues: () => report.issues,
    getSvg: () => report.numerical?.svg,
  }
}
