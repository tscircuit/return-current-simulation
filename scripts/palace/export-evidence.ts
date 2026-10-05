import { cp, mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { palaceImage } from "./run-case"

export async function exportEvidence(options: {
  source: string
  destination: string
}) {
  await mkdir(options.destination, { recursive: true })
  for (const filename of [
    "circuit.json",
    "model.json",
    "palace.json",
    "mesh-summary.json",
    "normalization.json",
    "reference.json",
    "sample-grid.json",
    "comparison.json",
    "palace.svg",
    "palace.png",
    "approximation.svg",
    "approximation.png",
    "palace.log",
  ])
    await cp(
      resolve(options.source, filename),
      resolve(options.destination, filename),
    )
  for (const filename of ["flux-check.json", "flux-specification.json"])
    if (await Bun.file(resolve(options.source, filename)).exists())
      await cp(
        resolve(options.source, filename),
        resolve(options.destination, filename),
      )
  for (const filename of [
    "port-I.csv",
    "port-V.csv",
    "port-S.csv",
    "domain-E.csv",
    "error-indicators.csv",
  ])
    await cp(
      resolve(options.source, "postpro", filename),
      resolve(options.destination, filename),
    )
  await Bun.write(
    resolve(options.destination, "run.json"),
    JSON.stringify(
      {
        palaceImage,
        gmshVersion: "4.13.1",
        vtkVersion: "9.3.1",
        unitsAdapter: "Palace v0.14.0 nondimensional ParaView E -> V/m",
        fieldExtraction:
          "J = sigma E, integrated through bottom copper using 5-point Gauss quadrature",
        phasorConvention: "peak, exp(+j omega t)",
        sourceNormalization:
          "solve full source-port basis current matrix; net source = 2 I_inc - I_termination",
        rawOutputCommand: "bun run generate:palace work/palace",
        rawOutputLocation: "work/palace/*/postpro/paraview",
        imageSampling: await Bun.file(
          resolve(options.source, "sample-grid.json"),
        )
          .json()
          .then(({ columns, rows, cellWidth, cellHeight }) => ({
            columns,
            rows,
            cellWidth,
            cellHeight,
          })),
      },
      null,
      2,
    ),
  )
}
