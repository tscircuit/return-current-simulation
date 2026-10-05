import type { Point } from "circuit-json"
import { applyToPoint, compose, scale, translate } from "transformation-matrix"
import { currentColor } from "./current-color"
import type { RenderOptions, SimulationResult } from "./types"

function escapeXml(text: string): string {
  return text.replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&apos;",
      })[character] ?? character,
  )
}

function polygonPath(outline: readonly Point[]): string {
  return `${outline.map((point, cornerIndex) => `${cornerIndex ? "L" : "M"}${svgNumber(point.x)},${svgNumber(point.y)}`).join(" ")} Z`
}

function svgNumber(number: number): string {
  return Number(number.toFixed(5)).toString()
}

function renderCells(
  result: Pick<SimulationResult, "nodes" | "cellWidth" | "cellHeight">,
  maxCurrentDensity: number,
): string {
  type CurrentColor = string
  const pathsByColor = new Map<CurrentColor, string[]>()
  for (const node of result.nodes) {
    const color = currentColor(node.currentDensity / maxCurrentDensity)
    const paths = pathsByColor.get(color) ?? []
    paths.push(
      `M${svgNumber(node.x - result.cellWidth / 2)},${svgNumber(node.y - result.cellHeight / 2)}h${svgNumber(result.cellWidth)}v${svgNumber(result.cellHeight)}h${svgNumber(-result.cellWidth)}z`,
    )
    pathsByColor.set(color, paths)
  }
  return [...pathsByColor]
    .map(([color, paths]) => `<path fill="${color}" d="${paths.join(" ")}"/>`)
    .join("")
}

function displayNumber(number: number): string {
  if (number === 0) return "0"
  return number >= 0.01 && number < 10000
    ? Number(number.toPrecision(3)).toString()
    : number.toExponential(1)
}

/** Render a solved field without DOM, canvas, or native dependencies.
 * Circuit world points are mm, +Y up; SVG scene points are pixels, +Y down.
 * White regions contain no selected ground copper. Traces are a top-layer overlay.
 */
export function renderCurrentFieldSvg(
  result: Pick<
    SimulationResult,
    | "geometry"
    | "nodes"
    | "columns"
    | "rows"
    | "cellWidth"
    | "cellHeight"
    | "bounds"
    | "copperThickness"
    | "layerSeparation"
  > & {
    diagnostics: Pick<
      SimulationResult["diagnostics"],
      "converged" | "maxCurrentDensity"
    >
  },
  options: RenderOptions & {
    description: string
    subtitle: string
    footer: string
    gridLabel?: string
  },
): string {
  if (!result.diagnostics.converged)
    throw new Error("Only a converged simulation can be rendered")
  const width = options.width ?? 1100
  const height = options.height ?? 1100
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width < 300 ||
    height < 300
  )
    throw new Error("Image dimensions must be finite and at least 300 pixels")
  const maxCurrentDensity =
    options.maxCurrentDensity ?? (result.diagnostics.maxCurrentDensity || 1)
  if (!Number.isFinite(maxCurrentDensity) || maxCurrentDensity <= 0)
    throw new Error("maxCurrentDensity must be finite and positive")
  const vectorSpacing = options.vectorSpacing ?? 5
  if (!Number.isInteger(vectorSpacing) || vectorSpacing < 1)
    throw new Error("vectorSpacing must be a positive integer")
  const boardWidth = result.bounds.maxX - result.bounds.minX
  const boardHeight = result.bounds.maxY - result.bounds.minY
  const pixelsPerMm = Math.min(
    (width - 120) / boardWidth,
    (height - 250) / boardHeight,
  )
  const left = (width - boardWidth * pixelsPerMm) / 2
  const top = 160
  const worldToSvg = compose(
    translate(left, top),
    scale(pixelsPerMm, -pixelsPerMm),
    translate(-result.bounds.minX, -result.bounds.maxY),
  )
  const groundPaths = result.geometry.groundRegions
    .map(
      (region) =>
        `<path d="${[region.outer, ...region.holes].map(polygonPath).join(" ")}" clip-rule="evenodd"/>`,
    )
    .join("")
  const boardPath = [result.geometry.boardOutline, ...result.geometry.cutouts]
    .map(polygonPath)
    .join(" ")
  const cells = renderCells(result, maxCurrentDensity)
  const arrows: string[] = []
  if (!options.hideVectors) {
    const arrowLength =
      Math.min(result.cellWidth, result.cellHeight) * vectorSpacing * 0.58
    for (const node of result.nodes) {
      if (
        node.column % vectorSpacing !== Math.floor(vectorSpacing / 2) ||
        node.row % vectorSpacing !== Math.floor(vectorSpacing / 2) ||
        node.currentDensity < result.diagnostics.maxCurrentDensity * 0.003
      )
        continue
      const magnitude = Math.hypot(node.sheetCurrentX, node.sheetCurrentY)
      if (magnitude === 0) continue
      const dx = ((node.sheetCurrentX / magnitude) * arrowLength) / 2
      const dy = ((node.sheetCurrentY / magnitude) * arrowLength) / 2
      arrows.push(
        `<path d="M${svgNumber(node.x - dx)},${svgNumber(node.y - dy)} L${svgNumber(node.x + dx)},${svgNumber(node.y + dy)} M${svgNumber(node.x + dx * 0.25 + dy * 0.4)},${svgNumber(node.y + dy * 0.25 - dx * 0.4)} L${svgNumber(node.x + dx)},${svgNumber(node.y + dy)} L${svgNumber(node.x + dx * 0.25 - dy * 0.4)},${svgNumber(node.y + dy * 0.25 + dx * 0.4)}"/>`,
      )
    }
  }
  const traces = options.hideTraces
    ? ""
    : result.geometry.signals
        .map((signal) => {
          const wires = signal.route.flatMap((routePoint) =>
            routePoint.route_type === "wire" ? [routePoint] : [],
          )
          return `<polyline points="${wires.map((point) => `${point.x},${point.y}`).join(" ")}" fill="none" stroke="#16383b" stroke-width="${wires[0].width}" stroke-linejoin="round" stroke-linecap="round"/>`
        })
        .join("")
  const contacts = result.geometry.excitations
    .map((excitation, excitationIndex) =>
      [
        {
          point: excitation.return_sink,
          label: `S${excitationIndex + 1}`,
          color: "#19394c",
        },
        {
          point: excitation.return_source,
          label: `L${excitationIndex + 1}`,
          color: "#ae300f",
        },
      ]
        .map((contact) => {
          const scenePoint = applyToPoint(worldToSvg, contact.point)
          return `<circle cx="${scenePoint.x}" cy="${scenePoint.y}" r="5" fill="#fff" stroke="${contact.color}" stroke-width="2"/><text x="${scenePoint.x + 10}" y="${scenePoint.y - 8}" font-size="13" font-weight="600" fill="#122735" stroke="white" stroke-width="3" paint-order="stroke">${contact.label}</text>`
        })
        .join(""),
    )
    .join("")
  const ticks = [0, 0.25, 0.5, 0.75, 1]
    .map(
      (fraction) =>
        `<text x="${60 + fraction * (width - 120)}" y="136" text-anchor="middle" font-size="14" fill="#475569">${displayNumber(fraction * maxCurrentDensity)}</text>`,
    )
    .join("")
  const boardBottom = top + boardHeight * pixelsPerMm
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description">
<title id="title">${escapeXml(options.title ?? "Ground-plane return current")}</title>
<desc id="description">${escapeXml(options.description)}</desc>
<defs><linearGradient id="current-scale">${Array.from({ length: 6 }, (_, stopIndex) => `<stop offset="${stopIndex * 20}%" stop-color="${currentColor(stopIndex / 5)}"/>`).join("")}</linearGradient><clipPath id="board-clip"><path d="${boardPath}" clip-rule="evenodd"/></clipPath><clipPath id="ground-clip">${groundPaths}</clipPath></defs>
<rect width="100%" height="100%" fill="white"/>
<g font-family="Arial, sans-serif"><text x="60" y="42" font-size="26" font-weight="600" fill="#172b3a">${escapeXml(options.title ?? "Ground-plane return current")}</text>
<text x="60" y="72" font-size="14" fill="#475569">${escapeXml(options.subtitle)}</text>
<rect x="60" y="90" width="${width - 120}" height="26" rx="3" fill="url(#current-scale)"/>${ticks}
<g transform="matrix(${worldToSvg.a},${worldToSvg.b},${worldToSvg.c},${worldToSvg.d},${worldToSvg.e},${worldToSvg.f})">
<g clip-path="url(#board-clip)"><g clip-path="url(#ground-clip)"><g shape-rendering="crispEdges">${cells}</g><g fill="none" stroke="white" stroke-width="${1 / pixelsPerMm}" opacity="0.75">${arrows.join("")}</g></g></g>
<path d="${polygonPath(result.geometry.boardOutline)}" fill="none" stroke="#94a3b8" stroke-width="${1 / pixelsPerMm}"/>${traces}</g>
${contacts}
<text x="60" y="${boardBottom + 30}" font-size="14" fill="#334155">${result.geometry.excitations.map((excitation, excitationIndex) => `S${excitationIndex + 1} → L${excitationIndex + 1}: ${displayNumber(excitation.current)} A`).join("   ·   ")}</text>
<text x="60" y="${boardBottom + 53}" font-size="13" fill="#64748b">h = ${displayNumber(result.layerSeparation)} mm · copper = ${displayNumber(result.copperThickness)} mm · ${escapeXml(options.gridLabel ?? "mesh")} = ${result.columns} × ${result.rows}</text>
<text x="60" y="${boardBottom + 76}" font-size="12" fill="#64748b">${escapeXml(options.footer)}</text></g>
</svg>`
}

export function renderReturnCurrentSvg(
  result: SimulationResult,
  options: RenderOptions = {},
): string {
  return renderCurrentFieldSvg(result, {
    ...options,
    description:
      "Image-current approximation; frequency is not modelled. Colors show |J| in A/mm². White indicates absent ground copper. Dark lines show top-layer signals. Arrows show return direction.",
    subtitle:
      "Top signals · Bottom ground plane · |J| (A/mm²) · frequency not modelled",
    footer: `Image-current approximation · frequency not modelled · max conservation error ${displayNumber(result.diagnostics.maxConservationError)} A`,
  })
}
