# Winbond W631GG6MB native-model validation

The DQS eye workflow still uses an assumed Winbond die load. A recovered vendor
model must pass device checks before replacing that load, and the PCB channel
must separately demonstrate broadband convergence. Neither successful ngspice
completion nor a visually open eye establishes routing accuracy.

**Current result: the supplied native model fails DC sanity.** The explicit
micron-unit control is a diagnostic experiment with unresolved parasitic
geometry; it is not ready for eye integration.
The [saved scalar summary](../../examples/am3352/dqs-em-eye/winbond-dc-summary.json)
records case outcomes and hashes of the private full reports.

## Source and recovery

Winbond's public [W631GG6MB HSPICE archive](https://www.winbond.com/resource-files/w631gg6mb_hspice.zip)
identifies revision **1.0, September 20, 2017**. It provides DQ/DQS, command and
clock circuitry, package RLC, drive-strength and ODT selections. The archive
SHA-256 is `a033f6b9d7f8ff7ba50625b3c3cd5128f48bbe4345223c5a3bfa72555a15eaed`.
The four protected files match the original handoff:

| File | Protected-file SHA-256 |
| --- | --- |
| `W631GG6MB` | `c5740156f3c13a103eb873a81fcebeb8f4c5a206ca53f8de8a305a02c5525d89` |
| `model_tt` | `43b234bf26f50696951e5413efc45c76f83dfab2ef9012229ea8ad05a906f0a7` |
| `model_ss` | `fa4f79d7f718d39ebf7dfc5f077f94d56957ab4f8284c1599db72b1e5815f3ad` |
| `model_ff` | `aca058886b67b0cfd5a137f98be96b88a4656692c3f613127d10280146e1000b` |

The legacy `.PROT freelib` format uses eight position-dependent substitution
tables. Ciphertext letters are normalized to lowercase, and the position
advances across ciphertext characters while excluding physical line breaks.
Plaintext line breaks are encoded characters. The header contains `**enc`
and eight decimal `2290649224` words. Recovery uses interface identifiers,
constrained pin indices, SPICE grammar and standard model-parameter names;
numerical coefficients must not be guessed or fitted.

Substitution round trips establish internal consistency. They do not establish
equivalence to licensed HSPICE. Vendor source, recovered text, compatibility
copies and raw expanded circuits remain local and are not bundled with this
repository.

The reconstructed main circuit has no unresolved characters. Each corner file
retains **22 unresolved comment-only characters**. All active text is recovered,
and a standalone decoder replay reproduces the files byte for byte.

## Run the native DC diagnostic

Supply a locally recovered directory containing `W631GG6MB`, `model_tt` and
`ds_odt_param`. Protected files and unresolved active characters are rejected.
With native ngspice **44.2**:

```sh
python scripts/si/validate-winbond-dc.py /path/to/recovered-model \
  --ngspice /path/to/ngspice --out work/winbond-dc
```

The diagnostic makes a separate compatibility copy, records input/output
hashes and exact identifier changes, and renames the subcircuit length
parameter `ln` to `length_n`. Real `ln(...)` function calls remain intact.
No numerical circuit or model coefficients are changed. Each native run uses
local `.spiceinit` with `set ngbehavior=hsa`.

The output-stage comparison is extracted from the complete buffer's actual
nested instance and calibration sources, preserving the vendor pin order and
resolved voltages. Long flattened device names are queried explicitly because
ngspice's `show` table truncates hierarchy names.

DAT low/high at **27°C and 85°C**, with a **1.5 V supply**, **1 kΩ load** and
vendor **ds034** controls, are separate cases. The fixed **0.5 V bias** is a
bench condition inherited from the failing test; it is not a measured board
calibration. The diagnostic also clamps DQ from **−0.15 to 1.65 V** in
**10 mV** steps to record driver I/V. These are DC probes of one I/O buffer,
not a DQS protocol or differential receiver qualification.

`validation.json` records completion, resolved supply/control voltages and
evaluated devices. Case directories preserve the exact deck, native log,
expanded `listing e`, `show all`, raw circuit vectors and tabular samples.
The command fails on missing/incomplete native results or electrical sanity
failures even when ngspice returns zero.

## Reproduced failure and receiver geometry

The supplied model, after only the `ln` identifier adaptation, reproduces
**−3.159931016789 V** at loaded DQ for DAT high at **27°C**. The resolved
supply, DAT, enable and ds034 A1 control are all **1.5 V**; A5 and the ODT
controls are zero. Supply-source current is **+2.528653 A**, meaning the
ideal supply absorbs current. The output stage alone, with the same native
calibration voltages, produces **1.454234242366 V** and draws **1.479258 mA**.

The full low/high and temperature comparison gives:

| Temperature | DAT | Complete buffer DQ (V) | Output stage DQ (V) |
| --- | --- | ---: | ---: |
| 27°C | low | 0.000000124 | 0.000000123 |
| 27°C | high | −3.159931 | 1.454234 |
| 85°C | low | 0.000886 | **308.852402** |
| 85°C | high | 1.451399 | 1.451399 |

All twelve resolved calibration voltages match between the paired benches.
The 85°C output-stage low result is another electrical-sanity failure; a
plausible room-temperature high alone does not qualify this stage. In the
supplied-model 181-point sweep attempts, seven of eight cases exceed the
240-second per-run cap. The one completed sweep still fails current sanity.
Those attempts are retained as failures, not complete driver I/V curves.

At 85°C, changing only the initial DQ guess with `.nodeset v(dq)=0` yields a
plausible terminal voltage, but internal nodes still reach tens of megavolts
and some `m0res` branches evaluate negative. Both SPARSE and KLU reproduce
the alternate terminal roots. This demonstrates model extrapolation and
initialization sensitivity; terminal voltage alone is an insufficient gate.
Initializing all output-resistor ladder junctions to zero finds a bounded
alternative root in both solvers: DQ **0.38048 µV**, supply draw **53.153 µA**,
positive resistor values and internal nodes within 0–1.5 V. This is additional
initialization evidence; it does not qualify the default operating-point
selection or a switching model.

The expanded receiver reveals a separate unit contract: `gcres` and the
`ynresx → ynres` path use resistor formulas documented to take micron-valued
dimensions, while their circuit calls pass dimensions with SI `u` suffixes.
Native `W − 2×DW` becomes negative. The complete receiver contains eight such
`gcres` elements and twelve internal `ynres` half-resistors. Plausible DQ
voltages at another temperature do not make those elements physically valid.

An isolated supplied `gcres` at a **1 mV** clamp has **−0.000795363 Ω** secant
resistance at 27°C and generates power. Expressing its same physical dimensions
in the documented micron units, without changing the resistor coefficients,
gives **+165.922176 Ω**. `m0res` uses SI geometry and a different contract;
its unchanged output ladders plus the native series resistor give positive
**124.269 Ω / 128.362 Ω** at **27°C / 85°C**, matching an independent nonlinear
series calculation. A blanket conversion of resistor dimensions is incorrect.

The opt-in `--receiver-geometry-microns` diagnostic adds boundary wrappers for
only `gcres` and `ynresx`, recording every call change and wrapper addition.
Original model coefficients remain unchanged. An unchanged fresh baseline and
wrappers with a factor of one reproduce the bad operating point; the same
wrappers with the micron conversion produce **1.454234239072 V** and draw
**1.479279 mA**. This excludes wrapper naming/order alone as the explanation.
These are controlled native results, **not independent HSPICE equivalence**.
The default diagnostic continues to test the supplied unit interpretation.
The conversion also changes derived receiver-resistor diode area/perimeter;
their geometry-scale convention remains unresolved. The adapted DC control
must not be used as a qualified switching or eye model.
One queried receiver diode in that control has **1.084 mF** native capacitance,
which demonstrates why plausible DC behavior does not validate its parasitics.

To inspect that explicit adaptation with a shorter **37-point** I/V capture:

```sh
python scripts/si/validate-winbond-dc.py /path/to/recovered-model \
  --ngspice /path/to/ngspice --receiver-geometry-microns \
  --jobs 4 --sweep-step 0.05 --timeout 300 --out work/winbond-micron-control
```

That capture completes six of eight 37-point sweeps; the two complete-buffer
85°C sweeps exceed 300 seconds. Every completed sweep fails current or
resistance sanity. The local tables preserve the resulting I/V samples;
they are rejected diagnostics, not qualified driver curves.

The 0.5 V bias, ideal supplies and calibration bit patterns remain bench
conditions. Unit conversion and a plausible DC point alone do not qualify the
receiver's threshold, switching, ODT or process behavior.

## Checks required before eye integration

Inspect the expanded `dq_m0res_dq_pu` and `dq_m0res_dq_pd` networks, including
evaluated nonlinear resistance, geometry units and temperature dependence.
Inspect output-transistor `w`, `l`, `m` and `nf`, and compare the complete I/O
buffer with the recovered output stage using identical calibration controls.
The accepted [ngspice multiplicity issue #693](https://sourceforge.net/p/ngspice/bugs/693/)
is not an established cause of the earlier impossible DQ voltage: release
44.2 handles some multiplication paths correctly in HSPICE compatibility mode.

After plausible DC operation, switching, disabled output, ODT, receiver
behavior and process corners still require validation. Board DDR rate,
drive/ODT settings and jitter budgets must be measured or explicitly assumed.
The separate [channel-validation limits](../../examples/am3352/dqs-em-eye)
remain applicable after device validation.
