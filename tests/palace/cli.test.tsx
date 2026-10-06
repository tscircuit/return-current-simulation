import { expect, test } from "bun:test"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("Palace CLI reads a TSX-derived circuit-json file before model validation", async () => {
  const circuitJson = await renderFixture(<StraightBoard />)
  const destination = await mkdtemp(join(tmpdir(), "palace-cli-"))
  try {
    const input = join(destination, "circuit.json")
    await Bun.write(input, JSON.stringify(circuitJson))
    const process = Bun.spawn(
      [
        Bun.which("bun") ?? "bun",
        resolve(import.meta.dir, "../../scripts/run-palace.ts"),
        input,
        join(destination, "output"),
        "--frequency-hz",
        "0",
      ],
      { stdout: "pipe", stderr: "pipe" },
    )
    const stderr = await new Response(process.stderr).text()
    expect(await process.exited).toBe(1)
    // Invalid frequency stops before any Python, Docker or Palace invocation.
    expect(stderr).toContain("frequencyHz must be finite and greater than zero")
    expect(stderr).not.toContain("Expected array, received string")
  } finally {
    await rm(destination, { recursive: true, force: true })
  }
})
