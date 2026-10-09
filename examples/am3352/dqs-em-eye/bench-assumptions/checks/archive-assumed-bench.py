"""Archive compact review data from complete assumed-bench captures."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_case(raw, observed, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with np.load(raw / "waveforms.npz") as circuit, np.load(observed / "waveforms.npz") as scope:
        if not np.array_equal(circuit["time_s"], scope["time_s"]):
            raise ValueError("Raw and scope review timestamps differ")
        arrays = {
            "time_s": circuit["time_s"],
            "transmitter_differential_v": circuit["tx_p_v"] - circuit["tx_n_v"],
            "receiver_die_differential_v": circuit["dqs_p_v"] - circuit["dqs_n_v"],
            "receiver_pad_differential_v": circuit["pad_p_v"] - circuit["pad_n_v"],
            "scope_filtered_differential_v": scope["scope_filtered_p_v"] - scope["scope_filtered_n_v"],
            "scope_noise_v": scope["scope_noise_v"],
            "observed_differential_v": scope["dqs_p_v"] - scope["dqs_n_v"],
        }
        np.savez_compressed(destination / "review-waveforms.npz", **arrays)
    for name in ("provenance.json", "simulation.cir", "ngspice.log", "source-report.json", "receiver-noise-report.json", "probe-report.json"):
        shutil.copy2(raw / name, destination / name)
    shutil.copy2(observed / "provenance.json", destination / "observation-provenance.json")
    mapping = {
        "kind": "exact derived differential arrays for review; not complete native or scope leg captures",
        "nativeWaveformsSha256": digest(raw / "waveforms.npz"),
        "observedWaveformsSha256": digest(observed / "waveforms.npz"),
        "reviewWaveformsSha256": digest(destination / "review-waveforms.npz"),
        "derivation": {
            "time_s": "native time_s (same exact scope timestamps)",
            "transmitter_differential_v": "native tx_p_v - tx_n_v",
            "receiver_die_differential_v": "native dqs_p_v - dqs_n_v",
            "receiver_pad_differential_v": "native pad_p_v - pad_n_v",
            "scope_filtered_differential_v": "observation scope_filtered_p_v - scope_filtered_n_v",
            "scope_noise_v": "observation scope_noise_v",
            "observed_differential_v": "observation dqs_p_v - dqs_n_v",
        },
        "units": "seconds and differential volts; all saved samples, no rounding, resampling or time trimming",
        "reproduction": "Regenerate complete native/observed captures and large PWL includes with scripts/generate-dqs-bench-eye.sh; audits check complete original files, not these derived review arrays.",
    }
    (destination / "archive.json").write_text(json.dumps(mapping, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--routed-only", action="store_true")
    args = parser.parse_args()
    source, out = Path(args.root).resolve(), Path(args.out).resolve()
    if source == out or source in out.parents or out in source.parents:
        raise ValueError("Review output must be separate from complete captures")
    for budget in ("clean", "noisy"):
        for route in (("routed",) if args.routed_only else ("routed", "reference")):
            name = f"5ghz-{budget}-{route}"
            archive_case(source / "captures" / name, source / "observations" / name, out / "captures" / name)
        inputs = out / "inputs" / budget
        inputs.mkdir(parents=True, exist_ok=True)
        for name in ("source-timing.npz", "commanded-noise.npz", "stimulus-events.csv"):
            shutil.copy2(source / "captures" / f"5ghz-{budget}-routed" / name, inputs / name)
        if (source / "5ghz" / budget).is_dir():
            shutil.copytree(source / "5ghz" / budget, out / "5ghz" / budget, dirs_exist_ok=True)
    shutil.copytree(source / "5ghz/routed-clean-vs-noisy", out / "5ghz/routed-clean-vs-noisy", dirs_exist_ok=True)
    name = "5ghz-noisy-routed-0.25ps"
    archive_case(source / "checks" / name, source / "checks" / (name + "-observed"), out / "checks" / name)
    shutil.copy2(source / "checks" / "bench-audit.json", out / "checks" / "bench-audit.json")
    shutil.copy2(Path(__file__), out / "checks" / "archive-assumed-bench.py")
    print(json.dumps({"out": str(out), "bytes": sum(p.stat().st_size for p in out.rglob("*") if p.is_file())}))


if __name__ == "__main__":
    main()
