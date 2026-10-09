import { expect, test } from "bun:test"
import { Circuit } from "@tscircuit/core"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { DdrAuditBoard } from "./fixtures/DdrAuditBoard"

const python = process.env.PALACE_MESH_PYTHON

test.skipIf(!python)(
  "DDR audit detects absolute-length failure despite matching skew and preserves pour holes",
  async () => {
    const directory = await mkdtemp(join(tmpdir(), "ddr-audit-"))
    try {
      for (const detour of [false, true]) {
        const circuit = new Circuit()
        circuit.add(<DdrAuditBoard detour={detour} />)
        await circuit.renderUntilSettled()
        const filename = join(directory, "board.json")
        await writeFile(filename, JSON.stringify(circuit.getCircuitJson()))
        const child = Bun.spawn(
          [
            python!,
            "-c",
            `
import importlib.util,json,sys
spec=importlib.util.spec_from_file_location("audit",sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
r,_=m.audit(json.load(open(sys.argv[2])),[0],[("top","bottom",["GND"])])
print(json.dumps(r))
`,
            resolve("scripts/audit-am335x-ddr.py"),
            filename,
          ],
          { stdout: "pipe", stderr: "pipe" },
        )
        const [stdout, stderr, code] = await Promise.all([
          new Response(child.stdout).text(),
          new Response(child.stderr).text(),
          child.exited,
        ])
        if (code !== 0) throw new Error(stderr)
        const result = JSON.parse(stdout)
        expect(result.groups[0].dataLengthPass).toBe(!detour)
        expect(result.groups[0].byteSkewPass).toBe(true)
        expect(result.groups[0].pairSkewPass).toBe(true)
        expect(result.groups[0].dqlmMm).toBeCloseTo(20, 8)
        expect(
          result.referencePourProjection.find(
            (r: { signal: string }) => r.signal === "DDR_D5",
          ).centerlineOutsidePourMm,
          // Core includes its 0.2 mm cutout clearance around the 1 mm opening.
        ).toBeCloseTo(1.4, 5)
      }
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  },
  60000,
)

test.skipIf(!python)(
  "waveform analysis preserves known jitter and rejects ambiguous captures",
  async () => {
    const child = Bun.spawn([python!, "tests/python/test_ddr_waveforms.py"], {
      stdout: "pipe",
      stderr: "pipe",
    })
    const [stdout, stderr, code] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ])
    if (code !== 0) throw new Error(stdout + stderr)
    expect(code).toBe(0)
  },
)
