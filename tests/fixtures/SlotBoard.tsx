import { Signal } from "./Signal"

export const slotRoutes = [
  [
    { x: -18, y: 5 },
    { x: -11, y: 5 },
    { x: -10, y: 4 },
    { x: -10, y: -8 },
    { x: -9, y: -9 },
    { x: -2, y: -9 },
    { x: 0, y: -7 },
    { x: 0, y: 10 },
    { x: 1, y: 11 },
    { x: 17, y: 11 },
    { x: 18, y: 10 },
    { x: 18, y: -7 },
    { x: 17, y: -8 },
    { x: 8, y: -8 },
    { x: 7, y: -7 },
    { x: 7, y: -1 },
    { x: 8, y: 0 },
    { x: 13, y: 0 },
  ],
  [
    { x: -18, y: 0 },
    { x: -14, y: 0 },
    { x: -13, y: -1 },
    { x: -13, y: -12 },
    { x: -12, y: -13 },
    { x: 2, y: -13 },
    { x: 3, y: -12 },
    { x: 3, y: 7 },
    { x: 4, y: 8 },
    { x: 14, y: 8 },
    { x: 15, y: 7 },
    { x: 15, y: -3 },
    { x: 14, y: -4 },
    { x: 13, y: -4 },
  ],
  [
    { x: -18, y: -4 },
    { x: -17, y: -4 },
    { x: -16, y: -5 },
    { x: -16, y: -16 },
    { x: -15, y: -17 },
    { x: 5, y: -17 },
    { x: 6, y: -16 },
    { x: 6, y: 4 },
    { x: 7, y: 5 },
    { x: 13, y: 5 },
  ],
]

export const groundSlotOutline = [
  { x: -20, y: -20 },
  { x: -6, y: -20 },
  { x: -6, y: 19 },
  { x: -3, y: 19 },
  { x: -3, y: -20 },
  { x: 20, y: -20 },
  { x: 20, y: 20 },
  { x: -20, y: 20 },
]

export function SlotBoard({ unbrokenGround }: { unbrokenGround?: boolean }) {
  return (
    <board width={40} height={40} layers={2} thickness={0.8} schematicDisabled>
      <net name="GND" />
      {slotRoutes.map((route, signalIndex) => (
        <Signal
          key={signalIndex}
          name={`SIG${signalIndex + 1}`}
          route={route}
        />
      ))}
      <copperpour
        layer="bottom"
        connectsTo="net.GND"
        outline={unbrokenGround ? undefined : groundSlotOutline}
        boardEdgeMargin={0}
        padMargin={0}
        traceMargin={0}
      />
    </board>
  )
}
