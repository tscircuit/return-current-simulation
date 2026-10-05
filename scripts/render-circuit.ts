import { Resvg } from "@resvg/resvg-js"
import {
  parseReturnCurrentCircuitJson,
  renderReturnCurrentSvg,
  simulateReturnCurrent,
} from "lib/index"

const [inputPath, outputPath, cellSizeArgument] = process.argv.slice(2)
if (!inputPath || !outputPath)
  throw new Error(
    "Usage: bun run render input.circuit.json output.svg|output.png [cellSizeMm]",
  )
const circuitJson = parseReturnCurrentCircuitJson(
  await Bun.file(inputPath).json(),
)
const result = simulateReturnCurrent({
  circuitJson,
  cellSize: cellSizeArgument ? Number(cellSizeArgument) : undefined,
})
const svg = renderReturnCurrentSvg(result)
if (!/\.(svg|png)$/.test(outputPath))
  throw new Error("Output filename must end in .svg or .png")
await Bun.write(
  outputPath,
  outputPath.endsWith(".png") ? new Resvg(svg).render().asPng() : svg,
)
console.log(result.diagnostics)
