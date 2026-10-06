import argparse, json, os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("work/matplotlib").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path("work/cache").resolve()))
import numpy as np
import skrf as rf

p = argparse.ArgumentParser()
p.add_argument("port1")
p.add_argument("port2")
p.add_argument("--out", required=True)
a = p.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
c1 = np.loadtxt(a.port1, delimiter=",", skiprows=1)
c2 = np.loadtxt(a.port2, delimiter=",", skiprows=1)
assert all(
    c.ndim == 2 and c.shape[1] == 5 and len(c) >= 50 and np.isfinite(c).all()
    for c in [c1, c2]
), "Both source runs must supply finite two-port spectra"
assert np.array_equal(c1[:, 0], c2[:, 0])
f = c1[:, 0]
assert f[0] > 0 and np.all(np.diff(f) > 0), "Frequencies must increase"
s = np.zeros((len(f), 2, 2), complex)
for j, col in enumerate([c1, c2]):
    for i in range(2):
        s[:, i, j] = col[:, 1 + 2 * i] + 1j * col[:, 2 + 2 * i]
net = rf.Network(frequency=rf.Frequency.from_f(f, "hz"), s=s, z0=100)
net.write_touchstone(str(out / "channel"))
# Passive rational model from mature scikit-rf vector fitting. No hidden rescaling.
v = rf.VectorFitting(net)
v.max_iterations = 100
v.vector_fit(n_poles_real=2, n_poles_cmplx=12, init_pole_spacing="lin")
rms_before = float(v.get_rms_error())
passive_before = v.is_passive()
unconstrained_fit = np.array(
    [[v.get_model_response(i, j, f) for j in range(2)] for i in range(2)]
).transpose(2, 0, 1)
if not passive_before:
    v.passivity_enforce(n_samples=2000, f_max=7e9, preserve_dc=False)

fit = np.array(
    [[v.get_model_response(i, j, f) for j in range(2)] for i in range(2)]
).transpose(2, 0, 1)
np.savez(out / "channel.npz", f=f, s=s, fit=fit)
results = {
    "z0Ohms": 100,
    "solver": "openEMS 0.0.35",
    "fitter": "scikit-rf " + rf.__version__,
    "fitRmsErrorBeforePassivity": rms_before,
    "fitRmsError": float(v.get_rms_error()),
    "fitRmsPerEntry": float(np.sqrt(np.mean(abs(fit - s) ** 2))),
    "fitMaxError": float(abs(fit - s).max()),
    "fitPassive": bool(v.is_passive()),
    "fitPassiveBeforeEnforcement": bool(passive_before),
    "passivityCorrectionRmsPerEntry": float(
        np.sqrt(np.mean(abs(fit - unconstrained_fit) ** 2))
    ),
    "passivityCorrectionMaxAbs": float(abs(fit - unconstrained_fit).max()),
    "stablePoles": bool(np.all(v.poles.real < 0)),
    "extractionMaxSingularValue": float(np.linalg.svd(s, compute_uv=False).max()),
    "extractionReciprocityMaxAbs": float(abs(s[:, 0, 1] - s[:, 1, 0]).max()),
    "s21At400MHzDb": float(20 * np.log10(abs(np.interp(4e8, f, s[:, 1, 0])))),
}
(out / "fit.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
assert results["fitPassive"] and results["stablePoles"]
assert results["fitRmsPerEntry"] < 0.05 and results["fitMaxError"] < 0.1
v.write_spice_subcircuit_s(str(out / "channel.sp"), "pcb_channel")
