"""Run a balanced differential extracted channel with an IBIS driver in ngspice."""

import argparse, json, hashlib, os, re, subprocess, time
from pathlib import Path
import numpy as np

os.environ.setdefault("MPLCONFIGDIR", str(Path("work/matplotlib").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("work/cache").resolve()))

p = argparse.ArgumentParser()
p.add_argument("--channel", required=True)
p.add_argument("--driver", required=True)
p.add_argument("--negative-driver", required=True)
p.add_argument("--ngspice", required=True)
p.add_argument("--out", required=True)
p.add_argument("--rj-ps", type=float, default=10)
p.add_argument("--pj-ps", type=float, default=5)
p.add_argument("--ui-count", type=int, default=512)
p.add_argument("--mode", choices=["clock", "prbs"], default="clock")
p.add_argument("--dt-ps", type=float, default=2)
p.add_argument("--odt-ohms", type=float, default=60)
p.add_argument("--cin-pf", type=float, default=2)
p.add_argument("--matched-reference", action="store_true")
p.add_argument("--rate-mts", type=float, default=800)
p.add_argument("--noise-mv", type=float, default=2)
p.add_argument("--spice-scripts")
p.add_argument("--timeout-seconds", type=float, default=300)
a = p.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
start = time.monotonic()
ui = 1 / (a.rate_mts * 1e6) if a.rate_mts > 0 else 0
assert (
    a.rate_mts > 0
    and a.rj_ps >= 0
    and a.pj_ps >= 0
    and a.noise_mv >= 0
    and a.odt_ohms > 0
    and a.cin_pf >= 0
    and a.dt_ps > 0
    and a.ui_count >= 64
)
assert ui >= 1.22e-9, (
    "Selected slow IBIS switching edge requires a unit interval of at least 1.22 ns"
)
rng = np.random.default_rng(40501)
nj = a.ui_count
edge = (
    np.arange(nj) * ui
    + 5e-9
    + rng.normal(0, a.rj_ps * 1e-12, nj)
    + a.pj_ps * 1e-12 * np.sin(2 * np.pi * np.arange(nj) / 31)
)
if a.mode == "clock":
    states = np.arange(nj) % 2
else:
    reg = 0x7F
    v = []
    for _ in range(nj):
        v.append(reg & 1)
        bit = ((reg >> 6) ^ (reg >> 5)) & 1
        reg = ((reg << 1) | bit) & 127
    states = np.array(v)
np.savetxt(
    out / "stimulus-events.csv",
    np.column_stack([np.arange(nj), edge, states]),
    delimiter=",",
    header="ui_index,event_time_s,positive_state",
    comments="",
)
end = edge[-1] + 3 * ui
assert np.all(np.diff(edge) > 0), "Injected timing jitter produced unordered bit events"


def retime_driver(model_text, timing):
    """Retain converted I/V tables; schedule each isolated switching edge."""
    checks = {}
    sequence = timing["states"]
    for name in ["ku", "kd"]:
        match = re.search("V" + name + r"[^\n]+", model_text)
        assert match, "Missing converted switching source"
        weights = np.array(
            [float(v) for v in match[0].split("pwl (")[1].split(")")[0].split()]
        ).reshape(-1, 2)
        assert (
            len(weights) >= 4
            and np.all(np.diff(weights[:, 0]) > 0)
            and np.isfinite(weights).all()
        ), "Invalid switching-source times"
        assert weights[:, 1].min() > -0.1 and weights[:, 1].max() < 1.2, (
            "Invalid switching weights"
        )
        templates = {}
        for kind, offset in zip(["rising", "falling"], timing["offsets"]):
            assert weights[-1, 0] >= offset + 1.2e-9, (
                "Converted source does not contain a complete isolated edge"
            )
            offsets = np.linspace(0, 1.2e-9, 241)
            templates[kind] = (
                offsets,
                np.interp(offset + offsets, weights[:, 0], weights[:, 1]),
            )
        low = templates["falling"][1][-1]
        high = templates["rising"][1][-1]
        previous = timing["initialState"]
        points = [(0, high if previous else low)]
        clipped = 0
        max_tail_change = 0.0
        for i, (event_time, state) in enumerate(zip(edge, sequence)):
            if state == previous:
                continue
            offsets, values = templates["rising" if state else "falling"]
            next_change = next(
                (edge[j] for j in range(i + 1, nj) if sequence[j] != state),
                edge[-1] + 5 * ui,
            )
            duration = min(offsets[-1], next_change - event_time - 5e-12)
            assert duration > 0, "Switching events overlap"
            clipped += int(duration < offsets[-1])
            tail_change = abs(np.interp(duration, offsets, values) - values[-1])
            max_tail_change = max(max_tail_change, float(tail_change))
            assert tail_change < 0.02, (
                "Jittered event overlaps an unsettled switching edge"
            )
            mask = offsets < duration
            points.extend(zip(event_time + offsets[mask], values[mask]))
            points.append(
                (event_time + duration, float(np.interp(duration, offsets, values)))
            )
            previous = state
        points.append((end, high if previous else low))
        points = np.array(points)
        assert np.all(np.diff(points[:, 0]) > 0)
        checks[name] = {
            "minimum": float(weights[:, 1].min()),
            "maximum": float(weights[:, 1].max()),
            "clippedSettledTails": clipped,
            "maxClippedTailWeightChange": max_tail_change,
        }
        knots = " ".join(f"{t:.12e} {v:.9e}" for t, v in points)
        model_text = (
            model_text[: match.start()]
            + f"V{name} {name.upper()} GND pwl ( {knots} )"
            + model_text[match.end() :]
        )
    return model_text, checks


s, positive_checks = retime_driver(
    Path(a.driver).read_text(),
    {"states": states, "initialState": 0, "offsets": [0, 10e-9]},
)
negative, negative_checks = retime_driver(
    Path(a.negative_driver).read_text(),
    {"states": 1 - states, "initialState": 1, "offsets": [10e-9, 20e-9]},
)
audit = {"positive": positive_checks, "negative": negative_checks}


# Strip the converter's average package; add the selected pin R/L plus mutual L.
def unpackage(s, name):
    s = re.sub(r"(?m)^\.SUBCKT [^\n]+", f".SUBCKT {name} GND DIE0", s)
    for n in ["RPIN", "LPIN", "CPIN"]:
        s = re.sub(r"(?m)^" + n + r"[^\n]*\n", "", s)
    s = re.sub(r"(?m)^\.ENDS[^\n]*", f".ENDS {name}", s)
    return s


(out / "driver-positive.sp").write_text(unpackage(s, "txpos"))
(out / "driver-negative.sp").write_text(unpackage(negative, "txneg"))
from scipy.signal import butter, sosfilt

noise_t = np.arange(0, end + 20e-12, 20e-12)
noise = sosfilt(
    butter(2, 500e6, fs=50e9, output="sos"),
    np.random.default_rng(40502).normal(size=len(noise_t)),
)
noise = noise / np.std(noise) * a.noise_mv * 1e-3
noise_p = " ".join(f"{t:.12e} {v / 2:.9e}" for t, v in zip(noise_t, noise))
noise_n = " ".join(f"{t:.12e} {-v / 2:.9e}" for t, v in zip(noise_t, noise))
channel = Path(a.channel).resolve()
control = (
    "Tref csrc 0 cload 0 Z0=100 TD=.4n"
    if a.matched_reference
    else f'.include "{channel}"\nXpcb csrc cload pcb_channel'
)
net = f"""AM3352 DQS0 routing eye: actual EM channel / explicit I/O assumptions
.include "driver-positive.sp"
.include "driver-negative.sp"
Xpositive 0 diep txpos
Xnegative 0 dien txneg
Rpp diep pkp .170474
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
Rcm srccm cm {a.odt_ohms / 2}
Fcmp txp 0 Ecmsrc -.5
Fcmn txn 0 Ecmsrc -.5
Erxp rxp0 cm cload 0 .5
Vnp rxp rxp0 pwl ( {noise_p} )
Erxn rxn0 cm cload 0 -.5
Vnn rxn rxn0 pwl ( {noise_n} )
Frxp cload 0 Erxp -.5
Frxn cload 0 Erxn .5
* Winbond LDQS/LDQSB package parasitics; independent lumped package model.
Rrp rxp rkp .42069
Rrn rxn rkn .39422
Lrp rkp rdiep 1.1804n
Lrn rkn rdien 1.1796n
Crp rxp 0 .41107p
Crn rxn 0 .42404p
Rtp rdiep cm {a.odt_ohms}
Rtn rdien cm {a.odt_ohms}
Cip rdiep 0 {a.cin_pf}p
Cin rdien 0 {a.cin_pf}p
.options reltol=1e-5 abstol=1e-11 vntol=1e-7 method=gear maxord=2 trtol=3
.control
set wr_vecnames
set wr_singlescale
tran {a.dt_ps}p {end:.12e} 0 {a.dt_ps}p
wrdata adaptive.dat v(txp) v(txn) v(rdiep) v(rdien)
linearize v(txp) v(txn) v(rdiep) v(rdien)
wrdata waveforms.dat v(txp) v(txn) v(rdiep) v(rdien)
quit
.endc
.end
"""
(out / "simulation.cir").write_text(net)
env = os.environ.copy()
if a.spice_scripts:
    env["SPICE_SCRIPTS"] = str(Path(a.spice_scripts).resolve())
run = subprocess.run(
    [a.ngspice, "-b", "simulation.cir"],
    cwd=out,
    env=env,
    capture_output=True,
    text=True,
    timeout=a.timeout_seconds,
)
(out / "ngspice.log").write_text(run.stdout + run.stderr)
if run.returncode or "simulation(s) aborted" in run.stdout + run.stderr:
    raise RuntimeError(run.stdout + run.stderr)
raw = np.loadtxt(out / "adaptive.dat", skiprows=1)
assert raw[-1, 0] >= end - 1e-13, (raw[-1, 0], end)
(out / "adaptive.dat").unlink()
w = np.loadtxt(out / "waveforms.dat", skiprows=1)
assert w.shape[1] == 5 and np.isfinite(w).all()
np.savetxt(
    out / "waveforms.csv",
    w,
    delimiter=",",
    header="time_s,tx_p_v,tx_n_v,dqs_p_v,dqs_n_v",
    comments="",
)
np.savez_compressed(
    out / "waveforms.npz",
    time_s=w[:, 0],
    tx_p_v=w[:, 1],
    tx_n_v=w[:, 2],
    dqs_p_v=w[:, 3],
    dqs_n_v=w[:, 4],
)
(out / "waveforms.dat").unlink()
metadata = {
    "kind": "ngspice IBIS plus extracted EM differential channel",
    "direction": "write",
    "rateMTs": a.rate_mts,
    "clockMHz": a.rate_mts / 2 if a.mode == "clock" else None,
    "mode": a.mode,
    "channel": {
        "model": "ideal matched 100 ohm, 400ps control"
        if a.matched_reference
        else "openEMS geometry extracted differential two-port",
        "modelSha256": hashlib.sha256(
            control.encode() if a.matched_reference else channel.read_bytes()
        ).hexdigest(),
        "commonMode": "ideal fixed receiver 0.75V; transmitter common-mode DC load from ODT; no extracted common-mode propagation",
    },
    "ioModels": {
        "transmitter": "TI AM335x Model_655/847 0x18B example; not confirmed board register values",
        "conversion": "KiCad 9.0.2 isolated-edge Ku/Kd via ngspice, locally retimed; no redistributed vendor tables",
        "driverModelSha256": hashlib.sha256(Path(a.driver).read_bytes()).hexdigest(),
        "negativeDriverModelSha256": hashlib.sha256(
            Path(a.negative_driver).read_bytes()
        ).hexdigest(),
        "package": "selected TI pin self R/L/C plus mutual P1-P2 inductance; mutual package capacitance omitted due sign ambiguity",
        "receiver": "Winbond unencrypted LDQS/LDQSB package RLC, assumed linear ODT and capacitance; no transistor-level receiver",
        "receiverCapacitancePf": a.cin_pf,
        "odtOhmsPerLeg": a.odt_ohms,
    },
    "jitter": {
        "configuredInputRjRmsPs": a.rj_ps,
        "configuredPeriodicJitterPeakPs": a.pj_ps,
        "periodicJitterPeriodUI": 31,
        "seed": 40501,
        "provenance": "assumed source timing budget, not measured board jitter; injected before ngspice",
    },
    "noise": {
        "kind": "assumed differential receiver-input voltage noise; ideal supplies",
        "configuredRmsMv": a.noise_mv,
        "lowPassBandwidthMHz": 500,
        "seed": 40502,
        "provenance": "assumed noise budget, not measured board noise",
    },
    "timeStepPs": a.dt_ps,
    "uiCount": nj,
    "wallSeconds": time.monotonic() - start,
    "netlistSha256": hashlib.sha256(net.encode()).hexdigest(),
    "signoff": False,
    "edgeWeightChecks": audit,
    "limitations": [
        "Balanced differential excitation; no active DQ aggressors, extracted common-mode conversion or simulated PDN noise",
        "Receiver Cin and ODT are assumptions, actual mode registers are unknown",
        "Isolated vendor switching edges retimed; settled tails may be clipped on unusually close jittered edges",
        "No DDR protocol preamble/postamble or turnaround; PRBS is a channel stress test, not DQS protocol",
    ],
}
(out / "provenance.json").write_text(json.dumps(metadata, indent=2))
print(json.dumps(metadata, indent=2))
