import { Signal } from "./Signal"

export function StraightBoard({
  splitGround,
  physicalCutout,
  narrowSlot,
}: {
  splitGround?: boolean
  physicalCutout?: boolean
  narrowSlot?: boolean
}) {
  const slitWidth = narrowSlot ? 0.04 : 2
  const outline = [
    { x: -15, y: -10 },
    { x: -slitWidth / 2, y: -10 },
    { x: -slitWidth / 2, y: 8 },
    { x: slitWidth / 2, y: 8 },
    { x: slitWidth / 2, y: -10 },
    { x: 15, y: -10 },
    { x: 15, y: 10 },
    { x: -15, y: 10 },
  ]
  return (
    <board width={30} height={20} layers={2} thickness={0.8} schematicDisabled>
      <net name="GND" />
      <Signal
        name="SIG"
        route={
          physicalCutout
            ? [
                { x: -12, y: 0 },
                { x: -4, y: 0 },
                { x: -4, y: 6 },
                { x: 4, y: 6 },
                { x: 4, y: 0 },
                { x: 12, y: 0 },
              ]
            : [
                { x: -12, y: 0 },
                { x: 12, y: 0 },
              ]
        }
      />
      {physicalCutout && (
        <cutout shape="rect" pcbX={0} pcbY={0} width={4} height={6} />
      )}
      {splitGround ? (
        <>
          <copperpour
            layer="bottom"
            connectsTo="net.GND"
            outline={[
              { x: -15, y: -10 },
              { x: -1, y: -10 },
              { x: -1, y: 10 },
              { x: -15, y: 10 },
            ]}
            boardEdgeMargin={0}
          />
          <copperpour
            layer="bottom"
            connectsTo="net.GND"
            outline={[
              { x: 1, y: -10 },
              { x: 15, y: -10 },
              { x: 15, y: 10 },
              { x: 1, y: 10 },
            ]}
            boardEdgeMargin={0}
          />
        </>
      ) : (
        <copperpour
          layer="bottom"
          connectsTo="net.GND"
          outline={narrowSlot ? outline : undefined}
          boardEdgeMargin={0}
          cutoutMargin={0}
          padMargin={0}
          traceMargin={0}
        />
      )}
    </board>
  )
}
