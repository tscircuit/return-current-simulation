import { createHash } from "node:crypto"
import { mkdir, writeFile } from "node:fs/promises"
import { resolve, join } from "node:path"
import { z } from "zod"
import {
  parseFabricationStackup,
  parseReturnCurrentCircuitJson,
} from "lib/index"
import { preparePalaceSimulation } from "lib/palace"

// Pin the public release so changes to the board cannot silently alter a case.
const packageReleaseId = "a56db1f7-99bf-4f14-b32e-ab5431f039d0"
const destination = resolve(process.argv[2] ?? "work/am3352-example")
await mkdir(destination, { recursive: true })
const files = [
  {
    remote: "dist/index/circuit.json",
    local: "board.json",
    sha256: "c9d7059fe536865784f175855e0dcc76510972319eec848c18b0ef6dcd2adb40",
  },
  {
    remote: "design/fabrication-stackup.json",
    local: "stackup.json",
    sha256: "e59944a9dd976b0522a9bce45ca6231d9213f13ea65a53a1e076c8c3a91c79a4",
  },
]
const fetched = await Promise.all(
  files.map(async (file) => {
    const url = new URL("https://api.tscircuit.com/package_files/get")
    url.searchParams.set("package_release_id", packageReleaseId)
    url.searchParams.set("file_path", file.remote)
    const response = await fetch(url)
    if (!response.ok)
      throw new Error(
        `Download failed: ${file.remote}: HTTP ${response.status}`,
      )
    const { package_file } = z
      .object({ package_file: z.object({ content_text: z.string() }) })
      .parse(await response.json())
    const sha256 = createHash("sha256")
      .update(package_file.content_text)
      .digest("hex")
    if (sha256 !== file.sha256)
      throw new Error(`Pinned public file changed: ${file.remote}`)
    await writeFile(join(destination, file.local), package_file.content_text)
    return JSON.parse(package_file.content_text)
  }),
)
const started = performance.now()
const prepared = await preparePalaceSimulation({
  circuitJson: parseReturnCurrentCircuitJson(fetched[0]),
  stackup: parseFabricationStackup(fetched[1]),
  groundNet: "GND",
  ports: [{ source: "U1.K4", load: "U3.A7", current: "5mA" }],
  frequencyHz: 1e6,
  sampleLayer: "bottom",
  cellSize: 0.2,
  outputDirectory: join(destination, "case"),
})
const audit = {
  board: "astra/am3352-sbc",
  version: "0.1.19",
  packageReleaseId,
  files,
  exampleSignal: "DDR_D12",
  source: "U1.K4",
  load: "U3.A7",
  frequencyHz: 1e6,
  currentAmps: 0.005,
  sampleLayer: "bottom",
  preparationSeconds: (performance.now() - started) / 1000,
  emSolvePerformed: false,
  stackup: prepared.model.multilayer!.stackup,
  audit: prepared.model.multilayer!.audit,
  grid: prepared.grid,
}
await writeFile(
  join(destination, "preparation-audit.json"),
  JSON.stringify(audit, null, 2),
)
console.log(JSON.stringify(audit, null, 2))
