import { BaseSolver } from "@tscircuit/solver-utils"
import type { GraphicsObject } from "graphics-debug"
import {
  applyLaplacian,
  dot,
  precondition,
  updateCurrentField,
} from "./conjugate-gradient"
import { createCurrentSystem } from "./create-mesh"
import { positiveFinite } from "./read-geometry"
import type { SimulationOptions, SimulationResult } from "./types"
import { currentColor } from "./current-color"

/** Stepwise conservative image-current projection on a two-layer copper mesh. */
export class ReturnCurrentSolver extends BaseSolver {
  readonly options: SimulationOptions
  readonly system: ReturnType<typeof createCurrentSystem>
  readonly potential: Float64Array
  readonly tolerance: number
  residual: Float64Array
  direction: Float64Array
  residualProduct: number
  initialNorm: number

  constructor(options: SimulationOptions) {
    super()
    this.options = options
    this.tolerance = positiveFinite(options.tolerance ?? 1e-8, "tolerance")
    this.MAX_ITERATIONS = positiveFinite(
      options.maxIterations ?? 5000,
      "maxIterations",
    )
    if (!Number.isInteger(this.MAX_ITERATIONS))
      throw new Error("maxIterations must be an integer")
    this.system = createCurrentSystem(options)
    this.potential = new Float64Array(this.system.result.nodes.length)
    this.residual = this.system.rightHandSide.slice()
    this.direction = precondition(this.residual, this.system)
    this.residualProduct = dot(this.residual, this.direction)
    this.initialNorm = Math.sqrt(dot(this.residual, this.residual))
    updateCurrentField(this.potential, this.system)
  }

  _step(): void {
    if (this.initialNorm === 0) {
      this.finish(0)
      return
    }
    const appliedDirection = applyLaplacian(this.direction, this.system)
    const denominator = dot(this.direction, appliedDirection)
    if (!Number.isFinite(denominator) || denominator <= 0)
      throw new Error("The conservation solve encountered a degenerate mesh")
    const alpha = this.residualProduct / denominator
    for (let nodeIndex = 0; nodeIndex < this.potential.length; nodeIndex++) {
      this.potential[nodeIndex] += alpha * this.direction[nodeIndex]
      this.residual[nodeIndex] -= alpha * appliedDirection[nodeIndex]
    }
    let relativeResidual =
      Math.sqrt(dot(this.residual, this.residual)) / this.initialNorm
    // Recompute the true residual before accepting convergence (floating-point drift).
    if (relativeResidual <= this.tolerance) {
      const appliedPotential = applyLaplacian(this.potential, this.system)
      this.residual = this.system.rightHandSide.map(
        (injection, nodeIndex) => injection - appliedPotential[nodeIndex],
      )
      relativeResidual =
        Math.sqrt(dot(this.residual, this.residual)) / this.initialNorm
      if (relativeResidual <= this.tolerance) {
        this.finish(relativeResidual)
        return
      }
      this.direction = precondition(this.residual, this.system)
      this.residualProduct = dot(this.residual, this.direction)
      return
    }
    const preconditioned = precondition(this.residual, this.system)
    const residualProduct = dot(this.residual, preconditioned)
    const beta = residualProduct / this.residualProduct
    for (let nodeIndex = 0; nodeIndex < this.direction.length; nodeIndex++)
      this.direction[nodeIndex] =
        preconditioned[nodeIndex] + beta * this.direction[nodeIndex]
    this.residualProduct = residualProduct
    this.system.result.diagnostics.relativeResidual = relativeResidual
    this.system.result.diagnostics.iterations = this.iterations
    this.progress = Math.min(
      0.99,
      Math.max(
        0,
        Math.log10(1 / relativeResidual) / Math.log10(1 / this.tolerance),
      ),
    )
    this.stats = { relativeResidual, meshNodes: this.potential.length }
  }

  finish(relativeResidual: number): void {
    updateCurrentField(this.potential, this.system)
    Object.assign(this.system.result.diagnostics, {
      converged: true,
      iterations: this.iterations,
      relativeResidual,
    })
    this.solved = true
    this.progress = 1
    this.stats = {
      ...this.system.result.diagnostics,
      meshNodes: this.potential.length,
    }
  }

  getConstructorParams(): SimulationOptions {
    return this.options
  }

  getOutput(): SimulationResult {
    if (!this.solved)
      throw new Error(
        this.error ?? "The return-current solver has not converged",
      )
    return this.system.result
  }

  visualize(): GraphicsObject {
    updateCurrentField(this.potential, this.system)
    const result = this.system.result
    return {
      rects: result.nodes.map((node) => ({
        center: { x: node.x, y: node.y },
        width: result.cellWidth,
        height: result.cellHeight,
        fill: currentColor(
          node.currentDensity / (result.diagnostics.maxCurrentDensity || 1),
        ),
      })),
      lines: result.geometry.signals.map((signal) => ({
        points: signal.route.flatMap((routePoint) =>
          routePoint.route_type === "wire"
            ? [{ x: routePoint.x, y: routePoint.y }]
            : [],
        ),
        strokeColor: "#102c36",
        strokeWidth: 0.15,
      })),
    }
  }
}
