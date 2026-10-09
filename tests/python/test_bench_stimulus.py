"""Independent statistics and waveform controls for assumed bench disturbances."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.signal import butter, freqz

ROOT = Path(__file__).resolve().parents[2]
BENCH_SCRIPT = ROOT / "scripts/si/simulate-dqs-bench.py"
NGSPICE = os.environ.get("SI_NGSPICE") or shutil.which("ngspice")
spec = importlib.util.spec_from_file_location(
    "bench_stimulus", ROOT / "scripts/si/bench_stimulus.py"
)
stimulus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stimulus)


def noise_config(**changes):
    config = {
        "dt_s": 1e-10,
        "cutoff_hz": 2e9,
        "rms_v": 0.002,
        "seed": 40503,
        "sample_count": 262144,
    }
    return {**config, **changes}


def timing_config(**changes):
    config = {
        "ui_s": 25e-12,
        "rise_s": 1e-12,
        "delay_s": 5e-9,
        "ui_count": 512,
        "rj_rms_s": 0,
        "rj_corner_hz": 500e6,
        "pj_peak_s": 0,
        "pj_frequency_hz": 500e6,
        "timing_seed": 40501,
        "end_s": 18e-9,
    }
    return {**config, **changes}


def independent_noise_covariance(config):
    # Spectral integration is independent of the helper's state covariance
    # calculation. For unit white input, lag k is the inverse PSD transform.
    b, a = butter(2, 2 * config["cutoff_hz"] * config["dt_s"])
    frequency, response = freqz(b, a, worN=131072, whole=True)
    power = np.abs(response) ** 2
    variance = np.mean(power)
    lag_one = np.mean(power * np.cos(frequency))
    return variance, lag_one


class StationaryDisturbanceTests(unittest.TestCase):
    def test_noise_seed_and_prefix_are_stable_without_realization_rescaling(self):
        short, report = stimulus.butterworth_noise(noise_config(sample_count=256))
        repeated, _ = stimulus.butterworth_noise(noise_config(sample_count=256))
        longer, _ = stimulus.butterworth_noise(noise_config(sample_count=512))
        changed_seed, _ = stimulus.butterworth_noise(noise_config(sample_count=256, seed=40504))
        np.testing.assert_array_equal(short, repeated)
        np.testing.assert_array_equal(short, longer[: len(short)])
        self.assertFalse(np.array_equal(short, changed_seed))
        self.assertFalse(report["perRealizationRmsNormalization"])

    def test_long_noise_matches_independent_spectrum_and_stationary_rms(self):
        config = noise_config()
        values, report = stimulus.butterworth_noise(config)
        variance, lag_one = independent_noise_covariance(config)
        self.assertAlmostEqual(report["unitWhiteKnotVariance"] / variance, 1, places=10)
        self.assertAlmostEqual(report["unitWhiteLagOneCovariance"] / lag_one, 1, places=10)
        expected_correlation = lag_one / variance
        observed_correlation = np.corrcoef(values[:-1], values[1:])[0, 1]
        self.assertLess(abs(observed_correlation - expected_correlation), 0.008)
        self.assertLess(abs(np.std(values) / config["rms_v"] - 1), 0.015)
        self.assertLess(abs(np.mean(values)) / config["rms_v"], 0.015)

    def test_first_order_hold_normalization_matches_continuous_segment_energy(self):
        config = noise_config(first_order_hold=True)
        values, report = stimulus.butterworth_noise(config)
        variance, lag_one = independent_noise_covariance(config)
        hold_variance = (2 * variance + lag_one) / 3
        self.assertAlmostEqual(report["stationaryGain"] / np.sqrt(hold_variance), 1, places=10)
        self.assertAlmostEqual(report["theoreticalContinuousRmsV"], config["rms_v"])
        self.assertAlmostEqual(
            report["theoreticalKnotRmsV"] / config["rms_v"],
            np.sqrt(variance / hold_variance),
            places=10,
        )
        # Integral of the squared linear segment between successive knots.
        continuous_rms = np.sqrt(np.mean(
            (values[:-1] ** 2 + values[:-1] * values[1:] + values[1:] ** 2) / 3
        ))
        self.assertLess(abs(continuous_rms / config["rms_v"] - 1), 0.015)
        self.assertGreater(np.std(values) / config["rms_v"], 1.05)

    def test_ou_timing_has_stationary_rms_and_expected_decay(self):
        config = {
            "ui_s": 25e-12,
            "corner_hz": 2e9,
            "rms_s": 50e-15,
            "seed": 40501,
            "sample_count": 262144,
        }
        values, report = stimulus.ou_jitter(config)
        alpha = np.exp(-2 * np.pi * config["corner_hz"] * config["ui_s"])
        self.assertAlmostEqual(report["ar1Coefficient"], alpha)
        self.assertLess(abs(np.std(values) / config["rms_s"] - 1), 0.02)
        for lag in (1, 10):
            with self.subTest(lag=lag):
                correlation = np.corrcoef(values[:-lag], values[lag:])[0, 1]
                self.assertLess(abs(correlation - alpha ** lag), 0.01)
        short, _ = stimulus.ou_jitter({**config, "sample_count": 256})
        np.testing.assert_array_equal(short, values[: len(short)])
        repeated, _ = stimulus.ou_jitter({**config, "sample_count": 256})
        changed_seed, _ = stimulus.ou_jitter({**config, "sample_count": 256, "seed": 40502})
        np.testing.assert_array_equal(short, repeated)
        self.assertFalse(np.array_equal(short, changed_seed))
        self.assertFalse(report["perRealizationRmsNormalization"])

    def test_noise_and_timing_are_stationary_from_the_first_sample(self):
        noise = np.array([
            stimulus.butterworth_noise(noise_config(seed=seed, sample_count=2))[0]
            for seed in range(1500)
        ])
        jitter = np.array([
            stimulus.ou_jitter({
                "ui_s": 25e-12, "corner_hz": 2e9, "rms_s": 50e-15,
                "seed": seed, "sample_count": 2,
            })[0]
            for seed in range(1500)
        ])
        for name, samples, sigma in (("noise", noise, 0.002), ("timing", jitter, 50e-15)):
            with self.subTest(process=name):
                np.testing.assert_allclose(np.std(samples, axis=0) / sigma, 1, atol=0.08, rtol=0)
                self.assertLess(np.max(np.abs(np.mean(samples, axis=0))) / sigma, 0.08)

    def test_zero_noise_and_invalid_filter_configuration(self):
        values, _ = stimulus.butterworth_noise(noise_config(rms_v=0, sample_count=64))
        np.testing.assert_array_equal(values, np.zeros(64))
        for changes in (
            {"dt_s": 0}, {"cutoff_hz": 0}, {"cutoff_hz": 5e9},
            {"cutoff_hz": float("nan")}, {"rms_v": -1},
            {"sample_count": 1}, {"seed": -1},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    stimulus.butterworth_noise(noise_config(**changes))


class SourceTransitionTests(unittest.TestCase):
    def test_clean_source_has_nominal_crossings_and_complementary_transitions(self):
        config = timing_config()
        events, report = stimulus.source_events(config)
        expected = config["delay_s"] + config["rise_s"] / 2 + np.arange(512) * config["ui_s"]
        np.testing.assert_array_equal(events["crossing_s"], expected)
        np.testing.assert_array_equal(events["rj_s"], np.zeros(512))
        np.testing.assert_array_equal(events["pj_s"], np.zeros(512))
        np.testing.assert_array_equal(events["state"], 1 - np.arange(512) % 2)
        times, positive, negative = stimulus.source_pwl(events, config["end_s"], config["rise_s"])
        self.assertTrue(np.all(np.diff(times) > 0))
        np.testing.assert_array_equal(positive + negative, np.full(len(times), 1.5))
        np.testing.assert_allclose(np.interp(expected, times, positive), 0.75, atol=1e-10, rtol=0)
        np.testing.assert_allclose(np.interp(expected, times, negative), 0.75, atol=1e-10, rtol=0)
        self.assertTrue(report["sharedByComplementaryLegs"])
        self.assertFalse(report["transitionOverlap"])

    def test_zero_budget_pwl_matches_independent_pulse_on_flats_and_ramps(self):
        config = timing_config()
        events, _ = stimulus.source_events(config)
        times, positive, negative = stimulus.source_pwl(events, config["end_s"], config["rise_s"])
        transition_samples = (
            events["transition_start_s"][:128, None]
            + config["rise_s"] * np.array([-0.5, 0, 0.25, 0.5, 0.75, 1, 1.5])
        ).ravel()
        flat_samples = config["delay_s"] + (np.arange(128) + 0.5) * config["ui_s"]
        samples = np.concatenate(([0, config["delay_s"] / 2], transition_samples, flat_samples))
        phase = np.mod(samples - config["delay_s"], 2 * config["ui_s"])
        expected = np.where(
            phase < config["rise_s"],
            1.5 * phase / config["rise_s"],
            np.where(
                phase < config["ui_s"],
                1.5,
                np.clip(1.5 * (1 - (phase - config["ui_s"]) / config["rise_s"]), 0, 1.5),
            ),
        )
        expected[samples < config["delay_s"]] = 0
        np.testing.assert_allclose(np.interp(samples, times, positive), expected, atol=1e-8, rtol=0)
        np.testing.assert_allclose(np.interp(samples, times, negative), 1.5 - expected, atol=1e-8, rtol=0)

    def test_periodic_jitter_frequency_remains_physical_when_ui_changes(self):
        for ui in (100e-12, 250e-12):
            with self.subTest(ui_ps=ui * 1e12):
                config = timing_config(
                    ui_s=ui, ui_count=128, end_s=40e-9,
                    pj_frequency_hz=50e6, pj_peak_s=100e-15,
                )
                events, report = stimulus.source_events(config)
                quarter_period_index = round(5e-9 / ui)
                self.assertAlmostEqual(
                    (events["nominal_crossing_s"][quarter_period_index]
                     - events["nominal_crossing_s"][0]) * 1e9,
                    5,
                )
                self.assertAlmostEqual(events["pj_s"][quarter_period_index] / config["pj_peak_s"], 1)
                self.assertEqual(report["periodicJitterHz"], 50e6)

    def test_periodic_jitter_displacement_is_measured_at_nominal_crossings(self):
        config = timing_config(pj_peak_s=100e-15)
        events, report = stimulus.source_events(config)
        nominal = events["nominal_crossing_s"]
        expected = config["pj_peak_s"] * np.sin(
            2 * np.pi * config["pj_frequency_hz"] * (nominal - nominal[0])
        )
        np.testing.assert_allclose(events["crossing_s"] - nominal, expected, atol=2e-24, rtol=0)
        self.assertEqual(report["periodicJitterPhaseOriginS"], nominal[0])

    def test_unordered_overlapping_and_out_of_range_events_are_rejected(self):
        ui = 25e-12
        for changes in (
            {"pj_peak_s": 40e-12, "pj_frequency_hz": 1 / (4 * ui)},
            {"pj_peak_s": 24.5e-12, "pj_frequency_hz": 1 / (4 * ui)},
            {"end_s": 5e-9 + 511 * ui + 0.5e-12},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    stimulus.source_events(timing_config(**changes))


class BenchRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bench_runner", BENCH_SCRIPT)
        cls.bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bench)

    @staticmethod
    def tiny_arguments():
        return [
            "--channel", "/unused", "--ngspice", "/unused", "--out", "/unused",
            "--ui-count", "256", "--capture-start-ns", "10",
            "--analysis-start-ns", "12", "--analysis-stop-ns", "28",
            "--timeout-seconds", "20",
        ]

    def test_sampling_and_analysis_bounds_are_checked(self):
        parser = self.bench.build_parser()
        valid = self.bench.derive_timing(parser.parse_args(self.tiny_arguments()))
        self.assertAlmostEqual(valid["sample_dt_s"] * 1e12, 2)
        self.assertAlmostEqual(valid["electrical_dt_s"] * 1e12, 0.5)
        self.assertAlmostEqual(valid["capture_start_s"] * 1e9, 10)
        for changes in (
            ["--sample-ps", "0.25"], ["--sample-ps", "10"],
            ["--dt-ps", "1"], ["--capture-start-ns", "13"],
            ["--capture-start-ns", "11.5"], ["--analysis-stop-ns", "32"],
            ["--analysis-start-ns", "26"], ["--noise-grid-ps", "1000"],
            ["--rj-ps", "nan"], ["--probe-pf", "-1"], ["--timing-seed", "-1"],
        ):
            with self.subTest(changes=changes):
                args = parser.parse_args(self.tiny_arguments() + changes)
                with self.assertRaises(ValueError):
                    self.bench.derive_timing(args)

    def test_channel_collision_preserves_input_before_any_output_write(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            for kind in ("direct", "symlink", "hardlink"):
                with self.subTest(alias_kind=kind):
                    case = scratch / kind
                    output = case / "out"
                    output.mkdir(parents=True)
                    target = output / "simulation.cir"
                    channel = target if kind == "direct" else case / "channel.sp"
                    original = b"* Channel bytes must survive a rejected collision\n"
                    channel.write_bytes(original)
                    if kind == "symlink":
                        target.symlink_to(channel)
                    elif kind == "hardlink":
                        os.link(channel, target)
                    command = [
                        sys.executable, str(BENCH_SCRIPT), *self.tiny_arguments(),
                        "--channel", str(channel), "--out", str(output),
                        "--ngspice", str(case / "nonexistent-ngspice"),
                    ]
                    run = subprocess.run(command, capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertEqual(channel.read_bytes(), original)
                    self.assertEqual(target.read_bytes(), original)
                    self.assertEqual(list(output.iterdir()), [target])

    @unittest.skipUnless(NGSPICE, "ngspice is optional for native bench regression")
    def test_short_native_capture_has_loaded_probes_and_independent_saved_grid(self):
        def fundamental(time, voltage):
            phase = 2 * np.pi * 5e9 * time
            basis = np.column_stack((np.cos(phase), np.sin(phase), np.ones_like(time)))
            fit = np.linalg.lstsq(basis, voltage, rcond=None)[0]
            return fit[0] - 1j * fit[1]

        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            channel = scratch / "rc-channel.sp"
            channel.write_text(
                "* Independent analytic control; no EM or vendor I/O claims\n"
                ".subckt pcb_channel in out\nRfixture in out 100\n"
                "Cfixture out 0 2p\n.ends pcb_channel\n"
            )
            captures = {}
            for name, dt, probe, clean in (
                ("noisy-05", 0.5, 0.2, False),
                ("noisy-025", 0.25, 0.2, False),
                ("clean-loaded", 0.5, 0.2, True),
                ("clean-unloaded", 0.5, 0, True),
            ):
                with self.subTest(case=name):
                    output = scratch / name
                    command = [
                        sys.executable, str(BENCH_SCRIPT), *self.tiny_arguments(),
                        "--channel", str(channel), "--ngspice", NGSPICE,
                        "--out", str(output), "--dt-ps", str(dt), "--probe-pf", str(probe),
                    ]
                    if clean:
                        command += ["--rj-ps", "0", "--pj-ps", "0", "--noise-mv", "0"]
                    run = subprocess.run(command, capture_output=True, text=True, timeout=40)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    with np.load(output / "waveforms.npz") as stored:
                        waveform = dict(stored)
                    expected_keys = {
                        "time_s", "tx_p_v", "tx_n_v", "dqs_p_v", "dqs_n_v",
                        "channel_input_v", "channel_output_v", "pad_p_v", "pad_n_v",
                    }
                    self.assertEqual(set(waveform), expected_keys)
                    self.assertTrue(all(np.isfinite(values).all() for values in waveform.values()))
                    time = waveform["time_s"]
                    self.assertLessEqual(abs(time[0] - 10e-9), 2e-12)
                    self.assertGreaterEqual(time[-1], 31.4e-9 - 2e-12)
                    np.testing.assert_allclose(np.diff(time), 2e-12, rtol=1e-8, atol=0)
                    raw = np.loadtxt(output / "waveforms.dat", skiprows=1)
                    self.assertEqual(raw.shape[1], 9)
                    metadata = json.loads((output / "provenance.json").read_text())
                    self.assertFalse(metadata["signoff"])
                    self.assertTrue(metadata["benchScenario"])
                    self.assertEqual(metadata["sampleTimeStepPs"], 2)
                    self.assertEqual(metadata["electricalTimeStepPs"], dt)
                    self.assertEqual(metadata["ioModels"]["probeCapacitancePfPerLeg"], probe)
                    self.assertFalse(metadata["sourceTimingReport"]["rj"]["perRealizationRmsNormalization"])
                    self.assertFalse(metadata["receiverSeriesNoiseReport"]["perRealizationRmsNormalization"])
                    self.assertTrue(metadata["receiverSeriesNoiseReport"]["firstOrderHold"])
                    probe_report = json.loads((output / "probe-report.json").read_text())
                    self.assertEqual(probe_report["nodes"], ["rxp", "rxn"])
                    self.assertEqual(probe_report["configuredCapacitancePfPerLeg"], probe)
                    with np.load(output / "commanded-noise.npz") as noise:
                        expected_noise = np.interp(time, noise["time_s"], noise["differential_v"])
                    actual_noise = waveform["pad_p_v"] - waveform["pad_n_v"] - waveform["channel_output_v"]
                    np.testing.assert_allclose(actual_noise, expected_noise, atol=1e-7, rtol=0)
                    if clean:
                        selected = (time >= 12e-9) & (time < 28e-9)
                        actual = fundamental(time[selected], waveform["channel_output_v"][selected]) / fundamental(
                            time[selected], waveform["channel_input_v"][selected]
                        )
                        s = 2j * np.pi * 5e9

                        def receiver(r, inductance, capacitance):
                            return s * (capacitance + probe * 1e-12) + 1 / (
                                r + s * inductance + 1 / (1 / 60 + s * 2e-12)
                            )

                        admittance = (
                            receiver(0.42069, 1.1804e-9, 0.41107e-12)
                            + receiver(0.39422, 1.1796e-9, 0.42404e-12)
                        ) / 4
                        expected = 1 / (1 + 100 * (s * 2e-12 + admittance))
                        self.assertLess(abs(actual / expected - 1), 0.01)
                    captures[name] = waveform
            np.testing.assert_array_equal(captures["noisy-05"]["time_s"], captures["noisy-025"]["time_s"])
            loaded = captures["clean-loaded"]["pad_p_v"] - captures["clean-loaded"]["pad_n_v"]
            unloaded = captures["clean-unloaded"]["pad_p_v"] - captures["clean-unloaded"]["pad_n_v"]
            self.assertGreater(np.linalg.norm(loaded - unloaded) / np.linalg.norm(unloaded), 0.001)


if __name__ == "__main__":
    unittest.main()
