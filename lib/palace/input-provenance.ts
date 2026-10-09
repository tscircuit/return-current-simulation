import { createHash } from "node:crypto"
import { readFile } from "node:fs/promises"
import type { ReturnCurrentCircuitJson } from "../types"
import { canonicalJson } from "./canonical-json"
import type { PalaceInputManifest, PalaceModel, PalaceReference } from "./types"

export const sha256 = (bytes: string | Uint8Array) =>
  createHash("sha256").update(bytes).digest("hex")

/** Includes all pads, vias, materials, contacts and resolved solver settings.
 * Other experiments/results do not change the selected physical input.
 */
export function palaceInputManifest(
  circuitJson: ReturnCurrentCircuitJson,
  model: PalaceModel,
): PalaceInputManifest {
  return {
    schemaVersion: 1,
    numericPrecision: "model_12_input_17_significant_digits",
    circuitSha256: sha256(
      canonicalJson(
        [
          ...circuitJson.filter((e) => !e.type.startsWith("simulation_")),
          ...model.geometry.excitations,
        ],
        17,
      ),
    ),
    modelSha256: sha256(canonicalJson(model)),
  }
}

export function validatePalaceInputs(
  reference: PalaceReference,
  model: PalaceModel,
  circuitJson?: ReturnCurrentCircuitJson,
): void {
  const manifest = reference.provenance.inputManifest
  if (manifest) {
    if (
      manifest.schemaVersion !== 1 ||
      manifest.numericPrecision !== "model_12_input_17_significant_digits" ||
      manifest.modelSha256 !== sha256(canonicalJson(model)) ||
      (circuitJson &&
        manifest.circuitSha256 !==
          palaceInputManifest(circuitJson, model).circuitSha256)
    )
      throw new Error(
        "Palace input provenance is stale: physical inputs or solver settings changed",
      )
  } else if (
    reference.provenance.modelSha256 !==
      sha256(JSON.stringify(model, null, 2)) ||
    (circuitJson &&
      reference.provenance.circuitSha256 !==
        sha256(JSON.stringify(circuitJson)))
  )
    throw new Error(
      "Legacy Palace input hashes differ; resample the original verified case",
    )
}

/** Verify original bytes, including the actual mesh, at a case-file boundary. */
export async function validatePalaceCaseInputs(
  reference: PalaceReference,
  destination: string,
): Promise<void> {
  const files = await Promise.all(
    ["circuit.json", "model.json", "mesh.msh"].map((file) =>
      readFile(`${destination}/${file}`),
    ),
  )
  for (const [index, key] of [
    "circuitSha256",
    "modelSha256",
    "meshSha256",
  ].entries())
    if (
      sha256(files[index]) !==
      reference.provenance[
        key as "circuitSha256" | "modelSha256" | "meshSha256"
      ]
    )
      throw new Error(`Palace ${key} differs from the original input bytes`)
  if (reference.provenance.inputManifest)
    validatePalaceInputs(
      reference,
      JSON.parse(files[1].toString()),
      JSON.parse(files[0].toString()),
    )
}
