/** Local reproduction of the AM3352 MMC0_DAT3 via / VIN_5V width change. */
export function TraceCapBoard({ short = false }: { short?: boolean }) {
  return (
    <board width={100} height={80} layers={4} schematicDisabled>
      <net name="GND" />
      <net name="MMC0_DAT3" />
      <net name="VIN_5V" />
      {[
        { name: "M1", x: -24.4, y: 26.6 },
        { name: "M2", x: -18.7, y: 12.5 },
        { name: "V1", x: -19.1, y: 11.609090909090913 },
        {
          name: "V2",
          x: short ? -18.75 : -18.5,
          y: short ? 12.35 : 12.018181818181823,
        },
      ].map(({ name, x, y }) => (
        <chip
          key={name}
          name={name}
          pcbX={x}
          pcbY={y}
          pinLabels={{ pin1: "IO" }}
          footprint={
            <footprint>
              <smtpad
                portHints={["pin1"]}
                pcbX={0}
                pcbY={0}
                radius={0.05}
                shape="circle"
                layer="inner1"
              />
            </footprint>
          }
        />
      ))}
      <trace
        from=".M1 > .IO"
        to=".M2 > .IO"
        thickness={0.1}
        pcbPathRelativeTo=".M1 > .IO"
        pcbPath={[
          { x: 0, y: 0 },
          { x: 5.7, y: -14.1 },
        ]}
      />
      <trace from=".M1 > .IO" to="net.MMC0_DAT3" />
      <trace
        from=".V1 > .IO"
        to=".V2 > .IO"
        thickness={1}
        pcbPathRelativeTo=".V1 > .IO"
        pcbPath={[
          { x: 0, y: 0 },
          { x: 0.2, y: 0.136363636363635 },
          { x: 0.4, y: 0.272727272727273 },
          {
            x: short ? 0.35 : 0.6,
            y: short ? 0.740909090909087 : 0.40909090909091,
          },
        ]}
      />
      <trace from=".V1 > .IO" to="net.VIN_5V" />
      <via
        name="MV"
        pcbX={-18.7}
        pcbY={12.5}
        fromLayer="top"
        toLayer="bottom"
        connectsTo="net.MMC0_DAT3"
        holeDiameter={0.15}
        outerDiameter={0.3}
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
