import { Circuit } from "@tscircuit/core"

export const syntheticStackup = {
  source: "assumed" as const,
  layers: [
    {
      type: "copper" as const,
      layer: "top" as const,
      thickness_mm: 0.035,
      conductivity_s_per_m: 58e6,
    },
    {
      type: "dielectric" as const,
      material: "Synthetic nondispersive test dielectric",
      thickness_mm: 0.2,
      dielectric_constant: 4,
      dielectric_constant_frequency_hz: 1e9,
      dielectric_loss_tangent: 0,
      dielectric_loss_tangent_frequency_hz: 1e9,
    },
    {
      type: "copper" as const,
      layer: "bottom" as const,
      thickness_mm: 0.035,
      conductivity_s_per_m: 58e6,
    },
  ],
}

const receiver =
  ".subckt receiver signal reference\nVbias bias reference .75\nRload signal bias 60\nCload signal reference 1e-12\n.ends receiver"
const driver = (switching: boolean) =>
  ".subckt driver signal reference\nVdrive internal reference PWL(" +
  (switching
    ? "0 0 2e-9 0 2.1e-9 1.5 4.1e-9 1.5 4.2e-9 0 8e-9 0"
    : "0 0 8e-9 0") +
  ")\nRsource internal signal 40\n.ends driver"

/** Ideal source/load fixture pads expose top signal and bottom reference ports. */
export function CoupledLines({
  gap = 0.1,
  physicalData = true,
  bend = false,
}: {
  gap?: number
  physicalData?: boolean
  bend?: boolean
}) {
  return (
    <board
      width={54}
      height={12}
      layers={2}
      thickness={0.27}
      routingDisabled
      schematicDisabled
      {...(physicalData ? { stackup: syntheticStackup } : {})}
    >
      <net name="GND" isGroundNet />
      <analogsimulation
        duration="8ns"
        timePerStep="1ps"
        spiceEngine="record-testbench"
      />
      {[0, 1].flatMap((line) =>
        [0, 1].map((end) => {
          const name = "U" + (1 + line + end * 2)
          return (
            <chip
              key={name}
              name={name}
              pcbX={end ? 25 : -25}
              pcbY={((line ? 1 : -1) * (0.3 + gap)) / 2}
              pinLabels={{ pin1: "SIGNAL", pin2: "REF" }}
              footprint={
                <footprint>
                  <smtpad
                    portHints={["pin1"]}
                    shape="rect"
                    width={0.3}
                    height={0.3}
                    pcbX={0}
                    pcbY={0}
                    layer="top"
                  />
                  <smtpad
                    portHints={["pin2"]}
                    shape="rect"
                    width={0.3}
                    height={0.3}
                    pcbX={0}
                    pcbY={0}
                    layer="bottom"
                  />
                </footprint>
              }
            >
              <spicemodel
                source={end ? receiver : driver(line === 1)}
                spicePinMapping={{ signal: "SIGNAL", reference: "REF" }}
              />
            </chip>
          )
        }),
      )}
      {[1, 2, 3, 4].map((n) => (
        <trace key={String(n)} from={".U" + n + " > .REF"} to="net.GND" />
      ))}
      {[0, 1].map((line) => (
        <trace
          key={String(line)}
          from={".U" + (1 + line) + " > .SIGNAL"}
          to={".U" + (3 + line) + " > .SIGNAL"}
          thickness={0.3}
          pcbPathRelativeTo={".U" + (1 + line) + " > .SIGNAL"}
          pcbPath={
            bend && line === 0
              ? [
                  { x: 25, y: 1 },
                  { x: 50, y: 0 },
                ]
              : [{ x: 50, y: 0 }]
          }
        />
      ))}
      <copperpour
        layer="bottom"
        connectsTo="net.GND"
        outline={[
          { x: -27, y: -6 },
          { x: 27, y: -6 },
          { x: 27, y: 6 },
          { x: -27, y: 6 },
        ]}
      />
    </board>
  )
}

export async function renderCoupledLines(
  props: Parameters<typeof CoupledLines>[0] = {},
) {
  // Render declarations only. This recording engine emits no numerical graphs;
  // the analyzer executes the geometry-dependent ngspice model afterwards.
  const circuit = new Circuit({
    platform: {
      spiceEngineMap: {
        "record-testbench": {
          simulate: async () => ({ simulationResultCircuitJson: [] }),
        },
      },
    },
  })
  circuit.add(<CoupledLines {...props} />)
  await circuit.renderUntilSettled()
  return circuit.getCircuitJson()
}
