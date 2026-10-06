export interface CrosstalkIssue {
  code: string
  message: string
  elementIds: string[]
}

export type CrosstalkStatus =
  | "missing_data"
  | "unsupported"
  | "failed"
  | "complete"

export interface LineTestbench {
  traceId: string
  name: string
  nearPortId: string
  farPortId: string
  sourceResistance: number
  loadResistance: number
  loadCapacitance: number
  loadVoltage: number
  waveform: [number, number][] // seconds, volts; supplied PWL, never guessed bits
}

export interface CrosstalkModel {
  geometry: {
    widthMm: number
    thicknessMm: number
    heightMm: number
    lengthMm: number
    gapMm: number
    referencePourId: string
    traceIds: string[]
  }
  material: {
    relativePermittivity: number
    conductivity: number
    referenceFrequencyHz: number
    stackupSource: "specified" | "assumed"
  }
  stopSeconds: number
  lines: [LineTestbench, LineTestbench]
}

export interface CrosstalkReport {
  status: CrosstalkStatus
  issues: CrosstalkIssue[]
  assumptions: string[]
  model?: CrosstalkModel
  numerical?: {
    extraction: Record<string, unknown>
    metrics: Record<string, unknown>
    convergence: Record<string, unknown>
    waveforms: Record<string, number[][]>
    provenance: Record<string, unknown>
    svg: string
  }
  artifactDirectory?: string
}
