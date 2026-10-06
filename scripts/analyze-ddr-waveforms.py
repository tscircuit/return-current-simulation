"""Measure captured/co-simulated DDR waveforms without aligning away jitter.

CSV columns: time_s,dqs_p_v,dqs_n_v; optional tx_p_v,tx_n_v,dq0_v,...
Requires an active continuous burst (no preamble, turnaround or high-Z samples).
Input provenance is mandatory. This analyzer supplies no channel or noise model.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np


def crossings(t, v, threshold=0.0):
    """Linear interpolation, counting both polarities; no edge debouncing."""
    high = v >= threshold
    i = np.flatnonzero(high[1:] != high[:-1])
    return t[i] + (threshold - v[i]) * (t[i + 1] - t[i]) / (v[i + 1] - v[i])


def stats_ps(values):
    values = np.asarray(values) * 1e12
    return {
        "count": len(values),
        "rmsPs": float(np.sqrt(np.mean(values**2))),
        "peakToPeakPs": float(np.ptp(values)),
        "minPs": float(np.min(values)),
        "maxPs": float(np.max(values)),
    }


def strobe_timing(t, differential, ui):
    edges = crossings(t, differential)
    if len(edges) < 32:
        raise ValueError("At least 32 active DQS crossings are required")
    intervals = np.diff(edges)
    if np.any(intervals < ui * 0.5) or np.any(intervals > ui * 1.5):
        raise ValueError(
            "Missing/extra DQS crossing or >0.5 UI deviation: crop to an active burst; do not silently debounce"
        )
    index = np.arange(len(edges))
    phase = float(np.mean(edges - index * ui))
    tie = edges - (phase + index * ui)
    if np.max(np.abs(tie)) >= ui * 0.5:
        raise ValueError(
            "Nominal-clock association ambiguous; verify data rate or split bursts"
        )
    return edges, tie, phase


def valid_margin(t, v, sample, threshold, high):
    roots = crossings(t, v, threshold)
    if (np.interp(sample, t, v) >= threshold) != high:
        return None
    before = roots[roots <= sample]
    after = roots[roots >= sample]
    left = before[-1] if len(before) else t[0]
    right = after[0] if len(after) else t[-1]
    # Ignore windows truncated by the capture boundaries.
    if not len(before) or not len(after):
        return None
    return float(sample - left), float(right - sample)


def analyze(table, rate_mts, max_gap_ps, vil=None, vih=None, sample_delay_ps=None):
    names = table.dtype.names
    required = {"time_s", "dqs_p_v", "dqs_n_v"}
    if not required.issubset(names):
        raise ValueError(f"CSV requires {sorted(required)}")
    if len(table) < 3 or any(not np.all(np.isfinite(table[n])) for n in names):
        raise ValueError("CSV must contain finite waveform values")
    t = table["time_s"]
    dt = np.diff(t)
    if np.any(dt <= 0) or np.max(dt) > max_gap_ps * 1e-12 * (1 + 1e-9):
        raise ValueError(
            "Timestamps must increase and resolve the requested maximum sample gap"
        )
    if (
        rate_mts <= 0
        or not math.isfinite(rate_mts)
        or max_gap_ps <= 0
        or not math.isfinite(max_gap_ps)
    ):
        raise ValueError("Positive finite rate and sample-gap limit required")
    ui = 1 / (rate_mts * 1e6)
    differential = table["dqs_p_v"] - table["dqs_n_v"]
    edges, tie, phase = strobe_timing(t, differential, ui)
    result = {
        "rateMts": rate_mts,
        "uiPs": ui * 1e12,
        "dqsMHz": rate_mts / 2,
        "samples": len(t),
        "durationNs": float(t[-1] - t[0]) * 1e9,
        "maxSampleGapPs": float(np.max(dt)) * 1e12,
        "receiverTie": stats_ps(tie),
        "halfCycleError": stats_ps(np.diff(edges) - ui),
        "dqsCommonModeMinV": float(np.min((table["dqs_p_v"] + table["dqs_n_v"]) / 2)),
        "dqsCommonModeMaxV": float(np.max((table["dqs_p_v"] + table["dqs_n_v"]) / 2)),
        "signoff": False,
        "limitations": [
            "Finite-capture TIE, not a random/deterministic jitter decomposition or BER extrapolation.",
            "Nominal frequency is fixed; only one mean phase is removed. Individual edges are not realigned.",
            "Waveform quality depends on the supplied measurement/co-simulation and declared provenance.",
        ],
    }
    have_tx = [n in names for n in ["tx_p_v", "tx_n_v"]]
    if any(have_tx) and not all(have_tx):
        raise ValueError("Both transmitter legs are required")
    if all(have_tx):
        tx_edges, tx_tie, _ = strobe_timing(t, table["tx_p_v"] - table["tx_n_v"], ui)
        if len(tx_edges) != len(edges):
            raise ValueError(
                "TX/RX crossing counts differ; crop to corresponding edges"
            )
        delays = edges - tx_edges
        # Causal index matching is explicit. No nearest-edge pairing that could
        # conceal a dropped edge or select the following cycle.
        if np.any(delays < 0) or np.ptp(delays) >= ui * 0.5:
            raise ValueError("TX/RX edge correspondence is ambiguous or noncausal")
        result["transmitterTie"] = stats_ps(tx_tie)
        result["meanPropagationDelayPs"] = float(np.mean(delays)) * 1e12
        result["channelAddedEdgeVariation"] = stats_ps(delays - np.mean(delays))
        result["limitations"].append(
            "TX/RX edges are paired by index; the input capture must identify corresponding physical edges. Periodic waveforms alone cannot disambiguate an integer-cycle delay."
        )
    data_names = [
        n
        for n in names
        if n.startswith("dq") and n.endswith("_v") and n[2:-2].isdigit()
    ]
    if data_names:
        if (
            vil is None
            or vih is None
            or sample_delay_ps is None
            or not (
                math.isfinite(vil)
                and math.isfinite(vih)
                and vil < vih
                and math.isfinite(sample_delay_ps)
            )
        ):
            raise ValueError(
                "DQ analysis requires --vil, --vih and explicit --sample-delay-ps (read/write PHY timing matters)"
            )
        result["dqThresholds"] = {
            "vilV": vil,
            "vihV": vih,
            "sampleDelayPs": sample_delay_ps,
        }
        result["dq"] = []
        for name in data_names:
            samples = edges + sample_delay_ps * 1e-12
            samples = samples[(samples > t[0]) & (samples < t[-1])]
            voltages = np.interp(samples, t, table[name])
            invalid = (voltages > vil) & (voltages < vih)
            margins = []
            for sample, voltage in zip(samples, voltages):
                if vil < voltage < vih:
                    continue
                margin = valid_margin(
                    t,
                    table[name],
                    sample,
                    vih if voltage >= vih else vil,
                    voltage >= vih,
                )
                if margin is not None:
                    margins.append(margin)
            result["dq"].append(
                {
                    "signal": name,
                    "samplingEdges": len(samples),
                    "indeterminateSamples": int(np.sum(invalid)),
                    "completeValidWindows": len(margins),
                    "minimumTimeValidBeforeSamplePs": min(
                        (a * 1e12 for a, b in margins), default=None
                    ),
                    "minimumTimeValidAfterSamplePs": min(
                        (b * 1e12 for a, b in margins), default=None
                    ),
                    "minimumThresholdHeadroomV": (
                        float(
                            np.min(
                                np.where(
                                    voltages >= vih, voltages - vih, vil - voltages
                                )
                            )
                        )
                        if len(voltages)
                        else None
                    ),
                    "bitErrorsChecked": False,
                }
            )
        result["limitations"].append(
            "DQ validity is measured at configured voltage thresholds, without expected data bits or a device timing mask; it is not setup/hold compliance or a bit-error count."
        )
    return result, (t, differential, edges, tie, phase, ui, data_names)


def plot(table, result, arrays, out):
    os.environ.setdefault("MPLCONFIGDIR", str(Path("work/matplotlib").resolve()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    t, v, edges, tie, phase, ui, data_names = arrays
    fig, axes = plt.subplots(
        1,
        3 if data_names else 2,
        figsize=(16 if data_names else 12, 5),
        layout="constrained",
    )
    # Two UIs preserve the alternate rising and falling strobe edges. Use a
    # uniformly resampled grid so adaptive simulator steps do not bias density.
    grid = np.arange(t[0], t[-1], np.max(np.diff(t)))
    fold = ((grid - phase + ui) % (2 * ui) - ui) * 1e12
    axes[0].hist2d(
        fold, np.interp(grid, t, v), bins=(300, 180), norm=LogNorm(), cmap="inferno"
    )
    axes[0].set_title("DQS differential density — fixed nominal clock")
    axes[0].set_xlabel("Time (ps), 2 UI")
    axes[0].set_ylabel("DQS+ − DQS− (V)")
    axes[1].hist(tie * 1e12, bins=min(60, max(8, len(tie) // 8)), color="#316691")
    axes[1].set_title(
        f"Receiver TIE: RMS {result['receiverTie']['rmsPs']:.2f} ps\nobserved p-p {result['receiverTie']['peakToPeakPs']:.2f} ps ({len(tie)} edges)"
    )
    axes[1].set_xlabel("TIE (ps)")
    axes[1].set_ylabel("Edges")
    if data_names:
        name = data_names[0]
        # DQ is referenced to actual sampling strobes, preserving relative
        # DQ/DQS jitter. This differs intentionally from the fixed-clock DQS eye.
        window = np.linspace(-ui / 2, ui / 2, 250)
        for edge in edges:
            sample = edge + result["dqThresholds"]["sampleDelayPs"] * 1e-12
            if sample + window[0] >= t[0] and sample + window[-1] <= t[-1]:
                axes[2].plot(
                    window * 1e12,
                    np.interp(sample + window, t, table[name]),
                    color="#316691",
                    alpha=min(0.5, 20 / len(edges)),
                    lw=0.8,
                )
        axes[2].axvline(0, color="black", ls="--")
        for threshold in [
            result["dqThresholds"]["vilV"],
            result["dqThresholds"]["vihV"],
        ]:
            axes[2].axhline(threshold, color="#c64336", ls=":")
        axes[2].set_title(f"{name}: relative to actual DQS sampling edge")
        axes[2].set_xlabel("Time from sample (ps)")
        axes[2].set_ylabel("DQ (V)")
    fig.suptitle(
        f"Captured-waveform analysis, {result['rateMts']:g} MT/s — no BER/signoff inference"
    )
    fig.savefig(out / "eye-and-jitter.png", dpi=150)
    fig.savefig(out / "eye-and-jitter.svg")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument(
        "--provenance",
        required=True,
        help="JSON describing measurement/simulator, channel, models, jitter/noise settings and direction",
    )
    parser.add_argument("--rate-mts", type=float, required=True)
    parser.add_argument("--max-gap-ps", type=float, default=10)
    parser.add_argument("--start-ns", type=float)
    parser.add_argument("--stop-ns", type=float)
    parser.add_argument("--vil", type=float)
    parser.add_argument("--vih", type=float)
    parser.add_argument("--sample-delay-ps", type=float)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    provenance = json.loads(Path(args.provenance).read_text())
    for field in ["kind", "direction", "channel", "ioModels", "jitter", "noise"]:
        if not provenance.get(field):
            parser.error(
                f"Provenance must describe {field}; explicitly state unknown/omitted assumptions"
            )
    table = np.atleast_1d(np.genfromtxt(args.csv, delimiter=",", names=True))
    if args.start_ns is not None:
        table = table[table["time_s"] >= args.start_ns * 1e-9]
    if args.stop_ns is not None:
        table = table[table["time_s"] <= args.stop_ns * 1e-9]
    result, arrays = analyze(
        table, args.rate_mts, args.max_gap_ps, args.vil, args.vih, args.sample_delay_ps
    )
    result["provenance"] = provenance
    result["waveformSha256"] = hashlib.sha256(Path(args.csv).read_bytes()).hexdigest()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "waveform-analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    plot(table, result, arrays, out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
