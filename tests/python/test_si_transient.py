"""Independent analytic channel/driver fixture; no vendor models or EM claims."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NGSPICE = os.environ.get("SI_NGSPICE") or shutil.which("ngspice")


@unittest.skipUnless(NGSPICE, "ngspice is optional for native SI regression")
class NativeEyeTests(unittest.TestCase):
    def test_jitter_survives_and_transient_completes(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            driver = """* Independent resistive I/O fixture
.SUBCKT fixture GND PIN
Vku KU GND pwl (0 0 1e-10 0 3e-10 1 1e-8 1 101e-10 1 103e-10 0 2e-8 0)
Vkd KD GND pwl (0 1 1e-10 1 3e-10 0 1e-8 0 101e-10 0 103e-10 1 2e-8 1)
Edriver OUT GND KU GND 1.5
Rdriver OUT DIE0 40
Cdie DIE0 GND 1p
.ENDS fixture
"""
            for name in ["positive", "negative"]:
                (scratch / f"{name}.sp").write_text(
                    driver
                    if name == "positive"
                    else driver.replace(
                        "Vku KU GND pwl (0 0 1e-10 0 3e-10 1 1e-8 1 101e-10 1 103e-10 0 2e-8 0)",
                        "Vku KU GND pwl (0 0 1e-8 0 101e-10 0 103e-10 1 2e-8 1 201e-10 1 203e-10 0 3e-8 0)",
                    ).replace(
                        "Vkd KD GND pwl (0 1 1e-10 1 3e-10 0 1e-8 0 101e-10 0 103e-10 1 2e-8 1)",
                        "Vkd KD GND pwl (0 1 1e-8 1 101e-10 1 103e-10 0 2e-8 0 201e-10 0 203e-10 1 3e-8 1)",
                    )
                )
            channel = scratch / "channel.sp"
            channel.write_text("unused in matched control\n")
            command = [
                sys.executable,
                str(ROOT / "scripts/si/simulate-dqs-eye.py"),
                "--channel",
                str(channel),
                "--driver",
                str(scratch / "positive.sp"),
                "--negative-driver",
                str(scratch / "negative.sp"),
                "--ngspice",
                NGSPICE,
                "--matched-reference",
                "--ui-count",
                "64",
                "--noise-mv",
                "0",
                "--dt-ps",
                "5",
                "--out",
                str(scratch / "eye"),
            ]
            run = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            import numpy as np

            waveform = np.loadtxt(
                scratch / "eye/waveforms.csv", skiprows=1, delimiter=","
            )
            self.assertGreater(waveform[-1, 0], 80e-9)
            self.assertTrue(np.isfinite(waveform).all())
            t = waveform[:, 0]
            v = waveform[:, 3] - waveform[:, 4]
            i = np.flatnonzero(v[:-1] * v[1:] < 0)
            edges = t[i] - v[i] * (t[i + 1] - t[i]) / (v[i + 1] - v[i])
            edges = edges[(edges > 20e-9) & (edges < 80e-9)]
            self.assertGreater(len(edges), 40)
            tie = edges - np.arange(len(edges)) * 1.25e-9
            tie -= tie.mean()
            self.assertGreater(np.std(tie) * 1e12, 7)
            self.assertLess(np.std(tie) * 1e12, 15)
            provenance = json.loads((scratch / "eye/provenance.json").read_text())
            self.assertFalse(provenance["signoff"])
            self.assertEqual(provenance["jitter"]["configuredInputRjRmsPs"], 10)

    def test_empty_conversion_rejected(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            model = scratch / "driver.sp"
            model.write_text(
                ".SUBCKT bad GND PIN\nVku KU GND pwl ()\nVkd KD GND pwl ()\n.ENDS bad\n"
            )
            channel = scratch / "channel.sp"
            channel.write_text("unused\n")
            run = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/si/simulate-dqs-eye.py"),
                    "--channel",
                    str(channel),
                    "--driver",
                    str(model),
                    "--negative-driver",
                    str(model),
                    "--ngspice",
                    NGSPICE,
                    "--out",
                    str(scratch / "eye"),
                    "--matched-reference",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((scratch / "eye/provenance.json").exists())


if __name__ == "__main__":
    unittest.main()
