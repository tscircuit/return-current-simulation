"""Bounded geometry extraction and real ngspice transients; no fitted coupling."""
import gzip
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy

from crosstalk_extract import extract


def pwl(points, quiet=False):
    initial = points[0][1]
    return "PWL(" + " ".join("%.14e %.14e" % (t, initial if quiet else v)
                             for t, v in points) + ")"


def netlist(model, extracted, timestep, quiet=None, independent=None):
    length = model["geometry"]["lengthMm"] * 1e-3
    testbench = model["lines"]
    capacitance = np.array(extracted["C_f_per_m"])
    inductance = np.array(extracted["L_h_per_m"])
    resistance = np.array(extracted["R_ohm_per_m"])
    rows = ["Geometry-derived uniform coupled-line transient",
            "* Exact symmetric modes; DC trace R split at ends, not broadband copper loss",
            ".options reltol=1e-7 abstol=1e-12 vntol=1e-9 method=trap maxord=2"]
    if independent is not None:
        j = independent
        line = testbench[j]
        z = np.sqrt(inductance[j, j] / capacitance[j, j])
        delay = length * np.sqrt(inductance[j, j] * capacitance[j, j])
        half_r = length * resistance[j, j] / 2
        rows += ["Vsrc src 0 " + pwl(line["waveform"]),
                 "Vref ref 0 %.14e" % line["loadVoltage"],
                 "Rsrc src near %.14e" % line["sourceResistance"],
                 "Rcu0 near ti %.14e" % half_r,
                 "Tline ti 0 to 0 Z0=%.14e TD=%.14e" % (z, delay),
                 "Rcu1 to far %.14e" % half_r,
                 "Rload far ref %.14e" % line["loadResistance"],
                 "Cload far 0 %.14e" % line["loadCapacitance"]]
        columns = "v(near) v(far) v(src)"
    else:
        transform = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
        modal = {}
        for name, matrix in [("L", inductance), ("C", capacitance), ("R", resistance)]:
            projected = transform.T @ matrix @ transform
            if np.linalg.norm(projected - np.diag(np.diag(projected))) / np.linalg.norm(matrix) > 1e-10:
                raise ValueError("Geometry does not have independent symmetric modes")
            modal[name] = np.diag(projected)
        for j, line in enumerate(testbench):
            rows += ["Vsrc%d src%d 0 %s" % (j, j, pwl(line["waveform"], j == quiet))]
        for j, sign in enumerate([1, -1]):
            z = np.sqrt(modal["L"][j] / modal["C"][j])
            delay = length * np.sqrt(modal["L"][j] * modal["C"][j])
            if length * modal["R"][j] > z * .01:
                raise ValueError("DC end-loss approximation exceeds 1 percent of modal impedance")
            half_r = length * modal["R"][j] / 2
            line = testbench[0]
            bias = np.sqrt(2) * line["loadVoltage"] if j == 0 else 0
            rows += ["Edrv%d md%d 0 value={(v(src0)+(%d)*v(src1))/%.14e}" % (j, j, sign, np.sqrt(2)),
                     "Vref%d ref%d 0 %.14e" % (j, j, bias),
                     "Rsrc%d md%d launch%d %.14e" % (j, j, j, line["sourceResistance"]),
                     "Rcu_in%d launch%d mi%d %.14e" % (j, j, j, half_r),
                     "Tline%d mi%d 0 mo%d 0 Z0=%.14e TD=%.14e" % (j, j, j, z, delay),
                     "Rcu_out%d mo%d receive%d %.14e" % (j, j, j, half_r),
                     "Rload%d receive%d ref%d %.14e" % (j, j, j, line["loadResistance"]),
                     "Cload%d receive%d 0 %.14e" % (j, j, line["loadCapacitance"])]
        for j, sign in enumerate([1, -1]):
            for end, node in [(0, "launch"), (1, "receive")]:
                rows += ["Eout%d_%d n%d_%d 0 value={(v(%s0)+(%d)*v(%s1))/%.14e}" %
                         (j, end, j, end, node, sign, node, np.sqrt(2))]
        columns = "v(n0_0) v(n0_1) v(n1_0) v(n1_1) v(src0) v(src1)"
    rows += [".control", "set noaskquit", "set numdgt=15", "set wr_singlescale", "set wr_vecnames",
             "tran %.14e %.14e 0 %.14e" % (timestep, model["stopSeconds"], timestep),
             "wrdata waveform.txt " + columns, "quit", ".endc", ".end"]
    return "\n".join(rows) + "\n"


def child_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (30, 35))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))


def run(directory, name, text, ngspice):
    path = directory / name
    path.mkdir()
    (path / "input.cir").write_text(text)
    started = time.monotonic()
    with (path / "ngspice.log").open("w") as log:
        process = subprocess.run([ngspice, "-b", "input.cir"], cwd=path, stdout=log,
                                 stderr=subprocess.STDOUT, timeout=30, preexec_fn=child_limits)
    raw = path / "waveform.txt"
    if process.returncode != 0 or not raw.exists():
        raise RuntimeError("ngspice failed in " + name + "; inspect ngspice.log")
    if raw.stat().st_size > 256 * 1024**2:
        raise RuntimeError("Waveform exceeds the bounded export budget")
    data = np.loadtxt(raw, skiprows=1)
    if len(data) > 1000000 or not np.isfinite(data).all() or np.any(np.diff(data[:, 0]) <= 0):
        raise RuntimeError("Invalid or oversized exported waveform")
    original_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    with raw.open("rb") as source, gzip.open(str(raw) + ".gz", "wb") as target:
        while chunk := source.read(1024**2):
            target.write(chunk)
    compressed = Path(str(raw) + ".gz")
    with gzip.open(compressed, "rb") as source:
        if hashlib.sha256(source.read()).hexdigest() != original_hash:
            raise RuntimeError("Compressed waveform verification failed")
    raw.unlink()
    return data, {"samples": len(data), "elapsedSeconds": time.monotonic() - started,
                  "netlistSha256": hashlib.sha256(text.encode()).hexdigest(),
                  "waveformSha256": original_hash,
                  "gzipSha256": hashlib.sha256(compressed.read_bytes()).hexdigest()}


def difference(a, b):
    return np.column_stack([a[:, 0], *[a[:, j] - np.interp(a[:, 0], b[:, 0], b[:, j])
                                     for j in range(1, a.shape[1])]])


def plot(directory, model, waves):
    matplotlib.rcParams.update({"svg.fonttype": "none", "svg.hashsalt": "crosstalk-v1",
                                "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for j, line in enumerate(model["lines"]):
        active, quiet = waves["switching"], waves["quiet-" + str(1-j)]
        for data, label, color in [(quiet, "Other line held at its initial voltage", "#8b9aa5"),
                                   (active, "Both supplied waveforms", "#126b76")]:
            axes[0, j].plot(data[:, 0] * 1e9, data[:, 2+2*j], color=color, linewidth=1, label=label)
        induced = difference(active, quiet)
        for col, label, color in [(1+2*j, "Near endpoint", "#bd652b"), (2+2*j, "Far endpoint", "#126b76")]:
            axes[1, j].plot(induced[:, 0] * 1e9, induced[:, col] * 1000,
                            color=color, linewidth=1, label=label)
        axes[0, j].set_title(line["name"] + " receiver")
        axes[0, j].set_ylabel("Voltage (V)")
        axes[1, j].set_title(line["name"] + ": aggressor-induced voltage")
        axes[1, j].set_ylabel("Switching minus quiet (mV)")
        for ax in axes[:, j]:
            ax.set_xlabel("Time (ns)")
            ax.grid(alpha=.18)
            ax.legend(fontsize=8)
    g = model["geometry"]
    fig.suptitle("Geometry-derived coupled-line transient | edge gap %.3f mm | length %.3f mm\n"
                 "Uniform quasi-TEM / declared DC copper-loss approximation; not DDR qualification" %
                 (g["gapMm"], g["lengthMm"]), fontsize=12)
    fig.savefig(directory / "transients.svg", metadata={"Date": None})
    fig.savefig(directory / "transients.png", dpi=160)
    plt.close(fig)


def main():
    started = time.monotonic()
    input_path, directory, ngspice = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    model = json.loads(input_path.read_text())
    version = subprocess.run([ngspice, "--version"], capture_output=True, text=True, timeout=5, check=True).stdout
    g, m = model["geometry"], model["material"]
    assumptions = {"geometry": {"trace_width_mm": g["widthMm"], "trace_thickness_mm": g["thicknessMm"],
                                "substrate_height_mm": g["heightMm"]},
                   "materials": {"relative_permittivity": m["relativePermittivity"],
                                 "trace_conductivity_s_per_m": m["conductivity"]}}
    fine = min(.005, g["widthMm"]/60, g["thicknessMm"]/5, g["heightMm"]/40, g["gapMm"]/20)
    margin = max(4, g["heightMm"]*10, g["widthMm"]*4)
    height = max(4, (g["heightMm"]+g["thicknessMm"])*10)
    extracted = []
    for step, padding in [(fine*4, 1), (fine*2, 1), (fine, 1), (fine, 2)]:
        values, _ = extract(assumptions, g["gapMm"], step, margin*padding, height*padding)
        extracted.append(values)
    selected = extracted[-1]
    checks = {}
    for key in ["C_f_per_m", "L_h_per_m"]:
        medium, refined, enlarged = [np.array(r[key]) for r in extracted[1:]]
        checks[key] = {"gridRelativeNorm": float(np.linalg.norm(medium-refined)/np.linalg.norm(refined)),
                       "domainRelativeNorm": float(np.linalg.norm(refined-enlarged)/np.linalg.norm(enlarged)),
                       "domainMutualRelative": float(abs(refined[0, 1]-enlarged[0, 1])/abs(enlarged[0, 1]))}
        if checks[key]["gridRelativeNorm"] > .02 or checks[key]["domainRelativeNorm"] > .005:
            (directory / "failed-convergence.json").write_text(json.dumps(checks, indent=2))
            raise RuntimeError("Electrostatic grid/domain convergence did not pass")
    edge_times = [b[0]-a[0] for line in model["lines"]
                  for a, b in zip(line["waveform"][:-1], line["waveform"][1:]) if b[1] != a[1]]
    if not edge_times:
        raise ValueError("Supply at least one switching waveform")
    delay = g["lengthMm"]*1e-3*np.sqrt(selected["L_h_per_m"][0][0]*selected["C_f_per_m"][0][0])
    timestep = min(min(edge_times)/50, delay/80)
    if model["stopSeconds"]/(timestep/4) > 800000:
        raise ValueError("Transient refinement exceeds the 800000 nominal-step budget")
    all_waves, runs, temporal = {}, {}, {}
    for case, quiet in [("switching", None), ("quiet-0", 0), ("quiet-1", 1)]:
        refinements = []
        for level, step in enumerate([timestep, timestep/2, timestep/4]):
            name = case + "-" + str(level)
            wave, metadata = run(directory, name, netlist(model, selected, step, quiet=quiet), ngspice)
            refinements.append(wave)
            runs[name] = metadata
        error = float(np.max(np.abs(difference(refinements[2], refinements[1])[:, 1:])))
        temporal[case] = {"maximumMediumToFineDifferenceV": error}
        if error > .005:
            (directory / "failed-convergence.json").write_text(json.dumps(temporal, indent=2))
            raise RuntimeError("Transient timestep convergence did not pass")
        all_waves[case] = refinements[-1]
    controls = {}
    for j in range(2):
        independent = []
        for label in ["quiet-other", "switching-other"]:
            name = "independent-" + str(j) + "-" + label
            wave, metadata = run(directory, name, netlist(model, selected, timestep/4, independent=j), ngspice)
            independent.append(wave)
            runs[name] = metadata
        residual = float(np.max(np.abs(difference(independent[0], independent[1])[:, 1:])))
        controls[str(j)] = {"independentlyExecutedZeroMutualDifferenceV": residual}
        if residual > 1e-8:
            raise RuntimeError("Independent zero-coupling control failed")
    metrics = {}
    for j, line in enumerate(model["lines"]):
        induced = difference(all_waves["switching"], all_waves["quiet-" + str(1-j)])
        metrics[line["traceId"]] = {
            "nearPeakAggressorInducedV": float(np.max(np.abs(induced[:, 1+2*j]))),
            "farPeakAggressorInducedV": float(np.max(np.abs(induced[:, 2+2*j]))),
            "farRmsAggressorInducedV": float(np.sqrt(np.trapezoid(induced[:, 2+2*j]**2, induced[:, 0]) /
                                                   (induced[-1, 0]-induced[0, 0])))}
    plot(directory, model, all_waves)
    max_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    result = {"extraction": {"runs": extracted, "selected": selected},
              "convergence": {"electrostatic": checks, "temporal": temporal, "independentControls": controls,
                              "gates": {"gridRelativeNorm": .02, "domainRelativeNorm": .005,
                                        "waveformAbsoluteV": .005, "independentZeroMutualV": 1e-8}},
              "metrics": metrics,
              "waveforms": {name: wave[::max(1, len(wave)//4000)].tolist() for name, wave in all_waves.items()},
              "provenance": {"ngspiceVersion": version, "pythonVersion": sys.version,
                             "numpyVersion": np.__version__, "scipyVersion": scipy.__version__,
                             "matplotlibVersion": matplotlib.__version__, "runs": runs,
                             "maxChildRssBytes": max_rss if sys.platform == "darwin" else max_rss*1024,
                             "elapsedSeconds": time.monotonic()-started,
                             "waveformColumns": ["timeSeconds", "line0NearV", "line0FarV", "line1NearV", "line1FarV", "source0V", "source1V"],
                             "maxTimestepSeconds": timestep,
                             "resourceBudget": {"serialNativeJobs": 1, "crossSectionNodes": 200000,
                                                "nativeCpuSeconds": 30, "nativeTimeoutSeconds": 30,
                                                "nominalFineSteps": 800000, "exportedSamples": 1000000}}}
    (directory / "result.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"status": "complete", "runs": len(runs), "elapsedSeconds": result["provenance"]["elapsedSeconds"]}))


if __name__ == "__main__":
    # Let subprocess.run clean up its child if the enclosing Node deadline fires.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    main()
