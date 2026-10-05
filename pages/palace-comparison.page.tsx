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
import wideCircuit from "../examples/palace/ground-slot-wide-gap-1mhz/circuit.json"
import wideReference from "../examples/palace/ground-slot-wide-gap-1mhz/reference.json"
import wideFlux from "../examples/palace/ground-slot-wide-gap-1mhz/flux-check.json"

export default function PalaceComparisonPage() {
  const [topGap, setTopGap] = useState(4)
  const [phaseDegrees, setPhaseDegrees] = useState(0)
  const [hideVectors, setHideVectors] = useState(false)
  const reference = (
    topGap === 4 ? wideReference : frozenReference
  ) as PalaceReference
  const circuitJson = (
    topGap === 4 ? wideCircuit : frozenCircuit
  ) as ReturnCurrentCircuitJson
  const flux = topGap === 4 ? wideFlux : refinement.fluxCheck
  const result = useMemo(
    () =>
      simulateReturnCurrent({
        circuitJson,
        cellSize: reference.cellWidth,
        contactRadius: 0.6,
      }),
    [reference, circuitJson],
  )
  const comparison = useMemo(
    () => comparePalaceReference(result, { reference }),
    [result, reference],
  )
  const renderOptions = {
    width: 900,
    height: 1000,
    maxCurrentDensity: 50,
    vectorSpacing: Math.max(1, Math.round(1.5 / reference.cellWidth)),
    hideVectors,
  }
  const palaceSvg = renderPalaceReferenceSvg(result, {
    ...renderOptions,
    reference,
    phaseDegrees,
    title: `Palace: ${topGap} mm clearance above the slot`,
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
        Image samples: {reference.columns} × {reference.rows} at{" "}
        {reference.cellWidth} mm spacing. Palace solves conductive copper
        volumes in a 3D Maxwell model. Colors show magnitude of the complex
        conduction-current vector averaged through the foil. Arrows show the
        instantaneous return field.
      </p>
      <label>
        Clearance above slot:{" "}
        <select
          value={topGap}
          onChange={(event) => setTopGap(Number(event.target.value))}
        >
          <option value={4}>4 mm</option>
          <option value={1}>1 mm</option>
        </select>
      </label>{" "}
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
        Reference under validation: dense sampled bridge balance error{" "}
        {(100 * flux.relativeComplexBalanceError).toFixed(2)}%.
        {topGap === 1
          ? ` Coarse/fine field change: ${(100 * refinement.relativeComplexL2Change).toFixed(1)}%.`
          : " Mesh convergence for the 4 mm clearance has not been established."}
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
