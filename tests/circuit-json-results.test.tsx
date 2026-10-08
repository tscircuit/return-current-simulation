import { expect, test } from "bun:test"
import { gunzipSync } from "node:zlib"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import {
  any_circuit_element,
  getSimulationReturnCurrentGridJsonSchema,
  type SimulationReturnCurrentGridJson,
} from "circuit-json"
import {
  createReturnCurrentExperiment,
  selectReturnCurrentExperiment,
  exportReturnCurrentCircuitJson,
  parseReturnCurrentCircuitJson,
  simulateReturnCurrent,
  createPalaceModel,
} from "lib/index"
import { palaceGeometrySignature } from "lib/palace/geometry-signature"
import { createSampleMask } from "lib/palace/create-sample-mask"
import type { PalaceReference } from "lib/palace/types"
import type { ReturnCurrentCircuitJson } from "lib/types"
import { StraightBoard } from "tests/fixtures/StraightBoard"
import { renderFixture } from "tests/fixtures/render-fixture"

const experimentId = "simulation_experiment_test"
async function definitions() {
  const board = parseReturnCurrentCircuitJson(
    (await renderFixture(<StraightBoard physicalCutout />)).filter(
      (e) => e.type !== "simulation_return_current_excitation",
    ),
  )
  return createReturnCurrentExperiment({
    circuitJson: board,
    groundNet: "GND",
    experimentId,
    ports: [{ source: "SIG_S.pin1", load: "SIG_L.SIGNAL", current: "5mA" }],
  })
}
function fieldAndGrid(circuitJson: ReturnCurrentCircuitJson) {
  const field = circuitJson.find(
    (e) => e.type === "simulation_pcb_return_current_field",
  )!
  if (field.type !== "simulation_pcb_return_current_field")
    throw new Error("Missing field")
  const raw = Buffer.from(field.field_asset.url.split(",")[1], "base64")
  const decoded =
    field.field_asset.mimetype === "application/gzip" ? gunzipSync(raw) : raw
  const grid: SimulationReturnCurrentGridJson =
    getSimulationReturnCurrentGridJsonSchema(field).parse(
      JSON.parse(decoded.toString()),
    )
  return { field, grid }
}

test("official definitions and real results preserve the board, masks, units and portable assets", async () => {
  const input = await definitions()
  const selected = selectReturnCurrentExperiment({ circuitJson: input })
  expect(selected.excitations[0].current).toBe(0.005)
  expect(selected.excitations[0].return_sink.contact_type).toBe(
    "pcb_copper_pour",
  )
  const result = simulateReturnCurrent({
    circuitJson: input,
    excitations: selected.excitations,
    cellSize: 1,
  })
  const output = exportReturnCurrentCircuitJson({
    circuitJson: input,
    experimentId,
    resultId: "simulation_pcb_return_current_result_real",
    simulation: result,
  })
  output
    .filter((e) => e.type.startsWith("simulation_"))
    .forEach((e) => expect(any_circuit_element.safeParse(e).success).toBe(true))
  expect(output.slice(0, input.length)).toEqual([...input])
  const { field, grid } = fieldAndGrid(output)
  expect(field.field_asset.mimetype).toBe("application/gzip")
  expect(grid.field_type).toBe("real")
  if (grid.field_type !== "real") throw new Error("Wrong field")
  expect(grid.sheet_current_x.filter((v) => v === null)).not.toHaveLength(0)
  for (const node of result.nodes) {
    expect(grid.sheet_current_x[node.row * result.columns + node.column]).toBe(
      node.sheetCurrentX,
    )
    expect(grid.sheet_current_y[node.row * result.columns + node.column]).toBe(
      node.sheetCurrentY,
    )
  }
  const resultElement = output.find(
    (e) => e.type === "simulation_pcb_return_current_result",
  )!
  expect(resultElement).not.toHaveProperty("frequency_hz")
  const heatmap = output.find(
    (e) => e.type === "simulation_pcb_return_current_heatmap",
  )!
  if (heatmap.type !== "simulation_pcb_return_current_heatmap")
    throw new Error("Missing heatmap")
  expect(
    Buffer.from(heatmap.image_asset.url.split(",")[1], "base64")
      .subarray(1, 4)
      .toString(),
  ).toBe("PNG")
  expect(heatmap.min_x).toBe(result.bounds.minX)
  expect(heatmap.max_y).toBe(result.bounds.maxY)
  const rerun = exportReturnCurrentCircuitJson({
    circuitJson: output,
    experimentId,
    simulation: result,
    fieldFormat: "json",
  })
  expect(
    rerun.filter((e) => e.type === "simulation_pcb_return_current_result"),
  ).toHaveLength(1)
  expect(
    rerun.some(
      (e) =>
        "simulation_pcb_return_current_result_id" in e &&
        e.simulation_pcb_return_current_result_id ===
          "simulation_pcb_return_current_result_real",
    ),
  ).toBe(false)
  expect(fieldAndGrid(rerun).field.field_asset.mimetype).toBe(
    "application/json",
  )
  const stale = input.map((e) =>
    e.type === "simulation_return_current_excitation"
      ? { ...e, current: 0.1 }
      : e,
  )
  expect(() =>
    exportReturnCurrentCircuitJson({
      circuitJson: stale,
      experimentId,
      simulation: result,
    }),
  ).toThrow("stale")
})

test("phasor serializer keeps numerical A/mm channels and frequency, rejecting stale provenance", async () => {
  const input = await definitions()
  const selected = selectReturnCurrentExperiment({ circuitJson: input })
  const model = createPalaceModel({
    circuitJson: input,
    excitations: selected.excitations,
    frequencyHz: 1e6,
  })
  const mask = createSampleMask(model.geometry)
  // This is a serializer unit fixture, not a simulated physical field.
  const samples: PalaceReference["samples"] = []
  for (let row = 0; row < 20; row++)
    for (let column = 0; column < 30; column++) {
      const point = { x: -15 + column + 0.5, y: -10 + row + 0.5 }
      if (mask(point))
        samples.push({
          ...point,
          sheetCurrentXReal: column / 1000,
          sheetCurrentXImag: -0.002,
          sheetCurrentYReal: row / 1000,
          sheetCurrentYImag: 0.003,
        })
    }
  const reference: PalaceReference = {
    schemaVersion: 1,
    solver: "palace",
    solverVersion: "0.14.0",
    femOrder: 2,
    frequencyHz: 1e6,
    copperModel: "volumetric_copper",
    copperThickness: model.copperThickness,
    layerSeparation: model.layerSeparation,
    cellWidth: 1,
    cellHeight: 1,
    columns: 30,
    rows: 20,
    samples,
    sourceCurrents: [{ real: 0.005, imag: 0 }],
    loadCurrents: [{ real: 0.005, imag: 0 }],
    electricFieldScaleVoltsPerMeter: 1,
    normalizationConditionNumber: 1,
    provenance: {
      geometrySignature: palaceGeometrySignature(model.geometry),
      circuitSha256: "test",
      modelSha256: "test",
      meshSha256: "test",
    },
  }
  const output = exportReturnCurrentCircuitJson({
    circuitJson: input,
    experimentId,
    simulation: { model, reference },
  })
  const { grid } = fieldAndGrid(output)
  if (grid.field_type !== "complex_phasor") throw new Error("Wrong field")
  expect(grid.sheet_current_x_imag[0]).toBe(-0.002)
  expect(grid.sheet_current_y_imag[0]).toBe(0.003)
  expect(grid.sheet_current_x_real[31]).toBe(0.001)
  expect(
    output.find((e) => e.type === "simulation_pcb_return_current_result"),
  ).toHaveProperty("frequency_hz", 1e6)
  expect(() =>
    exportReturnCurrentCircuitJson({
      circuitJson: input,
      experimentId,
      simulation: {
        model,
        reference: {
          ...reference,
          provenance: { ...reference.provenance, geometrySignature: "wrong" },
        },
      },
    }),
  ).toThrow("provenance")
  const stale = input.map((e) =>
    e.type === "simulation_return_current_excitation"
      ? { ...e, current: 0.1 }
      : e,
  )
  expect(() =>
    exportReturnCurrentCircuitJson({
      circuitJson: stale,
      experimentId,
      simulation: { model, reference },
    }),
  ).toThrow("stale")
  expect(() =>
    exportReturnCurrentCircuitJson({
      circuitJson: input,
      experimentId,
      simulation: {
        model,
        reference: { ...reference, samples: samples.slice(1) },
      },
    }),
  ).toThrow("conductor mask")
})

test("CLI accepts pending definitions and flags; rejects ambiguous or broken experiment links", async () => {
  const input = await definitions()
  const directory = await mkdtemp(
    join(tmpdir(), "return-current-official-cli-"),
  )
  const run = async (args: string[]) => {
    const process = Bun.spawn(
      [Bun.which("bun")!, resolve(import.meta.dir, "../cli/index.ts"), ...args],
      { stdout: "pipe", stderr: "pipe" },
    )
    const [code, stdout, stderr] = await Promise.all([
      process.exited,
      new Response(process.stdout).text(),
      new Response(process.stderr).text(),
    ])
    return { code, stdout, stderr }
  }
  try {
    const filename = join(directory, "pending.json")
    await Bun.write(filename, JSON.stringify(input))
    const resultPath = join(directory, "result.json")
    const result = await run([
      filename,
      "--solver",
      "approximation",
      "--experiment-id",
      experimentId,
      "--output",
      join(directory, "case"),
      "--result-json",
      resultPath,
      "--cell-size",
      "1",
    ])
    expect(result.code).toBe(0)
    const output = parseReturnCurrentCircuitJson(
      await Bun.file(resultPath).json(),
    )
    expect(fieldAndGrid(output).grid.field_type).toBe("real")
    expect(
      (await run([filename, "--experiment-id", experimentId, "--prepare-only"]))
        .stderr,
    ).toContain("--frequency-hz")
    const other = createReturnCurrentExperiment({
      circuitJson: input,
      experimentId: "simulation_experiment_other",
      ports: [{ source: "SIG_S.pin1", load: "SIG_L.SIGNAL", current: 0.001 }],
      groundNet: "GND",
    })
    expect(() => selectReturnCurrentExperiment({ circuitJson: other })).toThrow(
      "Select exactly one",
    )
    expect(
      selectReturnCurrentExperiment({ circuitJson: other, experimentId })
        .excitations[0].current,
    ).toBe(0.005)
    const broken = input.map((e) =>
      e.type === "simulation_return_current_excitation"
        ? { ...e, ground_source_net_id: "missing" }
        : e,
    )
    expect(() =>
      selectReturnCurrentExperiment({ circuitJson: broken, experimentId }),
    ).toThrow("Missing ground")
    expect(() =>
      selectReturnCurrentExperiment({
        circuitJson: [...input, input[0]],
        experimentId,
      }),
    ).toThrow("Duplicate")
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test("opposite-direction experiments preserve the same original PCB and orient only the solver view", async () => {
  const input = await definitions()
  const original = selectReturnCurrentExperiment({ circuitJson: input })
  const result = simulateReturnCurrent({
    circuitJson: original.solverCircuitJson,
    excitations: original.excitations,
    cellSize: 1,
  })
  const completed = exportReturnCurrentCircuitJson({
    circuitJson: input,
    experimentId,
    simulation: result,
  })
  const reverseId = "simulation_experiment_reverse"
  const reverse = createReturnCurrentExperiment({
    circuitJson: completed,
    experimentId: reverseId,
    groundNet: "GND",
    ports: [{ source: "SIG_L.SIGNAL", load: "SIG_S.pin1", current: 0.005 }],
  })
  expect(reverse.slice(0, completed.length)).toEqual([...completed])
  const selected = selectReturnCurrentExperiment({
    circuitJson: reverse,
    experimentId: reverseId,
  })
  const solverTrace = selected.solverCircuitJson.find(
    (e) =>
      e.type === "pcb_trace" &&
      e.pcb_trace_id === selected.excitations[0].pcb_trace_id,
  )!
  const first =
    solverTrace.type === "pcb_trace" ? solverTrace.route[0] : undefined
  expect(first?.route_type === "wire" && first.x).toBe(12)
  expect(
    selectReturnCurrentExperiment({ circuitJson: reverse, experimentId })
      .excitations[0].source_port,
  ).toEqual(original.excitations[0].source_port)
  const reverseResult = simulateReturnCurrent({
    circuitJson: selected.solverCircuitJson,
    excitations: selected.excitations,
    cellSize: 1,
  })
  const output = exportReturnCurrentCircuitJson({
    circuitJson: reverse,
    experimentId: reverseId,
    simulation: reverseResult,
  })
  expect(
    output.filter((e) => e.type === "simulation_pcb_return_current_result"),
  ).toHaveLength(2)
})
