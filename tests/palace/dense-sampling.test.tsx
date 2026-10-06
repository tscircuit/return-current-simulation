import { expect, test } from "bun:test"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { createPalaceModel } from "lib/index"
import { writeSampleGrid } from "../../scripts/palace/write-sample-grid"
import { SlotBoard } from "tests/fixtures/SlotBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("0.05 mm Palace sampling uses an 800 × 800 grid from the wider TSX board", async () => {
  const circuitJson = await renderFixture(<SlotBoard topGap={4} />, [1, 1, 1])
  const model = createPalaceModel({ circuitJson, frequencyHz: 1e6 })
  const destination = await mkdtemp(join(tmpdir(), "palace-grid-"))
  try {
    const summary = await writeSampleGrid({
      destination,
      geometry: model.geometry,
      cellSize: 0.05,
    })
    expect(summary).toEqual({
      columns: 800,
      rows: 800,
      cellWidth: 0.05,
      cellHeight: 0.05,
      copperSamples: 596800,
    })
    const grid = await Bun.file(`${destination}/sample-grid.json`).json()
    expect(grid.points.length).toBe(596800)
    expect(grid.points[0]).toEqual({ x: -19.975, y: -19.975 })
    expect(grid.points.at(-1)).toEqual({ x: 19.975, y: 19.975 })
    expect(
      grid.points.some(
        (point: { x: number; y: number }) =>
          point.x > -6 && point.x < -3 && point.y < 16,
      ),
    ).toBe(false)
    await expect(
      writeSampleGrid({
        destination,
        geometry: model.geometry,
        cellSize: 0.01,
      }),
    ).rejects.toThrow("1,000,000")
  } finally {
    await rm(destination, { recursive: true, force: true })
  }
})
