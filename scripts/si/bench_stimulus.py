"""Stationary assumed disturbances for an explicitly ideal bench companion."""

import math
from pathlib import Path

import numpy as np
from scipy.linalg import solve_discrete_lyapunov
from scipy.signal import butter, lfilter


def positive(value, name, *, zero=False):
    if not math.isfinite(value) or value < 0 or (value == 0 and not zero):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")
    return value


def count_and_seed(config):
    count, seed = config["sample_count"], config["seed"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 2:
        raise ValueError("sample count must be an integer of at least two")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    return count, seed


def distribution_report(values):
    return {
        "mean": float(np.mean(values)),
        "rms": float(np.sqrt(np.mean(values**2))),
        "acRms": float(np.std(values)),
        "minimum": float(np.min(values)), "maximum": float(np.max(values)),
    }


def ou_jitter(config):
    """Sample a stationary OU timing process at nominal UI spacing."""
    count, seed = count_and_seed(config)
    ui = positive(config["ui_s"], "unit interval")
    corner = positive(config["corner_hz"], "jitter corner")
    sigma = positive(config["rms_s"], "jitter RMS", zero=True)
    alpha = math.exp(-2 * math.pi * corner * ui)
    rng = np.random.default_rng(seed)
    values = np.zeros(count)
    if sigma:
        normals = rng.normal(size=count)
        values[0] = sigma * normals[0]
        values[1:], _ = lfilter(
            [sigma * math.sqrt(-math.expm1(-4 * math.pi * corner * ui))],
            [1, -alpha], normals[1:], zi=[alpha * values[0]],
        )
    report = {
        "kind": "stationary Gaussian OU sampled as AR(1) at nominal UI",
        "configuredRmsS": sigma, "cornerHz": corner,
        "sampleIntervalS": ui, "ar1Coefficient": alpha,
        "stationaryInitialization": True, "seed": seed,
        "sampleCount": count, "perRealizationRmsNormalization": False,
        "observedSeconds": distribution_report(values),
    }
    return values, report


def butterworth_noise(config):
    """Generate stationary two-pole noise using theoretical covariance scaling.

    With first_order_hold=True, the target RMS applies to the continuous PWL
    interpolation, rather than only its sampled knots. Neither path rescales
    the generated realization by its observed RMS.
    """
    count, seed = count_and_seed(config)
    dt = positive(config["dt_s"], "noise sample interval")
    corner = positive(config["cutoff_hz"], "noise cutoff")
    sigma = positive(config["rms_v"], "noise RMS", zero=True)
    if corner >= 0.5 / dt:
        raise ValueError("noise cutoff must lie below the grid Nyquist frequency")
    hold = bool(config.get("first_order_hold", False))
    b, a = butter(2, corner, fs=1 / dt)
    # Transposed direct-form II state used by scipy.signal.lfilter.
    state_matrix = np.array([[-a[1], 1.0], [-a[2], 0.0]])
    input_vector = np.array([b[1] - a[1] * b[0], b[2] - a[2] * b[0]])
    covariance = solve_discrete_lyapunov(
        state_matrix, np.outer(input_vector, input_vector),
    )
    covariance = (covariance + covariance.T) / 2
    knot_variance = float(covariance[0, 0] + b[0]**2)
    lag_covariance = float((state_matrix @ covariance)[0, 0] + b[0] * input_vector[0])
    hold_variance = (2 * knot_variance + lag_covariance) / 3
    if not all(math.isfinite(x) and x > 0 for x in (knot_variance, hold_variance)):
        raise ValueError("noise filter has invalid stationary variance")
    gain = math.sqrt(hold_variance if hold else knot_variance)
    white_sigma = sigma / gain
    values = np.zeros(count)
    if sigma:
        rng = np.random.default_rng(seed)
        initial = rng.multivariate_normal([0, 0], covariance, check_valid="raise")
        values, _ = lfilter(b, a, rng.normal(size=count) * white_sigma,
                            zi=initial * white_sigma)
    hold_mean = float(np.mean((values[:-1] + values[1:]) / 2))
    hold_second_moment = float(np.mean(
        (values[:-1]**2 + values[:-1] * values[1:] + values[1:]**2) / 3,
    ))
    observed = distribution_report(values)
    report = {
        "kind": "stationary Gaussian two-pole digital Butterworth low-pass",
        "configuredRmsV": sigma, "cutoffHz": corner,
        "sampleIntervalS": dt, "sampleCount": count, "order": 2,
        "seed": seed, "firstOrderHold": hold,
        "stationaryInitialization": True,
        "perRealizationRmsNormalization": False,
        "stationaryGain": gain, "whiteInputRmsV": white_sigma,
        "unitWhiteKnotVariance": knot_variance,
        "unitWhiteLagOneCovariance": lag_covariance,
        "unitWhiteFirstOrderHoldVariance": hold_variance,
        "theoreticalLagOneCorrelation": lag_covariance / knot_variance,
        "theoreticalKnotRmsV": white_sigma * math.sqrt(knot_variance),
        "theoreticalContinuousRmsV": white_sigma * math.sqrt(hold_variance),
        "filterNumerator": b.tolist(), "filterDenominator": a.tolist(),
        "observedRmsV": observed["rms"], "observedAcRmsV": observed["acRms"],
        "observedMeanV": observed["mean"],
        "observedContinuousRmsV": math.sqrt(max(0.0, hold_second_moment)),
        "observedContinuousAcRmsV": math.sqrt(max(0.0, hold_second_moment - hold_mean**2)),
    }
    return values, report


def source_events(config):
    ui = positive(config["ui_s"], "unit interval")
    rise = positive(config["rise_s"], "transition duration")
    delay = positive(config["delay_s"], "launch delay", zero=True)
    end = positive(config["end_s"], "transient end")
    count = config["ui_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 2:
        raise ValueError("UI count must be an integer of at least two")
    peak = positive(config["pj_peak_s"], "periodic jitter peak", zero=True)
    frequency = positive(config["pj_frequency_hz"], "periodic jitter frequency")
    rj, rj_report = ou_jitter({
        "sample_count": count, "seed": config["timing_seed"], "ui_s": ui,
        "corner_hz": config["rj_corner_hz"], "rms_s": config["rj_rms_s"],
    })
    index = np.arange(count)
    nominal = delay + rise / 2 + index * ui
    pj = peak * np.sin(2 * math.pi * frequency * (nominal - nominal[0]))
    crossing = nominal + rj + pj
    start = crossing - rise / 2
    if (not np.isfinite(crossing).all() or start[0] <= 0
            or np.any(np.diff(crossing) <= 0)
            or np.any(start[1:] <= start[:-1] + rise)
            or start[-1] + rise >= end):
        raise ValueError("jitter produces unordered, overlapping, or out-of-range transitions")
    events = {
        "index": index, "nominal_crossing_s": nominal, "crossing_s": crossing,
        "state": 1 - index % 2, "transition_start_s": start,
        "rj_s": rj, "pj_s": pj,
    }
    report = {
        "rj": rj_report, "configuredPeriodicJitterPeakS": peak,
        "periodicJitterHz": frequency, "periodicJitterPhaseRadians": 0,
        "periodicJitterPhaseOriginS": float(nominal[0]),
        "sharedByComplementaryLegs": True,
        "nominalFirstCrossingS": float(nominal[0]),
        "actualFirstCrossingS": float(crossing[0]),
        "transitionDurationS": rise, "eventCount": count,
        "observedTotalJitterSeconds": distribution_report(rj + pj),
        "minimumTransitionSeparationS": float(np.min(np.diff(start))),
        "strictlyOrderedTransitions": True, "transitionOverlap": False,
    }
    return events, report


def source_pwl(events, end_s, rise_s):
    count = len(events["index"])
    times = np.empty(2 * count + 2)
    positive = np.empty_like(times)
    times[0], positive[0] = 0, 0
    times[1:-1:2] = events["transition_start_s"]
    times[2:-1:2] = events["transition_start_s"] + rise_s
    positive[1:-1:2] = 1.5 * (1 - events["state"])
    positive[2:-1:2] = 1.5 * events["state"]
    times[-1], positive[-1] = end_s, positive[-2]
    return times, positive, 1.5 - positive


def write_pwl_sources(path, sources):
    """Write standard SPICE continuation cards while retaining every knot."""
    with Path(path).open("w") as stream:
        stream.write("* Assumed reproducible PWL disturbance; no realization RMS rescaling.\n")
        for source in sources:
            times, values = np.asarray(source["time_s"]), np.asarray(source["values"])
            if (times.ndim != 1 or times.shape != values.shape or len(times) < 2
                    or not np.isfinite(times).all() or not np.isfinite(values).all()
                    or times[0] < 0 or np.any(np.diff(times) <= 0)):
                raise ValueError("PWL knots require finite values and increasing nonnegative times")
            stream.write(f"{source['name']} {source['positive']} {source['negative']} PWL(\n")
            for first in range(0, len(times), 64):
                pairs = " ".join(
                    f"{t:.17e} {v:.17e}"
                    for t, v in zip(times[first:first + 64], values[first:first + 64])
                )
                stream.write("+ " + pairs + "\n")
            stream.write("+ )\n")
