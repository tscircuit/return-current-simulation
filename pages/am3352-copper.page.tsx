const heatmap = new URL(
  "../examples/am3352/inner1-copper-heatmap.png",
  import.meta.url,
).href

export default function Am3352CopperAudit() {
  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1>AM3352 inner1 copper audit</h1>
      <p>
        Square trace ends caused the earlier false overlap. Round ends leave
        0.111 mm between MMC0_DAT3 and VIN_5V. The corrected polygon audit finds
        zero overlaps across all four copper layers.
      </p>
      <p>
        This heat map shows copper occupancy at 0.005 mm cells. Gray: no copper;
        teal: one net; red: two nets. It does not show EM current density, and
        frequency does not apply. Open the image to inspect it at full size.
      </p>
      <a href={heatmap} target="_blank" rel="noreferrer">
        <img
          src={heatmap}
          alt="AM3352 inner1 copper overview and close-ups: square ends falsely overlap a via; round ends leave a gap"
          style={{ width: "100%", maxWidth: 1600 }}
        />
      </a>
    </main>
  )
}
