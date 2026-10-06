"""Compare two native field spectra; this is a sensitivity check, not convergence."""

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("baseline")
p.add_argument("comparison")
p.add_argument("--label", required=True)
p.add_argument("--out", required=True)
a = p.parse_args()
base = np.loadtxt(a.baseline, delimiter=",", skiprows=1)
other = np.loadtxt(a.comparison, delimiter=",", skiprows=1)
assert base.shape == other.shape and np.array_equal(base[:, 0], other[:, 0])
assert np.isfinite(base).all() and np.isfinite(other).all()
frequencies = base[:, 0]
result = {"label": a.label, "convergenceProven": False, "bands": {}}
for limit in [1e9, 2e9, 5e9]:
    mask = (frequencies >= 1e6) & (frequencies <= limit)
    report = {}
    for index in [0, 1]:
        s0 = base[mask, 1 + 2 * index] + 1j * base[mask, 2 + 2 * index]
        s1 = other[mask, 1 + 2 * index] + 1j * other[mask, 2 + 2 * index]
        report[f"s{index + 1}"] = {
            "maximumComplexDifference": float(abs(s0 - s1).max()),
            "rmsComplexDifference": float(np.sqrt(np.mean(abs(s0 - s1) ** 2))),
        }
    result["bands"][f"1MHz-{limit / 1e9:g}GHz"] = report
result["sha256"] = {
    name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for name, path in [("baseline", a.baseline), ("comparison", a.comparison)]
}
Path(a.out).write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
