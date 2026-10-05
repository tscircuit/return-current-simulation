import type { Point } from "circuit-json"

function Terminal({ name, point }: { name: string; point: Point }) {
  return (
    <chip
      name={name}
      pcbX={point.x}
      pcbY={point.y}
      pinLabels={{ pin1: "SIGNAL" }}
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
  )
}

export function Signal({ name, route }: { name: string; route: Point[] }) {
  return (
    <>
      <Terminal name={`${name}_S`} point={route[0]} />
      <Terminal name={`${name}_L`} point={route[route.length - 1]} />
      <trace
        name={name}
        from={`.${name}_S > .pin1`}
        to={`.${name}_L > .pin1`}
        thickness={0.18}
        pcbPathRelativeTo={`.${name}_S > .pin1`}
        pcbPath={route.map((point) => ({
          x: point.x - route[0].x,
          y: point.y - route[0].y,
        }))}
      />
    </>
  )
}
