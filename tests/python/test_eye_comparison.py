"""Closed-eye comparisons use analytic captures, not board validation evidence."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


eye = module("eye_comparison", ROOT / "scripts/si/eye_comparison.py")
analysis = module("waveforms", ROOT / "scripts/analyze-ddr-waveforms.py")


def capture(rate=800, amplitude=1.5, count=100):
    ui = 1 / (rate * 1e6)
    t = 5e-9 + np.arange(count * 100) * ui / 100
    differential = amplitude * np.sin(np.pi * (t - 5e-9) / ui)
    waveform = np.column_stack([t, 0.75 + differential / 2, 0.75 - differential / 2,
                               0.75 + differential / 2, 0.75 - differential / 2])
    meta = {"rateMTs": rate, "clockMHz": rate / 2, "mode": "clock",
            "analysisStartNs": float(t[0] * 1e9), "analysisStopNs": float(t[-1] * 1e9),
            "nominalSourcePhasePs": 5000, "nominalSourceFirstCenterPositive": True,
            "frequencyStress": rate > 800,
            "experimentDescription": "Ideal-source bandwidth stress; high-rate fit extrapolation",
            "limitations": ["Ideal source, no AM3352 switching model.", "20 GHz exceeds the extracted 5 GHz channel bandwidth."],
            "ioModels": {"odtOhmsPerLeg": 60, "receiverCapacitancePf": 2},
            "jitter": {"configuredInputRjRmsPs": 0, "configuredPeriodicJitterPeakPs": 0},
            "noise": {"configuredRmsMv": 0}}
    return waveform, meta


class EyeComparisonTests(unittest.TestCase):
    def test_valid_clock_keeps_original_finite_record_metrics(self):
        waveform, meta = capture()
        report, _ = eye.eye_diagnostics(waveform, meta, analysis)
        t, voltage = waveform[:, 0], waveform[:, 3] - waveform[:, 4]
        ui = 1 / (meta["rateMTs"] * 1e6)
        _, tie, phase = analysis.strobe_timing(t, voltage, ui)
        indices = np.arange(np.ceil((t[0] - phase) / ui - 0.5), np.floor((t[-1] - phase) / ui - 0.5) + 1)
        samples = phase + (indices + 0.5) * ui
        samples = samples[(samples > t[0]) & (samples < t[-1])]
        levels = np.interp(samples, t, voltage)
        height = levels[levels > 0].min() - levels[levels < 0].max()
        windows = [analysis.valid_margin(t, voltage, sample, 0.2 if level > 0 else -0.2, level > 0)
                   for sample, level in zip(samples, levels)]
        windows = [window for window in windows if window]
        width = (min(right for left, right in windows) + min(left for left, right in windows)) * 1e12
        self.assertAlmostEqual(report["finiteCaptureEyeHeightV"], height)
        self.assertAlmostEqual(report["commonOpeningAt200mVThresholdPs"], width)
        self.assertEqual(report["receiverTie"], analysis.stats_ps(tie))
        self.assertEqual(report["nominalThresholdFailures"], 0)

    def test_closed_eye_without_crossings_has_unavailable_timing(self):
        waveform, meta = capture(40000, 0)
        report, arrays = eye.eye_diagnostics(waveform, meta, analysis)
        self.assertFalse(report["timingAvailable"])
        self.assertIsNone(report["receiverTie"])
        self.assertIn("32", report["timingUnavailableReason"])
        self.assertEqual(report["commonOpeningAt200mVThresholdPs"], 0)
        self.assertIsNone(report["finiteCaptureEyeHeightV"])
        self.assertIn("source", report["nominalPhaseBasis"])
        self.assertAlmostEqual(arrays["ui"] * 1e12, 25)

    def test_one_invalid_nominal_center_closes_the_common_opening(self):
        waveform, meta = capture()
        ui = 1 / (meta["rateMTs"] * 1e6)
        center = 5e-9 + 32.5 * ui
        bad = np.abs(waveform[:, 0] - center) < ui * 0.1
        waveform[bad, 3:5] = 0.75 + (waveform[bad, 3:5] - 0.75) * 0.02
        report, _ = eye.eye_diagnostics(waveform, meta, analysis)
        self.assertGreater(report["nominalThresholdFailures"], 0)
        self.assertGreater(report["completeThresholdWindows"], 10)
        self.assertEqual(report["commonOpeningAt200mVThresholdPs"], 0)

    def test_wrong_clock_polarity_does_not_fabricate_positive_height(self):
        waveform, meta = capture()
        waveform[:, [3, 4]] = waveform[:, [4, 3]]
        report, _ = eye.eye_diagnostics(waveform, meta, analysis, nominal_phase_ps=5000)
        self.assertEqual(report["commonOpeningAt200mVThresholdPs"], 0)
        self.assertIsNone(report["finiteCaptureEyeHeightV"])

    def test_unipolar_signal_has_no_differential_eye_height(self):
        waveform, meta = capture(40000, 0.1)
        waveform[:, 3] += 0.15
        waveform[:, 4] -= 0.15
        report, _ = eye.eye_diagnostics(waveform, meta, analysis)
        self.assertIsNone(report["finiteCaptureEyeHeightV"])
        self.assertEqual(report["commonOpeningAt200mVThresholdPs"], 0)
        self.assertFalse(report["timingAvailable"])

    def test_timing_failure_without_a_phase_is_rejected(self):
        waveform, meta = capture(40000, 0)
        meta.pop("nominalSourcePhasePs")
        with self.assertRaisesRegex(ValueError, "no explicit or source nominal phase"):
            eye.eye_diagnostics(waveform, meta, analysis)
        report, _ = eye.eye_diagnostics(waveform, meta, analysis, nominal_phase_ps=5000)
        self.assertEqual(report["commonOpeningAt200mVThresholdPs"], 0)

    def test_stress_windows_and_three_or_four_column_events(self):
        waveform, meta = capture(40000)
        window = eye.waveform_window(waveform, meta)
        self.assertEqual(len(window), len(waveform))
        mask = eye.transient_bounds(window[:, 0], meta, 25e-12)
        self.assertAlmostEqual(np.ptp(window[mask, 0]) * 1e12, 200, delta=0.3)
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            for extra in (False, True):
                rows = [[0, 5e-9, 1], [1, 5.025e-9, 0]]
                if extra:
                    rows = [row + [row[1] - 0.5e-12] for row in rows]
                np.savetxt(directory / "stimulus-events.csv", rows, delimiter=",", header="events", comments="")
                self.assertEqual(eye.source_events(directory).shape, (2, 3))
            rows[1][1] = rows[0][1]
            np.savetxt(directory / "stimulus-events.csv", rows, delimiter=",", header="events", comments="")
            with self.assertRaisesRegex(ValueError, "increasing times"):
                eye.source_events(directory)

    def test_closed_eye_cli_exports_figures_and_valid_json(self):
        waveform, meta = capture(40000, 0)
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            for name in ("routed", "reference"):
                directory = scratch / name
                directory.mkdir()
                np.savez_compressed(directory / "waveforms.npz", **dict(zip(
                    ["time_s", "tx_p_v", "tx_n_v", "dqs_p_v", "dqs_n_v"], waveform.T)))
                (directory / "provenance.json").write_text(json.dumps(meta))
            env = dict(os.environ, MPLCONFIGDIR=str(scratch / "matplotlib"))
            run = subprocess.run([sys.executable, str(ROOT / "scripts/si/compare-eyes.py"),
                                  str(scratch / "routed"), str(scratch / "reference"), "--out", str(scratch / "comparison")],
                                 capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            output = scratch / "comparison"
            report = json.loads((output / "comparison.json").read_text())
            self.assertTrue((output / "eye-comparison.png").is_file())
            self.assertTrue((output / "eye-comparison.svg").is_file())
            self.assertTrue(all(case["commonOpeningAt200mVThresholdPs"] == 0 for case in report["cases"]))
            self.assertTrue(all(case["finiteCaptureEyeHeightV"] is None for case in report["cases"]))
            self.assertTrue(all(case["receiverTie"] is None for case in report["cases"]))
            self.assertNotIn("IBIS", report["cases"][0]["label"])


if __name__ == "__main__":
    unittest.main()
