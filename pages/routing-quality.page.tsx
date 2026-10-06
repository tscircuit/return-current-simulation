const audit = new URL(
  "../examples/am3352/routing-quality/routing-audit.png",
  import.meta.url,
).href

export default function RoutingQuality() {
  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1>AM3352 DDR routing quality</h1>
      <p>
        Release 0.1.19: both byte groups fail TI’s placement-derived DQ/DM
        maximum length despite passing length matching. Red trace segments lie
        outside the selected reference-pour projection. This is geometry
        evidence; it is not an EM current plot or a model-backed eye diagram.
      </p>
      <a href={audit} target="_blank" rel="noreferrer">
        <img
          src={audit}
          alt="DDR byte routes over their reference pours and length charts showing the placement-derived limit"
          style={{ width: "100%", maxWidth: 1600 }}
        />
      </a>
    </main>
  )
}
