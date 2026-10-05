export function NamedPortBoard({ reverse = false }: { reverse?: boolean }) {
  return (
    <board width={30} height={20} layers={2} thickness={0.8} schematicDisabled>
      <net name="GND" />
      <chip
        name="R1"
        pcbX={-12}
        pcbY={0}
        pinLabels={{ pin1: "OUT" }}
        footprint={
          <footprint>
            <smtpad
              portHints={["pin1"]}
              pcbX={0}
              pcbY={0}
              width={0.8}
              height={0.8}
              shape="rect"
            />
          </footprint>
        }
      />
      <chip
        name="U1"
        pcbX={12}
        pcbY={0}
        pinLabels={{ pin1: "VDDIO1" }}
        footprint={
          <footprint>
            <smtpad
              portHints={["pin1"]}
              pcbX={0}
              pcbY={0}
              width={0.8}
              height={0.8}
              shape="rect"
            />
          </footprint>
        }
      />
      <trace
        name="SIG"
        from={reverse ? ".U1 > .VDDIO1" : ".R1 > .pin1"}
        to={reverse ? ".R1 > .pin1" : ".U1 > .VDDIO1"}
        thickness={0.18}
        pcbPathRelativeTo={reverse ? ".U1 > .VDDIO1" : ".R1 > .pin1"}
        pcbPath={[
          { x: 0, y: 0 },
          { x: reverse ? -24 : 24, y: 0 },
        ]}
      />
      <copperpour
        layer="bottom"
        connectsTo="net.GND"
        boardEdgeMargin={0}
        padMargin={0}
        traceMargin={0}
      />
    </board>
  )
}
