"""Compare routed and matched-reference eyes without individual-edge alignment."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import textwrap
import numpy as np

from eye_comparison import eye_diagnostics, source_events, transient_bounds, waveform_window

os.environ.setdefault("MPLCONFIGDIR", str(Path("work/matplotlib").resolve()))
import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "simulate-return-current-dqs-eye"
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

spec = importlib.util.spec_from_file_location(
    "waveform_analysis",
    Path(__file__).resolve().parents[1] / "analyze-ddr-waveforms.py",
)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("routed")
p.add_argument("reference")
p.add_argument("--out", required=True)
p.add_argument("--channel-npz")
p.add_argument("--label", default="Routed DQS0: geometry EM + IBIS")
p.add_argument("--reference-label", default="Matched 100 Ω channel: identical I/O and budgets")
p.add_argument("--budget-caption", help="explicit caption when the compared capture budgets differ")
p.add_argument("--start-ns", type=float)
p.add_argument("--stop-ns", type=float)
p.add_argument("--transient-start-ns", type=float)
p.add_argument("--transient-stop-ns", type=float)
p.add_argument("--nominal-phase-ps", type=float, help="fixed nominal fold phase when receiver timing is unavailable, or an explicit override")
a = p.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
voltage_limit = 1.25
for directory in [a.routed, a.reference]:
    capture = np.load(Path(directory) / "waveforms.npz")
    voltage_limit = max(
        voltage_limit, float(abs(capture["dqs_p_v"] - capture["dqs_n_v"]).max()) * 1.08
    )
fig, axes = plt.subplots(2, 2, figsize=(14, 9))
reports = []
for column, (directory, label) in enumerate(
    [
        (a.routed, a.label),
        (a.reference, a.reference_label),
    ]
):
    directory = Path(directory)
    if (directory / "waveforms.csv").exists():
        w = np.loadtxt(directory / "waveforms.csv", delimiter=",", skiprows=1)
    else:
        capture = np.load(directory / "waveforms.npz")
        w = np.column_stack(
            [
                capture[key]
                for key in ["time_s", "tx_p_v", "tx_n_v", "dqs_p_v", "dqs_n_v"]
            ]
        )
    meta = json.loads((directory / "provenance.json").read_text())
    if meta.get("frequencyStress") and column == 0 and a.label == "Routed DQS0: geometry EM + IBIS":
        label = "Routed channel: ideal differential source bandwidth stress"
    w = waveform_window(w, meta, a.start_ns, a.stop_ns)
    report, arrays = eye_diagnostics(w, meta, analysis, a.nominal_phase_ps, source_events(directory))
    t, v, tie, phase, ui = (arrays[key] for key in ("t", "v", "tie", "phase", "ui"))
    fold = ((t - phase) % ui - ui / 2) * 1e12
    voltage = np.tile(v, 3)
    fold = np.concatenate([fold - ui * 1e12, fold, fold + ui * 1e12])
    visible = np.abs(fold) <= ui * 1e12
    axis = axes[0, column]
    axis.set_facecolor("#120d22")
    time_bins = 650
    if meta.get("benchScenario"):
        # A fixed saved grid needs corresponding density bins: narrower bins
        # would draw artificial empty columns between the sampled timestamps.
        time_bins = min(time_bins, max(16, round(2 * ui / np.median(np.diff(t)))))
    axis.hist2d(
        fold[visible],
        voltage[visible],
        bins=(time_bins, 350),
        range=[[-ui * 1e12, ui * 1e12], [-voltage_limit, voltage_limit]],
        norm=LogNorm(vmin=1),
        cmap="inferno",
        rasterized=True,
    )
    axis.set_xlabel("Time from nominal eye center (ps)")
    observation = meta.get("observation", {})
    measurement_plane = observation.get("plane", "receiver die")
    axis.set_ylabel(f"DQS+ − DQS− at {measurement_plane} (V)")
    axis.set_title(label)
    axis.axvline(0, color="white", alpha=0.3, lw=0.7)
    for threshold in [-0.2, 0.2]:
        axis.axhline(threshold, color="white", ls=":", alpha=0.5, lw=0.7)
    report.update({"label": label, "sourceBudgets": {"jitter": meta["jitter"], "noise": meta["noise"]},
                   "frequencyStress": meta.get("frequencyStress", False),
                   "experimentDescription": meta.get("experimentDescription"), "limitations": meta.get("limitations", []),
                   "benchScenario": meta.get("benchScenario", False), "observation": observation})
    if meta.get("benchScenario"):
        report["densityDisplay"] = {"timeBins": time_bins, "voltageBins": 350,
                                    "timeBinWidthPs": 2 * ui * 1e12 / time_bins,
                                    "policy": "saved samples; no display interpolation or additional noise"}
    reports.append(report)
    height, width = report["finiteCaptureEyeHeightV"], report["commonOpeningAt200mVThresholdPs"]
    height_text = f"{height:.3f} V" if height is not None else "unavailable"
    width_text = f"{width:.0f} ps" if width is not None else "unavailable"
    opening_text = "No ±200 mV opening" if width == 0 else f"Opening at ±0.2 V: {width_text}"
    timing_text = f"TIE RMS {report['receiverTie']['rmsPs']:.2f} ps" if report["receiverTie"] else "TIE unavailable\n" + textwrap.fill(report["timingUnavailableReason"] or "No associated edges", 44)
    if report["receiverTie"] and report["nominalThresholdFailures"] == report["nominalCenterSamples"]:
        timing_text = f"Subthreshold zero-crossing TIE\nRMS {report['receiverTie']['rmsPs']:.3g} ps"
    axis.text(
        0.03,
        0.96,
        f"Observed height {height_text}\n{opening_text}\n{timing_text}",
        transform=axis.transAxes,
        color="white",
        va="top",
        fontsize=9,
        bbox={"facecolor": "#120d22", "alpha": 0.8, "edgecolor": "none"},
    )
    if tie is not None and len(tie):
        legend_label = label.split(":")[0]
        if (meta.get("benchScenario") and a.budget_caption
                and a.label.split(":")[0] == a.reference_label.split(":")[0]):
            legend_label = label.split(": ", 1)[-1]
        axes[1, 1].hist(tie * 1e12, bins=35, alpha=0.55, label=legend_label)
    else:
        axes[1, 1].text(0.03, 0.92 - 0.30 * column, textwrap.fill(label + ": " + (report["timingUnavailableReason"] or "Timing unavailable"), 65),
                        transform=axes[1, 1].transAxes, va="top", fontsize=9,
                        bbox={"facecolor": "white", "alpha": 0.86, "edgecolor": "none"})
    axes[1, 1].set_xlabel("Receiver timing error from fixed nominal clock (ps)")
    axes[1, 1].set_ylabel("Edges")
    axes[1, 1].set_title("Receiver timing variation under the same stimulus")
    if meta.get("benchScenario") and a.budget_caption:
        axes[1, 1].set_title("Clean and noisy receiver timing")
    if column == 0:
        tx = w[:, 1] - w[:, 2]
        cut = transient_bounds(t, meta, ui, a.transient_start_ns, a.transient_stop_ns)
        display_time_ns = t[cut] * 1e9
        if meta.get("frequencyStress"):
            display_time_ns -= meta.get("analysisStartNs", t[0] * 1e9)
        axes[1, 0].plot(display_time_ns, tx[cut], label="Transmitter BGA", lw=1)
        axes[1, 0].plot(display_time_ns, v[cut], label=measurement_plane.capitalize(), lw=1)
axes[1, 0].set_title("Routed transient: delay, slew and reflection response")
axes[1, 0].set_xlabel("Time (ns)")
if meta.get("frequencyStress"):
    axes[1, 0].set_title("Routed differential waveform: analysis window")
    axes[1, 0].set_xlabel("Time from analysis start (ns)")
    axes[1, 0].ticklabel_format(axis="x", useOffset=False, style="plain")
axes[1, 0].set_ylabel("Differential voltage (V)")
axes[1, 0].legend(fontsize=9)
if axes[1, 1].get_legend_handles_labels()[0]:
    axes[1, 1].legend(fontsize=8)
meta = json.loads((Path(a.routed) / "provenance.json").read_text())
caption = (
    f"AM3352 DQS0 · {meta['rateMTs']:g} MT/s · {meta['clockMHz']:g} MHz strobe · UI {ui * 1e12:g} ps"
    if meta.get("mode") == "clock"
    else f"AM3352 DQS pair · PRBS7 channel stress · {meta['rateMTs']:g} MT/s · not DQS clock protocol"
)
if meta.get("frequencyStress"):
    strobe_ghz = meta.get("strobeGHz", meta["clockMHz"] / 1000)
    caption = (f"Ideal-source DQS bandwidth stress · {strobe_ghz:g} GHz strobe · "
               f"{meta['rateMTs'] / 1000:g} GT/s · UI {1e6 / meta['rateMTs']:g} ps")
    if meta.get("benchScenario"):
        caption = (f"Assumed DQS measurement scenario · {strobe_ghz:g} GHz strobe · "
                   f"{meta['rateMTs'] / 1000:g} GT/s · UI {1e6 / meta['rateMTs']:g} ps")
elif meta.get("experimentDescription"):
    caption = textwrap.fill(meta["experimentDescription"], 105)
fig.suptitle(
    caption,
    fontsize=15 if meta.get("frequencyStress") else 18,
    y=0.98,
)
budget_caption = (
    f"Configured source RJ {meta['jitter']['configuredInputRjRmsPs']:g} ps RMS + PJ {meta['jitter']['configuredPeriodicJitterPeakPs']:g} ps peak; receiver noise {meta['noise'].get('configuredRmsMv', 0):g} mV RMS. These are budgets, not board measurements."
)
if meta.get("benchScenario"):
    observation = meta.get("observation", {})
    budget_caption = (
        f"Assumed source RJ {meta['jitter']['configuredInputRjRmsPs']:g} ps RMS + PJ {meta['jitter']['configuredPeriodicJitterPeakPs']:g} ps peak; "
        f"pad noise {meta['noise'].get('configuredRmsMv', 0):g} mV RMS; scope noise {observation.get('scopeNoiseRmsMv', 0):g} mV RMS."
    )
if a.budget_caption:
    budget_caption = a.budget_caption
fig.text(
    0.5,
    0.085,
    f"U1.P1/P2 → U3.F3/G3 · write · {meta['ioModels']['odtOhmsPerLeg']:g} Ω ODT/leg · {meta['ioModels']['receiverCapacitancePf']:g} pF assumed input/leg",
    ha="center",
    fontsize=10,
)
fig.text(
    0.5,
    0.060,
    budget_caption,
    ha="center",
    fontsize=9,
)
limitations = "Experimental differential channel: mesh/time convergence and active crosstalk/PDN are not validated. No DDR pass/fail or BER inference."
if meta.get("frequencyStress"):
    channel = meta.get("channel", {})
    maximum = channel.get("maximumExtractedFrequencyGHz")
    bandwidth = f"1 MHz–{maximum:g} GHz fit" if maximum is not None else "supplied differential fit"
    frequency_note = (f"{strobe_ghz:g} GHz is extrapolated" if maximum is not None and strobe_ghz > maximum
                      else f"{strobe_ghz:g} GHz band edge; higher harmonics extrapolated" if maximum is not None and strobe_ghz == maximum
                      else "fundamental is within the declared fit bandwidth" if maximum is not None
                      else "extracted bandwidth is unspecified")
    source = meta.get("source", {})
    source_note = (f"Ideal {source['resistanceOhmsPerLeg']:g} Ω/leg, {source['riseTimePs']:g} ps source"
                   if "resistanceOhmsPerLeg" in source and "riseTimePs" in source else "Ideal differential source")
    limitations = (f"Routed response uses {bandwidth}; {frequency_note}. Matched reference is ideal; packages/assumed load retained.\n"
                   f"{source_note}, zero jitter/noise; no AM3352 switching model, DDR margin or BER claim.")
    if meta.get("benchScenario"):
        observation = meta.get("observation", {})
        scope_note = (
            f"{observation['scopeBandwidthGHz']:g} GHz two-pole scope response"
            if "scopeBandwidthGHz" in observation else "raw circuit response"
        )
        limitations = (
            f"{source_note}; {scope_note}. Probe and receiver loading are assumptions.\n"
            f"Routed response uses {bandwidth}; out-of-band sidebands/harmonics extrapolated. Uncalibrated scenario; no DDR margin or BER claim."
        )
fig.text(
    0.5,
    0.025 if meta.get("frequencyStress") else 0.035,
    limitations,
    ha="center",
    fontsize=9,
    color="#9b3e2a",
)
fig.subplots_adjust(top=0.88 if meta.get("frequencyStress") else 0.90,
                    bottom=0.21 if meta.get("frequencyStress") else 0.17, hspace=0.40, wspace=0.23)
fig.savefig(out / "eye-comparison.png", dpi=160)
fig.savefig(out / "eye-comparison.svg", dpi=160, metadata={"Date": None})
svg_path = out / "eye-comparison.svg"
svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text().splitlines()) + "\n")
plt.close(fig)
(out / "comparison.json").write_text(
    json.dumps(
        {
            "cases": reports,
            "receiverInputThresholdMv": 200,
            "signoff": False,
            "definition": "Finite-record extrema at a single nominal sampling phase, not a receiver timing mask or BER extrapolation",
        },
        indent=2,
    )
)
print(json.dumps(reports, indent=2))
if a.channel_npz:
    ch = np.load(a.channel_npz)
    f = ch["f"]
    s = ch["s"]
    fit = ch["fit"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for i, j, label in [(0, 0, "S11"), (1, 0, "S21"), (1, 1, "S22")]:
        axes[0].plot(
            f / 1e9,
            20 * np.log10(np.maximum(abs(s[:, i, j]), 1e-8)),
            label=label + " raw",
        )
        axes[0].plot(
            f / 1e9,
            20 * np.log10(np.maximum(abs(fit[:, i, j]), 1e-8)),
            ls="--",
            alpha=0.6,
        )
    axes[0].set_xlabel("Frequency (GHz)")
    axes[0].set_ylabel("Magnitude (dB)")
    axes[0].legend()
    axes[0].set_title("Extracted scattering parameters and passive fit")
    axes[1].plot(
        f / 1e9,
        -np.gradient(np.unwrap(np.angle(s[:, 1, 0])), 2 * np.pi * f) * 1e12,
        label="Raw S21",
    )
    axes[1].plot(
        f / 1e9,
        -np.gradient(np.unwrap(np.angle(fit[:, 1, 0])), 2 * np.pi * f) * 1e12,
        ls="--",
        label="Fit",
    )
    axes[1].set_xlabel("Frequency (GHz)")
    axes[1].set_ylabel("Group delay (ps)")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(out / "channel-response.png", dpi=150)
    fig.savefig(out / "channel-response.svg")
    plt.close(fig)
