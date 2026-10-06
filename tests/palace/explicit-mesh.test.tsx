import { expect, test } from "bun:test"
import { Circuit } from "@tscircuit/core"
import { mkdtemp, rm, readFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { preparePalaceSimulation } from "lib/palace"
import { ExplicitPortBoard } from "tests/fixtures/ExplicitPortBoard"

const python = process.env.PALACE_MESH_PYTHON
test.skipIf(!python)(
  "Gmsh builds drilled two-terminal ports with distinct resistances and nonzero copper volume",
  async () => {
    const directory = await mkdtemp(join(tmpdir(), "return-current-mesh-"))
    try {
      for (const referenceLayer of ["top", "bottom"] as const) {
        const circuit = new Circuit()
        circuit.add(<ExplicitPortBoard referenceLayer={referenceLayer} />)
        await circuit.renderUntilSettled()
        const destination = join(directory, referenceLayer)
        await preparePalaceSimulation({
          circuitJson: circuit.getCircuitJson(),
          groundNet: "GND",
          ports: [
            {
              source: "U1.OUT",
              sourceReference: "U1.GND",
              load: "U2.IN",
              loadReference: "U2.GND",
              current: "5mA",
              sourceImpedance: 25,
              loadImpedance: 100,
            },
          ],
          frequencyHz: 1e6,
          outputDirectory: destination,
          order: 1,
          meshSize: 2,
          airPadding: 2,
        })
        const child = Bun.spawn(
          [
            python!,
            resolve("lib/palace/python/mesh.py"),
            join(destination, "model.json"),
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
          await readFile(join(destination, "palace.json"), "utf8"),
        )
        expect(
          config.Boundaries.LumpedPort.map((port: { R: number }) => port.R),
        ).toEqual([25, 100])
        expect(config.Boundaries.LumpedPort[0].Direction).toEqual(
          referenceLayer === "top"
            ? [0, 1, 0]
            : [0, 1.5 / Math.hypot(1.5, 0.8), -0.8 / Math.hypot(1.5, 0.8)],
        )
        const summary = JSON.parse(
          await readFile(join(destination, "mesh-summary.json"), "utf8"),
        )
        expect(summary.tetrahedra).toBeGreaterThan(100)
        expect(summary.portAttributes).toEqual([21, 22])
        // The polygon ring adapter must subtract drill area rather than add it.
        const area = Bun.spawn(
          [
            python!,
            "-c",
            `import sys; sys.path.insert(0, ${JSON.stringify(resolve("lib/palace/python"))}); import gmsh; from mesh import add_polygon; from shapely.geometry import Polygon; gmsh.initialize(); p=Polygon([(0,0),(4,0),(4,4),(0,4)], [[(1,1),(1,2),(2,2),(2,1)]]); s=add_polygon(p,0); assert abs(gmsh.model.occ.getMass(*s)-15)<1e-8; gmsh.finalize()`,
          ],
          { stdout: "pipe", stderr: "pipe" },
        )
        await Promise.all([
          new Response(area.stdout).text(),
          new Response(area.stderr).text(),
        ])
        expect(await area.exited).toBe(0)
      }
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  },
  120000,
)
