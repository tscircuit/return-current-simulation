import { expect, test } from "bun:test"
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { multilayerModel } from "tests/fixtures/renderMultilayerBoard"

const python = process.env.PALACE_MESH_PYTHON

test.skipIf(!python)(
  "openEMS export preserves physical copper from TSX circuit-json",
  async () => {
    const directory = await mkdtemp(join(tmpdir(), "si-copper-"))
    try {
      const { model, circuitJson } = await multilayerModel()
      expect(circuitJson.some((element) => element.type === "pcb_trace")).toBe(
        true,
      )
      const input = join(directory, "model.json")
      const output = join(directory, "copper.json")
      await writeFile(input, JSON.stringify(model))
      const child = Bun.spawn(
        [
          python!,
          resolve("scripts/si/export-openems-copper.py"),
          input,
          "--out",
          output,
        ],
        { stdout: "pipe", stderr: "pipe" },
      )
      const [stdout, stderr, code] = await Promise.all([
        new Response(child.stdout).text(),
        new Response(child.stderr).text(),
        child.exited,
      ])
      if (code !== 0) throw new Error(stdout + stderr)
      const copper = JSON.parse(await readFile(output, "utf8"))
      expect(Object.keys(copper).sort()).toEqual([
        "bottom",
        "inner1",
        "inner2",
        "top",
      ])
      const receipt = JSON.parse(
        await readFile(join(directory, "copper.provenance.json"), "utf8"),
      )
      expect(receipt.differentNetOverlaps).toBe(0)
      expect(receipt.traceCaps).toBe("round")
      expect(receipt.modelSha256).toHaveLength(64)
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  },
  60000,
)

test.skipIf(!process.env.SI_PYTHON)(
  "ngspice eye preserves injected jitter and rejects empty conversion",
  async () => {
    const child = Bun.spawn(
      [process.env.SI_PYTHON!, "tests/python/test_si_transient.py"],
      { stdout: "pipe", stderr: "pipe" },
    )
    const [stdout, stderr, code] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ])
    if (code !== 0) throw new Error(stdout + stderr)
    expect(code).toBe(0)
  },
  120000,
)
