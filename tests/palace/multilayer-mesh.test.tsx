import { expect, test } from "bun:test"
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { multilayerModel } from "tests/fixtures/renderMultilayerBoard"

const python = process.env.PALACE_MESH_PYTHON
test.skipIf(!python)(
  "Gmsh meshes four-layer dielectric interfaces, blind vias, through barrels and coplanar ports",
  async () => {
    const directory = await mkdtemp(
      join(tmpdir(), "return-current-multilayer-"),
    )
    try {
      for (const referenceLayer of ["top", "inner2"] as const) {
        const { model } = await multilayerModel({ referenceLayer })
        await writeFile(join(directory, "model.json"), JSON.stringify(model))
        const child = Bun.spawn(
          [
            python!,
            resolve("lib/palace/python/mesh.py"),
            join(directory, "model.json"),
          ],
          { stdout: "pipe", stderr: "pipe" },
        )
        const [stdout, stderr, code] = await Promise.all([
          new Response(child.stdout).text(),
          new Response(child.stderr).text(),
          child.exited,
        ])
        if (code !== 0)
          throw new Error(`Gmsh failed: ${stdout.slice(-2000)}\n${stderr}`)
        const config = JSON.parse(
          await readFile(join(directory, "palace.json"), "utf8"),
        )
        expect(
          config.Domains.Materials.map(
            (m: { Attributes: number[] }) => m.Attributes[0],
          ),
        ).toEqual([1, 3, 105, 103, 101])
        expect(
          config.Domains.Materials.slice(2).map(
            (m: { Permittivity: number }) => m.Permittivity,
          ),
        ).toEqual([4.1, 4.42, 4.1])
        expect(
          config.Boundaries.LumpedPort.map((p: { R: number }) => p.R),
        ).toEqual([25, 100])
        const dz = model.ports![0].referenceZ! - model.ports![0].signalZ!
        const length = Math.hypot(1.5, dz)
        expect(config.Boundaries.LumpedPort[0].Direction[1]).toBeCloseTo(
          1.5 / length,
          12,
        )
        expect(config.Boundaries.LumpedPort[0].Direction[2]).toBeCloseTo(
          dz / length,
          12,
        )
        const summary = JSON.parse(
          await readFile(join(directory, "mesh-summary.json"), "utf8"),
        )
        expect(summary.copperVolumeMm3).toBeGreaterThan(2)
        expect(summary.tetrahedra).toBeGreaterThan(100)
        expect(summary.sampleLayer).toBe("inner2")
        expect(summary.portAttributes).toEqual([21, 22])
      }
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  },
  240000,
)

test.skipIf(!python)(
  "layered ports reject floating ground pads and apertures through an intermediate plane",
  async () => {
    const { Circuit } = await import("@tscircuit/core")
    const { MultilayerBoard, fourLayerStackup } = await import(
      "tests/fixtures/MultilayerBoard"
    )
    const { createPalaceModel, withNamedExcitations } = await import(
      "lib/index"
    )
    const directory = await mkdtemp(
      join(tmpdir(), "return-current-invalid-layered-"),
    )
    try {
      for (const mode of ["floating", "obstructed"] as const) {
        const circuit = new Circuit()
        circuit.add(<MultilayerBoard innerPlane />)
        await circuit.renderUntilSettled()
        const circuitJson = withNamedExcitations({
          circuitJson: circuit
            .getCircuitJson()
            .filter(
              (element) =>
                mode !== "floating" ||
                element.type !== "pcb_via" ||
                !element.source_net_id,
            ),
          groundNet: "GND",
          ports: [
            {
              source: "U1.OUT",
              load: "U2.IN",
              current: "5mA",
              ...(mode === "floating"
                ? { sourceReference: "U1.GND", loadReference: "U2.GND" }
                : {}),
            },
          ],
        })
        const model = createPalaceModel({
          circuitJson,
          stackup: fourLayerStackup,
          frequencyHz: 1e6,
        })
        const filename = join(directory, "model.json")
        await writeFile(filename, JSON.stringify(model))
        const child = Bun.spawn(
          [python!, resolve("lib/palace/python/mesh.py"), filename],
          { stdout: "pipe", stderr: "pipe" },
        )
        const [, stderr, code] = await Promise.all([
          new Response(child.stdout).text(),
          new Response(child.stderr).text(),
          child.exited,
        ])
        expect(code).not.toBe(0)
        expect(stderr).toContain(
          mode === "floating"
            ? "not physically connected"
            : "intermediate copper",
        )
      }
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  },
  60000,
)
