import { useMemo, useState } from "react"
import {
  comparePalaceReference,
  renderPalaceReferenceSvg,
  renderReturnCurrentSvg,
  simulateReturnCurrent,
} from "lib/index"
import type { PalaceReference, ReturnCurrentCircuitJson } from "lib/index"
import frozenCircuit from "../examples/palace/ground-slot-1mhz/circuit.json"
import frozenReference from "../examples/palace/ground-slot-1mhz/reference.json"
import refinement from "../examples/palace/refinement.json"

export default function PalaceComparisonPage() {
  const [phaseDegrees, setPhaseDegrees] = useState(0)
  const [hideVectors, setHideVectors] = useState(false)
  const reference = frozenReference as PalaceReference
  const result = useMemo(
    () =>
      simulateReturnCurrent({
        circuitJson: frozenCircuit as ReturnCurrentCircuitJson,
        cellSize: 0.5,
        contactRadius: 0.6,
      }),
    [],
  )
  const comparison = useMemo(
    () => comparePalaceReference(result, { reference }),
    [result, reference],
  )
  const renderOptions = {
    width: 900,
    height: 1000,
    maxCurrentDensity: 50,
    vectorSpacing: 3,
    hideVectors,
  }
  const palaceSvg = renderPalaceReferenceSvg(result, {
    ...renderOptions,
    reference,
    phaseDegrees,
  })
  const approximationSvg = renderReturnCurrentSvg(result, renderOptions)
  return (
    <main
      style={{
        maxWidth: 1500,
        margin: "auto",
        padding: 24,
        fontFamily: "Arial, sans-serif",
      }}
    >
      <h1>Palace EM comparison at 1 MHz</h1>
      <p>
        Three in-phase 1 A peak signals; 35 µm copper, 0.8 mm FR4, εr = 4.3,
        tanδ = 0.02, 50 Ω ports.
      </p>
      <p>
        Palace solves conductive copper volumes in a 3D Maxwell model. Colors
        show magnitude of the complex conduction-current vector averaged through
        the foil. Arrows show the instantaneous return field.
      </p>
      <label>
        Arrow phase: {phaseDegrees}°{" "}
        <input
          type="range"
          min={0}
          max={360}
          step={15}
          value={phaseDegrees}
          onChange={(event) => setPhaseDegrees(Number(event.target.value))}
        />
      </label>{" "}
      <label>
        <input
          type="checkbox"
          checked={!hideVectors}
          onChange={(event) => setHideVectors(!event.target.checked)}
        />{" "}
        Show arrows
      </label>
      <p>
        Approximation vs Palace complex L2 difference:{" "}
        {(100 * comparison.relativeComplexL2Error).toFixed(1)}% (contacts and
        copper edges excluded). The approximation does not model frequency.
      </p>
      <p>
        Reference under validation: coarse/fine field change{" "}
        {(100 * refinement.relativeComplexL2Change).toFixed(1)}%; sampled bridge
        balance error{" "}
        {(100 * refinement.fluxCheck.relativeComplexBalanceError).toFixed(1)}%.
        These results are not established ground truth.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        {[
          { name: "Palace", svg: palaceSvg },
          { name: "Approximation", svg: approximationSvg },
        ].map(({ name, svg }) => (
          <figure key={name} style={{ flex: "1 1 500px", margin: 0 }}>
            <figcaption>{name}</figcaption>
            <img
              alt={`${name} return-current field`}
              src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
              style={{ width: "100%" }}
            />
            <a
              download={`${name.toLowerCase()}-return-current.svg`}
              href={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
            >
              Download SVG
            </a>
          </figure>
        ))}
      </div>
    </main>
  )
}
