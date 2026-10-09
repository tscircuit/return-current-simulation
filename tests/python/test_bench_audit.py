"""Independent finite-record controls for the read-only bench audit."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/si"
sys.path.insert(0, str(SCRIPTS))
import bench_audit_checks as audit


def physical_capture(directory, role):
    directory.mkdir(parents=True)
    for filename in audit.INPUT_ARTIFACTS:
        (directory / filename).write_bytes(b"identical physical source fixture\n")
    selector = '.include "/channel.sp"\nXpcb csrc cload pcb_channel' if role == "routed" else "Tref csrc 0 cload 0 Z0=100 TD=.4n"
    netlist = f'Assumed fixture\n.include "transmitter-stimulus.sp"\n.include "receiver-noise.sp"\nRsourcep srcp diep 50\nCprobep rxp 0 2e-13\n{selector}\n.control\ntran 2e-12 35e-9 10e-9 5e-13\n.endc\n.end\n'
    (directory / "simulation.cir").write_text(netlist)
    metadata = {key: {} for key in ("source", "noise", "jitter", "ioModels")}
    metadata.update({"analysisStartNs": 20, "analysisStopNs": 30, "rateMTs": 10000,
                     "sampleTimeStepPs": 2, "captureStartNs": 10, "integrationMethod": "trap",
                     "channel": {"model": role, "modelSha256": role}})
    (directory / "provenance.json").write_text(json.dumps(metadata))


def observed_capture(directory, phase):
    directory.mkdir()
    time = 10e-9 + np.arange(10001) * 2e-12
    voltage = np.cos(2 * np.pi * 5e9 * time + phase)
    np.savez(directory / "waveforms.npz", time_s=time, tx_p_v=0.75 + voltage / 2,
             tx_n_v=0.75 - voltage / 2, dqs_p_v=0.75 + voltage / 2,
             dqs_n_v=0.75 - voltage / 2, scope_noise_v=np.zeros(len(time)))
    metadata = {"analysisStartNs": 20, "analysisStopNs": 30, "rateMTs": 10000,
                "sampleTimeStepPs": 2, "timeStepPs": 2, "electricalTimeStepPs": 0.5 if phase == 0 else 0.25,
                "nominalSourcePhasePs": 5000.5, "nominalSourceFirstCenterPositive": True,
                "mode": "clock", "strobeGHz": 5}
    (directory / "provenance.json").write_text(json.dumps(metadata))


def metadata_only_case(paths):
    # Registry orchestration is isolated; the numerical checks have their own controls.
    json.loads((paths["raw"] / "provenance.json").read_text())
    return {"checks": []}


class BenchAuditTests(unittest.TestCase):
    def test_routed_only_uses_completed_cases_and_compares_circuit_without_zeroing_budgets(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            paths = audit.capture_paths(root, routed_only=True)
            self.assertEqual(set(paths), {"clean-routed", "noisy-routed", "noisy-routed-refined"})
            self.assertEqual(len(audit.capture_paths(root)), 5)
            for name, captures in paths.items():
                physical_capture(captures["raw"], "routed")
                if name != "clean-routed":
                    (captures["raw"] / "receiver-noise.sp").write_text("nonzero physical disturbance\n")
                    metadata = json.loads((captures["raw"] / "provenance.json").read_text())
                    metadata["noise"] = {"configuredRmsMv": 5}
                    (captures["raw"] / "provenance.json").write_text(json.dumps(metadata))
            with patch.object(audit, "audit_case", side_effect=metadata_only_case), \
                    patch.object(audit, "scope_pair_checks", return_value=[]), \
                    patch.object(audit, "refinement_comparison", return_value={}):
                report = audit.audit_bench(root, routed_only=True)
                self.assertTrue(report["pass"])
                self.assertEqual(set(report["cases"]), set(paths))
                self.assertEqual(set(report["pairedIdentityChecks"]),
                                 {"noisy routed electrical refinement", "clean/noisy routed circuit identity"})
                with self.assertRaises(FileNotFoundError):
                    audit.audit_bench(root)
                netlist = paths["clean-routed"]["raw"] / "simulation.cir"
                netlist.write_text(netlist.read_text().replace("Cprobep rxp 0 2e-13", "Cprobep rxp 0 3e-13"))
                self.assertFalse(audit.audit_bench(root, routed_only=True)["pass"])

    def test_pair_identity_allows_only_channel_and_electrical_step_substitutions(self):
        with tempfile.TemporaryDirectory() as scratch:
            routed, reference, refined = [Path(scratch) / name for name in ("routed", "reference", "refined")]
            for directory, role in ((routed, "routed"), (reference, "reference"), (refined, "routed")):
                physical_capture(directory, role)
            netlist = refined / "simulation.cir"
            netlist.write_text(netlist.read_text().replace("5e-13", "2.5e-13"))
            self.assertTrue(all(check["pass"] for check in audit.physical_input_checks(routed, reference)))
            self.assertTrue(all(check["pass"] for check in audit.physical_input_checks(routed, refined)))
            netlist.write_text(netlist.read_text().replace("Cprobep rxp 0 2e-13", "Cprobep rxp 0 3e-13"))
            self.assertFalse(all(check["pass"] for check in audit.physical_input_checks(routed, refined)))
            (reference / "receiver-noise.sp").write_text("changed physical disturbance\n")
            self.assertFalse(all(check["pass"] for check in audit.physical_input_checks(routed, reference)))

    def test_pwl_rms_integrates_the_continuous_triangle_and_clipped_edges(self):
        signal = np.array([0., 1., 2.]), np.array([0., 2., 0.])
        whole = audit.pwl_statistics(signal, (0, 2))
        self.assertAlmostEqual(whole["mean"], 1)
        self.assertAlmostEqual(whole["rms"], 2 / np.sqrt(3))
        clipped = audit.pwl_statistics(signal, (0.5, 1.5))
        self.assertAlmostEqual(clipped["mean"], 1.5)
        self.assertAlmostEqual(clipped["rms"], np.sqrt(7 / 3))
        with self.assertRaisesRegex(ValueError, "does not cover"):
            audit.pwl_statistics(signal, (-0.1, 2))

    def test_white_psd_power_and_band_fraction_use_physical_units(self):
        voltage = np.random.default_rng(8427).normal(scale=0.002, size=100000)
        report = audit.psd_diagnostics(voltage, {"dt_s": 2e-12, "corner_hz": 12e9,
                                                "b": [1], "a": [1], "white_rms": 0.002})
        self.assertAlmostEqual(report["expectedIntegratedPower"], 0.002**2, places=14)
        self.assertAlmostEqual(report["powerRatio"], 1, delta=0.025)
        self.assertAlmostEqual(report["observedBelowCornerPowerFraction"], 12e9 / 250e9, delta=0.005)
        self.assertIn("not pass/fail", report["interpretation"])

    def test_refinement_preserves_a_known_absolute_phase_difference(self):
        with tempfile.TemporaryDirectory() as scratch:
            coarse, refined = Path(scratch) / "coarse", Path(scratch) / "refined"
            observed_capture(coarse, 0)
            observed_capture(refined, 0.1)
            report = audit.refinement_comparison(coarse, refined)
            self.assertEqual(report["electricalMaxStepPs"], [0.5, 0.25])
            self.assertEqual(report["savedSampleTimeStepPs"], [2, 2])
            self.assertAlmostEqual(report["fundamentalPhaseDifferenceRad"], 0.1, places=11)
            self.assertGreater(report["waveformDifferenceV"]["maximumAbsolute"], 0.099)
            self.assertAlmostEqual(report["observedPadStatistics"][0]["fundamentalPeakV"], 1, places=11)
            self.assertEqual(len(report["eyeMetrics"]), 2)
            self.assertTrue(all(check["pass"] for check in audit.scope_pair_checks(coarse, refined)))
            with np.load(refined / "waveforms.npz") as saved:
                modified = {key: saved[key] for key in saved.files}
            modified["scope_noise_v"] = np.full(len(modified["time_s"]), 0.001)
            np.savez(refined / "waveforms.npz", **modified)
            self.assertFalse(all(check["pass"] for check in audit.scope_pair_checks(coarse, refined)))

    def test_cli_refuses_report_inside_input_or_hardlinked_to_an_artifact(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            capture = root / "captures/5ghz-clean-routed"
            capture.mkdir(parents=True)
            artifact = capture / "waveforms.npz"
            original = b"supplied artifact bytes\n"
            artifact.write_bytes(original)
            hardlink = root / "report.json"
            os.link(artifact, hardlink)
            for destination in (capture / "new-audit.json", hardlink):
                run = subprocess.run([sys.executable, str(SCRIPTS / "bench_audit.py"),
                                      "--root", str(root), "--out", str(destination)],
                                     capture_output=True, text=True, timeout=30)
                self.assertNotEqual(run.returncode, 0)
                self.assertNotIn("Traceback", run.stderr)
                self.assertEqual(artifact.read_bytes(), original)
            self.assertFalse((capture / "new-audit.json").exists())


if __name__ == "__main__":
    unittest.main()
