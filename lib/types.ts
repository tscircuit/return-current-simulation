import type { AnyCircuitElement, PcbBoard, PcbTrace, Point } from "circuit-json"

/** Temporary circuit-json extension; see the linked schema PR in README.md.
 * Positions use circuit world coordinates: millimetres, +X right, +Y up.
 * Positive current runs along the ordered signal trace, and returns source → sink.
 */
export interface SimulationReturnCurrentExcitation {
  type: "simulation_return_current_excitation"
  simulation_return_current_excitation_id: string
  pcb_trace_id: string
  ground_source_net_id: string
  current: number
  return_source: Point
  return_sink: Point
}

export type ReturnCurrentCircuitJson = readonly (
  | AnyCircuitElement
  | SimulationReturnCurrentExcitation
)[]

export interface SimulationOptions {
  circuitJson: ReturnCurrentCircuitJson
  /** Overrides excitation elements in circuitJson. No current is guessed. */
  excitations?: readonly SimulationReturnCurrentExcitation[]
  /** Target cell pitch in mm. Actual pitches fit the board bounds exactly. */
  cellSize?: number
  /** Top signal to bottom ground spacing in mm; defaults to board thickness. */
  layerSeparation?: number
  /** Ground copper thickness in mm; defaults to 0.035 (one ounce). */
  copperThickness?: number
  /** Radius of each return contact in mm; defaults to one target cell pitch. */
  contactRadius?: number
  /** Relative L2 residual of the conservation solve; defaults to 1e-8. */
  tolerance?: number
  maxIterations?: number
}

export interface SignalSegment {
  start: Point
  end: Point
  width: number
  current: number
}

export interface CopperRegion {
  outer: Point[]
  holes: Point[][]
}

export interface SimulationGeometry {
  board: PcbBoard
  boardOutline: Point[]
  groundRegions: CopperRegion[]
  cutouts: Point[][]
  signals: PcbTrace[]
  segments: SignalSegment[]
  excitations: readonly SimulationReturnCurrentExcitation[]
}

/** Node positions and direction components use circuit world coordinates (mm, +Y up).
 * Edge current is in A, oriented from startNode to endNode. Sheet current is A/mm.
 */
export interface CurrentNode extends Point {
  column: number
  row: number
  injection: number
  sheetCurrentX: number
  sheetCurrentY: number
  currentDensity: number
}

export interface CurrentEdge {
  startNode: number
  endNode: number
  axis: "x" | "y"
  preferredCurrent: number
  current: number
}

export interface SimulationResult {
  geometry: SimulationGeometry
  nodes: CurrentNode[]
  edges: CurrentEdge[]
  columns: number
  rows: number
  cellWidth: number
  cellHeight: number
  bounds: { minX: number; minY: number; maxX: number; maxY: number }
  copperThickness: number
  layerSeparation: number
  diagnostics: {
    converged: boolean
    iterations: number
    relativeResidual: number
    maxConservationError: number
    maxCurrentDensity: number
    connectedCopperRegions: number
  }
}

export interface RenderOptions {
  width?: number
  height?: number
  title?: string
  /** Fixed linear color scale maximum in A/mm²; otherwise use field maximum. */
  maxCurrentDensity?: number
  hideVectors?: boolean
  hideTraces?: boolean
  vectorSpacing?: number
}
