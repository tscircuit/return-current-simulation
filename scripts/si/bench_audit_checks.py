"""Read-only finite-record checks for assumed bench and instrument captures.

Exact input identities are checks. PSD, block scatter and noisy eye extrema
are finite-record diagnostics, without a cycle-repeat settling or BER claim.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from scipy.signal import welch

from bench_observation import scope_filter, validate_capture
from eye_comparison import eye_diagnostics, source_events, waveform_window
from frequency_audit import load_capture


INPUT_ARTIFACTS = ("transmitter-stimulus.sp", "receiver-noise.sp", "stimulus-events.csv",
                   "source-timing.npz", "commanded-noise.npz")
spec = importlib.util.spec_from_file_location("bench_waveform_analysis", Path(__file__).resolve().parents[1] / "analyze-ddr-waveforms.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def statistics(values):
    return {"samples": len(values), "mean": float(np.mean(values)), "rms": float(np.sqrt(np.mean(values**2))),
            "acRms": float(np.std(values)), "maximumAbsolute": float(abs(values).max())}


def signal_statistics(signal, frequency):
    time, voltage = signal
    basis = np.column_stack([np.cos(2 * np.pi * frequency * time),
                             np.sin(2 * np.pi * frequency * time), np.ones(len(time))])
    cosine, sine, offset = np.linalg.lstsq(basis, voltage, rcond=None)[0]
    return {**statistics(voltage), "halfPeakToPeakV": float(np.ptp(voltage) / 2),
            "fundamentalPeakV": float(np.hypot(cosine, sine)),
            "fundamentalPhaseRad": float(np.angle(cosine - 1j * sine)), "fittedDcOffsetV": float(offset)}


def pwl_statistics(signal, bounds):
    """Integrate the actual continuous linear waveform, clipping boundary segments."""
    time, voltage = signal
    start, stop = bounds
    if start < time[0] or stop > time[-1] or stop <= start:
        raise ValueError("Commanded PWL noise does not cover the analysis window")
    knots = np.concatenate([[start], time[(time > start) & (time < stop)], [stop]])
    sampled = np.interp(knots, time, voltage)
    widths = np.diff(knots)
    mean = float(np.sum(widths * (sampled[:-1] + sampled[1:]) / 2) / (stop - start))
    second = float(np.sum(widths * (sampled[:-1]**2 + sampled[:-1] * sampled[1:] + sampled[1:]**2) / 3) / (stop - start))
    return {"mean": mean, "rms": np.sqrt(second), "acRms": np.sqrt(max(0, second - mean**2)),
            "maximumAbsolute": float(abs(sampled).max()), "definition": "continuous PWL segment integral"}


def psd_diagnostics(values, configuration):
    dt, corner = configuration["dt_s"], configuration["corner_hz"]
    segments = min(len(values), max(16, len(values) // 10))
    frequency, observed = welch(values, fs=1 / dt, window="hann", nperseg=segments,
                                noverlap=0, detrend=False)
    z = np.exp(-2j * np.pi * frequency * dt)
    numerator = sum(coefficient * z**index for index, coefficient in enumerate(configuration["b"]))
    denominator = sum(coefficient * z**index for index, coefficient in enumerate(configuration["a"]))
    expected = 2 * configuration["white_rms"]**2 * dt * abs(numerator / denominator)**2
    expected[0] /= 2
    if np.isclose(frequency[-1], 0.5 / dt):
        expected[-1] /= 2
    below = frequency <= corner
    observed_power, expected_power = float(observed.sum()), float(expected.sum())
    return {"method": "Hann Welch, ten nonoverlapping segments, no detrending; broad-band powers only",
            "segmentSamples": segments, "frequencyResolutionHz": float(frequency[1] - frequency[0]),
            "observedIntegratedPower": observed_power * float(frequency[1] - frequency[0]),
            "expectedIntegratedPower": expected_power * float(frequency[1] - frequency[0]),
            "powerRatio": observed_power / expected_power if expected_power else None,
            "observedBelowCornerPowerFraction": float(observed[below].sum() / observed_power) if observed_power else None,
            "expectedBelowCornerPowerFraction": float(expected[below].sum() / expected_power) if expected_power else None,
            "interpretation": "finite-record consistency diagnostic; individual bins and these ratios are not pass/fail limits"}


def rj_diagnostics(values, metadata):
    ui, sigma = 1 / (metadata["rateMTs"] * 1e6), metadata["jitter"]["configuredInputRjRmsPs"] * 1e-12
    alpha = np.exp(-2 * np.pi * metadata["jitter"]["randomJitterCornerHz"] * ui)
    lags = []
    for lag in (1, 2, 5):
        covariance = float(np.mean(values[:-lag] * values[lag:]))
        lags.append({"lagUi": lag, "measuredCovarianceS2": covariance,
                     "expectedCovarianceS2": float(sigma**2 * alpha**lag)})
    innovations = (values[1:] - alpha * values[:-1]) / (sigma * np.sqrt(1 - alpha**2)) if sigma else None
    return {"lagCovariance": lags, "normalizedInnovations": statistics(innovations) if innovations is not None else None,
            "innovationLagOneCorrelation": float(np.corrcoef(innovations[:-1], innovations[1:])[0, 1]) if innovations is not None else None,
            "psd": psd_diagnostics(values, {"dt_s": ui, "corner_hz": metadata["jitter"]["randomJitterCornerHz"],
                                          "b": [1], "a": [1, -alpha], "white_rms": sigma * np.sqrt(1 - alpha**2)})}


def circuit_identity(path):
    """Omit only the declared channel substitution and electrical maximum step."""
    retained, includes, routed, reference, transients = [], 0, 0, 0, 0
    for line in Path(path).read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(".include ") and stripped not in ('.include "transmitter-stimulus.sp"', '.include "receiver-noise.sp"'):
            includes += 1
        elif stripped == "Xpcb csrc cload pcb_channel":
            routed += 1
        elif stripped == "Tref csrc 0 cload 0 Z0=100 TD=.4n":
            reference += 1
        elif stripped.startswith("tran "):
            tokens = stripped.split()
            if len(tokens) != 5:
                raise ValueError("Unexpected bench transient command")
            retained.append(" ".join(tokens[:-1] + ["<electrical-max-step>"]))
            transients += 1
        else:
            retained.append(line)
    if (includes, routed, reference) not in ((1, 1, 0), (0, 0, 1)) or transients != 1:
        raise ValueError("Unexpected bench channel selector or transient topology")
    return "\n".join(retained)


def physical_input_checks(left, right):
    checks = [{"check": filename + " exact input bytes", "pass": file_hash(left / filename) == file_hash(right / filename)}
              for filename in INPUT_ARTIFACTS]
    checks.append({"check": "all nonchannel circuit lines identical, excluding only electrical maxdt",
                   "pass": circuit_identity(left / "simulation.cir") == circuit_identity(right / "simulation.cir")})
    metadata = [json.loads((path / "provenance.json").read_text()) for path in (left, right)]
    for key in ("source", "noise", "jitter", "ioModels", "analysisStartNs", "analysisStopNs",
                "rateMTs", "sampleTimeStepPs", "captureStartNs", "integrationMethod"):
        checks.append({"check": key + " matched physical configuration", "pass": metadata[0][key] == metadata[1][key]})
    if metadata[0]["channel"]["model"] == metadata[1]["channel"]["model"]:
        checks.append({"check": "same-channel model coefficients hash", "pass": metadata[0]["channel"]["modelSha256"] == metadata[1]["channel"]["modelSha256"]})
    return checks


def scope_pair_checks(left, right):
    with np.load(left / "waveforms.npz") as coarse, np.load(right / "waveforms.npz") as paired:
        return [{"check": "identical physical scope timestamp grid", "pass": np.array_equal(coarse["time_s"], paired["time_s"])},
                {"check": "identical additive scope-noise realization", "pass": np.array_equal(coarse["scope_noise_v"], paired["scope_noise_v"])}]


def budget_window(context, bounds):
    raw, observed, timing, command, metadata = (context[key] for key in ("raw", "observed", "timing", "command", "metadata"))
    start, stop = bounds
    samples = (raw["time_s"] >= start) & (raw["time_s"] < stop)
    events = (timing["nominal_crossing_s"] >= start) & (timing["nominal_crossing_s"] < stop)
    rj, pj = timing["rj_s"][events], timing["pj_s"][events]
    frequency = metadata["strobeGHz"] * 1e9
    return {"startNs": start * 1e9, "stopNs": stop * 1e9,
            "sourceRjPs": statistics(rj * 1e12), "sourcePjPs": statistics(pj * 1e12),
            "combinedSourceTimingPs": statistics((rj + pj) * 1e12),
            "commandedSeriesNoiseV": pwl_statistics((command["time_s"], command["differential_v"]), bounds),
            "observedSeriesNoiseV": statistics((raw["pad_p_v"] - raw["pad_n_v"] - raw["channel_output_v"])[samples]),
            "scopeNoiseV": statistics(observed["scope_noise_v"][samples]),
            "rawPadDifferentialV": signal_statistics((raw["time_s"][samples], (raw["pad_p_v"] - raw["pad_n_v"])[samples]), frequency),
            "observedPadDifferentialV": signal_statistics((observed["time_s"][samples], (observed["dqs_p_v"] - observed["dqs_n_v"])[samples]), frequency)}


def audit_case(paths):
    metadata, raw = load_capture(paths["raw"])
    observed_metadata, observed = load_capture(paths["observed"])
    validate_capture(raw, metadata)
    validate_capture(observed, observed_metadata)
    with np.load(paths["raw"] / "source-timing.npz") as saved:
        timing = {key: saved[key] for key in saved.files}
    with np.load(paths["raw"] / "commanded-noise.npz") as saved:
        command = {key: saved[key] for key in saved.files}
    scope = observed_metadata["observation"]
    checks = [{"check": "package-pad observation plane", "pass": scope["plane"] == "receiver package pads"},
              {"check": "raw/observed timestamp identity", "pass": np.array_equal(raw["time_s"], observed["time_s"])},
              {"check": "observation source waveform hash", "pass": scope["sourceWaveformsSha256"] == file_hash(paths["raw"] / "waveforms.npz")},
              {"check": "observation source provenance hash", "pass": scope["sourceProvenanceSha256"] == file_hash(paths["raw"] / "provenance.json")},
              {"check": "observation waveform hash", "pass": scope["waveformsSha256"] == file_hash(paths["observed"] / "waveforms.npz")},
              {"check": "declared causal 12 GHz observation", "pass": scope["scopeBandwidthGHz"] == 12 and scope["causal"]},
              {"check": "physical noise/jitter budgets preserved", "pass": metadata["noise"] == observed_metadata["noise"] and metadata["jitter"] == observed_metadata["jitter"]}]
    for key in ("analysisStartNs", "analysisStopNs", "rateMTs", "sampleTimeStepPs", "electricalTimeStepPs", "nominalSourcePhasePs", "source", "ioModels", "channel"):
        checks.append({"check": key + " preserved in observation", "pass": metadata[key] == observed_metadata[key]})
    for key, original in (("raw_dqs_p_v", "dqs_p_v"), ("raw_dqs_n_v", "dqs_n_v"), ("pad_p_v", "pad_p_v"), ("pad_n_v", "pad_n_v")):
        checks.append({"check": key + " raw circuit samples unchanged", "pass": np.array_equal(observed[key], raw[original])})
    for filename, expected in metadata["inputFilesSha256"].items():
        checks.append({"check": filename + " recorded input hash", "pass": file_hash(paths["raw"] / filename) == expected})
    for leg, sign in (("p", 1), ("n", -1)):
        checks.append({"check": leg + " unfiltered observation plane equals raw package pad",
                       "pass": np.array_equal(observed[f"unfiltered_plane_{leg}_v"], raw[f"pad_{leg}_v"])})
        reconstructed = scope_filter(raw[f"pad_{leg}_v"], 2e-12)
        reconstruction_error = float(abs(reconstructed - observed[f"scope_filtered_{leg}_v"]).max())
        checks.append({"check": leg + " stored scope response matches declared causal filter",
                       "pass": reconstruction_error <= 1e-12, "maximumDifferenceV": reconstruction_error,
                       "numericalToleranceV": 1e-12})
        checks.append({"check": leg + " observed leg equals filtered plane plus scope noise",
                       "pass": np.array_equal(observed[f"dqs_{leg}_v"], observed[f"scope_filtered_{leg}_v"] + sign * observed["scope_noise_v"] / 2)})
    bounds = metadata["analysisStartNs"] * 1e-9, metadata["analysisStopNs"] * 1e-9
    context = {"metadata": metadata, "raw": raw, "observed": observed, "timing": timing, "command": command}
    edges = np.linspace(*bounds, 11)
    events = (timing["nominal_crossing_s"] >= bounds[0]) & (timing["nominal_crossing_s"] < bounds[1])
    selected = (raw["time_s"] >= bounds[0]) & (raw["time_s"] < bounds[1])
    phase = 2 * np.pi * metadata["jitter"]["periodicJitterFrequencyHz"] * (timing["nominal_crossing_s"][events] - timing["nominal_crossing_s"][0])
    pj_basis = np.column_stack([np.sin(phase), np.cos(phase), np.ones(len(phase))])
    sine, cosine, offset = np.linalg.lstsq(pj_basis, timing["pj_s"][events], rcond=None)[0]
    source_noise = metadata["receiverSeriesNoiseReport"]
    scope_noise = scope["noise"]
    noise_mask = (command["time_s"] >= bounds[0]) & (command["time_s"] < bounds[1])
    psds = {}
    for label, values, report in (("commandedNoiseKnots", command["differential_v"][noise_mask], source_noise),
                                   ("scopeNoiseSamples", observed["scope_noise_v"][selected], scope_noise)):
        psds[label] = psd_diagnostics(values, {"dt_s": report["sampleIntervalS"], "corner_hz": report["cutoffHz"],
                                              "b": report["filterNumerator"], "a": report["filterDenominator"], "white_rms": report["whiteInputRmsV"]})
    return {"rawCapture": str(paths["raw"]), "observationCapture": str(paths["observed"]), "checks": checks,
            "electricalTimeStepPs": metadata["electricalTimeStepPs"], "savedSampleTimeStepPs": metadata["sampleTimeStepPs"],
            "analysisDurationNs": metadata["analysisStopNs"] - metadata["analysisStartNs"],
            "analysisUiCount": (bounds[1] - bounds[0]) * metadata["rateMTs"] * 1e6,
            "configuredBudgets": {"sourceRjRmsPs": metadata["jitter"]["configuredInputRjRmsPs"],
                                  "sourcePjPeakPs": metadata["jitter"]["configuredPeriodicJitterPeakPs"],
                                  "combinedSourceTimingRmsPs": float(np.hypot(metadata["jitter"]["configuredInputRjRmsPs"], metadata["jitter"]["configuredPeriodicJitterPeakPs"] / np.sqrt(2))),
                                  "commandedContinuousSeriesNoiseRmsMv": metadata["noise"]["configuredRmsMv"],
                                  "scopeSampleNoiseRmsMv": scope["scopeNoiseRmsMv"]},
            "wholeAnalysis": budget_window(context, bounds),
            "blocks": [budget_window(context, (left, right)) for left, right in zip(edges[:-1], edges[1:])],
            "sourceRjConsistency": rj_diagnostics(timing["rj_s"][events], metadata),
            "sourcePjFit": {"frequencyHz": metadata["jitter"]["periodicJitterFrequencyHz"],
                            "peakPs": float(np.hypot(sine, cosine) * 1e12), "phaseRad": float(np.arctan2(cosine, sine)) if np.hypot(sine, cosine) else None,
                            "samples": len(phase), "residualRmsPs": float(np.sqrt(np.mean((timing["pj_s"][events] - pj_basis @ [sine, cosine, offset])**2)) * 1e12)},
            "noisePsdConsistency": psds,
            "commandedNoisePsdDefinition": "PSD is of saved knots; continuous PWL additionally has sinc^4 interpolation power response; its RMS is integrated separately"}


def eye_metrics(capture):
    metadata, waveforms = load_capture(capture)
    waveform = np.column_stack([waveforms[key] for key in ("time_s", "tx_p_v", "tx_n_v", "dqs_p_v", "dqs_n_v")])
    report, _ = eye_diagnostics(waveform_window(waveform, metadata), metadata, analysis, events=source_events(capture))
    return report


def refinement_comparison(coarse, refined):
    metadata, original = load_capture(coarse)
    fine_metadata, fine = load_capture(refined)
    start, stop = metadata["analysisStartNs"] * 1e-9, metadata["analysisStopNs"] * 1e-9
    time = original["time_s"][(original["time_s"] >= start) & (original["time_s"] < stop)]
    if time[0] < fine["time_s"][0] or time[-1] > fine["time_s"][-1]:
        raise ValueError("Refined observation does not cover the same absolute timestamps")
    first = np.interp(time, original["time_s"], original["dqs_p_v"] - original["dqs_n_v"])
    second = np.interp(time, fine["time_s"], fine["dqs_p_v"] - fine["dqs_n_v"])
    frequency = metadata["strobeGHz"] * 1e9
    statistics_pair = [signal_statistics((time, voltage), frequency) for voltage in (first, second)]
    phase_difference = float(np.angle(np.exp(1j * (statistics_pair[1]["fundamentalPhaseRad"] - statistics_pair[0]["fundamentalPhaseRad"]))))
    eyes = [eye_metrics(capture) for capture in (coarse, refined)]
    differences = {key: eyes[1][key] - eyes[0][key] if eyes[0][key] is not None and eyes[1][key] is not None else None
                   for key in ("finiteCaptureEyeHeightV", "commonOpeningAt200mVThresholdPs", "nominalThresholdFailures")}
    return {"comparison": "observed receiver package pads at the same absolute time, no independent phase alignment",
            "electricalMaxStepPs": [metadata["electricalTimeStepPs"], fine_metadata["electricalTimeStepPs"]],
            "savedSampleTimeStepPs": [metadata["sampleTimeStepPs"], fine_metadata["sampleTimeStepPs"]],
            "waveformDifferenceV": statistics(second - first), "observedPadStatistics": statistics_pair,
            "observedAcRmsDifferenceV": statistics_pair[1]["acRms"] - statistics_pair[0]["acRms"],
            "observedAcRmsRelativeChange": statistics_pair[1]["acRms"] / statistics_pair[0]["acRms"] - 1 if statistics_pair[0]["acRms"] else None,
            "fundamentalPeakRelativeChange": statistics_pair[1]["fundamentalPeakV"] / statistics_pair[0]["fundamentalPeakV"] - 1 if statistics_pair[0]["fundamentalPeakV"] else None,
            "fundamentalPhaseDifferenceRad": phase_difference,
            "phaseEquivalentTimeDifferencePs": phase_difference / (2 * np.pi * frequency) * 1e12,
            "eyeMetrics": eyes, "eyeMetricDifferences": differences}


def capture_paths(root, routed_only=False):
    routes = ("routed",) if routed_only else ("routed", "reference")
    cases = {f"{budget}-{route}": {"raw": root / "captures" / f"5ghz-{budget}-{route}",
                                    "observed": root / "observations" / f"5ghz-{budget}-{route}"}
             for budget in ("clean", "noisy") for route in routes}
    cases["noisy-routed-refined"] = {"raw": root / "checks/5ghz-noisy-routed-0.25ps",
                                      "observed": root / "checks/5ghz-noisy-routed-0.25ps-observed"}
    return cases


def audit_bench(root, routed_only=False):
    paths = capture_paths(Path(root).resolve(), routed_only)
    cases = {name: audit_case(captures) for name, captures in paths.items()}
    pairs = {}
    comparisons = [("noisy routed electrical refinement", "noisy-routed", "noisy-routed-refined")]
    if not routed_only:
        comparisons = [("clean routed/reference", "clean-routed", "clean-reference"),
                       ("noisy routed/reference", "noisy-routed", "noisy-reference")] + comparisons
    for label, left, right in comparisons:
        pairs[label] = physical_input_checks(paths[left]["raw"], paths[right]["raw"]) + scope_pair_checks(paths[left]["observed"], paths[right]["observed"])
    if routed_only:
        pairs["clean/noisy routed circuit identity"] = [{
            "check": "same clean/noisy circuit lines; disturbances are in external PWL files",
            "pass": circuit_identity(paths["clean-routed"]["raw"] / "simulation.cir") == circuit_identity(paths["noisy-routed"]["raw"] / "simulation.cir"),
        }]
    checks = [check for case in cases.values() for check in case["checks"]] + [check for pair in pairs.values() for check in pair]
    return {"pass": all(check["pass"] for check in checks), "signoff": False, "cases": cases, "pairedIdentityChecks": pairs,
            "observedPadRefinement": refinement_comparison(paths["noisy-routed"]["observed"], paths["noisy-routed-refined"]["observed"]),
            "limitations": ["Input identities are deterministic checks; budget/PSD/block consistency remains finite-record diagnostics.",
                            "Noisy cycle differences are not interpreted as settling or attenuation.",
                            "One mean nominal clock phase is allowed; individual edges are not aligned, sorted or clipped.",
                            "Finite noisy eye extrema do not establish DDR compliance, BER or rare-event tails."]}


