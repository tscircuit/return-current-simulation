"""Assumed noisy bench companion using a virtual ideal differential source.

This does not represent an AM3352 switching at 5 GHz or a measured bench eye.
Physical disturbances and probe loading precede the separate scope observation.
"""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np


def local_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stimulus = local_module("bench_stimulus.py", "_bench_stimulus")
paths = local_module("audit_paths.py", "_bench_paths")
# This isolated module instance reuses the exact original validation code.
# Its local capture schema includes receiver pads; the original file and
# ordinary stress process retain their seven-column schema.
native = local_module("stress-dqs-bandwidth.py", "_bench_native_validation")
CAPTURE_KEYS = (*native.CAPTURE_KEYS, "pad_p_v", "pad_n_v")
native.CAPTURE_KEYS = CAPTURE_KEYS
OUTPUT_FILES = (
    "simulation.cir", "transmitter-stimulus.sp", "receiver-noise.sp",
    "stimulus-events.csv", "source-timing.npz", "commanded-noise.npz",
    "ngspice.log", "adaptive.dat", "waveforms.dat", "waveforms.npz",
    "provenance.json", "source-report.json", "receiver-noise-report.json", "probe-report.json",
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("channel", "ngspice", "out"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--strobe-ghz", type=float, default=5)
    parser.add_argument("--dt-ps", type=float, default=0.5)
    parser.add_argument("--sample-ps", type=float, default=2)
    parser.add_argument("--ui-count", type=int, default=35000)
    parser.add_argument("--capture-start-ns", type=float, default=2990)
    parser.add_argument("--analysis-start-ns", type=float, default=3000)
    parser.add_argument("--analysis-stop-ns", type=float, default=3500)
    parser.add_argument("--matched-reference", action="store_true")
    parser.add_argument("--channel-max-ghz", type=float, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--method", choices=("trap", "gear"), default="trap")
    parser.add_argument("--rj-ps", type=float, default=3)
    parser.add_argument("--rj-corner-mhz", type=float, default=500)
    parser.add_argument("--pj-ps", type=float, default=3)
    parser.add_argument("--pj-mhz", type=float, default=100)
    parser.add_argument("--noise-mv", type=float, default=5)
    parser.add_argument("--noise-corner-ghz", type=float, default=1)
    parser.add_argument("--noise-grid-ps", type=float, default=10)
    parser.add_argument("--probe-pf", type=float, default=0.2)
    parser.add_argument("--timing-seed", type=int, default=50701)
    parser.add_argument("--noise-seed", type=int, default=50702)
    return parser


def derive_timing(args):
    timing = native.derive_timing(
        args.strobe_ghz, args.dt_ps, args.ui_count,
        analysis_window={"start_ns": args.analysis_start_ns, "stop_ns": args.analysis_stop_ns},
    )
    sample = stimulus.positive(args.sample_ps, "saved sample interval") * 1e-12
    capture = stimulus.positive(args.capture_start_ns, "capture start", zero=True) * 1e-9
    if sample > timing["ui_s"] / 16 or sample < timing["dt_s"]:
        raise ValueError("saved sampling must resolve the UI and be no finer than the electrical step")
    if capture < 0 or capture > timing["analysis_start_s"]:
        raise ValueError("capture must start no later than analysis")
    if timing["analysis_start_s"] - capture < 1e-9:
        raise ValueError("capture requires at least 1 ns of pre-analysis history for observation")
    for key in ("rj_ps", "pj_ps", "noise_mv", "probe_pf"):
        stimulus.positive(getattr(args, key), key, zero=True)
    for key in ("rj_corner_mhz", "pj_mhz", "noise_corner_ghz", "noise_grid_ps",
                "channel_max_ghz", "timeout_seconds"):
        stimulus.positive(getattr(args, key), key)
    if args.noise_corner_ghz * 1e9 >= 0.5 / (args.noise_grid_ps * 1e-12):
        raise ValueError("noise corner must be below the noise-grid Nyquist frequency")
    for seed in (args.timing_seed, args.noise_seed):
        if seed < 0:
            raise ValueError("seeds must be nonnegative")
    timing.update({"electrical_dt_s": timing["dt_s"], "sample_dt_s": sample,
                   "capture_start_s": capture})
    return timing


def build_netlist(args, timing):
    network = native.passive_network(args.channel, args.matched_reference)
    network = network.replace("Vnp rxp rxp0 0\n", "").replace("Vnn rxn rxn0 0\n", "")
    t = timing
    vectors = "v(txp) v(txn) v(rdiep) v(rdien) v(csrc) v(cload) v(rxp) v(rxn)"
    return f"""Assumed noisy bench companion: virtual ideal differential source
.include "transmitter-stimulus.sp"
.include "receiver-noise.sp"
Rsourcep srcp diep 50
Rsourcen srcn dien 50
{network}
* Identical ideal probe loading in clean and noisy cases.
Cprobep rxp 0 {args.probe_pf * 1e-12:.17e}
Cproben rxn 0 {args.probe_pf * 1e-12:.17e}
.options reltol=1e-5 abstol=1e-11 vntol=1e-7 method={args.method} maxord=2 trtol=3
.control
set wr_vecnames
set wr_singlescale
set numdgt=17
* Saved grid is independent of the electrical integration maximum step.
tran {t['sample_dt_s']:.17e} {t['end_s']:.17e} {t['capture_start_s']:.17e} {t['electrical_dt_s']:.17e}
wrdata adaptive.dat {vectors}
linearize {vectors}
wrdata waveforms.dat {vectors}
echo {native.COMPLETION_MARKER}
quit
.endc
.end
"""


def timing_inputs(args, timing):
    events, report = stimulus.source_events({
        "ui_s": timing["ui_s"], "rise_s": timing["rise_s"], "delay_s": timing["delay_s"],
        "ui_count": args.ui_count + 8, "end_s": timing["end_s"],
        "rj_rms_s": args.rj_ps * 1e-12, "rj_corner_hz": args.rj_corner_mhz * 1e6,
        "pj_peak_s": args.pj_ps * 1e-12, "pj_frequency_hz": args.pj_mhz * 1e6,
        "timing_seed": args.timing_seed,
    })
    selected = ((events["nominal_crossing_s"] >= timing["analysis_start_s"])
                & (events["nominal_crossing_s"] < timing["analysis_stop_s"]))
    report["analysisWindow"] = {
        "eventCount": int(np.count_nonzero(selected)),
        "randomJitterSeconds": stimulus.distribution_report(events["rj_s"][selected]),
        "periodicJitterSeconds": stimulus.distribution_report(events["pj_s"][selected]),
        "totalJitterSeconds": stimulus.distribution_report((events["rj_s"] + events["pj_s"])[selected]),
    }
    report["theoreticalCombinedRmsS"] = math.sqrt((args.rj_ps * 1e-12)**2 + (args.pj_ps * 1e-12)**2 / 2)
    return events, report


def write_inputs(out, args, timing):
    events, source_report = timing_inputs(args, timing)
    knots, pos, neg = stimulus.source_pwl(events, timing["end_s"], timing["rise_s"])
    stimulus.write_pwl_sources(out / "transmitter-stimulus.sp", [
        {"name": "Vpositive", "positive": "srcp", "negative": "0", "time_s": knots, "values": pos},
        {"name": "Vnegative", "positive": "srcn", "negative": "0", "time_s": knots, "values": neg},
    ])
    dt = args.noise_grid_ps * 1e-12
    count = math.ceil(timing["end_s"] / dt) + 1
    noise_times = np.arange(count) * dt
    noise, noise_report = stimulus.butterworth_noise({
        "dt_s": dt, "cutoff_hz": args.noise_corner_ghz * 1e9,
        "rms_v": args.noise_mv * 1e-3, "seed": args.noise_seed,
        "sample_count": count, "first_order_hold": True,
    })
    stimulus.write_pwl_sources(out / "receiver-noise.sp", [
        {"name": "Vnp", "positive": "rxp", "negative": "rxp0", "time_s": noise_times, "values": noise / 2},
        {"name": "Vnn", "positive": "rxn", "negative": "rxn0", "time_s": noise_times, "values": -noise / 2},
    ])
    np.savetxt(out / "stimulus-events.csv", np.column_stack([
        events["index"], events["crossing_s"], events["state"], events["transition_start_s"],
    ]), delimiter=",", fmt=["%d", "%.17e", "%d", "%.17e"],
        header="ui_index,event_time_s,positive_state,transition_start_s", comments="")
    np.savez_compressed(out / "source-timing.npz", **events)
    np.savez_compressed(out / "commanded-noise.npz", time_s=noise_times, differential_v=noise)
    noise_report.update({
        "location": "differential series voltage sources at receiver package pins, split +/- half",
        "budgetMeaning": "commanded differential series-source RMS after shaping; not guaranteed total pad or die noise RMS",
        "gridEndS": float(noise_times[-1]),
    })
    return source_report, noise_report


def observed_reports(waveforms, timing):
    selected = ((waveforms[:, 0] >= timing["analysis_start_s"])
                & (waveforms[:, 0] < timing["analysis_stop_s"]))
    values = waveforms[selected]
    pad = values[:, 7] - values[:, 8]
    die = values[:, 3] - values[:, 4]
    # The balanced receiver source imposes pad differential = cload + series noise.
    series_noise = pad - values[:, 6]
    return {
        "samples": len(values), "observedSeriesSourceVolts": stimulus.distribution_report(series_noise),
        "totalPadDifferentialVolts": stimulus.distribution_report(pad),
        "totalDieDifferentialVolts": stimulus.distribution_report(die),
        "totalWaveformStatisticsAreNotIsolatedNoiseBudgets": True,
    }


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def solver_identity(binary):
    resolved = Path(shutil.which(binary) or binary).resolve()
    identity = {"path": str(resolved), "sha256": file_hash(resolved)}
    build_file = resolved.parent.parent / "build-provenance.json"
    if build_file.is_file():
        build = json.loads(build_file.read_text())
        if build.get("optimizedBinarySha256") == identity["sha256"]:
            identity.update({"buildProvenanceFileSha256": file_hash(build_file),
                             "buildProvenance": build,
                             "patchSha256": build.get("patchSha256")})
    return identity


def provenance(args, timing, out, source_report, noise_report, adaptive, elapsed, version):
    metadata = native.provenance(args, timing, (out / "simulation.cir").read_text(),
                                 Path(args.channel).read_bytes(), elapsed, version)
    metadata.update({
        "kind": "ngspice assumed noisy bench companion with virtual ideal source",
        "experimentDescription": "Assumed source timing jitter, differential series disturbance and probe loading before a separate scope observation",
        "benchScenario": True, "frequencyStress": True,
        "analysisWindowExplicit": True, "captureStartNs": args.capture_start_ns,
        "timeStepPs": args.sample_ps, "sampleTimeStepPs": args.sample_ps,
        "electricalTimeStepPs": args.dt_ps,
        "sourceTimingReport": source_report, "receiverSeriesNoiseReport": noise_report,
        "jitter": {
            "configuredInputRjRmsPs": args.rj_ps,
            "configuredPeriodicJitterPeakPs": args.pj_ps,
            "periodicJitterFrequencyHz": args.pj_mhz * 1e6,
            "periodicJitterPeriodUI": 1 / (args.pj_mhz * 1e6 * timing["ui_s"]),
            "randomJitterCornerHz": args.rj_corner_mhz * 1e6,
            "seed": args.timing_seed,
            "provenance": "assumed stationary correlated source timing; shared by complementary legs before simulation",
        },
        "noise": {
            "kind": "commanded differential receiver-pad series voltage disturbance",
            "configuredRmsMv": args.noise_mv,
            "cutoffHz": args.noise_corner_ghz * 1e9, "order": 2,
            "sampleIntervalPs": args.noise_grid_ps, "seed": args.noise_seed,
            "provenance": "assumed stationary shaped series source, not observed total pad/die noise or instrument noise",
        },
        "captureValidation": {
            "adaptive": {**native.capture_time_diagnostics(adaptive), "timeOrdering": "nondecreasing",
                         "duplicateVoltageToleranceV": native.ADAPTIVE_DUPLICATE_VOLTAGE_TOLERANCE,
                         "rawDuplicateRowsPreserved": True, "analysisStartCoverageVerified": True},
            "linearized": {"timeOrdering": "strictly increasing", "analysisStartCoverageVerified": True,
                           "maximumGapToleranceFactor": 1 + 1e-8},
        },
        "inputFilesSha256": {
            name: file_hash(out / name) for name in
            ("simulation.cir", "transmitter-stimulus.sp", "receiver-noise.sp", "stimulus-events.csv",
             "source-timing.npz", "commanded-noise.npz")
        },
        "solver": solver_identity(args.ngspice),
        "implementationSha256": {"generator": file_hash(__file__),
                                  "stimulusHelper": file_hash(Path(__file__).with_name("bench_stimulus.py")),
                                  "passiveAndValidationSource": file_hash(Path(__file__).with_name("stress-dqs-bandwidth.py"))},
    })
    metadata["source"].update({"kind": "ideal complementary PWL sources with shared assumed timing error",
        "firstPositiveRisingCrossingPs": source_report["nominalFirstCrossingS"] * 1e12,
        "actualFirstPositiveRisingCrossingPs": source_report["actualFirstCrossingS"] * 1e12,
        "pulseWidthPs": None, "pulseWidthMeaning": "event spacing varies with injected timing error"})
    metadata["ioModels"]["transmitter"] = "virtual ideal complementary PWL stimulus; no actual AM3352 at 5 GHz"
    metadata["ioModels"]["probeCapacitancePfPerLeg"] = args.probe_pf
    metadata["limitations"] = [
        "All disturbance budgets are assumptions, not bench measurements or validated DDR operating limits",
        "Virtual 1ps ideal source does not represent an AM3352 switching at 5 GHz; no vendor I/O model is retimed",
        "Fast-edge harmonics extend beyond the supplied channel's 5GHz extraction range; their response uses rational-fit extrapolation",
        "Timing modulation creates out-of-band carrier sidebands, including a 5.1GHz upper sideband for 100MHz periodic jitter at 5GHz",
        "Commanded series-source noise RMS does not guarantee observed total pad or die noise RMS",
        "Receiver ODT/Cin and ideal shunt probe capacitance are assumptions; no active receiver, measured probe transfer, PDN or aggressors",
        "Scope filtering and instrument noise belong to a separate observation artifact; this native capture is not a measured bench eye",
        "Finite captures and assumed distributions do not establish DDR compliance, BER or rare-event tails",
    ]
    return metadata


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        timing = derive_timing(args)
        channel = Path(args.channel).resolve()
        channel.read_bytes()
        native.spice_path(channel)
        out = Path(args.out).resolve()
        if channel.is_relative_to(out):
            raise ValueError("channel input must be outside the output directory")
        outputs = [out / name for name in OUTPUT_FILES]
        inputs = [channel, Path(__file__), Path(__file__).with_name("bench_stimulus.py"),
                  Path(__file__).with_name("stress-dqs-bandwidth.py"),
                  Path(__file__).with_name("audit_paths.py")]
        solver_path = Path(shutil.which(args.ngspice) or args.ngspice).resolve()
        inputs.append(solver_path)
        build_file = solver_path.parent.parent / "build-provenance.json"
        if build_file.is_file():
            inputs.append(build_file)
        paths.check_report_paths(outputs, inputs)
        if any(not output.resolve().is_relative_to(out) for output in outputs):
            raise ValueError("output targets must remain inside the output directory")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    args.channel = str(channel)
    binary = str(Path(args.ngspice).resolve()) if "/" in args.ngspice else args.ngspice
    out.mkdir(parents=True, exist_ok=True)
    for name in ("adaptive.dat", "waveforms.dat", "waveforms.npz", "provenance.json",
                 "source-report.json", "receiver-noise-report.json", "probe-report.json"):
        (out / name).unlink(missing_ok=True)
    source_report, noise_report = write_inputs(out, args, timing)
    (out / "simulation.cir").write_text(build_netlist(args, timing))
    (out / "source-report.json").write_text(json.dumps(source_report, indent=2) + "\n")
    (out / "receiver-noise-report.json").write_text(json.dumps(noise_report, indent=2) + "\n")
    began = time.monotonic()
    try:
        run = subprocess.run([binary, "-b", "simulation.cir"], cwd=out,
                             capture_output=True, text=True, timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        (out / "ngspice.log").write_text(decoded(error.stdout) + decoded(error.stderr))
        raise RuntimeError("bench companion timed out; partial log preserved") from error
    log = run.stdout + run.stderr
    (out / "ngspice.log").write_text(log)
    if run.returncode or native.COMPLETION_MARKER not in log or native.NATIVE_ERROR.search(log):
        raise RuntimeError("bench companion did not complete; inspect ngspice.log")
    validation_timing = {**timing, "dt_s": timing["sample_dt_s"],
                         "analysis_start_s": timing["capture_start_s"]}
    adaptive = native.load_capture(out / "adaptive.dat", validation_timing, adaptive=True)
    waveforms = native.load_capture(out / "waveforms.dat", validation_timing)
    # Independently require coverage of the declared analysis window as well.
    native.load_capture(out / "waveforms.dat", {**validation_timing, "analysis_start_s": timing["analysis_start_s"]})
    np.savez_compressed(out / "waveforms.npz", **{key: waveforms[:, i] for i, key in enumerate(CAPTURE_KEYS)})
    noise_report["observedAnalysis"] = observed_reports(waveforms, timing)
    (out / "receiver-noise-report.json").write_text(json.dumps(noise_report, indent=2) + "\n")
    probe_report = {"kind": "ideal shunt capacitance to ground at receiver package pins",
                    "configuredCapacitancePfPerLeg": args.probe_pf,
                    "nodes": ["rxp", "rxn"], "identicalInCleanAndNoisyCases": True,
                    "observedAnalysis": {key: noise_report["observedAnalysis"][key] for key in
                                         ("totalPadDifferentialVolts", "totalDieDifferentialVolts")}}
    (out / "probe-report.json").write_text(json.dumps(probe_report, indent=2) + "\n")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    metadata = provenance(args, timing, out, source_report, noise_report, adaptive,
                          time.monotonic() - began, (version.stdout + version.stderr).strip())
    (out / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
