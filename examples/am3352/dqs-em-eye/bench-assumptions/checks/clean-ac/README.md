# Independent clean probe-loaded AC check

This directory preserves independent AC predictions for routed and matched
reference cases. Only the routed case has a completed long native capture and
scope observation checked below. Both long reference attempts exceeded their
600 s limit without accepted captures. Reference amplitude/phase values here
are **AC predictions only**; reference transient settling and its bench eye
remain unverified.

From this evidence directory, reproduce the short AC solves with:

```sh
python run_ac.py --repo /path/to/simulate-return-current --out /path/to/ac-output --ngspice /path/to/ngspice
```

The repository can also be inferred from the current directory or the script's
ancestors when `--repo` is omitted. The script imports the exact
unchanged `passive_network()` from `scripts/si/stress-dqs-bandwidth.py`, adds
0.2 pF from each receiver pad (`rxp`, `rxn`) to ground, and runs native ngspice AC
for the routed fit and the matched 100 ohm / 400 ps reference. Each case retains
its exact deck, native log, complex AC data, scalar/harmonic results, and a
reconstructed 2 ps periodic grid. No transient is run.

The normalized sources are complementary 1 V AC per leg, giving 2 V
differential. For odd harmonic n at f = n * 5 GHz, the actual differential
source phasor is

`4*1.5/(pi*n) * sinc(f*1ps) * exp(-j*(pi/2 + 2*pi*f*5000.5ps))`.

Phasors use cosine coefficient minus j times sine coefficient and absolute
time. Thus their phases can be checked directly against a late native
capture fitted using its original time values.

| Case | Pad fundamental peak | Pad phase | Scope-observed fundamental peak | Scope phase |
| --- | ---: | ---: | ---: | ---: |
| Routed | 0.507304075986 V | -1.044463490521 rad | 0.499873129965 V | -1.662841553157 rad |
| Reference | 1.374164685965 V | -2.787872170038 rad | 1.354036041057 V | 2.876935074505 rad |

The scope response is evaluated independently with the bilinear transform,
prewarped at 12 GHz, at dt = 2 ps:

`H(z) = Omega_c^2 / (s^2 + sqrt(2)*Omega_c*s + Omega_c^2)`

`Omega_c = 2/dt*tan(pi*12GHz*dt)`,
`s = 2/dt*(1-z^-1)/(1+z^-1)`, `z = exp(j*2*pi*f*dt)`.

At 5 GHz, its gain is 0.985352086898 and phase is -0.618378062636 rad,
equivalent to 19.683585074 ps phase delay at this frequency. A separate
SciPy `butter`/`sosfreqz` comparison at 5/15/25 GHz agrees with this manual
response within 4.96e-15 complex magnitude.

The reconstructed scope-observed AC RMS / half peak-to-peak values are
0.353463942636 / 0.499210380852 V for routed and
0.957482504565 / 1.344249873659 V for reference. These half peak-to-peak
values include harmonics and are evaluated on the declared 2 ps grid;
they differ from the fundamental peak.

Odd harmonics through n = 401 are included solely to quantify the numerical
model's periodic reconstruction and sampling aliases. The summed scope peak
contribution above the 250 GHz grid Nyquist frequency is below 0.001 uV
for routed and 1.545 uV for reference. The corresponding aliased fundamental
changes are about 0.000033 uV and 0.701 uV. This is a truncation check, not
a physical prediction at these frequencies.

The 5 GHz fundamental lies at the extraction band edge. All higher routed
harmonics use the rational fit beyond available channel data. The AC check
validates the stated linear network and observation processing, not board,
package, probe, AM3352 operation, or DDR compliance. AC contains no startup
modes, so late native transient settling remains a separate check.

Use the complete native capture work tree to reproduce the read-only check:

```sh
python audit_clean_captures.py --root /path/to/dqs-bench-assumptions --ac-root /path/to/ac-evidence --out /path/to/check-output/clean-capture-check.json
```

For this recorded run, also supply
`--reference-unavailable-reason "Long matched-reference Tline captures timed out at 600 s and are excluded; no valid native/reference observation capture."`.
That marks missing reference entries as unavailable with the stated reason;
the default remains pending for a workflow whose captures are still running.

The input root contains `captures/5ghz-clean-{routed,reference}` and
`observations/5ghz-clean-{routed,reference}`. Each completed case needs its full
`waveforms.npz` and `provenance.json`; cropped review archives are not supplied
as full native captures. The script reads the 3000--3500 ns window, leaves all
supplied files unchanged, and reports missing files as pending. The report
includes absolute fundamental fits,
RMS and peak values, 20 ns and eight-cycle early/middle/late blocks, direct AC
waveform discrepancies with no phase alignment, and late clean cycle-repeat
residuals. The tiny sampling-alias correction is kept separate from the
continuous native AC fundamental. AC waveforms are evaluated directly at the
recorded absolute timestamps, allowing harmless floating-point grid drift
without aligning the receiver phase.

The completed routed capture used a 0.5 ps electrical maximum step and 2 ps
saved samples. Its observed fundamental peak is 0.499955398814 V with phase
-1.662956272578 rad: +0.016458% amplitude difference and -0.003652 ps phase
equivalent difference from AC. Observed AC RMS / half peak-to-peak are
0.353522115258 / 0.499310801045 V. Across early/middle/late 20 ns blocks,
fundamental peak range is 0.579 uV and phase-time range is 0.0000832 ps;
eight-cycle ranges are 4.052 uV and 0.000480 ps. The late observed cycle-repeat
residual is 17.53 uV maximum / 6.21 uV RMS. These quantify finite numerical
consistency of this model, rather than injected or physical noise. Reference
entries in `clean-capture-check.json` are explicitly unavailable with the
recorded timeout reason and remain unverified.
