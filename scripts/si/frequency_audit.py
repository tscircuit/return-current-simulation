"""Record finite-window amplitudes, settling, and timestep sensitivity.

Reads the supplied captures without modifying them. Amplitudes and phase fits
are diagnostics of the stated model; no physical high-frequency accuracy is
inferred. The RMS definition removes the window's differential DC mean.
"""

import hashlib
import json
from pathlib import Path

import numpy as np


def validate_waveforms(waveforms):
    time = np.asarray(waveforms["time_s"])
    if time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all() or not (np.diff(time) > 0).all():
        raise ValueError("Capture time must be finite, one-dimensional and strictly increasing")
    signals = ["dqs_p_v", "dqs_n_v", "tx_p_v", "tx_n_v"]
    signals += [key for key in ("channel_input_v", "channel_output_v") if key in waveforms]
    for key in signals:
        voltage = np.asarray(waveforms[key])
        if voltage.shape != time.shape or not np.isfinite(voltage).all():
            raise ValueError(f"Capture signal {key} must be finite and match the time vector")


def load_capture(directory):
    directory = Path(directory)
    metadata = json.loads((directory / "provenance.json").read_text())
    with np.load(directory / "waveforms.npz") as capture:
        waveforms = {name: capture[name] for name in capture.files}
    validate_waveforms(waveforms)
    return metadata, waveforms


def window_metrics(waveforms, window):
    validate_waveforms(waveforms)
    time = waveforms["time_s"]
    frequency = window["frequencyHz"]
    start, stop = window["startNs"] * 1e-9, window["stopNs"] * 1e-9
    if not np.isfinite([frequency, start, stop]).all() or frequency <= 0 or stop <= start:
        raise ValueError("Analysis window needs a positive frequency and finite increasing bounds")
    tolerance = 1e-12 * max(abs(start), abs(stop), np.ptp(time))
    if start < time[0] - tolerance or stop > time[-1] + np.diff(time).max() + tolerance:
        raise ValueError("Analysis window extends outside the supplied capture")
    mask = (time >= window["startNs"] * 1e-9) & (time < window["stopNs"] * 1e-9)
    time = time[mask]
    if len(time) <= 10:
        raise ValueError("Analysis window needs more than ten samples")
    basis = np.column_stack([
        np.cos(2 * np.pi * frequency * time),
        np.sin(2 * np.pi * frequency * time),
        np.ones_like(time),
    ])
    signals = {
        "receiverDieDifferential": waveforms["dqs_p_v"][mask] - waveforms["dqs_n_v"][mask],
        "transmitterBgaDifferential": waveforms["tx_p_v"][mask] - waveforms["tx_n_v"][mask],
    }
    for key in ("channel_input_v", "channel_output_v"):
        if key in waveforms:
            signals[key] = waveforms[key][mask]
    result = {"window": window, "samples": len(time), "signals": {}}
    for name, voltage in signals.items():
        cosine, sine, offset = np.linalg.lstsq(basis, voltage, rcond=None)[0]
        result["signals"][name] = {
            "meanV": float(voltage.mean()),
            "acRmsV": float(np.std(voltage)),
            "halfPeakToPeakV": float(np.ptp(voltage) / 2),
            "maximumAbsoluteV": float(abs(voltage).max()),
            "fundamentalPeakV": float(np.hypot(cosine, sine)),
            "fundamentalPhaseRad": float(np.angle(cosine - 1j * sine)),
            "fittedDcOffsetV": float(offset),
        }
    return result


def audit_capture(directory):
    directory = Path(directory)
    metadata, waveforms = load_capture(directory)
    frequency = metadata["strobeGHz"] * 1e9
    start, stop = metadata["analysisStartNs"], metadata["analysisStopNs"]
    if not np.isfinite([frequency, start, stop]).all() or frequency <= 0 or stop <= start:
        raise ValueError("Capture metadata needs a positive strobe frequency and increasing analysis bounds")
    short_window_ns = min(8 / frequency * 1e9, (stop - start) / 4)
    windows = [
        {"label": "whole analysis", "startNs": start, "stopNs": stop, "frequencyHz": frequency},
        {"label": "early", "startNs": start, "stopNs": start + short_window_ns, "frequencyHz": frequency},
        {"label": "middle", "startNs": (start + stop - short_window_ns) / 2,
         "stopNs": (start + stop + short_window_ns) / 2, "frequencyHz": frequency},
        {"label": "late", "startNs": stop - short_window_ns, "stopNs": stop, "frequencyHz": frequency},
    ]
    period = 1 / frequency
    time = waveforms["time_s"]
    receiver = waveforms["dqs_p_v"] - waveforms["dqs_n_v"]
    late_time = np.linspace(stop * 1e-9 - period, stop * 1e-9, 201, endpoint=False)
    if late_time[0] - period < time[0] or late_time[-1] > time[-1]:
        raise ValueError("Late-cycle diagnostic needs two complete cycles within the supplied capture")
    last_cycle = np.interp(late_time, time, receiver)
    previous_cycle = np.interp(late_time - period, time, receiver)
    repeat_error = last_cycle - previous_cycle
    return {
        "capture": str(directory.resolve()),
        "waveformsSha256": hashlib.sha256((directory / "waveforms.npz").read_bytes()).hexdigest(),
        "netlistSha256": metadata["netlistSha256"],
        "frequencyHz": frequency, "timeStepPs": metadata["timeStepPs"],
        "windows": [window_metrics(waveforms, window) for window in windows],
        "lateCycleRepeat": {
            "cycleDurationPs": period * 1e12,
            "receiverAcRmsV": float(np.std(last_cycle)),
            "maximumAbsoluteDifferenceV": float(abs(repeat_error).max()),
            "rmsDifferenceV": float(np.sqrt(np.mean(repeat_error ** 2))),
        },
        "limitations": [
            "Windows are finite captures and may include launch settling.",
            "Response outside the channel's saved frequency band is rational-model extrapolation.",
            "Amplitude differences include source/package/load filtering and channel extrapolation.",
        ],
    }


def timestep_comparison(coarse_directory, refined_directory):
    directories = [Path(coarse_directory), Path(refined_directory)]
    captures = [load_capture(directory) for directory in directories]
    coarse_metadata, coarse = captures[0]
    refined_metadata, refined = captures[1]
    for key in ("source", "ioModels", "strobeGHz", "analysisStartNs", "analysisStopNs", "uiCount"):
        if coarse_metadata[key] != refined_metadata[key]:
            raise ValueError(f"Timestep cases differ in {key}")
    if coarse_metadata.get("integrationMethod") != refined_metadata.get("integrationMethod"):
        raise ValueError("Timestep cases differ in integrationMethod")
    if coarse_metadata["channel"]["modelSha256"] != refined_metadata["channel"]["modelSha256"]:
        raise ValueError("Timestep cases differ in channel modelSha256")
    mask = ((coarse["time_s"] >= coarse_metadata["analysisStartNs"] * 1e-9)
            & (coarse["time_s"] < coarse_metadata["analysisStopNs"] * 1e-9))
    coarse_voltage = (coarse["dqs_p_v"] - coarse["dqs_n_v"])[mask]
    sampled_time = coarse["time_s"][mask]
    if not len(sampled_time) or sampled_time[0] < refined["time_s"][0] or sampled_time[-1] > refined["time_s"][-1]:
        raise ValueError("Refined capture does not cover all analyzed coarse timestamps")
    refined_voltage = np.interp(
        coarse["time_s"][mask], refined["time_s"], refined["dqs_p_v"] - refined["dqs_n_v"]
    )
    summaries = [audit_capture(directory)["windows"][0]["signals"]["receiverDieDifferential"] for directory in directories]
    coarse_summary, refined_summary = summaries
    phase_change = float(np.angle(np.exp(1j * (
        refined_summary["fundamentalPhaseRad"] - coarse_summary["fundamentalPhaseRad"]
    ))))
    return {
        "coarseCapture": str(directories[0].resolve()), "refinedCapture": str(directories[1].resolve()),
        "coarseTimeStepPs": coarse_metadata["timeStepPs"], "refinedTimeStepPs": refined_metadata["timeStepPs"],
        "receiverHalfPeakToPeakRelativeChange": relative_change(refined_summary["halfPeakToPeakV"], coarse_summary["halfPeakToPeakV"]),
        "receiverAcRmsRelativeChange": relative_change(refined_summary["acRmsV"], coarse_summary["acRmsV"]),
        "receiverFundamentalPeakRelativeChange": relative_change(refined_summary["fundamentalPeakV"], coarse_summary["fundamentalPeakV"]),
        "receiverFundamentalPhaseChangeRad": phase_change,
        "receiverFundamentalPhaseEquivalentTimeChangePs": phase_change / (2 * np.pi * coarse_metadata["strobeGHz"] * 1e9) * 1e12,
        "receiverMaximumAbsoluteWaveformDifferenceV": float(abs(refined_voltage - coarse_voltage).max()),
        "waveformComparison": "Same absolute time; refined capture linearly interpolated to coarse timestamps; no phase alignment",
    }


def relative_change(refined, coarse):
    return refined / coarse - 1 if coarse != 0 else None


def capture_summary(report):
    summaries = []
    for capture in report["captures"]:
        windows = [{"window": window["window"], "receiver": window["signals"]["receiverDieDifferential"]}
                   for window in capture["windows"]]
        summaries.append({"capture": capture["capture"], "waveformsSha256": capture["waveformsSha256"],
                          "timeStepPs": capture["timeStepPs"], "windows": windows,
                          "lateCycleRepeat": capture["lateCycleRepeat"]})
    return {"captures": summaries, "timestepComparison": report.get("timestepComparison")}
