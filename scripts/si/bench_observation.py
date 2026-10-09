"""Apply a declared instrument observation to unchanged native bench captures.

The selected receiver plane passes through a causal two-pole 12 GHz Butterworth
scope response. Independent differential scope noise uses theoretical stationary
scaling, with a shared fixed seed for paired captures on identical time grids.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

from audit_paths import check_report_paths
from bench_stimulus import butterworth_noise


SCOPE_BANDWIDTH_HZ = 12e9
SAMPLE_INTERVAL_S = 2e-12
MINIMUM_WARMUP_S = 10e-9
PLANES = {"pads": (("pad_p_v", "pad_n_v"), "receiver package pads"),
          "die": (("dqs_p_v", "dqs_n_v"), "receiver die")}


def scope_filter(voltage, sample_interval_s):
    """Initialize at the first captured DC level, then use only causal samples."""
    voltage = np.asarray(voltage)
    if voltage.ndim != 1 or len(voltage) < 2 or not np.isfinite(voltage).all():
        raise ValueError("Scope input must be a finite one-dimensional voltage capture")
    if not np.isfinite(sample_interval_s) or not 0 < sample_interval_s < 0.5 / SCOPE_BANDWIDTH_HZ:
        raise ValueError("Scope sampling must resolve its 12 GHz corner below Nyquist")
    sections = butter(2, SCOPE_BANDWIDTH_HZ, fs=1 / sample_interval_s, output="sos")
    return sosfilt(sections, voltage, zi=sosfilt_zi(sections) * voltage[0])[0]


def validate_capture(waveforms, metadata):
    time = waveforms["time_s"]
    if time.ndim != 1 or len(time) < 3 or not np.isfinite(time).all():
        raise ValueError("Observation requires a finite one-dimensional time vector")
    for key, voltage in waveforms.items():
        if voltage.shape != time.shape or not np.isfinite(voltage).all():
            raise ValueError(f"Invalid waveform {key}: finite samples matching time are required")
    sample_ps = metadata.get("sampleTimeStepPs", metadata.get("timeStepPs"))
    if sample_ps is None or not np.isfinite(sample_ps) or not np.isclose(sample_ps, 2, rtol=1e-6, atol=0):
        raise ValueError("Observation requires a uniformly saved 2 ps capture")
    if not np.allclose(np.diff(time), SAMPLE_INTERVAL_S, rtol=1e-6, atol=1e-18):
        raise ValueError("Observation requires increasing uniform 2 ps timestamps without gaps")
    start, stop = metadata["analysisStartNs"] * 1e-9, metadata["analysisStopNs"] * 1e-9
    if not np.isfinite([start, stop]).all() or stop <= start:
        raise ValueError("Observation analysis bounds must be finite and increasing")
    if start - time[0] < MINIMUM_WARMUP_S - SAMPLE_INTERVAL_S:
        raise ValueError("Causal scope filtering requires at least 10 ns of captured pre-analysis warmup")
    if time[-1] < stop - SAMPLE_INTERVAL_S:
        raise ValueError("Capture ends before the requested observation analysis window")
    mask = (time >= start) & (time <= stop)
    if np.count_nonzero(mask) < 3:
        raise ValueError("Observation analysis window has insufficient samples")
    return mask


def observe_capture(source, configuration):
    source = Path(source)
    metadata = json.loads((source / "provenance.json").read_text())
    if "observation" in metadata:
        raise ValueError("Input is already an observation; supply the unchanged native capture")
    with np.load(source / "waveforms.npz") as saved:
        waveforms = {key: saved[key] for key in saved.files}
    mask = validate_capture(waveforms, metadata)
    plane = configuration.get("plane", "pads")
    if plane not in PLANES:
        raise ValueError("Observation plane must be pads or die")
    keys, plane_name = PLANES[plane]
    for key in ("tx_p_v", "tx_n_v", "dqs_p_v", "dqs_n_v", *keys):
        if key not in waveforms:
            raise ValueError(f"Observation capture lacks required waveform {key}")
    rms_mv, seed = configuration.get("scope_noise_mv", 2), configuration.get("seed", 50703)
    if not np.isfinite(rms_mv) or rms_mv < 0:
        raise ValueError("Scope noise RMS must be finite and nonnegative")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("Scope noise seed must be a nonnegative integer")
    noise, noise_report = butterworth_noise({
        "dt_s": SAMPLE_INTERVAL_S, "cutoff_hz": SCOPE_BANDWIDTH_HZ,
        "rms_v": rms_mv * 1e-3, "seed": seed, "sample_count": len(waveforms["time_s"]),
        "first_order_hold": False,
    })
    positive = scope_filter(waveforms[keys[0]], SAMPLE_INTERVAL_S)
    negative = scope_filter(waveforms[keys[1]], SAMPLE_INTERVAL_S)
    observed = dict(waveforms)
    observed.update({"raw_dqs_p_v": waveforms["dqs_p_v"], "raw_dqs_n_v": waveforms["dqs_n_v"],
                     "unfiltered_plane_p_v": waveforms[keys[0]], "unfiltered_plane_n_v": waveforms[keys[1]],
                     "scope_filtered_p_v": positive, "scope_filtered_n_v": negative,
                     "scope_noise_v": noise, "dqs_p_v": positive + noise / 2,
                     "dqs_n_v": negative - noise / 2})
    result = copy.deepcopy(metadata)
    result["kind"] = "simulated instrument observation of " + metadata.get("kind", "native bench capture")
    result["signoff"] = False
    result["observation"] = {
        "plane": plane_name, "planeKeys": list(keys), "scopeBandwidthGHz": 12,
        "scopeResponse": "causal digital two-pole Butterworth; bilinear transform prewarped at 12 GHz",
        "scopeFilterOrder": 2, "scopeNoiseRmsMv": rms_mv,
        "noiseDefinition": "differential voltage; +/-noise/2 added to filtered legs",
        "scopeNoiseRmsDefinition": "theoretical stationary RMS of final differential scope noise after 12 GHz shaping",
        "noiseScaling": "theoretical stationary filter variance; no finite-realization renormalization",
        "seed": seed, "pairedNoise": "same realization only for the same seed and identical physical timestamp grid",
        "noiseGenerationGrid": {"startNs": float(waveforms["time_s"][0] * 1e9),
                                "stopNs": float(waveforms["time_s"][-1] * 1e9),
                                "sampleIntervalPs": 2, "sampleCount": len(waveforms["time_s"]),
                                "independentOfElectricalMaxdt": True,
                                "changedSampling": "other sampling grids are rejected; no pointwise realization equivalence is claimed"},
        "causal": True, "sampleTimeStepPs": 2,
        "warmupNs": float((metadata["analysisStartNs"] * 1e-9 - waveforms["time_s"][0]) * 1e9),
        "signalInitialization": "steady state at first captured leg voltage; full captured warmup is filtered",
        "samplingJitterRmsPs": 0, "supplies": "ideal supplies as in the native bench",
        "phaseHandling": "fixed nominal clock; one receiver mean phase may be estimated; no individual edge alignment",
        "sourceCapture": str(source.resolve()),
        "sourceWaveformsSha256": hashlib.sha256((source / "waveforms.npz").read_bytes()).hexdigest(),
        "sourceProvenanceSha256": hashlib.sha256((source / "provenance.json").read_bytes()).hexdigest(),
        "noise": noise_report,
        "measuredAnalysisNoise": {"meanMv": float(noise[mask].mean() * 1e3),
                                  "acRmsMv": float(noise[mask].std() * 1e3),
                                  "rmsMv": float(np.sqrt(np.mean(noise[mask] ** 2)) * 1e3),
                                  "maximumAbsoluteMv": float(abs(noise[mask]).max() * 1e3)},
        "analysisSamples": int(np.count_nonzero(mask)),
        "analysisWindowUiCount": (metadata["analysisStopNs"] - metadata["analysisStartNs"]) * 1e-9 * metadata["rateMTs"] * 1e6,
        "rawVersusObserved": "native fields retained; raw_dqs_* preserves circuit die voltage; dqs_* is the rendered instrument observation",
        "signoff": False,
    }
    result.setdefault("limitations", []).extend([
        "Instrument processing is a simulated nonloading 12 GHz response and independent additive voltage noise, not a hardware measurement.",
        "No scope sampling, trigger or clock-recovery jitter is modeled; folding uses a fixed nominal clock or one mean phase.",
        "Scope noise is separate from the physical source and circuit noise budgets retained in provenance.",
    ])
    return observed, result


def write_observation(source, configuration):
    source, destination = Path(source).resolve(), Path(configuration["out"]).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Observation output and supplied capture directories must not overlap")
    outputs = [destination / filename for filename in ("waveforms.npz", "provenance.json", "stimulus-events.csv")]
    inputs = [path for path in source.iterdir() if path.is_file()]
    check_report_paths(outputs, inputs)
    if destination.is_dir() and any(path.name not in {"waveforms.npz", "provenance.json", "stimulus-events.csv"}
                                   for path in destination.iterdir()):
        raise ValueError("Observation output contains unrelated files; select a dedicated output directory")
    observed, metadata = observe_capture(source, configuration)
    destination.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination / "waveforms.npz", **observed)
    metadata["observation"]["waveformsSha256"] = hashlib.sha256((destination / "waveforms.npz").read_bytes()).hexdigest()
    events = source / "stimulus-events.csv"
    if events.is_file():
        (destination / events.name).write_bytes(events.read_bytes())
        metadata["observation"]["sourceStimulusEventsSha256"] = hashlib.sha256(events.read_bytes()).hexdigest()
    else:
        (destination / events.name).unlink(missing_ok=True)
    (destination / "provenance.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    return metadata["observation"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="unchanged native bench capture directory")
    parser.add_argument("--out", required=True)
    parser.add_argument("--plane", choices=tuple(PLANES), default="pads")
    parser.add_argument("--scope-noise-mv", type=float, default=2, help="differential instrument noise RMS; 0 is the clean observation")
    parser.add_argument("--seed", type=int, default=50703, help="shared fixed seed for paired observations")
    arguments = parser.parse_args()
    try:
        report = write_observation(arguments.capture, vars(arguments))
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
