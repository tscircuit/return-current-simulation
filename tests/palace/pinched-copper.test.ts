import { expect, test } from "bun:test"
import { resolve } from "node:path"

const python = process.env.PALACE_MESH_PYTHON
test.skipIf(!python)(
  "Palace prism construction opens the three isolated AM3352 point contacts",
  async () => {
    const script = `
import sys,json
from pathlib import Path
import gmsh
from shapely.geometry import shape
sys.path.insert(0,sys.argv[1])
from mesh_multilayer import prism
cases=[('top-pinched-hole',7.55,1.15,1.4942,1.5292),('bottom-touching-antipads',-34.95,-4.65,-.035,0),('ddr-vref-inner1',-10.95,-23.6,1.3796,1.3948)]
result=[]
gmsh.initialize();gmsh.option.setNumber('General.Terminal',0)
try:
 for name,x,y,zmin,zmax in cases:
  gmsh.clear();gmsh.model.add(name)
  polygon=shape(json.loads((Path(sys.argv[2])/(name+'.geojson')).read_text()));repairs=[]
  entities=prism({'shape':polygon,'zMin':zmin,'zMax':zmax,'repairs':repairs})
  gmsh.model.occ.synchronize()
  result.append({'case':name,'volumes':len(entities),'repairs':repairs,
   'contactInside':sum(gmsh.model.isInside(3,tag,[x,y,(zmin+zmax)/2]) for _,tag in entities),
   'removedVolumeMm3':polygon.area*(zmax-zmin)-sum(gmsh.model.occ.getMass(*e) for e in entities)})
finally:gmsh.finalize()
print(json.dumps(result))
`
    const process = Bun.spawn(
      [
        python!,
        "-c",
        script,
        resolve("lib/palace/python"),
        resolve("tests/fixtures/cad-reproductions"),
      ],
      { stdout: "pipe", stderr: "pipe" },
    )
    const [code, stdout, stderr] = await Promise.all([
      process.exited,
      new Response(process.stdout).text(),
      new Response(process.stderr).text(),
    ])
    if (code) throw new Error(stderr)
    const cases: {
      volumes: number
      repairs: unknown[]
      contactInside: number
      removedVolumeMm3: number
    }[] = JSON.parse(stdout)
    expect(cases).toHaveLength(3)
    for (const entry of cases) {
      expect(entry.volumes).toBe(1)
      expect(entry.repairs).toHaveLength(1)
      expect(entry.contactInside).toBe(0)
      expect(entry.removedVolumeMm3).toBeGreaterThan(0)
      expect(entry.removedVolumeMm3).toBeLessThan(2e-9)
    }
  },
  30_000,
)
