import { expect, test } from "bun:test"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { NamedPortBoard } from "tests/fixtures/NamedPortBoard"
import { renderFixture } from "tests/fixtures/render-fixture"
import { ExplicitPortBoard } from "tests/fixtures/ExplicitPortBoard"
import { Circuit } from "@tscircuit/core"

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

test("CLI explicit reference pins, impedances and unit currents reach the saved Palace model", async () => {
  const circuit = new Circuit()
  circuit.add(<ExplicitPortBoard />)
  await circuit.renderUntilSettled()
  const directory = await mkdtemp(join(tmpdir(), "return-current-explicit-"))
  try {
    const input = join(directory, "board.json")
    await Bun.write(input, JSON.stringify(circuit.getCircuitJson()))
    const common = [
      input,
      "--ground",
      "GND",
      "--frequency-hz",
      "1000000",
      "--prepare-only",
      "--output",
      join(directory, "case"),
    ]
    const flags = [
      "--source",
      "U1.OUT",
      "--source-reference",
      "U1.GND",
      "--load",
      "U2.IN",
      "--load-reference",
      "U2.GND",
      "--current",
      "5mA",
      "--source-impedance",
      "25ohm",
      "--load-impedance",
      "1kohm",
    ]
    const prepared = await cli([...common, ...flags])
    expect(prepared.code).toBe(0)
    const model = await Bun.file(join(directory, "case/model.json")).json()
    expect(model.geometry.excitations[0].current).toBe(0.005)
    expect(
      model.ports.map((port: { resistance: number }) => port.resistance),
    ).toEqual([25, 1000])
    expect(model.ports[0].reference).toEqual({ x: -2, y: 1.5 })
    expect(model.groundVias).toHaveLength(2)
    expect(
      (
        await cli([
          ...common,
          "--excitation",
          "U1.OUT,U1.GND,U2.IN,U2.GND,-0.1A",
          "--load-impedance",
          "100",
        ])
      ).code,
    ).toBe(0)
    expect(
      (await Bun.file(join(directory, "case/model.json")).json()).geometry
        .excitations[0].current,
    ).toBe(-0.1)
    const file = join(directory, "ports.json")
    await Bun.write(
      file,
      JSON.stringify([
        {
          source: "U1.OUT",
          sourceReference: "U1.GND",
          load: "U2.IN",
          loadReference: "U2.GND",
          current: "250uA",
          sourceImpedance: 10,
          loadImpedance: "100ohm",
        },
      ]),
    )
    expect((await cli([...common, "--ports-file", file])).code).toBe(0)
    expect(
      (await Bun.file(join(directory, "case/model.json")).json()).geometry
        .excitations[0].current,
    ).toBe(0.00025)
    const provenance = await Bun.file(
      join(directory, "case/excitation-ports.json"),
    ).json()
    expect(provenance.ports[0].current).toBe(0.00025)
    expect(provenance.ports[0].loadImpedance).toBe(100)
    expect(
      (await cli([...common, "--ports-file", file, "--current", "5mA"])).stderr,
    ).toContain("Choose --ports-file")
    expect(
      (
        await cli([
          ...common,
          ...flags.map((value) => (value === "5mA" ? "5MA" : value)),
        ])
      ).stderr,
    ).toContain("Invalid current")
    await Bun.write(
      file,
      JSON.stringify([
        { source: "U1.OUT", load: "U2.IN", current: "5mA", typo: true },
      ]),
    )
    expect((await cli([...common, "--ports-file", file])).code).toBe(1)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
