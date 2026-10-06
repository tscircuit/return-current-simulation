import { useState } from "react"
import { renderPalaceModelSvg } from "lib/index"
import type { PalaceModel, PalaceReference } from "lib/index"
import innerModel from "../examples/palace/multilayer-inner2-1mhz/model.json"
import innerReference from "../examples/palace/multilayer-inner2-1mhz/reference.json"
import bottomModel from "../examples/palace/multilayer-bottom-1mhz/model.json"
import bottomReference from "../examples/palace/multilayer-bottom-1mhz/reference.json"

export default function PalaceMultilayerPage() {
  const [layer, setLayer] = useState("inner2")
  const [phaseDegrees, setPhaseDegrees] = useState(0)
  const model = (layer === "inner2" ? innerModel : bottomModel) as PalaceModel
  const reference = (
    layer === "inner2" ? innerReference : bottomReference
  ) as PalaceReference
  const svg = renderPalaceModelSvg(model, {
    reference,
    phaseDegrees,
    title: `Four-layer board: ${layer} return at 1 MHz`,
    maxCurrentDensity: 0.2,
    width: 1000,
    height: 1000,
    vectorSpacing: 5,
  })
  return (
    <main style={{ maxWidth: 1100, padding: 24, fontFamily: "sans-serif" }}>
      <h1>Palace return current across multiple ground layers</h1>
      <p>
        5 mA peak at 1 MHz, 25 Ω source / 100 Ω load. Top pads connect through
        blind vias to an inner1 signal; ground through vias connect inner2 and
        bottom. These recorded FEM examples are not mesh-convergence certified.
      </p>
      <label>
        Sampled copper{" "}
        <select
          value={layer}
          onChange={(event) => setLayer(event.target.value)}
        >
          <option>inner2</option>
          <option>bottom</option>
        </select>
      </label>
      <label style={{ marginLeft: 20 }}>
        Arrow phase {phaseDegrees}°{" "}
        <input
          type="range"
          min={0}
          max={360}
          step={15}
          value={phaseDegrees}
          onChange={(event) => setPhaseDegrees(Number(event.target.value))}
        />
      </label>
      <div dangerouslySetInnerHTML={{ __html: svg }} />
    </main>
  )
}
