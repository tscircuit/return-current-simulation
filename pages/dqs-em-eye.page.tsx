const eye = new URL(
  "../examples/am3352/dqs-em-eye/eye-comparison.png",
  import.meta.url,
).href
const stressEye = new URL(
  "../examples/am3352/dqs-em-eye/prbs-eye-comparison.png",
  import.meta.url,
).href
const frequencyControl = new URL(
  "../examples/am3352/dqs-em-eye/frequency-stress/400mhz/eye-comparison.png",
  import.meta.url,
).href
const frequencyBandEdge = new URL(
  "../examples/am3352/dqs-em-eye/frequency-stress/5ghz/eye-comparison.png",
  import.meta.url,
).href
const frequencyStress = new URL(
  "../examples/am3352/dqs-em-eye/frequency-stress/20ghz/eye-comparison.png",
  import.meta.url,
).href
const benchComparison = new URL(
  "../examples/am3352/dqs-em-eye/bench-assumptions/5ghz/routed-clean-vs-noisy/eye-comparison.png",
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
      <h2>Frequency stress: 400 MHz, 5 GHz and 20 GHz</h2>
      <p>
        These companion captures use an ideal test source through the same
        package, routed channel and receiver load. All use 50 Ω source
        resistance per leg, 1 ps edges and zero jitter or noise to isolate
        frequency sensitivity. The TI IBIS switching model is retained for the
        original captures above.
      </p>
      <p>
        The 5 GHz strobe has a 100 ps unit interval (10 GT/s). Its fundamental
        lies at the upper edge of the extracted dataset; its harmonics above 5
        GHz still use fit extrapolation. It retains the same ideal source and
        assumed receiver load as the other frequency companions.
      </p>
      <p>
        The 20 GHz strobe has a 25 ps unit interval (40 GT/s). Its routed
        channel response extrapolates a fit based on data up to 5 GHz. Eye
        closure shows bandwidth sensitivity under these assumptions; it does not
        validate the extrapolated channel or imply that AM3352 operates at this
        rate.
      </p>
      <a href={frequencyControl} target="_blank" rel="noreferrer">
        <img
          src={frequencyControl}
          alt="400 MHz ideal-source bandwidth control through routed and matched channels"
          style={{ width: "100%", maxWidth: 1800 }}
        />
      </a>
      <a href={frequencyBandEdge} target="_blank" rel="noreferrer">
        <img
          src={frequencyBandEdge}
          alt="5 GHz ideal-source bandwidth companion; fundamental at dataset edge with extrapolated harmonics"
          style={{ width: "100%", maxWidth: 1800 }}
        />
      </a>
      <a href={frequencyStress} target="_blank" rel="noreferrer">
        <img
          src={frequencyStress}
          alt="20 GHz ideal-source bandwidth stress; routed channel uses fit extrapolation"
          style={{ width: "100%", maxWidth: 1800 }}
        />
      </a>
      <h2>Assumed 5 GHz bench observation</h2>
      <p>
        This companion observes the package pads at 10 GT/s (100 ps UI) with 0.2
        pF probe loading per pin and a causal 12 GHz two-pole Butterworth scope
        response. Both controls retain that loading and response. The noisy case
        assumes 3 ps RMS source jitter with a 500 MHz correlation corner, 3 ps
        peak periodic jitter at 100 MHz, a 5 mV RMS differential pad series
        source after 1 GHz shaping, and 2 mV RMS differential scope noise after
        12 GHz shaping. Circuit loading and feedback change the pad source's
        realized voltage contribution.
      </p>
      <p>
        The clean control zeroes the injected jitter and noise. This plot
        compares clean and noisy captures of the same routed network over 500 ns
        (5,000 UI), after 3 µs of source history. The configured injections
        reduce captured opening at ±200 mV from 73.8 ps to 42.3 ps. These are
        declared simulation assumptions, not measured bench data or qualified
        AM3352 operation at 5 GHz. Timing modulation adds carrier sidebands,
        including a 5.1 GHz upper sideband from the periodic jitter. Sidebands
        and harmonics above 5 GHz use channel-fit extrapolation.
      </p>
      <a href={benchComparison} target="_blank" rel="noreferrer">
        <img
          src={benchComparison}
          alt="Assumed 5 GHz package-pad bench observation, clean versus noisy on the same routed path with identical probe and scope response"
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
