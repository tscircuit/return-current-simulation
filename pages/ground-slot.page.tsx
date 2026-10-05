import { useMemo, useState } from "react"
import { renderReturnCurrentSvg, simulateReturnCurrent } from "lib/index"
import type { ReturnCurrentCircuitJson } from "lib/types"
import slottedCircuit from "../examples/ground-slot.circuit.json"
import intactCircuit from "../examples/unbroken-ground.circuit.json"

export default function GroundSlotPage() {
  const [unbrokenGround, setUnbrokenGround] = useState(false)
  const [current, setCurrent] = useState(1)
  const [showVectors, setShowVectors] = useState(true)
  const result = useMemo(() => {
    const circuitJson = (
      unbrokenGround ? intactCircuit : slottedCircuit
    ) as ReturnCurrentCircuitJson
    const excitations = circuitJson
      .filter(
        (element) => element.type === "simulation_return_current_excitation",
      )
      .map((excitation) => ({ ...excitation, current }))
    return simulateReturnCurrent({
      circuitJson,
      excitations,
      cellSize: 0.5,
      contactRadius: 0.6,
    })
  }, [unbrokenGround, current])
  const svg = renderReturnCurrentSvg(result, {
    width: 950,
    height: 1000,
    maxCurrentDensity: 50,
    hideVectors: !showVectors,
    vectorSpacing: 3,
    title: unbrokenGround
      ? "Unbroken ground plane"
      : "Return current around a ground-plane slot",
  })
  return (
    <main style={{ maxWidth: 1100, margin: "auto" }}>
      <h1>Explore ground-plane return current</h1>
      <p>
        Top signals cross the slot in the bottom copper. Compare their return
        paths with an unbroken reference plane.
      </p>
      <div
        style={{
          display: "flex",
          gap: 24,
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: 20,
        }}
      >
        <label>
          <input
            type="checkbox"
            checked={unbrokenGround}
            onChange={(event) => setUnbrokenGround(event.target.checked)}
          />{" "}
          Unbroken ground
        </label>
        <label>
          Signal current: {current} A{" "}
          <input
            type="range"
            min={0}
            max={2}
            step={0.25}
            value={current}
            onChange={(event) => setCurrent(Number(event.target.value))}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={showVectors}
            onChange={(event) => setShowVectors(event.target.checked)}
          />{" "}
          Direction arrows
        </label>
        <a
          download="return-current.svg"
          href={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
        >
          Download SVG
        </a>
      </div>
      <img
        src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`}
        alt="Computed ground-plane return-current density and direction"
        style={{ width: "100%", maxWidth: 950 }}
      />
      <p>
        High-frequency image-current approximation with conservation enforced on
        the copper mesh. It does not model waves, skin depth, or
        frequency-dependent impedance.
      </p>
    </main>
  )
}
