"""Capture an ideal differential clock through the existing passive DQS path.

This frequency stress deliberately bypasses vendor switching models. It does
not represent an AM3352 transmitter or establish DDR timing compliance.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time

import numpy as np


COMPLETION_MARKER = "BANDWIDTH_STRESS_COMPLETE"
ADAPTIVE_DUPLICATE_VOLTAGE_TOLERANCE = 1e-10
CAPTURE_KEYS = (
    "time_s", "tx_p_v", "tx_n_v", "dqs_p_v", "dqs_n_v",
    "channel_input_v", "channel_output_v",
)
NATIVE_ERROR = re.compile(
    r"(?im)^\s*(?:error\b|fatal\b|panic\b|segmentation fault\b|"
    r"doAnalyses:.*(?:failed|singular|convergence|timestep))|"
    r"(?i:simulation(?:s)? aborted|analysis failed)"
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--ngspice", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--strobe-ghz", type=float, default=20)
    parser.add_argument("--dt-ps", type=float, default=0.25)
    parser.add_argument("--ui-count", type=int, default=512)
    parser.add_argument("--matched-reference", action="store_true")
    parser.add_argument("--channel-max-ghz", type=float, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--method", choices=("trap", "gear"), default="trap")
    parser.add_argument("--analysis-start-ns", type=float)
    parser.add_argument("--analysis-stop-ns", type=float)
    return parser


def derive_timing(strobe_ghz, dt_ps, ui_count, *, analysis_window=None):
    if not math.isfinite(strobe_ghz) or strobe_ghz <= 0:
        raise ValueError("strobe frequency must be finite and positive")
    if not math.isfinite(dt_ps) or dt_ps <= 0:
        raise ValueError("time step must be finite and positive")
    if not isinstance(ui_count, int) or isinstance(ui_count, bool) or ui_count <= 0:
        raise ValueError("UI count must be a positive integer")
    ui = 1 / (2 * strobe_ghz * 1e9)
    rise = fall = 1e-12
    dt = dt_ps * 1e-12
    if ui <= rise:
        raise ValueError("unit interval must exceed the 1 ps source transition")
    if dt > min(rise / 2, ui / 16):
        raise ValueError("time step must resolve each edge and unit interval")
    delay = 5e-9
    analysis_start = delay + max(3e-9, 64 * ui)
    analysis_stop = delay + ui_count * ui
    if analysis_window:
        if analysis_window["start_ns"] is not None:
            analysis_start = analysis_window["start_ns"] * 1e-9
        if analysis_window["stop_ns"] is not None:
            analysis_stop = analysis_window["stop_ns"] * 1e-9
    end = delay + (ui_count + 8) * ui
    if not all(math.isfinite(value) for value in (analysis_start, analysis_stop)):
        raise ValueError("analysis window endpoints must be finite")
    if analysis_start < delay or analysis_stop > end:
        raise ValueError("analysis window must lie inside the clock transient")
    if analysis_stop - analysis_start < 32 * ui * (1 - 1e-12):
        raise ValueError("analysis window must contain at least 32 unit intervals")
    return {
        "ui_s": ui, "period_s": 2 * ui, "delay_s": delay,
        "rise_s": rise, "fall_s": fall, "pulse_width_s": ui - rise,
        "nominal_phase_s": delay + rise / 2,
        "end_s": end,
        "analysis_start_s": analysis_start, "analysis_stop_s": analysis_stop,
        "dt_s": dt, "ui_count": ui_count,
    }


def spice_path(path):
    value = str(Path(path).resolve())
    if any(character in value for character in ('"', "\n", "\r")):
        raise ValueError("channel path cannot contain quotes or newlines")
    return '"' + value + '"'


def passive_network(channel, matched_reference=False):
    """Keep the passive network identical to simulate-dqs-eye.py.

    Zero-volt noise sources retain the original receiver node topology. The
    balanced transformer and lumped common-mode return are explicit model
    assumptions, as in the existing simulation.
    """
    control = (
        "Tref csrc 0 cload 0 Z0=100 TD=.4n"
        if matched_reference else
        f".include {spice_path(channel)}\nXpcb csrc cload pcb_channel"
    )
    return f"""Rpp diep pkp .170474
Rpn dien pkn .176587
Lpp pkp txp 5.06641n
Lpn pkn txn 4.91396n
Kpkg Lpp Lpn .627032
Cpp txp 0 1.19704p
Cpn txn 0 1.34626p
* Lossless balanced transformer: differential PCB channel with no common-mode propagation.
Ebal csrc 0 txp txn 1
Fpos txp 0 Ebal -1
Fneg txn 0 Ebal 1
{control}
Vcm cm 0 .75
* Common-mode DC return: receiver ODT projected as a lumped ideal channel.
Ecmhalf halfcm 0 txp 0 .5
Ecmsrc srccm halfcm txn 0 .5
Rcm srccm cm 30
Fcmp txp 0 Ecmsrc -.5
Fcmn txn 0 Ecmsrc -.5
Erxp rxp0 cm cload 0 .5
Vnp rxp rxp0 0
Erxn rxn0 cm cload 0 -.5
Vnn rxn rxn0 0
Frxp cload 0 Erxp -.5
Frxn cload 0 Erxn .5
* Winbond LDQS/LDQSB package parasitics; independent lumped package model.
Rrp rxp rkp .42069
Rrn rxn rkn .39422
Lrp rkp rdiep 1.1804n
Lrn rkn rdien 1.1796n
Crp rxp 0 .41107p
Crn rxn 0 .42404p
Rtp rdiep cm 60
Rtn rdien cm 60
Cip rdiep 0 2p
Cin rdien 0 2p
"""


def build_netlist(args, timing):
    t = timing
    pulse = (
        f"{t['delay_s']:.17e} {t['rise_s']:.17e} "
        f"{t['fall_s']:.17e} {t['pulse_width_s']:.17e} {t['period_s']:.17e}"
    )
    return f"""Ideal differential clock: passive DQS bandwidth stress
* Complementary 0/1.5 V legs around 0.75 V; differential open-circuit levels +/-1.5 V.
Vpositive srcp 0 PULSE(0 1.5 {pulse})
Vnegative srcn 0 PULSE(1.5 0 {pulse})
Rsourcep srcp diep 50
Rsourcen srcn dien 50
{passive_network(args.channel, args.matched_reference)}
.options reltol=1e-5 abstol=1e-11 vntol=1e-7 method={args.method} maxord=2 trtol=3
.control
set wr_vecnames
set wr_singlescale
set numdgt=17
* Compute the complete launch history; retain only the requested late window.
tran {t['dt_s']:.17e} {t['end_s']:.17e} {t['analysis_start_s']:.17e} {t['dt_s']:.17e}
wrdata adaptive.dat v(txp) v(txn) v(rdiep) v(rdien) v(csrc) v(cload)
linearize v(txp) v(txn) v(rdiep) v(rdien) v(csrc) v(cload)
wrdata waveforms.dat v(txp) v(txn) v(rdiep) v(rdien) v(csrc) v(cload)
echo {COMPLETION_MARKER}
quit
.endc
.end
"""


def capture_time_diagnostics(values):
    duplicates = np.diff(values[:, 0]) == 0
    maximum_jump = (
        float(np.max(np.abs(np.diff(values[:, 1:], axis=0)[duplicates])))
        if np.any(duplicates) else 0.0
    )
    return {
        "duplicateTimestampCount": int(np.count_nonzero(duplicates)),
        "maximumDuplicateVoltageDeltaV": maximum_jump,
    }


def load_capture(path, timing, *, adaptive=False):
    values = np.loadtxt(path, skiprows=1, ndmin=2)
    if values.shape[1] != len(CAPTURE_KEYS) or len(values) < 2:
        raise RuntimeError(f"invalid capture shape in {path.name}")
    if not np.isfinite(values).all() or np.any(values[:, 0] < 0):
        raise RuntimeError(f"nonfinite values or negative time in {path.name}")
    intervals = np.diff(values[:, 0])
    if np.any(intervals < 0) or (not adaptive and np.any(intervals == 0)):
        raise RuntimeError(f"nonfinite or unordered capture in {path.name}")
    if values[0, 0] > timing["analysis_start_s"] + timing["dt_s"]:
        raise RuntimeError(f"capture starts after the analysis window in {path.name}")
    if not adaptive and np.any(intervals > timing["dt_s"] * (1 + 1e-8)):
        raise RuntimeError(f"linearized capture has a sampling gap in {path.name}")
    if adaptive:
        diagnostics = capture_time_diagnostics(values)
        if (diagnostics["maximumDuplicateVoltageDeltaV"]
                > ADAPTIVE_DUPLICATE_VOLTAGE_TOLERANCE):
            raise RuntimeError(f"duplicate adaptive time has a voltage jump in {path.name}")
    if values[-1, 0] < timing["end_s"] - max(1e-15, timing["dt_s"]):
        raise RuntimeError(f"transient ended early in {path.name}")
    mask = (
        (values[:, 0] >= timing["analysis_start_s"])
        & (values[:, 0] <= timing["analysis_stop_s"])
    )
    if np.count_nonzero(mask) < 16:
        raise RuntimeError("capture does not contain the requested analysis window")
    return values


def provenance(args, timing, netlist, channel_bytes, elapsed, ngspice_version,
               *, capture_validation=None):
    matched = args.matched_reference
    control = "Tref csrc 0 cload 0 Z0=100 TD=.4n"
    return {
        "kind": "ngspice ideal-source passive differential frequency stress",
        "experimentDescription": (
            f"{args.strobe_ghz:g} GHz complementary ideal clock through the unchanged "
            "TI package, differential channel, Winbond package and assumed ODT/Cin"
        ),
        "frequencyStress": True,
        "direction": "write", "mode": "clock",
        "rateMTs": 2000 * args.strobe_ghz,
        "clockMHz": 1000 * args.strobe_ghz,
        "strobeGHz": args.strobe_ghz,
        "analysisStartNs": timing["analysis_start_s"] * 1e9,
        "analysisStopNs": timing["analysis_stop_s"] * 1e9,
        "analysisWindowUiCount": (
            timing["analysis_stop_s"] - timing["analysis_start_s"]
        ) / timing["ui_s"],
        "analysisWindowExplicit": (
            args.analysis_start_ns is not None or args.analysis_stop_ns is not None
        ),
        "nominalSourcePhasePs": timing["nominal_phase_s"] * 1e12,
        "nominalSourceFirstCenterPositive": True,
        "nominalSourceRising": True,
        "nominalSourcePhaseIncludesPropagation": False,
        "channel": {
            "model": "ideal matched 100 ohm, 400ps control" if matched else
            "supplied differential two-port channel fit",
            "modelSha256": hashlib.sha256(
                control.encode() if matched else channel_bytes
            ).hexdigest(),
            "suppliedModelSha256": hashlib.sha256(channel_bytes).hexdigest(),
            "maximumExtractedFrequencyGHz": args.channel_max_ghz,
            "fundamentalExceedsExtractedBandwidth": (
                not matched and args.strobe_ghz > args.channel_max_ghz
            ),
            "commonMode": "ideal fixed receiver 0.75V; transmitter common-mode DC load from ODT; no extracted common-mode propagation",
        },
        "source": {
            "kind": "complementary ideal ngspice PULSE voltage sources",
            "openCircuitDifferentialLowV": -1.5,
            "openCircuitDifferentialHighV": 1.5,
            "commonModeV": 0.75, "legLowV": 0, "legHighV": 1.5,
            "resistanceOhmsPerLeg": 50,
            "riseTimePs": 1, "fallTimePs": 1,
            "delayNs": timing["delay_s"] * 1e9,
            "pulseWidthPs": timing["pulse_width_s"] * 1e12,
            "periodPs": timing["period_s"] * 1e12,
            "unitIntervalPs": timing["ui_s"] * 1e12,
            "firstPositiveRisingCrossingPs": timing["nominal_phase_s"] * 1e12,
            "ibis": False, "vendorSwitchingRetimed": False,
        },
        "ioModels": {
            "transmitter": "ideal complementary PULSE stimulus; not an AM3352 switching model",
            "conversion": "none; no IBIS or vendor switching model used",
            "driverModelSha256": None, "negativeDriverModelSha256": None,
            "package": "selected TI pin self R/L/C plus mutual P1-P2 inductance; mutual package capacitance omitted due sign ambiguity",
            "receiver": "Winbond unencrypted LDQS/LDQSB package RLC with assumed linear 60 ohm ODT and 2pF per leg; no transistor-level receiver",
            "receiverCapacitancePf": 2, "odtOhmsPerLeg": 60,
            "sourceResistanceOhmsPerLeg": 50,
        },
        "jitter": {
            "configuredInputRjRmsPs": 0,
            "configuredPeriodicJitterPeakPs": 0,
            "periodicJitterPeriodUI": None, "seed": None,
            "provenance": "deterministic ideal clock; no jitter injection",
        },
        "noise": {
            "kind": "zero differential receiver-input noise; ideal supplies",
            "configuredRmsMv": 0, "seed": None,
            "provenance": "no noise injection",
        },
        "timeStepPs": args.dt_ps, "uiCount": args.ui_count,
        "integrationMethod": args.method,
        "captureStartNs": timing["analysis_start_s"] * 1e9,
        "launchHistoryComputed": True,
        "transientEndNs": timing["end_s"] * 1e9,
        "wallSeconds": elapsed, "ngspiceVersion": ngspice_version,
        "netlistSha256": hashlib.sha256(netlist.encode()).hexdigest(),
        "completionVerified": True, "finiteCaptureVerified": True,
        "captureValidation": capture_validation,
        "signoff": False,
        "limitations": [
            "Ideal 1ps stimulus does not represent AM3352 switching capability or repair an unqualified vendor I/O model",
            "Routed high-frequency response extrapolates the supplied channel fit beyond its extracted frequency range; 1ps edge harmonics also exceed that range",
            "Matched reference is an ideal analytic transmission line, not measured hardware",
            "Balanced differential channel omits extracted common-mode conversion, active aggressors and PDN noise",
            "Winbond receiver ODT and 2pF input capacitance are assumptions; transistor behavior is not included",
            "This frequency stress does not establish DDR compliance, BER or board eye validity",
        ],
    }


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        timing = derive_timing(
            args.strobe_ghz, args.dt_ps, args.ui_count,
            analysis_window={
                "start_ns": args.analysis_start_ns,
                "stop_ns": args.analysis_stop_ns,
            },
        )
        if not math.isfinite(args.channel_max_ghz) or args.channel_max_ghz <= 0:
            raise ValueError("channel bandwidth must be finite and positive")
        if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
            raise ValueError("timeout must be finite and positive")
        channel = Path(args.channel).resolve()
        channel_bytes = channel.read_bytes()
        spice_path(channel)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    out = Path(args.out).resolve()
    if channel.is_relative_to(out):
        parser.error("channel input must be outside the output directory")
    binary = str(Path(args.ngspice).resolve()) if "/" in args.ngspice else args.ngspice
    out.mkdir(parents=True, exist_ok=True)
    for filename in ("adaptive.dat", "waveforms.dat", "waveforms.npz", "provenance.json"):
        (out / filename).unlink(missing_ok=True)
    netlist = build_netlist(args, timing)
    (out / "simulation.cir").write_text(netlist)
    # Record every complete source transition through the transient endpoint.
    count = args.ui_count + 8
    indices = np.arange(count)
    np.savetxt(
        out / "stimulus-events.csv",
        np.column_stack([
            indices, timing["nominal_phase_s"] + indices * timing["ui_s"],
            1 - indices % 2, timing["delay_s"] + indices * timing["ui_s"],
        ]),
        delimiter=",", fmt=["%d", "%.17e", "%d", "%.17e"],
        header="ui_index,event_time_s,positive_state,transition_start_s", comments="",
    )
    start = time.monotonic()
    try:
        run = subprocess.run(
            [binary, "-b", "simulation.cir"], cwd=out,
            capture_output=True, text=True, timeout=args.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        (out / "ngspice.log").write_text(decoded(error.stdout) + decoded(error.stderr))
        raise RuntimeError("ngspice frequency stress timed out; partial log preserved") from error
    log = run.stdout + run.stderr
    (out / "ngspice.log").write_text(log)
    if run.returncode or COMPLETION_MARKER not in log or NATIVE_ERROR.search(log):
        raise RuntimeError("ngspice capture did not complete successfully; inspect ngspice.log")
    adaptive = load_capture(out / "adaptive.dat", timing, adaptive=True)
    waveforms = load_capture(out / "waveforms.dat", timing)
    np.savez_compressed(
        out / "waveforms.npz",
        **{key: waveforms[:, index] for index, key in enumerate(CAPTURE_KEYS)},
    )
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True,
        timeout=min(args.timeout_seconds, 10),
    )
    metadata = provenance(
        args, timing, netlist, channel_bytes, time.monotonic() - start,
        (version.stdout + version.stderr).strip(),
        capture_validation={
            "adaptive": {
                **capture_time_diagnostics(adaptive),
                "timeOrdering": "nondecreasing",
                "duplicateVoltageToleranceV": ADAPTIVE_DUPLICATE_VOLTAGE_TOLERANCE,
                "rawDuplicateRowsPreserved": True,
                "analysisStartCoverageVerified": True,
            },
            "linearized": {
                "timeOrdering": "strictly increasing",
                "analysisStartCoverageVerified": True,
                "maximumGapToleranceFactor": 1 + 1e-8,
            },
        },
    )
    (out / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
