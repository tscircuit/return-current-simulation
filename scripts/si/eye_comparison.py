"""Finite-record eye diagnostics, including closed-eye stress captures."""

import math
from pathlib import Path

import numpy as np


def waveform_window(waveform, metadata, start_ns=None, stop_ns=None):
    waveform = np.asarray(waveform)
    if waveform.ndim != 2 or waveform.shape[1] != 5 or len(waveform) < 3:
        raise ValueError("Eye comparison requires at least three five-column waveform rows")
    if not np.isfinite(waveform).all() or np.any(np.diff(waveform[:, 0]) <= 0):
        raise ValueError("Eye comparison requires finite values and increasing timestamps")
    start_ns = metadata.get("analysisStartNs", 20) if start_ns is None else start_ns
    stop_ns = metadata.get("analysisStopNs", 310) if stop_ns is None else stop_ns
    if not math.isfinite(start_ns) or not math.isfinite(stop_ns) or stop_ns <= start_ns:
        raise ValueError("Analysis window must have increasing finite bounds")
    window = waveform[(waveform[:, 0] >= start_ns * 1e-9) & (waveform[:, 0] <= stop_ns * 1e-9)]
    if len(window) < 3:
        raise ValueError("Analysis window contains fewer than three waveform samples")
    return window


def source_events(directory):
    path = Path(directory) / "stimulus-events.csv"
    if not path.is_file():
        return None
    events = np.atleast_2d(np.loadtxt(path, delimiter=",", skiprows=1))
    if events.shape[1] not in (3, 4) or not len(events) or not np.isfinite(events).all():
        raise ValueError("Invalid source stimulus event capture")
    if (np.any(np.diff(events[:, 0]) != 1) or np.any(events[:, 0] != np.round(events[:, 0]))
            or np.any(np.diff(events[:, 1]) <= 0) or not np.isin(events[:, 2], [0, 1]).all()):
        raise ValueError("Source stimulus events require consecutive indices, increasing times and binary states")
    return events[:, :3]


def eye_diagnostics(waveform, metadata, analysis, nominal_phase_ps=None, events=None):
    """Keep strict crossing association; unavailable timing does not block a plot."""
    rate = metadata["rateMTs"]
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Positive finite rateMTs is required")
    ui = 1 / (rate * 1e6)
    t, voltage = waveform[:, 0], waveform[:, 3] - waveform[:, 4]
    edges = analysis.crossings(t, voltage)
    tie, receiver_phase, timing_error = None, None, None
    try:
        if metadata.get("mode") == "prbs":
            if len(edges) < 32:
                raise ValueError("PRBS stress needs at least 32 transitions")
            receiver_phase = float(np.angle(np.mean(np.exp(2j * np.pi * edges / ui))) * ui / (2 * np.pi))
            indices = np.round((edges - receiver_phase) / ui).astype(int)
            if not np.all(np.diff(indices) > 0):
                raise ValueError("Multiple crossings in a bit interval; timing association is ambiguous")
            tie = edges - (receiver_phase + indices * ui)
        else:
            edges, tie, receiver_phase = analysis.strobe_timing(t, voltage, ui)
    except ValueError as exc:
        timing_error = str(exc)

    source_phase = metadata.get("nominalSourcePhasePs")
    source_positive = metadata.get("nominalSourceFirstCenterPositive")
    if source_phase is None and events is not None:
        source_phase = float(np.mean(events[:, 1] - events[:, 0] * ui)) * 1e12
        source_positive = bool(events[0, 2])
    if nominal_phase_ps is not None:
        phase, phase_basis = nominal_phase_ps * 1e-12, "explicit nominal phase"
    elif receiver_phase is not None:
        phase, phase_basis = receiver_phase, "receiver mean phase from strict crossing association"
    elif source_phase is not None:
        phase, phase_basis = source_phase * 1e-12, "source nominal phase; receiver propagation delay not removed"
    else:
        raise ValueError("Timing association failed and no explicit or source nominal phase is available")
    if not math.isfinite(phase):
        raise ValueError("Nominal phase must be finite")

    indices = np.arange(np.ceil((t[0] - phase) / ui - 0.5), np.floor((t[-1] - phase) / ui - 0.5) + 1)
    samples = phase + (indices + 0.5) * ui
    samples = samples[(samples > t[0]) & (samples < t[-1])]
    levels = np.interp(samples, t, voltage)
    expected_phase, first_positive, polarity_basis = None, None, "unavailable"
    if receiver_phase is not None and nominal_phase_ps is None:
        crossing_index = np.searchsorted(t, edges[0], side="right")
        first_positive = bool(voltage[crossing_index] > voltage[crossing_index - 1])
        expected_phase, polarity_basis = receiver_phase, "first observed crossing and fixed nominal clock"
    elif source_phase is not None and source_positive is not None:
        expected_phase, first_positive = source_phase * 1e-12, bool(source_positive)
        polarity_basis = "declared source clock polarity; receiver propagation delay not removed"
    elif receiver_phase is not None:
        crossing_index = np.searchsorted(t, edges[0], side="right")
        first_positive = bool(voltage[crossing_index] > voltage[crossing_index - 1])
        expected_phase, polarity_basis = receiver_phase, "first observed crossing and fixed nominal clock"

    height, width, invalid_count, complete_windows = None, None, None, 0
    if len(samples) and (expected_phase is not None or metadata.get("mode") == "prbs"):
        if metadata.get("mode") == "prbs":
            expected_positive = levels >= 0
            polarity_basis = "observed nominal-center polarity; expected PRBS bits are not verified"
        else:
            parity = np.floor((samples - expected_phase) / ui + 1e-9).astype(int) % 2
            expected_positive = (parity == 0) == first_positive
        signed_levels = np.where(expected_positive, levels, -levels)
        valid = signed_levels >= 0.2
        invalid_count = int(np.sum(~valid))
        positive, negative = levels[expected_positive], levels[~expected_positive]
        if len(positive) and len(negative) and np.any(valid) and np.all(positive > 0) and np.all(negative < 0):
            observed_height = float(positive.min() - negative.max())
            height = observed_height if observed_height > 0 else None
        windows = []
        threshold_roots = {
            True: analysis.crossings(t, voltage, 0.2),
            False: analysis.crossings(t, voltage, -0.2),
        }
        for sample, high, valid_sample in zip(samples, expected_positive, valid):
            if not valid_sample:
                continue
            roots = threshold_roots[bool(high)]
            left = np.searchsorted(roots, sample, side="right") - 1
            right = np.searchsorted(roots, sample, side="left")
            # Keep the same exclusion of capture-boundary-truncated windows.
            if left >= 0 and right < len(roots):
                windows.append((float(sample - roots[left]), float(roots[right] - sample)))
        complete_windows = len(windows)
        width = 0.0 if invalid_count else (
            float(min(right for left, right in windows) + min(left for left, right in windows)) * 1e12
            if windows else None
        )
    elif len(levels) and np.all(np.abs(levels) < 0.2):
        width = 0.0

    report = {
        "finiteCaptureEyeHeightV": height, "commonOpeningAt200mVThresholdPs": width,
        "receiverTie": analysis.stats_ps(tie) if tie is not None and len(tie) else None,
        "timingAvailable": tie is not None, "timingUnavailableReason": timing_error,
        "observedCrossingCount": len(edges), "nominalPhasePs": float(phase * 1e12),
        "nominalPhaseBasis": phase_basis, "nominalSamplePolarityBasis": polarity_basis,
        "nominalCenterSamples": len(samples), "nominalThresholdFailures": invalid_count,
        "completeThresholdWindows": complete_windows, "samplingThresholdMv": 200,
        "analysisStartNs": float(t[0] * 1e9), "analysisStopNs": float(t[-1] * 1e9),
        "rateMTs": rate, "uiPs": ui * 1e12, "signoff": False,
    }
    return report, {"t": t, "v": voltage, "tie": tie, "phase": phase, "ui": ui}


def transient_bounds(t, metadata, ui, start_ns=None, stop_ns=None):
    if start_ns is None:
        start_ns = float(t[0] * 1e9 + 2 * ui * 1e9) if metadata.get("frequencyStress") else 25
    if stop_ns is None:
        stop_ns = start_ns + 8 * ui * 1e9 if metadata.get("frequencyStress") else 30
    if not math.isfinite(start_ns) or not math.isfinite(stop_ns) or stop_ns <= start_ns:
        raise ValueError("Transient window must have increasing finite bounds")
    mask = (t >= start_ns * 1e-9) & (t <= stop_ns * 1e-9)
    if np.sum(mask) < 2:
        raise ValueError("Transient window contains fewer than two waveform samples")
    return mask
