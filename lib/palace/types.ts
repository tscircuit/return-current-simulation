import type { Point } from "circuit-json"
import type { SimulationGeometry, SimulationOptions } from "../types"

export interface PalaceOptions
  extends Pick<
    SimulationOptions,
    "circuitJson" | "excitations" | "layerSeparation" | "copperThickness"
  > {
  /** Required; peak phasors use exp(+jωt). No frequency is inferred. */
  frequencyHz: number
  /** Relative permittivity of the substrate; default 4.3. */
  substratePermittivity?: number
  substrateLossTangent?: number
  copperConductivity?: number
  /** Source and load termination resistance in ohms; default 50. */
  portResistance?: number
  portWidth?: number
  meshSize?: number
  airPadding?: number
  order?: 1 | 2
}

export interface PalaceModel {
  schemaVersion: 1
  geometry: SimulationGeometry
  topPads: Point[][]
  frequencyHz: number
  layerSeparation: number
  copperThickness: number
  copperConductivity: number
  substratePermittivity: number
  substrateLossTangent: number
  portResistance: number
  portWidth: number
  meshSize: number
  airPadding: number
  order: 1 | 2
  copperModel: "volumetric_copper"
}

export interface PalaceSample extends Point {
  /** Integrated-through-thickness sheet current in A/mm, complex peak phasor. */
  sheetCurrentXReal: number
  sheetCurrentYReal: number
  sheetCurrentXImag: number
  sheetCurrentYImag: number
}

export interface PalaceReference {
  schemaVersion: 1
  solver: "palace"
  solverVersion: string
  femOrder: 1 | 2
  frequencyHz: number
  copperModel: "volumetric_copper"
  copperThickness: number
  layerSeparation: number
  cellWidth: number
  cellHeight: number
  columns: number
  rows: number
  samples: PalaceSample[]
  sourceCurrents: { real: number; imag: number }[]
  loadCurrents: { real: number; imag: number }[]
  /** Palace v0.14.0 ParaView E fields are nondimensional. */
  electricFieldScaleVoltsPerMeter: number
  normalizationConditionNumber: number
  provenance: {
    geometrySignature: string
    circuitSha256: string
    modelSha256: string
    meshSha256: string
  }
}
