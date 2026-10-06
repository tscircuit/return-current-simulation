"""Generate explicitly assumed DQS transmission-line eyes with ngspice.

This uses routed lengths from circuit-json, not extracted EM/IBIS channels.
Requires Python with numpy/matplotlib and ngspice 44.2 or compatible.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

import numpy as np

os.environ.setdefault("MPLCONFIGDIR", str(Path("work/matplotlib").resolve()))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

C0 = 299792458.0
SIGMA = 5.8e7


def route_segments(route, stackup):
    """Keep layer/width changes and physical vertical travel; omit via parasitics."""
    cursor = 0.0
    layer_data = {}
    for layer in stackup["layers"]:
        if "name" in layer:
            t = layer["copperThicknessMm"]
            layer_data[layer["name"]] = {"z": cursor + t / 2, "thickness": t}
            cursor += t
        else:
            cursor += layer["dielectricThicknessMm"]
    segments = []
    layer_lengths = {}
    via_count = 0
    wire_total = 0.0
    for index, point in enumerate(route):
        if point["route_type"] == "via":
            via_count += 1
            length = abs(
                layer_data[point["to_layer"]]["z"]
                - layer_data[point["from_layer"]]["z"]
            )
            # Delay-only vertical segment. No inferred barrel inductance/stub/capacitance.
            key = ("via", 0.0)
            er = 4.3
            resistance = 0.0
        elif index + 1 < len(route):
            other = route[index + 1]
            if other["route_type"] != "wire":
                if other["route_type"] == "via":
                    if (
                        math.hypot(point["x"] - other["x"], point["y"] - other["y"])
                        > 1e-6
                    ):
                        raise ValueError(
                            "Via does not coincide with its preceding route endpoint"
                        )
                continue
            if other["layer"] != point["layer"]:
                raise ValueError("Layer change without an explicit via")
            length = math.hypot(point["x"] - other["x"], point["y"] - other["y"])
            layer = point["layer"]
            width = point["width"]
            key = (layer, width)
            er = 3.0 if layer in ("top", "bottom") else 4.1
            resistance = 1 / (
                SIGMA * width * 1e-3 * layer_data[layer]["thickness"] * 1e-3
            )
            layer_lengths[layer] = layer_lengths.get(layer, 0.0) + length
            wire_total += length
        else:
            continue
        if length <= 1e-9:
            continue
        if segments and key == (segments[-1]["layer"], segments[-1]["widthMm"]):
            segments[-1]["lengthMm"] += length
        else:
            segments.append(
                {
                    "layer": key[0],
                    "widthMm": key[1],
                    "lengthMm": length,
                    "assumedEffectivePermittivity": er,
                    "dcResistanceOhmsPerMetre": resistance,
                }
            )
    delay = sum(
        s["lengthMm"] * 1e-3 * math.sqrt(s["assumedEffectivePermittivity"]) / C0
        for s in segments
    )
    return {
        "wireLengthMm": wire_total,
        "layerWireLengthsMm": layer_lengths,
        "viaCount": via_count,
        "estimatedDelaySeconds": delay,
        "segments": segments,
    }


def make_pwl(ui, intervals, ramp, voltage, inverted):
    value = voltage if inverted else 0.0
    samples = [(0.0, value)]
    for edge in range(1, intervals):
        samples.append((edge * ui - ramp / 2, value))
        value = voltage - value
        samples.append((edge * ui + ramp / 2, value))
    samples.append((intervals * ui, value))
    return "PWL(\n" + "\n".join(f"+ {t:.14g} {v:.14g}" for t, v in samples) + "\n+ )"


def generate(args):
    started = time.monotonic()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    board_path = Path(args.board)
    stackup_path = Path(args.stackup)
    circuit = json.loads(board_path.read_text())
    stackup = json.loads(stackup_path.read_text())
    components = {
        x["source_component_id"]: x for x in circuit if x["type"] == "source_component"
    }
    ports = {x["source_port_id"]: x for x in circuit if x["type"] == "source_port"}
    traces = {
        x["name"]: x for x in circuit if x["type"] == "source_trace" and x.get("name")
    }
    pcb_traces = {}
    for trace in circuit:
        if trace["type"] == "pcb_trace":
            pcb_traces.setdefault(trace["source_trace_id"], []).append(trace)
    ui = 1 / (args.rate_mts * 1e6)
    dt = args.step_ps * 1e-12
    ramp = args.rise_time_ps * 1e-12 / 0.8
    if ramp >= ui or dt >= ramp / 10:
        raise ValueError(
            "Rise time must be shorter than a UI; timestep must resolve the edge"
        )
    lines = [
        "DQS route-based estimate: NOT EM/IBIS-validated",
        ".options reltol=1e-6 abstol=1e-12 vntol=1e-8",
        f"VREF ref 0 {args.voltage / 2:.14g}",
    ]
    lanes = []
    signals = []
    for lane in args.lanes.split(","):
        lane = lane.strip()
        lane_info = {"lane": lane, "legs": []}
        for polarity, name in [("p", f"DDR_DQS{lane}"), ("n", f"DDR_DQSn{lane}")]:
            trace = traces[name]
            routed = pcb_traces[trace["source_trace_id"]]
            if len(routed) != 1:
                raise ValueError(f"{name} must have one complete ordered PCB route")
            terminals = []
            for port_id in trace["connected_source_port_ids"]:
                port = ports[port_id]
                terminals.append(
                    f"{components[port['source_component_id']]['name']}.{port['name']}"
                )
            if len(terminals) != 2:
                raise ValueError(
                    "This estimate requires a point-to-point two-terminal signal"
                )
            route = route_segments(routed[0]["route"], stackup)
            route.update(
                signal=name, pcbTraceId=routed[0]["pcb_trace_id"], terminals=terminals
            )
            if args.direction == "read":
                route["segments"].reverse()
                route["terminals"].reverse()
            lane_info["legs"].append(route)
            prefix = f"d{lane}{polarity}"
            lines.append(
                f"V{prefix} {prefix}ideal 0 "
                + make_pwl(ui, args.intervals, ramp, args.voltage, polarity == "n")
            )
            lines.append(
                f"R{prefix}driver {prefix}ideal {prefix}0 {args.source_ohms:.14g}"
            )
            # A uniform assumed odd-mode impedance makes the lossless cascaded
            # delays equivalent to one line. Preserve total delay/DC resistance;
            # redistribute the small DC resistance uniformly. This avoids tiny
            # delay-only via sections imposing sub-picosecond solver timesteps.
            length = sum(s["lengthMm"] for s in route["segments"]) * 1e-3
            total_r = sum(
                s["lengthMm"] * 1e-3 * s["dcResistanceOhmsPerMetre"]
                for s in route["segments"]
            )
            speed = length / route["estimatedDelaySeconds"]
            z0 = args.differential_ohms / 2
            model = prefix + "line"
            load = prefix + "load"
            route["dcResistanceOhms"] = total_r
            lines.append(f"O{model} {prefix}0 0 {load} 0 {model}")
            lines.append(
                f".model {model} LTRA(R={total_r / length:.14g} L={z0 / speed:.14g} C={1 / (z0 * speed):.14g} G=0 LEN={length:.14g})"
            )
            lines.extend(
                [
                    f"R{prefix}term {load} ref {args.termination_ohms:.14g}",
                    f"C{prefix}input {load} 0 {args.input_cap_pf:.14g}p",
                ]
            )
            signals.append(f"v({load})")
        lanes.append(lane_info)
    lines.extend(
        [
            f".tran {dt:.14g} {args.intervals * ui:.14g} 0 {dt:.14g}",
            ".control",
            "set wr_singlescale",
            "set wr_vecnames",
            "run",
            "wrdata waveforms.csv " + " ".join(signals),
            "quit",
            ".endc",
            ".end",
        ]
    )
    (out / "dqs.cir").write_text("\n".join(lines) + "\n")
    solve_started = time.monotonic()
    completed = subprocess.run(
        [args.ngspice, "-b", "dqs.cir"], cwd=out, capture_output=True, text=True
    )
    solve_seconds = time.monotonic() - solve_started
    log = completed.stdout + completed.stderr
    (out / "ngspice.log").write_text(log)
    if completed.returncode or "Error:" in log or "Timestep too small" in log:
        raise RuntimeError(f"ngspice did not complete: see {out / 'ngspice.log'}")
    data = np.loadtxt(out / "waveforms.csv", skiprows=1)
    if (
        data.shape[1] != 1 + len(signals)
        or not np.all(np.isfinite(data))
        or not np.all(np.diff(data[:, 0]) > 0)
    ):
        raise ValueError("Invalid transient data")
    np.savez_compressed(
        out / "waveforms.npz",
        timeSeconds=data[:, 0],
        voltages=data[:, 1:],
        signalNames=np.array(signals),
    )
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    ymax = 1.15 * max(
        np.max(
            np.abs(
                data[data[:, 0] >= 16 * ui, 1 + i * 2]
                - data[data[:, 0] >= 16 * ui, 2 + i * 2]
            )
        )
        for i in range(len(lanes))
    )
    fig, axes = plt.subplots(
        1, len(lanes), figsize=(6.4 * len(lanes), 5.6), sharey=True, squeeze=False
    )
    for index, lane in enumerate(lanes):
        axis = axes[0, index]
        voltage = data[:, 1 + index * 2] - data[:, 2 + index * 2]
        delay = sum(leg["estimatedDelaySeconds"] for leg in lane["legs"]) / 2
        x = np.linspace(-ui, ui, 1201)
        windows = []
        for interval in range(16, args.intervals - 2):
            center = (interval + 0.5) * ui + delay
            samples = np.interp(center + x, data[:, 0], voltage)
            windows.append(samples)
            axis.plot(
                x * 1e9,
                samples,
                color="#2563eb" if interval % 2 else "#e8590c",
                alpha=0.18,
                linewidth=1,
            )
        windows = np.array(windows)
        lane["estimateMetrics"] = {
            "boardDelaySeconds": delay,
            "legDelaySkewSeconds": lane["legs"][1]["estimatedDelaySeconds"]
            - lane["legs"][0]["estimatedDelaySeconds"],
            "differentialCentreLevelVolts": [
                float(windows[:, 600].min()),
                float(windows[:, 600].max()),
            ],
            "plottedUIWindows": len(windows),
            "eyeAlignment": "route-estimated mean propagation delay; no clock recovery or individual-edge alignment",
        }
        axis.axhline(0, color="#64748b", linewidth=0.7)
        axis.axvline(0, color="#64748b", linewidth=0.7, linestyle="--")
        axis.set_xlim(-ui * 1e9, ui * 1e9)
        axis.set_ylim(-ymax, ymax)
        axis.set_xticks(np.array([-1, -0.5, 0, 0.5, 1]) * ui * 1e9)
        axis.set_xlabel("Time from nominal UI centre (ns)")
        axis.grid(alpha=0.18)
        p, n = lane["legs"]
        axis.set_title(
            f"DQS{lane['lane']} − DQSn{lane['lane']} at receiver\n{p['wireLengthMm']:.3f} / {n['wireLengthMm']:.3f} mm routed copper",
            fontsize=12,
        )
    axes[0, 0].set_ylabel("Differential receiver voltage (V)")
    fig.suptitle(
        f"AM3352 DQS · transmission-line estimate\n{args.rate_mts:g} MT/s · {args.rate_mts / 2:g} MHz strobe · {ui * 1e9:g} ns UI · {args.direction} direction",
        fontsize=15,
        y=0.99,
    )
    fig.text(
        0.5,
        0.065,
        f"Assumed: {args.differential_ohms:g} Ω differential line · {args.source_ohms:g} Ω drive/leg · {args.termination_ohms:g} Ω termination/leg · {args.input_cap_pf:g} pF input/leg\n{args.voltage:g} V supply · {args.rise_time_ps:g} ps 10–90% source edge · periodic strobe · no injected jitter/noise",
        ha="center",
        fontsize=9,
    )
    fig.text(
        0.5,
        0.012,
        "NOT EM/IBIS-VALIDATED · No package/via parasitics, crosstalk, skin-effect/dielectric loss, plane gaps or supply noise. Not a DDR compliance result.",
        ha="center",
        fontsize=8.5,
        color="#a61b1b",
    )
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.25, top=0.75, wspace=0.12)
    fig.savefig(out / "dqs-eye.png", dpi=200)
    fig.savefig(out / "dqs-eye.svg")
    plt.close(fig)
    report = {
        "status": "unvalidated transmission-line estimate",
        "source": "circuit-json and stackup identified by the SHA-256 hashes below",
        "inputCircuitSha256": hashlib.sha256(board_path.read_bytes()).hexdigest(),
        "inputStackupSha256": hashlib.sha256(stackup_path.read_bytes()).hexdigest(),
        "direction": args.direction,
        "rateMTs": args.rate_mts,
        "strobeFrequencyHz": args.rate_mts * 1e6 / 2,
        "uiSeconds": ui,
        "assumptions": {
            "supplyVolts": args.voltage,
            "driveResistanceOhmsPerLeg": args.source_ohms,
            "terminationOhmsPerLegToHalfSupply": args.termination_ohms,
            "differentialImpedanceOhms": args.differential_ohms,
            "receiverCapacitancePfPerLeg": args.input_cap_pf,
            "sourceRiseFall10To90Ps": args.rise_time_ps,
            "topBottomEffectivePermittivity": 3.0,
            "innerEffectivePermittivity": 4.1,
            "viaEffectivePermittivity": 4.3,
            "lineLossModel": "total DC copper resistance redistributed along a uniform line; no skin-effect or dielectric loss",
            "jitterNoiseInjected": False,
            "references": "ideal continuous AC reference; exported pours not field-solved",
        },
        "excluded": [
            "IBIS nonlinear drivers/receivers and actual register settings",
            "Package/via parasitics and stubs",
            "Mutual/crosstalk and common-mode channel extraction",
            "Discontinuous references and decoupling networks",
            "Frequency-dependent losses",
            "Preamble/postamble/tri-state and read-write turnaround",
            "Jitter/noise, PVT/BER/mask compliance",
            "DQ-to-DQS setup/hold",
        ],
        "lanes": lanes,
        "solver": {
            "program": "ngspice",
            "version": subprocess.check_output(
                [args.ngspice, "--version"], text=True
            ).strip(),
            "solveSeconds": solve_seconds,
            "maxTimestepSeconds": dt,
            "transientRows": len(data),
        },
        "totalSeconds": time.monotonic() - started,
    }
    (out / "assumptions-and-results.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "png": str(out / "dqs-eye.png"),
                "solveSeconds": solve_seconds,
                "totalSeconds": report["totalSeconds"],
                "lanes": [{"lane": l["lane"], **l["estimateMetrics"]} for l in lanes],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board")
    parser.add_argument("stackup")
    parser.add_argument("--output", required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--lanes", default="0,1")
    parser.add_argument("--direction", choices=["write", "read"], default="write")
    parser.add_argument("--rate-mts", type=float, default=800)
    parser.add_argument("--voltage", type=float, default=1.5)
    parser.add_argument("--differential-ohms", type=float, default=100.921304738)
    parser.add_argument("--source-ohms", type=float, default=40)
    parser.add_argument("--termination-ohms", type=float, default=60)
    parser.add_argument("--input-cap-pf", type=float, default=2)
    parser.add_argument("--rise-time-ps", type=float, default=200)
    parser.add_argument("--step-ps", type=float, default=2)
    parser.add_argument("--intervals", type=int, default=32)
    args = parser.parse_args()
    for name in [
        "rate_mts",
        "voltage",
        "differential_ohms",
        "source_ohms",
        "termination_ohms",
        "input_cap_pf",
        "rise_time_ps",
        "step_ps",
    ]:
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            parser.error(f"{name} must be finite and positive")
    if args.intervals < 20:
        parser.error("At least 20 UI intervals are required")
    generate(args)
