import { writeFile } from "node:fs/promises"
import { createSampleMask } from "./create-sample-mask"
import { positiveFinite } from "../read-geometry"
import type { SimulationGeometry } from "../types"

/** Sample positions only; this does not construct or solve a FEM mesh. */
export async function writeSampleGrid(options: {
  destination: string
  geometry: SimulationGeometry
  cellSize?: number
}) {
  const cellSize = positiveFinite(options.cellSize ?? 0.2, "cellSize")
  const outline = options.geometry.boardOutline
  const minX = Math.min(...outline.map((point) => point.x))
  const maxX = Math.max(...outline.map((point) => point.x))
  const minY = Math.min(...outline.map((point) => point.y))
  const maxY = Math.max(...outline.map((point) => point.y))
  const columns = Math.max(2, Math.ceil((maxX - minX) / cellSize))
  const rows = Math.max(2, Math.ceil((maxY - minY) / cellSize))
  if (columns * rows > 1_000_000)
    throw new Error(
      "The sample grid exceeds 1,000,000 cells; increase cellSize",
    )
  const cellWidth = (maxX - minX) / columns
  const cellHeight = (maxY - minY) / rows
  const containsCopper = createSampleMask(options.geometry)
  const points = []
  for (let row = 0; row < rows; row++)
    for (let column = 0; column < columns; column++) {
      const point = {
        x: minX + (column + 0.5) * cellWidth,
        y: minY + (row + 0.5) * cellHeight,
      }
      if (containsCopper(point)) points.push(point)
    }
  if (!points.length)
    throw new Error("The sample grid contains no ground copper")
  await writeFile(
    `${options.destination}/sample-grid.json`,
    JSON.stringify({ columns, rows, cellWidth, cellHeight, points }),
  )
  return { columns, rows, cellWidth, cellHeight, copperSamples: points.length }
}
