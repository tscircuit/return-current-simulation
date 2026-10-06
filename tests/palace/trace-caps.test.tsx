import { expect, test } from "bun:test"
import { Circuit } from "@tscircuit/core"
import { mkdtemp, writeFile, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { createPalaceModel, withNamedExcitations } from "lib/index"
import { TraceCapBoard } from "tests/fixtures/TraceCapBoard"
import { fourLayerStackup } from "tests/fixtures/MultilayerBoard"
import { traceOutline } from "lib/palace/copper-outlines"

const python = process.env.PALACE_MESH_PYTHON
test.skipIf(!python)(
  "round trace ends remove the AM3352 false overlap but still reject a real short",
  async () => {
    const directory = await mkdtemp(join(tmpdir(), "trace-caps-"))
    try {
      for (const short of [false, true]) {
        const circuit = new Circuit()
        circuit.add(<TraceCapBoard short={short} />)
        await circuit.renderUntilSettled()
        const circuitJson = withNamedExcitations({
          circuitJson: circuit.getCircuitJson(),
          groundNet: "GND",
          ports: [{ source: "M1.IO", load: "M2.IO", current: "5mA" }],
        })
        // Core currently emits a constant width; inject the exported VIN_5V widths.
        const source = circuitJson.find(
          (e) => e.type === "source_trace" && e.min_trace_thickness === 1,
        )!
        const trace = circuitJson.find(
          (e) =>
            e.type === "pcb_trace" &&
            source.type === "source_trace" &&
            e.source_trace_id === source.source_trace_id &&
            e.route.length > 2,
        )
        expect(trace?.type).toBe("pcb_trace")
        if (!trace || trace.type !== "pcb_trace")
          throw new Error("Missing VIN trace")
        for (const [index, point] of trace.route.entries())
          if (point.route_type === "wire")
            point.width = [1, 1, 0.7, 0.45, 0.45, 0.45][index]
        const model = createPalaceModel({
          circuitJson,
          stackup: fourLayerStackup,
          frequencyHz: 1e6,
        })
        const filename = join(directory, "model.json")
        await writeFile(filename, JSON.stringify(model))
        const outlines = model.multilayer!.copper.flatMap((group) =>
          group.segments.map((segment) => ({
            segment,
            outline: traceOutline(segment),
          })),
        )
        const outlineFile = join(directory, "outlines.json")
        await writeFile(outlineFile, JSON.stringify(outlines))
        const child = Bun.spawn(
          [
            python!,
            "-c",
            `
import sys,json
sys.path.insert(0,sys.argv[1])
from mesh_multilayer import build_layer_copper,copper_overlaps,layer_copper
from shapely.geometry import Polygon,LineString
m=json.load(open(sys.argv[2]))
mask_matches=True
for stroke in json.load(open(sys.argv[3])):
    segment=stroke["segment"]
    mask=Polygon([(p["x"],p["y"]) for p in stroke["outline"]])
    mesh=LineString([(segment[k]["x"],segment[k]["y"]) for k in ["start","end"]]).buffer(segment["width"]/2,quad_segs=8)
    mask_matches &= mask.symmetric_difference(mesh).area < 1e-9
_, old=build_layer_copper(m,trace_caps="square")
_, corrected=build_layer_copper(m)
print(json.dumps({"old":copper_overlaps(old),"corrected":copper_overlaps(corrected),"maskMatches":bool(mask_matches)}))
try:
    layer_copper(m)
except ValueError:
    sys.exit(2)
`,
            resolve("lib/palace/python"),
            filename,
            outlineFile,
          ],
          { stdout: "pipe", stderr: "pipe" },
        )
        const [stdout, stderr, code] = await Promise.all([
          new Response(child.stdout).text(),
          new Response(child.stderr).text(),
          child.exited,
        ])
        if (stderr) throw new Error(stderr)
        const result = JSON.parse(stdout)
        expect(
          result.old.some(
            (overlap: { layer: string }) => overlap.layer === "inner1",
          ),
        ).toBe(true)
        expect(result.corrected.length > 0).toBe(short)
        expect(result.maskMatches).toBe(true)
        expect(code).toBe(short ? 2 : 0)
      }
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  },
  60000,
)
