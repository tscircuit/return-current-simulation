# AM3352 DQS EM / ngspice workflow

This experimental workflow produces a **routing-dependent DQS0 eye**, rather
than inferring a uniform transmission line from route length. The pinned
`astra/am3352-sbc` 0.1.19 circuit-json is generated from that board's TSX source.
The geometry exporter reuses the validated Palace copper adapter (round trace
ends, holes, physical via spans, and no different-net overlap). openEMS solves
the resulting four-layer copper in the time domain. Geometry preparation's
separate DDR_D12 / 1 MHz return-current excitation is ignored here: the extractor
resolves the DQS traces and creates its own broadband differential ports. Two source runs supply all
four differential scattering parameters. scikit-rf fits a stable, passive
network; ngspice connects it to the nonlinear transmitter and receiver load.

This adapter currently supports the documented AM3352 stackup and the named
`DDR_DQS0`/`DDR_DQSn0` routes. It is not a general DDR bus signoff command, and
is separate from the npm package's return-current CLI.

## Run the example

Install Docker, Bun, KiCad **9.0.2** or compatible (with its IBIS exporter), and
ngspice with **XSPICE code modules**. The checked example uses ngspice **44.2**.
For the host Python environment:

```sh
python3 -m venv work/si-python
work/si-python/bin/pip install -r lib/palace/python/requirements.txt \
  -r scripts/si/requirements.txt
```

Obtain TI's AM335x model from
[SPRM552](https://www.ti.com/lit/zip/SPRM552). Extract `sprm552c.ibs` locally.
The source used here has SHA-256
`23011a68eb8ff35562615b5b108edcb9f017c5e61f4f68e32f35c5fb88f163be`.
Vendor IBIS files and converted I/V tables are not redistributed.

From the repository root:

```sh
SI_PYTHON=work/si-python/bin/python \
SI_NGSPICE=ngspice \
CELL_MM=0.05 FIELD_MAX_NS=1.5 \
bash scripts/generate-em-dqs-eye.sh /path/to/sprm552c.ibs work/em-eye
```

The Docker image installs Debian's openEMS **0.0.35** Python bindings. The full
extraction can take tens of minutes per excited port. The 0.05 mm spacing applies
to the DDR region; a graded coarser grid covers the remaining board and air. `CELL_MM=0.1` is a faster
pilot, with just one cell across a 0.1 mm trace. Use mesh and record-length
comparisons before interpreting numerical margins. The requested finite field
record is not equivalent to satisfying openEMS's energy decay criterion; read
both solver logs. The included result explicitly records these limitations.

Output includes:

- `port1/`, `port2/`: field-port time records, extraction metadata and raw spectra;
- `channel/channel.s2p`, `channel.sp`, `fit.json`: raw field extraction,
  transient equivalent and fit/passivity/reciprocity errors;
- `driver/`: local compatibility IBIS, isolated-edge conversion, and checks;
- `routed/`, `reference/`: ngspice netlist/log, transient CSV/NPZ and provenance;
- `comparison/eye-comparison.png`, SVG and JSON: receiver eyes and observed
  openings under the same input budgets.
- `prbs-routed/`, `prbs-reference/`, `prbs-comparison/`: the corresponding
  PRBS7 channel stress test and eye, separately labeled from the DQS strobe.

The waveform analyzer folds rising and falling edges at one **fixed nominal
unit interval**. It does not align each edge independently and erase jitter.
It verifies that the transient reached the requested end time before allowing
ngspice's `linearize` command to supply plotted samples. An aborted ngspice
transient is a failure, including when the process itself exits successfully.

## Stimulus, I/O assumptions and corners

800 MT/s corresponds to **400 MHz DQS** and **1250 ps UI**. Write direction is
`U1.P1/P2 → U3.F3/G3`. Frequency belongs to this timed stimulus, not an arbitrary
PCB pad. The controller's actual DDR drive/ODT registers are not present in
circuit-json. This run explicitly chooses TI's model-selection-guide example
**0x18B**, `Model_655`/`Model_847`, instead of asserting the board uses it.

KiCad's exporter cannot read the vendor's symbolic sparse package matrix, so
the compatibility copy disables that section. The eye attaches the selected
P1/P2 package self R/L/C and mutual inductance separately. Mutual package
capacitance is omitted because the vendor matrix's sign convention is
ambiguous. The I/O waveform records themselves are retained. Isolated 10 ns
switching events are converted first, checked for ordered times and plausible
weights, then retimed into the requested clock. This avoids the exporter's
invalid overlapping waveform sequence at 800 MT/s. Only settled tails can be
clipped for unusually close jittered events, and the count is recorded.

The Winbond model available for this part contains encrypted HSPICE transistor
models. The receiver here uses its unencrypted LDQS/LDQSB package RLC plus
**assumed 2 pF per-leg die capacitance and 60 Ω per-leg ODT to 0.75 V**. That ODT
is 120 Ω differential; it is not inferred from a mode register. These are
explicit engineering conditions, not an exact Winbond receiver.

Default budgets are **10 ps RMS Gaussian source timing jitter**, **5 ps peak
periodic jitter** with a 31 UI period, and **2 mV RMS differential receiver
input noise**, low-pass filtered at 500 MHz. Jitter changes the source event
times **before** ngspice; voltage noise enters the circuit. These are configured
budgets, not measured or inferred board jitter/noise. Seeds are fixed and the
reference uses the same sequence. Set `RJ_PS`, `PJ_PS`, and `NOISE_MV` on the
wrapper, or use `--rj-ps`, `--pj-ps`, `--noise-mv` on `simulate-dqs-eye.py`.

For load sensitivity, rerun the transient (no new EM extraction):

```sh
python scripts/si/simulate-dqs-eye.py \
  --channel work/em-eye/channel/channel.sp \
  --driver work/em-eye/driver/positive.sp \
  --negative-driver work/em-eye/driver/negative.sp \
  --ngspice ngspice --odt-ohms 120 --cin-pf 3.5 \
  --ui-count 256 --out work/em-eye/load-corner
```

`--mode prbs` sends PRBS7 across the extracted differential pair to stress
channel memory; that is a **channel diagnostic**, not the actual DQS clock
protocol. The continuous-strobe analyzer rejects irregular PRBS crossings. Use
`compare-eyes.py` for the PRBS case; it associates crossings with the fixed bit
clock and retains pattern-dependent timing spread. This is not an operational
DQS/DDR timing-mask check.

## Interpreting the plots

The matched reference is a 100 Ω line with 400 ps flight time, under the same
package, I/O, termination, jitter and noise conditions. The routed case uses
the extracted channel. Both eyes remove one mean clock phase for display,
while preserving edge variation. Their transient traces retain absolute delay.

The reported eye height and opening at **±200 mV differential thresholds** are
finite-capture diagnostics. They are not a manufacturer DDR mask or a BER
prediction. With a periodic DQS strobe, routing-induced reflections and slew
changes may be visible without large data-pattern jitter. Active DQ/DM
aggressors are needed to evaluate crosstalk-induced strobe jitter.

The current field model keeps neighboring copper but leaves neighboring I/O
and discrete components electrically unloaded. It uses PEC thin foils and
solid barrel exteriors, omits copper/dielectric loss and component PDN models,
and extracts **balanced differential** ports with short launch posts. The
transient projects receiver ODT into a lumped transmitter common-mode DC load;
common-mode propagation/conversion is not extracted. Many vias outside the fine DDR region remain unresolved by the graded grid;
the saved solver logs retain unused-primitive warnings. Power/ground supplies are
ideal. Preamble/postamble, turnaround and simultaneous DQ sampling are absent.
Therefore this eye gives a conditional view of the **DQS interconnect**, not
whole-board DDR setup/hold compliance. The independent TI routing-length audit
also remains relevant even if this particular eye is open.
