# Exact bench Tref / lossless LTRA AC equivalence

Derived both private AC decks from `/workspace/work/dqs-bench-smoke/noisy-reference/simulation.cir`. Retained source50ohms per leg, original transmitter/receiver packages, balanced transform/common-mode circuit, assumed ODT/input capacitance, and0.2pF probe per leg. Replaced the transmitter PWL include with DC0.75V sources having AC+0.5/-0.5V (exact1V differential), and retained physical receiver series-noise source topology with Vnp/Vnn DC0. All other electrical values are identical. No repository/code change or long transient was made.

Only the line declaration differs between:

    Tref csrc 0 cload 0 Z0=100 TD=.4n

and

    Oref csrc 0 cload 0 refline
    .model refline LTRA(R=0 G=0 L=40n C=4p LEN=1)

Both used the unchanged stock native ngspice44.2 binary in default compatibility mode.

At5GHz receiver-die differential transfer H (receiver die voltage/open-circuit source differential voltage):

- Real=-0.358477540269803, imaginary=+0.332972461154616.
- Magnitude=0.489261491193872, -6.20917930712504dB.
- Phase=137.112475466849degrees.
- Expected stated5GHzclock first-harmonic peak=0.934382191423V.

The LTRA result differs by approximately4e-16 in complex receiver H at5GHz. Across401frequencies from4to6GHz (5MHzspacing), maximum receiver relative complex difference is5.7345e-15, relative amplitude difference3.5528e-15 and phase difference3.002e-13degrees. Transmitter, receiver-pin and loaded-channel transfers also agree within floating-point precision. At5GHz, loaded cload/csrc is unity because400ps is exactly two periods; it remains a voltage ratio under the retained reactive load.

Zero R/G semantics in the exact ngspice44.2 source:

- `src/spicelib/devices/ltra/ltrampar.c:51-61` assigns supplied R/G values directly.
- `ltraset.c:107-109` selects the explicit `LTRA_MOD_LC` special case when R=G=0 and L/C are nonzero.
- `ltratemp.c:33-39` sets Z0=sqrt(L/C)=100ohms, TD=sqrt(LC)*LEN=400ps and attenuation=1.
- `ltraacld.c:51-58` sets real admittance1/Z0 and real propagation constant zero in that LC case.

Thus this model is exactly lossless; no positive resistance or conductance was substituted. This audit establishes AC electrical equivalence, not identical transient integration histories or total noisy-waveform behavior.

Evidence: paired `t/` and `ltra/` deck/log/fundamental/grid captures, `analyze-ac.py`, `analysis.log`, `results.json`, `provenance.json`. All scratch files are preserved.


## Explicit off-harmonic and low-frequency check

A separate native400MHzpoint and explicit sideband rows from the existing401pointgrid establish agreement away from the5GHzinteger-period line identity. Receiver die H relative to the1V differential open-circuit AC source:

| FrequencyGHz | Magnitude | Phase degrees |
| --- | ---: | ---: |
| 0.4 | 0.536158770 | -76.314706 |
| 4.5 | 0.174240315 | -112.002086 |
| 4.9 | 0.426915730 | -167.322880 |
| 5.1 | 0.303057188 | +97.878897 |
| 5.5 | 0.123709576 | +60.646230 |

Tref/LTRA relative complex receiver differences at these five points are at most5.75e-16; phase differences at most9.09e-15degrees. Loaded-channel voltage transfer is not unity away from the carrier: at400MHzit is1.288291752angle-67.770846degrees, and at4.5GHzit is0.622628383angle151.149451degrees; both models agree on these values. The reactive load explains voltage-ratio magnitudes greater than1 without implying power gain.

Additional preserved evidence: paired `low-frequency.cir`, `low-frequency.log`, `low-frequency.dat`; `analyze-offharmonic.py`, `offharmonic-analysis.log`, `offharmonic-results.json`. No additional transient was run.
