import { Fragment } from "react"

/** Circuit-json is generated through core, including the reference-pour void. */
export function DdrAuditBoard({ detour = false }: { detour?: boolean }) {
  const names = [
    ...Array.from({ length: 8 }, (_, bit) => `DDR_D${bit}`),
    "DDR_DQM0",
    "DDR_DQS0",
    "DDR_DQSn0",
  ]
  return (
    <board width={30} height={14} schematicDisabled>
      <net name="GND" />
      {names.map((name, index) => (
        <Fragment key={name}>
          {[-10, 10].map((x, side) => (
            <chip
              key={side}
              name={`${side === 0 ? "S" : "T"}${index}`}
              pcbX={x}
              pcbY={index - 5}
              pinLabels={{ pin1: "IO" }}
              footprint={
                <footprint>
                  <smtpad
                    portHints={["pin1"]}
                    pcbX={0}
                    pcbY={0}
                    radius={0.1}
                    shape="circle"
                    layer="top"
                  />
                </footprint>
              }
            />
          ))}
          <trace
            name={name}
            from={`.S${index} > .IO`}
            to={`.T${index} > .IO`}
            thickness={0.1}
            pcbPathRelativeTo={`.S${index} > .IO`}
            pcbPath={
              detour && index === 0
                ? [
                    { x: 0, y: 0 },
                    { x: 0, y: 0.2 },
                    { x: 20, y: 0.2 },
                    { x: 20, y: 0 },
                  ]
                : [
                    { x: 0, y: 0 },
                    { x: 20, y: 0 },
                  ]
            }
          />
        </Fragment>
      ))}
      <cutout shape="rect" pcbX={0} pcbY={0} width={1} height={0.5} />
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
