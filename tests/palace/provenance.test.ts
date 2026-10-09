import { expect, test } from "bun:test"
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { canonicalJson } from "lib/palace/canonical-json"
import {
  matchingGeometrySignatures,
  palaceGeometrySignature,
} from "lib/palace/geometry-signature"
import {
  palaceInputManifest,
  sha256,
  validatePalaceCaseInputs,
  validatePalaceInputs,
} from "lib/palace/input-provenance"
import { preparePalaceCase } from "lib/palace/run-case"
import type { PalaceModel, PalaceReference } from "lib/palace/types"
import type { ReturnCurrentCircuitJson } from "lib/types"

const root = `${import.meta.dir}/../../examples/palace/explicit-ports-1mhz`
const model: PalaceModel = await Bun.file(`${root}/model.json`).json()
const circuit: ReturnCurrentCircuitJson = await Bun.file(
  `${root}/circuit.json`,
).json()
const archived: PalaceReference = await Bun.file(
  `${root}/reference.json`,
).json()
const reference = {
  ...archived,
  provenance: {
    ...archived.provenance,
    inputManifest: palaceInputManifest(circuit, model),
  },
}

test("TypeScript and Python agree on complete nested model and authored-input provenance", async () => {
  for (const fixture of ["explicit-ports-1mhz", "multilayer-inner2-1mhz"]) {
    const path = `${import.meta.dir}/../../examples/palace/${fixture}`
    const fixtureModel: PalaceModel = await Bun.file(
      `${path}/model.json`,
    ).json()
    const fixtureCircuit: ReturnCurrentCircuitJson = await Bun.file(
      `${path}/circuit.json`,
    ).json()
    const process = Bun.spawn(
      [
        "python3",
        "-c",
        "import json,sys; from provenance import input_manifest, geometry_signature; d=json.load(sys.stdin); print(json.dumps([input_manifest(d['circuit'],d['model']),geometry_signature(d['model']['geometry'])]))",
      ],
      {
        cwd: `${import.meta.dir}/../../lib/palace/python`,
        stdin: new Blob([
          JSON.stringify({ circuit: fixtureCircuit, model: fixtureModel }),
        ]),
        stdout: "pipe",
        stderr: "pipe",
      },
    )
    const output = await new Response(process.stdout).text()
    expect(await process.exited).toBe(0)
    const [manifest, geometry] = JSON.parse(output)
    expect(manifest).toEqual(palaceInputManifest(fixtureCircuit, fixtureModel))
    expect(geometry).toBe(palaceGeometrySignature(fixtureModel.geometry))
  }
  expect(canonicalJson({ b: -0, a: 1e-18 })).toBe(
    canonicalJson({ a: 1e-18, b: 0 }),
  )
  expect(() => canonicalJson({ value: NaN })).toThrow("Non-finite")
})

test("roundoff is portable while changed pads, vias, materials, contacts and settings are stale", () => {
  const perturbations = [
    (m: PalaceModel) => {
      m.topPads[0][0].x += 0.001
    },
    (m: PalaceModel) => {
      m.groundVias![0].holeDiameter += 0.001
    },
    (m: PalaceModel) => {
      m.copperConductivity *= 0.9
    },
    (m: PalaceModel) => {
      m.substratePermittivity += 0.01
    },
    (m: PalaceModel) => {
      m.ports![0].reference.x += 0.001
    },
    (m: PalaceModel) => {
      m.ports![0].resistance += 1
    },
    (m: PalaceModel) => {
      m.meshSize += 0.1
    },
  ]
  for (const mutate of perturbations) {
    const changed = structuredClone(model)
    mutate(changed)
    expect(() => validatePalaceInputs(reference, changed, circuit)).toThrow(
      "stale",
    )
  }
  const changedInput = structuredClone(circuit)
  const pad = changedInput.find((e) => e.type === "pcb_smtpad")!
  if (pad.type !== "pcb_smtpad" || pad.shape === "polygon")
    throw new Error("Fixture needs a centered pad")
  pad.x += 1e-14 // Authored precision is deliberately stricter than derived-model precision.
  expect(() => validatePalaceInputs(reference, model, changedInput)).toThrow(
    "stale",
  )
  const derived = structuredClone(model)
  derived.topPads[0][0].x += 1e-16
  expect(() => validatePalaceInputs(reference, derived, circuit)).not.toThrow()
  const signature = JSON.stringify([
    [],
    [],
    [],
    [],
    JSON.stringify({ via: { x: 0.3, y: -0 } }),
    [],
  ])
  const withX = (x: number) =>
    JSON.stringify([[], [], [], [], JSON.stringify({ via: { y: 0, x } }), []])
  expect(matchingGeometrySignatures(signature, withX(0.3 + 1e-16))).toBe(true)
  expect(matchingGeometrySignatures(signature, withX(0.301))).toBe(false)
})

test("preparation retains original byte hashes and consumption rejects any changed input file", async () => {
  const destination = await mkdtemp(join(tmpdir(), "palace-provenance-"))
  try {
    const prepared = await preparePalaceCase({
      circuitJson: circuit,
      frequencyHz: 1e6,
      destination,
    })
    const recorded = await Bun.file(`${destination}/input-manifest.json`).json()
    expect(recorded).toMatchObject(palaceInputManifest(circuit, prepared.model))
    for (const file of ["circuit", "model"])
      expect(recorded[`${file}FileSha256`]).toBe(
        sha256(await readFile(`${destination}/${file}.json`)),
      )
    await writeFile(`${destination}/mesh.msh`, "verified mesh bytes")
    const provenance = {
      geometrySignature: palaceGeometrySignature(prepared.model.geometry),
      circuitSha256: recorded.circuitFileSha256,
      modelSha256: recorded.modelFileSha256,
      meshSha256: sha256("verified mesh bytes"),
      inputManifest: palaceInputManifest(circuit, prepared.model),
    }
    const completed = { ...archived, provenance }
    await writeFile(
      `${destination}/input-manifest.json`,
      JSON.stringify({
        ...recorded,
        meshSha256: provenance.meshSha256,
      }),
    )
    const pythonValidation = async () => {
      const process = Bun.spawn(
        [
          "python3",
          "-c",
          "import json,sys; from pathlib import Path; from provenance import validate_inputs; p=Path(sys.argv[1]); validate_inputs(p,json.loads((p/'model.json').read_text()))",
          destination,
        ],
        {
          cwd: `${import.meta.dir}/../../lib/palace/python`,
          stdout: "ignore",
          stderr: "pipe",
        },
      )
      await new Response(process.stderr).text()
      return process.exited
    }
    expect(await pythonValidation()).toBe(0)
    await expect(
      validatePalaceCaseInputs(completed, destination),
    ).resolves.toBeUndefined()
    for (const file of ["circuit.json", "model.json", "mesh.msh"]) {
      const path = join(destination, file)
      const original = await readFile(path)
      await writeFile(path, Buffer.concat([original, Buffer.from(" ")]))
      await expect(
        validatePalaceCaseInputs(completed, destination),
      ).rejects.toThrow("original input bytes")
      expect(await pythonValidation()).toBe(1)
      await writeFile(path, original)
    }
  } finally {
    await rm(destination, { recursive: true, force: true })
  }
})
