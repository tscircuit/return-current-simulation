const eye = new URL(
  "../examples/am3352/dqs-eye-800mts/dqs-eye.png",
  import.meta.url,
).href

export default function DqsEyeEstimate() {
  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1>AM3352 DQS eye estimate</h1>
      <p>
        Write direction at 800 MT/s: a 400 MHz DQS strobe, 1.25 ns unit
        interval. Routed lengths come from circuit-json. Driver, termination and
        channel properties are assumed; this is not an EM/IBIS validation or DDR
        timing signoff.
      </p>
      <p>
        The routing-quality page independently shows that both byte groups
        exceed TI’s maximum DQ/DM length for this placement. This idealized eye
        cannot override those failures; use coupled channel/I/O waveforms to
        assess jitter and DQ timing relative to DQS.
      </p>
      <a href={eye} target="_blank" rel="noreferrer">
        <img
          src={eye}
          alt="Estimated differential DQS0 and DQS1 receiver eyes with electrical assumptions and modeling limits"
          style={{ width: "100%", maxWidth: 1600 }}
        />
      </a>
    </main>
  )
}
