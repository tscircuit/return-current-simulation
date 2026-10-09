"""Analytic low-pass controls for explicitly idealized bandwidth stress.

These fixtures have no vendor model or claim of feasible DDR operation.
"""

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

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/si/stress-dqs-bandwidth.py"
NGSPICE = os.environ.get("SI_NGSPICE") or shutil.which("ngspice")


def phasor(time, voltage, frequency):
    """Recover the fundamental, including phase, without peak sampling bias."""
    angle = 2 * np.pi * frequency * time
    basis = np.column_stack((np.cos(angle), np.sin(angle), np.ones_like(angle)))
    coefficients = np.linalg.lstsq(basis, voltage, rcond=None)[0]
    return coefficients[0] - 1j * coefficients[1]


class StressTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bandwidth_stress", SCRIPT)
        cls.stress = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.stress)

    def test_nonphysical_or_unresolved_timing_is_rejected(self):
        cases = [
            (0, 0.5, 256),
            (-1, 0.5, 256),
            (float("nan"), 0.5, 256),
            (float("inf"), 0.5, 256),
            (4, 0, 256),
            (4, -1, 256),
            (4, float("nan"), 256),
            (4, float("inf"), 256),
            (4, 1e4, 256),
            (4, 0.5, 0),
            (4, 0.5, 63),
            (20, 0.25, 100),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    self.stress.derive_timing(*arguments)

    def test_twenty_ghz_clock_has_forty_gt_per_second_edge_rate(self):
        timing = self.stress.derive_timing(20, 0.25, 512)
        self.assertAlmostEqual(timing["ui_s"] * 1e12, 25)
        self.assertAlmostEqual(timing["period_s"] * 1e12, 50)
        self.assertAlmostEqual(1 / timing["ui_s"] / 1e9, 40)
        self.assertGreater(timing["analysis_stop_s"], timing["analysis_start_s"])
        self.assertGreater(timing["end_s"], timing["analysis_stop_s"])

    def test_explicit_late_window_uses_requested_time_without_retiming_source(self):
        default = self.stress.derive_timing(20, 0.25, 4096)
        timing = self.stress.derive_timing(
            20, 0.25, 4096, analysis_window={"start_ns": 80, "stop_ns": 100}
        )
        self.assertAlmostEqual(timing["analysis_start_s"] * 1e9, 80)
        self.assertAlmostEqual(timing["analysis_stop_s"] * 1e9, 100)
        window_ui_count = (
            timing["analysis_stop_s"] - timing["analysis_start_s"]
        ) / timing["ui_s"]
        self.assertAlmostEqual(window_ui_count, 800)
        for key in ("ui_s", "period_s", "nominal_phase_s", "end_s"):
            self.assertEqual(timing[key], default[key])

    def test_invalid_explicit_analysis_windows_are_rejected(self):
        windows = [
            (float("nan"), 100),
            (80, float("inf")),
            (100, 80),
            (80, 80),
            (4, 100),
            (80, 110),
            (80, 80.5),
        ]
        for start, stop in windows:
            with self.subTest(start_ns=start, stop_ns=stop):
                with self.assertRaises(ValueError):
                    self.stress.derive_timing(
                        20,
                        0.25,
                        4096,
                        analysis_window={"start_ns": start, "stop_ns": stop},
                    )
        minimum = self.stress.derive_timing(
            20, 0.25, 4096, analysis_window={"start_ns": 80, "stop_ns": 80.8}
        )
        self.assertAlmostEqual(
            (minimum["analysis_stop_s"] - minimum["analysis_start_s"])
            / minimum["ui_s"],
            32,
        )

    def test_method_changes_only_the_integration_choice(self):
        parser = self.stress.build_parser()
        arguments = ["--channel", "/unused", "--ngspice", "/unused", "--out", "/unused"]
        default = parser.parse_args(arguments)
        gear = parser.parse_args(arguments + ["--method", "gear"])
        self.assertEqual(default.method, "trap")
        self.assertEqual(gear.method, "gear")
        timing = self.stress.derive_timing(20, 0.25, 512)
        trap_netlist = self.stress.build_netlist(default, timing)
        gear_netlist = self.stress.build_netlist(gear, timing)
        self.assertIn("method=trap", trap_netlist)
        self.assertIn("method=gear", gear_netlist)
        # Solver selection must preserve every source and passive element.
        self.assertEqual(gear_netlist.replace("method=gear", "method=trap"), trap_netlist)

    def capture_fixture(self, *, uniform=False):
        timing = self.stress.derive_timing(20, 0.25, 512)
        if uniform:
            steps = round((timing["end_s"] - timing["analysis_start_s"]) / timing["dt_s"])
            time = timing["analysis_start_s"] + np.arange(steps + 1) * timing["dt_s"]
        else:
            time = np.linspace(timing["analysis_start_s"], timing["end_s"], 33)
        voltage = np.column_stack(
            [np.linspace(0.1 * node, 0.1 * node + 0.01, len(time)) for node in range(1, 7)]
        )
        return timing, np.column_stack((time, voltage))

    def write_capture_fixture(self, path, values):
        np.savetxt(
            path,
            values,
            fmt="%.18e",
            header="time txp txn rdiep rdien csrc cload",
            comments="",
        )

    def test_adaptive_zero_and_tiny_duplicate_jumps_preserve_raw_rows(self):
        timing, original = self.capture_fixture()
        duplicated = np.insert(original, 11, original[10], axis=0)
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "adaptive.dat"
            for jump in (0, 1e-12):
                with self.subTest(voltage_jump=jump):
                    values = duplicated.copy()
                    values[11, 3] += jump
                    self.write_capture_fixture(path, values)
                    loaded = self.stress.load_capture(path, timing, adaptive=True)
                    self.assertEqual(loaded.shape, (34, 7))
                    np.testing.assert_array_equal(loaded, values)
                    diagnostics = self.stress.capture_time_diagnostics(loaded)
                    self.assertEqual(diagnostics["duplicateTimestampCount"], 1)
                    self.assertAlmostEqual(
                        diagnostics["maximumDuplicateVoltageDeltaV"], jump, delta=1e-15
                    )

    def test_adaptive_large_duplicate_voltage_jump_is_rejected(self):
        timing, original = self.capture_fixture()
        values = np.insert(original, 11, original[10], axis=0)
        values[11, 3] += 1e-9
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "adaptive.dat"
            self.write_capture_fixture(path, values)
            with self.assertRaises(RuntimeError):
                self.stress.load_capture(path, timing, adaptive=True)

    def test_capture_negative_or_backward_time_is_rejected(self):
        timing, original = self.capture_fixture()
        negative = original.copy()
        negative[0, 0] = -1e-12
        backward = original.copy()
        backward[15, 0] = backward[14, 0] - 1e-15
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "capture.dat"
            for name, values in (("negative", negative), ("backward", backward)):
                for adaptive in (False, True):
                    with self.subTest(case=name, adaptive=adaptive):
                        self.write_capture_fixture(path, values)
                        with self.assertRaises(RuntimeError):
                            self.stress.load_capture(path, timing, adaptive=adaptive)

    def test_linearized_capture_rejects_duplicate_even_without_voltage_jump(self):
        timing, original = self.capture_fixture()
        values = np.insert(original, 11, original[10], axis=0)
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "linearized.dat"
            self.write_capture_fixture(path, values)
            with self.assertRaises(RuntimeError):
                self.stress.load_capture(path, timing)

    def test_uniform_capture_is_valid_for_both_time_policies(self):
        timing, values = self.capture_fixture(uniform=True)
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "uniform.dat"
            self.write_capture_fixture(path, values)
            for adaptive in (False, True):
                with self.subTest(adaptive=adaptive):
                    loaded = self.stress.load_capture(path, timing, adaptive=adaptive)
                    np.testing.assert_array_equal(loaded, values)

    def test_front_truncation_is_rejected_despite_valid_endpoint_and_sample_count(self):
        timing, original = self.capture_fixture(uniform=True)
        values = original[3:]
        self.assertEqual(values[-1, 0], original[-1, 0])
        self.assertGreater(
            np.count_nonzero(values[:, 0] <= timing["analysis_stop_s"]), 16
        )
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "truncated.dat"
            self.write_capture_fixture(path, values)
            for adaptive in (False, True):
                with self.subTest(adaptive=adaptive):
                    with self.assertRaises(RuntimeError):
                        self.stress.load_capture(path, timing, adaptive=adaptive)

    def test_linearized_interior_gap_is_rejected_while_adaptive_gap_is_allowed(self):
        timing, original = self.capture_fixture(uniform=True)
        values = np.delete(original, 11, axis=0)
        self.assertGreater(np.diff(values[:, 0]).max(), 1.5 * timing["dt_s"])
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "gap.dat"
            self.write_capture_fixture(path, values)
            with self.assertRaises(RuntimeError):
                self.stress.load_capture(path, timing)
            loaded = self.stress.load_capture(path, timing, adaptive=True)
            np.testing.assert_array_equal(loaded, values)

    def test_channel_inside_output_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            output = scratch / "out"
            output.mkdir()
            channel = output / "simulation.cir"
            original = b"* Original channel input must survive rejected run\n"
            channel.write_bytes(original)
            run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--channel",
                    str(channel),
                    "--ngspice",
                    str(scratch / "nonexistent-ngspice"),
                    "--out",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("channel input must be outside the output directory", run.stderr)
            self.assertEqual(channel.read_bytes(), original)
            self.assertEqual(list(output.iterdir()), [channel])


@unittest.skipUnless(NGSPICE, "ngspice is optional for native SI regression")
class NativeLowPassTests(unittest.TestCase):
    def test_low_and_high_frequency_match_complex_rc_transfer(self):
        resistance, capacitance = 100.0, 2e-12
        measured = []
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            for frequency in (0.4e9, 4e9):
                with self.subTest(frequency_ghz=frequency / 1e9):
                    period = 1 / frequency
                    step = period / 250
                    duration = max(40 * period, 100 * resistance * capacitance)
                    netlist = f"""Independent ideal-source RC attenuation control
Vsource source 0 SIN(0 1 {frequency:.12e})
Rseries source load {resistance:.12e}
Cshunt load 0 {capacitance:.12e}
.options reltol=1e-7 abstol=1e-12 vntol=1e-9 method=gear maxord=2
.control
set wr_vecnames
set wr_singlescale
tran {step:.12e} {duration:.12e} 0 {step:.12e}
linearize v(source) v(load)
wrdata response.dat v(source) v(load)
quit
.endc
.end
"""
                    (scratch / "rc.cir").write_text(netlist)
                    run = subprocess.run(
                        [NGSPICE, "-b", "rc.cir"],
                        cwd=scratch,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    waveform = np.loadtxt(scratch / "response.dat", skiprows=1)
                    self.assertEqual(waveform.shape[1], 3)
                    self.assertTrue(np.isfinite(waveform).all())
                    self.assertGreaterEqual(waveform[-1, 0], duration - step)
                    steady = waveform[:, 0] >= duration - 10 * period
                    time = waveform[steady, 0]
                    actual = phasor(time, waveform[steady, 2], frequency) / phasor(
                        time, waveform[steady, 1], frequency
                    )
                    expected = 1 / (
                        1 + 2j * np.pi * frequency * resistance * capacitance
                    )
                    self.assertLess(abs(actual / expected - 1), 0.002)
                    measured.append(abs(actual))
        # The tenfold rate increase must reveal the independent low-pass loss.
        self.assertGreater(measured[0], 0.85)
        self.assertLess(measured[1], 0.21)
        self.assertLess(measured[1] / measured[0], 0.25)

    def test_clock_channel_matches_independent_loaded_rc_transfer(self):
        resistance, capacitance = 100.0, 2e-12
        measured = []
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            channel = scratch / "rc-channel.sp"
            channel.write_text(
                "* Independent low-pass channel, not an EM extraction\n"
                ".subckt pcb_channel in out\n"
                f"Rfixture in out {resistance}\n"
                f"Cfixture out 0 {capacitance}\n"
                ".ends pcb_channel\n"
            )
            for strobe_ghz, dt_ps in ((0.4, 0.5), (4, 0.5)):
                with self.subTest(strobe_ghz=strobe_ghz):
                    output = scratch / f"stress-{strobe_ghz}"
                    method_arguments = ["--method", "gear"] if strobe_ghz == 4 else []
                    run = subprocess.run(
                        [
                            sys.executable,
                            str(SCRIPT),
                            "--channel",
                            str(channel),
                            "--ngspice",
                            NGSPICE,
                            "--strobe-ghz",
                            str(strobe_ghz),
                            "--ui-count",
                            "128",
                            "--dt-ps",
                            str(dt_ps),
                            "--out",
                            str(output),
                            *method_arguments,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=90,
                    )
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    provenance = json.loads((output / "provenance.json").read_text())
                    self.assertEqual(
                        provenance["integrationMethod"], "gear" if strobe_ghz == 4 else "trap"
                    )
                    validation = provenance["captureValidation"]
                    adaptive = validation["adaptive"]
                    self.assertGreaterEqual(adaptive["duplicateTimestampCount"], 0)
                    self.assertLessEqual(adaptive["maximumDuplicateVoltageDeltaV"], 1e-10)
                    self.assertEqual(adaptive["duplicateVoltageToleranceV"], 1e-10)
                    self.assertTrue(adaptive["rawDuplicateRowsPreserved"])
                    self.assertEqual(adaptive["timeOrdering"], "nondecreasing")
                    self.assertTrue(adaptive["analysisStartCoverageVerified"])
                    self.assertEqual(validation["linearized"]["timeOrdering"], "strictly increasing")
                    self.assertTrue(validation["linearized"]["analysisStartCoverageVerified"])
                    self.assertEqual(
                        validation["linearized"]["maximumGapToleranceFactor"], 1 + 1e-8
                    )
                    with np.load(output / "waveforms.npz") as waveform:
                        time = waveform["time_s"]
                        frequency = strobe_ghz * 1e9
                        self.assertTrue(np.isfinite(time).all())
                        self.assertLessEqual(
                            abs(time[0] - provenance["analysisStartNs"] * 1e-9),
                            dt_ps * 1e-12,
                        )
                        steady = time > time[-1] - 32 / frequency
                        source = waveform["channel_input_v"][steady]
                        load = waveform["channel_output_v"][steady]
                        self.assertTrue(np.isfinite(source).all())
                        self.assertTrue(np.isfinite(load).all())
                        actual = phasor(time[steady], load, frequency) / phasor(
                            time[steady], source, frequency
                        )

                    # Independent differential load admittance: each receiver
                    # leg sees half the channel voltage, and returns half its
                    # current through the ideal balanced transformer.
                    s = 2j * np.pi * frequency

                    def receiver_admittance(r, inductance, package_capacitance):
                        die = 1 / 60.0 + s * 2e-12
                        return s * package_capacitance + 1 / (
                            r + s * inductance + 1 / die
                        )

                    loaded_admittance = (
                        receiver_admittance(0.42069, 1.1804e-9, 0.41107e-12)
                        + receiver_admittance(0.39422, 1.1796e-9, 0.42404e-12)
                    ) / 4
                    expected = 1 / (
                        1 + resistance * (s * capacitance + loaded_admittance)
                    )
                    self.assertLess(abs(actual / expected - 1), 0.01)
                    measured.append(abs(actual))
                    self.assertFalse(provenance["signoff"])
        self.assertLess(measured[1], measured[0])


if __name__ == "__main__":
    unittest.main()
