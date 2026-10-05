import { expect, test } from "bun:test"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { NamedPortBoard } from "tests/fixtures/NamedPortBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

async function cli(args: string[]) {
  const child = Bun.spawn(
    [process.execPath, resolve(import.meta.dir, "../../cli/index.ts"), ...args],
    { stdout: "pipe", stderr: "pipe" },
  )
  const [stdout, stderr, code] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ])
  return { stdout, stderr, code }
}

test("CLI prepares raw TSX circuit-json with explicit frequency and named terminal current", async () => {
  const circuitJson = (await renderFixture(<NamedPortBoard reverse />)).filter(
    (element) => element.type !== "simulation_return_current_excitation",
  )
  const directory = await mkdtemp(join(tmpdir(), "return-current-cli-"))
  try {
    const input = join(directory, "board.json")
    await Bun.write(input, JSON.stringify(circuitJson))
    const flags = [
      "--source",
      "R1.pin1",
      "--load",
      "U1.VDDIO1",
      "--ground",
      "GND",
      "--current",
      "0.25",
    ]
    const prepared = await cli([
      input,
      ...flags,
      "--frequency-hz",
      "1000000",
      "--output",
      join(directory, "case"),
      "--prepare-only",
    ])
    expect(prepared.code).toBe(0)
    expect(prepared.stdout).toContain("1000000 Hz")
    const model = await Bun.file(join(directory, "case/model.json")).json()
    expect(model.frequencyHz).toBe(1e6)
    expect(model.geometry.excitations[0].current).toBe(0.25)
    expect(model.geometry.excitations[0].return_sink).toEqual({ x: -12, y: 0 })
    const provenance = await Bun.file(
      join(directory, "case/excitation-ports.json"),
    ).json()
    expect(provenance.ports[0]).toEqual({
      source: "R1.pin1",
      load: "U1.VDDIO1",
      current: 0.25,
    })
    expect(provenance.groundNet).toBe("GND")
    expect((await cli([input, ...flags, "--prepare-only"])).stderr).toContain(
      "--frequency-hz",
    )
    const listed = await cli(["ports", input])
    expect(JSON.parse(listed.stdout).ports[1].aliases).toContain("U1.VDDIO1")
    const metadata = await cli([
      input,
      "--frequency-hz",
      "1000000",
      "--use-circuit-excitations",
      "--prepare-only",
    ])
    expect(metadata.code).toBe(1)
    expect(metadata.stderr).toContain("no simulation_return_current_excitation")
    const preview = await cli([
      input,
      ...flags,
      "--solver",
      "approximation",
      "--output",
      join(directory, "preview"),
    ])
    expect(preview.code).toBe(0)
    expect(
      await Bun.file(join(directory, "preview/approximation.png")).exists(),
    ).toBe(true)
    expect(
      (await Bun.file(join(directory, "preview/diagnostics.json")).json())
        .frequencyModel,
    ).toBe("none")
    expect(
      (
        await cli([
          input,
          ...flags,
          "--solver",
          "approximation",
          "--frequency-hz",
          "1000000",
        ])
      ).stderr,
    ).toContain("no frequency model")
    expect(
      (
        await cli([
          "resample",
          join(directory, "case"),
          "--frequency-hz",
          "2000000",
        ])
      ).stderr,
    ).toContain("starting a new simulation")
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
