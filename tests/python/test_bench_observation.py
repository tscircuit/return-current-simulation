"""Analytic scope response and independent statistics validate instrument processing."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.signal import welch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/si"
sys.path.insert(0, str(SCRIPTS))
import bench_observation as observation


def analytic_scope(frequency):
    # Independently evaluate the prewarped analog Butterworth transfer function.
    ratio = np.tan(np.pi * np.asarray(frequency) / 500e9) / np.tan(np.pi * 12e9 / 500e9)
    return 1 / (1 - ratio**2 + 1j * np.sqrt(2) * ratio)


def capture(directory, electrical_step=0.5):
    directory.mkdir()
    time = 2990e-9 + np.arange(255001) * 2e-12
    differential = 0.1 + 0.4 * np.cos(2 * np.pi * 5e9 * (time - time[0]))
    waveforms = {"time_s": time, "tx_p_v": np.full(len(time), 1.1), "tx_n_v": np.full(len(time), 0.4),
                 "dqs_p_v": np.full(len(time), 0.77), "dqs_n_v": np.full(len(time), 0.73),
                 "pad_p_v": 0.75 + differential / 2, "pad_n_v": 0.75 - differential / 2}
    np.savez(directory / "waveforms.npz", **waveforms)
    metadata = {"kind": "independent analytic fixture", "benchScenario": True, "frequencyStress": True,
                "analysisStartNs": 3000, "analysisStopNs": 3500, "rateMTs": 10000,
                "sampleTimeStepPs": 2, "timeStepPs": 2, "electricalTimeStepPs": electrical_step,
                "nominalSourcePhasePs": 5000.5, "mode": "clock",
                "noise": {"configuredRmsMv": 5, "seed": 101},
                "jitter": {"configuredInputRjRmsPs": 10, "configuredPeriodicJitterPeakPs": 5},
                "limitations": ["Analytic fixture; no board validation."]}
    (directory / "provenance.json").write_text(json.dumps(metadata))
    (directory / "stimulus-events.csv").write_text("index,event_time_s,positive_state\n0,5.0005e-9,1\n")
    return waveforms, metadata


def noise_config(seed=50703, count=500000):
    return {"dt_s": 2e-12, "cutoff_hz": 12e9, "rms_v": 0.002,
            "seed": seed, "sample_count": count, "first_order_hold": False}


class BenchObservationTests(unittest.TestCase):
    def test_scope_has_analytic_gain_phase_dc_and_causal_step_response(self):
        time = np.arange(50000) * 2e-12
        for frequency in (6e9, 12e9, 24e9):
            with self.subTest(frequency=frequency):
                source = 0.75 + 0.4 * np.cos(2 * np.pi * frequency * time + 0.3)
                filtered = observation.scope_filter(source, 2e-12)
                settled = time >= 10e-9
                basis = np.column_stack([np.cos(2 * np.pi * frequency * time[settled]),
                                         np.sin(2 * np.pi * frequency * time[settled]), np.ones(settled.sum())])
                cosine, sine, dc = np.linalg.lstsq(basis, filtered[settled], rcond=None)[0]
                expected = 0.4 * np.exp(0.3j) * analytic_scope(frequency)
                self.assertAlmostEqual(abs(cosine - 1j * sine), abs(expected), places=10)
                self.assertAlmostEqual(np.angle((cosine - 1j * sine) / expected), 0, places=10)
                self.assertAlmostEqual(dc, 0.75, places=12)
        step = np.full(2000, 0.75)
        step[600:] = 1.25
        filtered = observation.scope_filter(step, 2e-12)
        np.testing.assert_allclose(filtered[:600], 0.75, atol=1e-12, rtol=0)
        self.assertGreater(filtered[600], 0.75)
        self.assertLess(filtered[600], 0.8)
        self.assertAlmostEqual(filtered[-1], 1.25, places=12)

    def test_noise_variance_and_psd_match_independent_stationary_prediction(self):
        noise, report = observation.butterworth_noise(noise_config())
        frequency = np.linspace(0, 250e9, 131073)
        stationary_variance = np.trapezoid(abs(analytic_scope(frequency))**2, frequency) / 250e9
        self.assertAlmostEqual(report["unitWhiteKnotVariance"], stationary_variance, places=12)
        self.assertAlmostEqual(report["theoreticalKnotRmsV"], 0.002, places=14)
        self.assertAlmostEqual(noise.std(), 0.002, delta=0.00006)
        # A fixed seed deliberately retains its finite-record fluctuation.
        self.assertGreater(abs(noise.std() - 0.002), 1e-8)
        frequencies, psd = welch(noise, fs=500e9, nperseg=8192)
        prediction = 2 * (0.002**2 / stationary_variance) / 500e9 * abs(analytic_scope(frequencies))**2
        for low, high in ((0.5e9, 4e9), (10e9, 14e9), (24e9, 28e9)):
            band = (frequencies >= low) & (frequencies < high)
            self.assertAlmostEqual(psd[band].mean() / prediction[band].mean(), 1, delta=0.12)
        first_samples = [observation.butterworth_noise(noise_config(seed, 2))[0][0] for seed in range(512)]
        self.assertAlmostEqual(np.std(first_samples), 0.002, delta=0.00025)

    def test_selected_plane_dc_thresholds_and_raw_fields_are_preserved(self):
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch) / "raw"
            raw, metadata = capture(source)
            observed, report = observation.observe_capture(source, {"plane": "pads", "scope_noise_mv": 0})
            time = raw["time_s"]
            mask = (time >= 3000e-9) & (time < 3500e-9)
            voltage = (observed["dqs_p_v"] - observed["dqs_n_v"])[mask]
            self.assertAlmostEqual(voltage.mean(), 0.1, delta=1e-5)
            self.assertGreater(voltage.max(), 0.2)
            self.assertLess(voltage.min(), -0.2)
            np.testing.assert_array_equal(observed["raw_dqs_p_v"], raw["dqs_p_v"])
            np.testing.assert_array_equal(observed["pad_p_v"], raw["pad_p_v"])
            np.testing.assert_array_equal(observed["tx_p_v"], raw["tx_p_v"])
            np.testing.assert_array_equal(observed["scope_noise_v"], 0)
            self.assertEqual(report["noise"], metadata["noise"])
            self.assertEqual(report["jitter"], metadata["jitter"])
            self.assertEqual(report["observation"]["plane"], "receiver package pads")
            self.assertAlmostEqual(report["observation"]["analysisWindowUiCount"], 5000)
            die, die_report = observation.observe_capture(source, {"plane": "die", "scope_noise_mv": 0})
            np.testing.assert_allclose(die["dqs_p_v"] - die["dqs_n_v"], 0.04, atol=1e-12, rtol=0)
            self.assertEqual(die_report["observation"]["plane"], "receiver die")
            self.assertFalse(report["signoff"])

    def test_scope_noise_is_identical_across_electrical_timestep_refinement(self):
        with tempfile.TemporaryDirectory() as scratch:
            sources = [Path(scratch) / name for name in ("coarse", "refined")]
            observations = []
            for source, step in zip(sources, (0.5, 0.25)):
                capture(source, step)
                observations.append(observation.observe_capture(source, {"scope_noise_mv": 2, "seed": 50703}))
            np.testing.assert_array_equal(observations[0][0]["scope_noise_v"], observations[1][0]["scope_noise_v"])
            for waveforms, metadata in observations:
                noise = waveforms["scope_noise_v"]
                np.testing.assert_allclose((waveforms["dqs_p_v"] - waveforms["dqs_n_v"])
                                           - (waveforms["scope_filtered_p_v"] - waveforms["scope_filtered_n_v"]), noise, atol=3e-16)
                self.assertAlmostEqual(metadata["observation"]["measuredAnalysisNoise"]["acRmsMv"], 2, delta=0.08)
                self.assertEqual(metadata["observation"]["noiseGenerationGrid"]["sampleIntervalPs"], 2)

    def test_missing_warmup_truncation_and_changed_sampling_are_rejected(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw, metadata = capture(Path(scratch) / "raw")
            for label, altered in (("warmup", {**metadata, "analysisStartNs": 2995}),
                                   ("truncation", {**metadata, "analysisStopNs": 3502}),
                                   ("sampling", {**metadata, "sampleTimeStepPs": 4})):
                with self.subTest(label=label), self.assertRaises(ValueError):
                    observation.validate_capture(raw, altered)
            gap = dict(raw)
            gap["time_s"] = raw["time_s"].copy()
            gap["time_s"][20] += 1e-12
            with self.assertRaisesRegex(ValueError, "uniform 2 ps"):
                observation.validate_capture(gap, metadata)

    def test_cli_exports_hashes_and_refuses_input_collisions_before_writing(self):
        with tempfile.TemporaryDirectory() as scratch:
            source, destination = Path(scratch) / "raw", Path(scratch) / "observed"
            capture(source)
            original = {path.name: path.read_bytes() for path in source.iterdir()}
            command = [sys.executable, str(SCRIPTS / "bench_observation.py"), str(source), "--scope-noise-mv", "0", "--out"]
            for collision in (source, source / "new-output", source.parent):
                run = subprocess.run(command + [str(collision)], capture_output=True, text=True, timeout=30)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("must not overlap", run.stderr)
                self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, original)
            destination.mkdir()
            (destination / "waveforms.npz").symlink_to(source / "waveforms.npz")
            run = subprocess.run(command + [str(destination)], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("overlaps supplied input", run.stderr)
            (destination / "waveforms.npz").unlink()
            run = subprocess.run(command + [str(destination)], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            metadata = json.loads((destination / "provenance.json").read_text())
            report = metadata["observation"]
            self.assertEqual(report["waveformsSha256"], hashlib.sha256((destination / "waveforms.npz").read_bytes()).hexdigest())
            self.assertEqual(report["sourceWaveformsSha256"], hashlib.sha256(original["waveforms.npz"]).hexdigest())
            self.assertEqual((destination / "stimulus-events.csv").read_bytes(), original["stimulus-events.csv"])
            self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, original)


if __name__ == "__main__":
    unittest.main()
