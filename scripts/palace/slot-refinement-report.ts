import { comparePalaceRuns } from "lib/palace/compare-palace-runs"
import type { PalaceReference } from "lib/palace/types"

export async function writeSlotRefinementReport(options: {
  coarse: string
  fine: string
  destination: string
}) {
  const coarse: PalaceReference = await Bun.file(
    `${options.coarse}/reference.json`,
  ).json()
  const fine: PalaceReference = await Bun.file(
    `${options.fine}/reference.json`,
  ).json()
  const report = comparePalaceRuns(coarse, fine)
  const sourceCurrent = fine.sourceCurrents.reduce(
    (total, current) => total + current.real,
    0,
  )
  const bridgeColumns = [-5.75, -5.25, -4.75, -4.25, -3.75, -3.25]
  const bridgeFlux = bridgeColumns.map((x) => {
    const samples = fine.samples.filter(
      (sample) => Math.abs(sample.x - x) < 1e-6,
    )
    return {
      x,
      real: samples.reduce(
        (total, sample) => total + sample.sheetCurrentXReal * fine.cellHeight,
        0,
      ),
      imag: samples.reduce(
        (total, sample) => total + sample.sheetCurrentXImag * fine.cellHeight,
        0,
      ),
    }
  })
  const meanBridgeReal =
    bridgeFlux.reduce((total, flux) => total + flux.real, 0) / bridgeFlux.length
  const meanBridgeImag =
    bridgeFlux.reduce((total, flux) => total + flux.imag, 0) / bridgeFlux.length
  const reportWithFlux = {
    ...report,
    sampledImageGridFluxCheck: {
      method:
        "midpoint integration of sampled Kx across each ground bridge column",
      expectedRealAmps: -sourceCurrent,
      expectedImagAmps: 0,
      bridgeFlux,
      meanBridgeRealAmps: meanBridgeReal,
      meanBridgeImagAmps: meanBridgeImag,
      relativeComplexBalanceError:
        Math.hypot(meanBridgeReal + sourceCurrent, meanBridgeImag) /
        sourceCurrent,
    },
    fluxCheck: await Bun.file(`${options.fine}/flux-check.json`).json(),
    isGroundTruth: false,
    reason:
      "Finite mesh/domain and assumed material/port model. Report refinement change and balance error before using as an accuracy benchmark.",
  }
  await Bun.write(options.destination, JSON.stringify(reportWithFlux, null, 2))
  console.log(reportWithFlux)
}
