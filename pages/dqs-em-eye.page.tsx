const eye = new URL(
  "../examples/am3352/dqs-em-eye/eye-comparison.png",
  import.meta.url,
).href
const stressEye = new URL(
  "../examples/am3352/dqs-em-eye/prbs-eye-comparison.png",
  import.meta.url,
).href

export default function DqsEmEye() {
  return (
    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1>AM3352 DQS0 EM / ngspice eye</h1>
      <p>
        U1.P1/P2 → U3.F3/G3, write at 800 MT/s (400 MHz strobe, 1250 ps UI). The
        routed case uses an openEMS differential channel and locally converted
        nonlinear TI IBIS drivers. The matched control uses the same package,
        load, jitter and noise budgets.
      </p>
      <p>
        Timing jitter enters the driver stimulus and noise enters the receiver
        circuit before simulation. Folding uses a fixed nominal clock. The
        configured budgets are 10 ps RMS random jitter, 5 ps peak periodic
        jitter, and 2 mV RMS differential input noise.
      </p>
      <a href={eye} target="_blank" rel="noreferrer">
        <img
          src={eye}
          alt="Routing-derived DQS0 eye with matched channel comparison, jitter and transient waveforms"
          style={{ width: "100%", maxWidth: 1800 }}
        />
      </a>
      <h2>PRBS7 channel stress</h2>
      <p>
        This pattern tests channel memory at 800 MT/s. It is a diagnostic
        excitation on the DQS pair, rather than the operational DQS clock
        protocol. The reference keeps the same source timing and noise.
      </p>
      <a href={stressEye} target="_blank" rel="noreferrer">
        <img
          src={stressEye}
          alt="PRBS7 stress eye on the routed DQS0 channel with matched reference"
          style={{ width: "100%", maxWidth: 1800 }}
        />
      </a>
      <p>
        These are conditional DQS interconnect results. Active DQ crosstalk,
        power integrity, protocol turnaround and DQ setup/hold are not
        validated. Read the saved extraction, fit and transient checks before
        interpreting numerical margins. The TI routing-length audit remains
        applicable.
      </p>
    </main>
  )
}
