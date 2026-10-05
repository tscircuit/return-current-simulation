import { expect, test } from "bun:test"
import type { PcbGroundPlaneRegion } from "circuit-json"
import { simulateReturnCurrent } from "lib/index"
import type { ReturnCurrentCircuitJson } from "lib/types"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

test("ground-plane region records and copper-pour records describe the same copper", async () => {
  const circuitJson = await renderFixture(<StraightBoard />)
  const original = simulateReturnCurrent({ circuitJson, cellSize: 1 })
  // Core emits copper pours; convert only the representation to the older
  // circuit-json ground-plane records while preserving TSX-generated geometry.
  const equivalent: ReturnCurrentCircuitJson = [
    ...circuitJson.filter((element) => element.type !== "pcb_copper_pour"),
    {
      type: "pcb_ground_plane",
      pcb_ground_plane_id: "pcb_ground_plane_test",
      source_pcb_ground_plane_id: "source_pcb_ground_plane_test",
      source_net_id: original.geometry.excitations[0].ground_source_net_id,
    },
    ...original.geometry.groundRegions.map(
      (region, regionIndex): PcbGroundPlaneRegion => ({
        type: "pcb_ground_plane_region" as const,
        pcb_ground_plane_region_id: `pcb_ground_plane_region_${regionIndex}`,
        pcb_ground_plane_id: "pcb_ground_plane_test",
        layer: "bottom",
        points: region.outer,
      }),
    ),
  ]
  const converted = simulateReturnCurrent({
    circuitJson: equivalent,
    cellSize: 1,
  })
  expect(converted.edges.map((edge) => edge.current)).toEqual(
    original.edges.map((edge) => edge.current),
  )
})
