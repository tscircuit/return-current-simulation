"""Compare routed and matched-reference eyes without individual-edge alignment."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import numpy as np

os.environ.setdefault("MPLCONFIGDIR", str(Path("work/matplotlib").resolve()))
import matplotlib

matplotlib.use("Agg")
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
        (a.reference, "Matched 100 Ω channel: identical I/O and budgets"),
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
    ui = 1 / (meta["rateMTs"] * 1e6)
    mask = (w[:, 0] >= 20e-9) & (w[:, 0] <= 310e-9)
    w = w[mask]
    t = w[:, 0]
    v = w[:, 3] - w[:, 4]
    if meta.get("mode") == "prbs":
        edges = analysis.crossings(t, v)
        assert len(edges) >= 32, "PRBS stress needs at least 32 transitions"
        phase = float(
            np.angle(np.mean(np.exp(2j * np.pi * edges / ui))) * ui / (2 * np.pi)
        )
        indices = np.round((edges - phase) / ui).astype(int)
        assert np.all(np.diff(indices) > 0), (
            "Multiple crossings in a bit interval; timing association is ambiguous"
        )
        tie = edges - (phase + indices * ui)
    else:
        edges, tie, phase = analysis.strobe_timing(t, v, ui)
    fold = ((t - phase) % ui - ui / 2) * 1e12
    voltage = np.tile(v, 3)
    fold = np.concatenate([fold - ui * 1e12, fold, fold + ui * 1e12])
    visible = np.abs(fold) <= ui * 1e12
    axis = axes[0, column]
    axis.set_facecolor("#120d22")
    axis.hist2d(
        fold[visible],
        voltage[visible],
        bins=(650, 350),
        range=[[-ui * 1e12, ui * 1e12], [-voltage_limit, voltage_limit]],
        norm=LogNorm(),
        cmap="inferno",
        rasterized=True,
    )
    axis.set_xlabel("Time from nominal eye center (ps)")
    axis.set_ylabel("DQS+ − DQS− at receiver die (V)")
    axis.set_title(label)
    axis.axvline(0, color="white", alpha=0.3, lw=0.7)
    for threshold in [-0.2, 0.2]:
        axis.axhline(threshold, color="white", ls=":", alpha=0.5, lw=0.7)
    sample_indices = np.arange(
        np.ceil((t[0] - phase) / ui - 0.5), np.floor((t[-1] - phase) / ui - 0.5) + 1
    )
    samples = phase + (sample_indices + 0.5) * ui
    samples = samples[(samples > t[0]) & (samples < t[-1])]
    levels = np.interp(samples, t, v)
    positive = levels[levels > 0]
    negative = levels[levels < 0]
    height = float(positive.min() - negative.max())
    windows = []
    for sample, level in zip(samples, levels):
        margin = analysis.valid_margin(
            t, v, sample, 0.2 if level > 0 else -0.2, level > 0
        )
        if margin:
            windows.append(margin)
    width = (
        float(min(r for l, r in windows) + min(l for l, r in windows)) * 1e12
        if windows
        else None
    )
    report = {
        "label": label,
        "finiteCaptureEyeHeightV": height,
        "commonOpeningAt200mVThresholdPs": width,
        "receiverTie": analysis.stats_ps(tie),
        "samplingThresholdMv": 200,
        "sourceBudgets": {"jitter": meta["jitter"], "noise": meta["noise"]},
        "signoff": False,
    }
    reports.append(report)
    axis.text(
        0.03,
        0.96,
        f"Observed height {height:.3f} V\nOpening at ±0.2 V: {width:.0f} ps\nTIE RMS {report['receiverTie']['rmsPs']:.2f} ps",
        transform=axis.transAxes,
        color="white",
        va="top",
        fontsize=9,
        bbox={"facecolor": "#120d22", "alpha": 0.8, "edgecolor": "none"},
    )
    axes[1, 1].hist(tie * 1e12, bins=35, alpha=0.55, label=label.split(":")[0])
    axes[1, 1].set_xlabel("Receiver timing error from fixed nominal clock (ps)")
    axes[1, 1].set_ylabel("Edges")
    axes[1, 1].set_title("Receiver timing variation under the same stimulus")
    if column == 0:
        tx = w[:, 1] - w[:, 2]
        cut = (t >= 25e-9) & (t < 30e-9)
        axes[1, 0].plot(t[cut] * 1e9, tx[cut], label="Transmitter BGA", lw=1)
        axes[1, 0].plot(t[cut] * 1e9, v[cut], label="Receiver die", lw=1)
axes[1, 0].set_title("Routed transient: delay, slew and reflection response")
axes[1, 0].set_xlabel("Time (ns)")
axes[1, 0].set_ylabel("Differential voltage (V)")
axes[1, 0].legend(fontsize=9)
axes[1, 1].legend(fontsize=8)
meta = json.loads((Path(a.routed) / "provenance.json").read_text())
caption = (
    f"AM3352 DQS0 · {meta['rateMTs']:g} MT/s · {meta['clockMHz']:g} MHz strobe · UI {ui * 1e12:g} ps"
    if meta.get("mode") == "clock"
    else f"AM3352 DQS pair · PRBS7 channel stress · {meta['rateMTs']:g} MT/s · not DQS clock protocol"
)
fig.suptitle(
    caption,
    fontsize=18,
    y=0.98,
)
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
    f"Configured source RJ {meta['jitter']['configuredInputRjRmsPs']:g} ps RMS + PJ {meta['jitter']['configuredPeriodicJitterPeakPs']:g} ps peak; receiver noise {meta['noise'].get('configuredRmsMv', 0):g} mV RMS. These are budgets, not board measurements.",
    ha="center",
    fontsize=9,
)
fig.text(
    0.5,
    0.035,
    "Experimental differential channel: mesh/time convergence and active crosstalk/PDN are not validated. No DDR pass/fail or BER inference.",
    ha="center",
    fontsize=9,
    color="#9b3e2a",
)
fig.subplots_adjust(top=0.90, bottom=0.17, hspace=0.40, wspace=0.23)
fig.savefig(out / "eye-comparison.png", dpi=160)
fig.savefig(out / "eye-comparison.svg", dpi=160)
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
