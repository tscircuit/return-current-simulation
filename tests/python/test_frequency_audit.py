"""Independent analytic signals and malformed exports exercise scientific audits."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/si"
sys.path.insert(0, str(SCRIPTS))
from channel_extrapolation import evaluate_response, read_elements
from frequency_audit import timestep_comparison, window_metrics


CHANNEL = ROOT / "examples/am3352/dqs-em-eye/channel"


def sinusoid(time, phase):
    differential = 0.37 + np.cos(2 * np.pi * 1e9 * time + phase)
    return {"time_s": time, "dqs_p_v": 0.75 + differential / 2,
            "dqs_n_v": 0.75 - differential / 2,
            "tx_p_v": 0.75 + differential / 4, "tx_n_v": 0.75 - differential / 4}


def save_capture(directory, configuration):
    directory.mkdir()
    step_ps, phase = configuration
    time = np.arange(round(25e3 / step_ps) + 1) * step_ps * 1e-12
    np.savez(directory / "waveforms.npz", **sinusoid(time, phase))
    metadata = {"strobeGHz": 1, "analysisStartNs": 2, "analysisStopNs": 22,
                "timeStepPs": step_ps, "source": {"kind": "independent cosine"},
                "ioModels": {}, "uiCount": 50, "integrationMethod": "trap",
                "channel": {"modelSha256": "unchanged"}, "netlistSha256": "fixture"}
    (directory / "provenance.json").write_text(json.dumps(metadata))


def cli(script, arguments):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, arguments)],
                          capture_output=True, text=True, timeout=30)


class FrequencyAuditTests(unittest.TestCase):
    def test_cosine_with_dc_has_ac_rms_peak_and_known_phasor(self):
        time = np.arange(20 * 120 + 1) / (120 * 1e9)
        amplitude, offset, phase = 1.4, 0.37, np.pi / 3
        waveforms = sinusoid(time, phase)
        differential = offset + amplitude * np.cos(2 * np.pi * 1e9 * time + phase)
        waveforms["dqs_p_v"] = 0.75 + differential / 2
        waveforms["dqs_n_v"] = 0.75 - differential / 2
        stats = window_metrics(waveforms, {"startNs": 0, "stopNs": 20, "frequencyHz": 1e9})
        receiver = stats["signals"]["receiverDieDifferential"]
        self.assertAlmostEqual(receiver["acRmsV"], amplitude / np.sqrt(2), places=12)
        self.assertAlmostEqual(receiver["halfPeakToPeakV"], amplitude, places=12)
        self.assertAlmostEqual(receiver["fundamentalPeakV"], amplitude, places=12)
        self.assertAlmostEqual(receiver["fundamentalPhaseRad"], phase, places=12)
        self.assertAlmostEqual(receiver["fittedDcOffsetV"], offset, places=12)
        self.assertAlmostEqual(receiver["meanV"], offset, places=12)

    def test_timestep_comparison_preserves_absolute_phase_difference(self):
        with tempfile.TemporaryDirectory() as scratch:
            coarse, refined = Path(scratch) / "coarse", Path(scratch) / "refined"
            save_capture(coarse, (10, 0.23))
            save_capture(refined, (5, 0.53))
            comparison = timestep_comparison(coarse, refined)
            self.assertAlmostEqual(comparison["receiverFundamentalPhaseChangeRad"], 0.3, places=12)
            self.assertAlmostEqual(comparison["receiverFundamentalPhaseEquivalentTimeChangePs"],
                                   0.3 / (2 * np.pi * 1e9) * 1e12, places=10)
            self.assertAlmostEqual(comparison["receiverFundamentalPeakRelativeChange"], 0, places=12)
            self.assertLess(abs(comparison["receiverAcRmsRelativeChange"]), 1e-3)
            self.assertGreater(comparison["receiverMaximumAbsoluteWaveformDifferenceV"], 0.29)
            self.assertIn("no phase alignment", comparison["waveformComparison"])

    def test_complete_export_reconstructs_the_existing_saved_fit(self):
        elements = read_elements(CHANNEL / "channel.sp")
        with np.load(CHANNEL / "channel.npz") as saved:
            response = evaluate_response(saved["f"], elements)
            self.assertEqual(response.shape, saved["fit"].shape)
            self.assertLess(np.max(abs(response - saved["fit"])), 1e-10)

    def test_electrical_refinement_can_keep_the_saved_sample_grid_fixed(self):
        with tempfile.TemporaryDirectory() as scratch:
            coarse, refined = Path(scratch) / "coarse", Path(scratch) / "refined"
            for directory, electrical_step in ((coarse, 0.5), (refined, 0.25)):
                save_capture(directory, (10, 0.23))
                path = directory / "provenance.json"
                metadata = json.loads(path.read_text())
                metadata.update(electricalTimeStepPs=electrical_step, sampleTimeStepPs=10)
                path.write_text(json.dumps(metadata))
            report = timestep_comparison(coarse, refined)
            self.assertEqual(report["coarseTimeStepPs"], 0.5)
            self.assertEqual(report["refinedTimeStepPs"], 0.25)
            self.assertEqual(report["coarseSavedSampleTimeStepPs"], 10)
            self.assertEqual(report["refinedSavedSampleTimeStepPs"], 10)
            self.assertEqual(report["receiverMaximumAbsoluteWaveformDifferenceV"], 0)

    def test_unmodeled_components_connections_and_small_damping_changes_are_rejected(self):
        original = (CHANNEL / "channel.sp").read_text()
        imaginary_resistor = next(line for line in original.splitlines() if line.startswith("Rp1_im_im_a1 "))
        altered_resistor = imaginary_resistor.rsplit(" ", 1)[0] + " " + str(float(imaginary_resistor.split()[-1]) * 2)
        variants = {
            "extra resistor": original.replace(".ENDS", "Rextra p1 p2 100\n.ENDS"),
            "changed connection": original.replace("Cx1_im_a1 x1_im_a1 0 1.0", "Cx1_im_a1 x1_im_a1 p2 1.0"),
            "different damping": original.replace(imaginary_resistor, altered_resistor),
            "unsupported directive": original.replace(".ENDS", ".param scale=2\n.ENDS"),
            "case collision": original.replace(".ENDS", "r1 s1 0 100\n.ENDS"),
        }
        with tempfile.TemporaryDirectory() as scratch:
            netlist = Path(scratch) / "invalid.sp"
            for name, source in variants.items():
                with self.subTest(name=name):
                    netlist.write_text(source)
                    with self.assertRaisesRegex(ValueError, "Unsupported SPICE topology"):
                        read_elements(netlist)

    def test_cli_rejects_unsupported_topology_without_a_report(self):
        with tempfile.TemporaryDirectory() as scratch:
            netlist, report = Path(scratch) / "unsupported.sp", Path(scratch) / "report.json"
            netlist.write_text(".subckt channel p1 p2\nR1 p1 p2 100\n.ends channel\n")
            run = cli("check-channel-extrapolation.py", ["--channel-spice", netlist,
                       "--saved-fit", CHANNEL / "channel.npz", "--out", report])
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("Unsupported SPICE topology", run.stderr)
            self.assertNotIn("Traceback", run.stderr)
            self.assertFalse(report.exists())

    def test_cli_outputs_cannot_replace_supplied_artifacts_or_symlink_targets(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            capture = scratch / "capture"
            save_capture(capture, (10, 0.23))
            waveform = capture / "waveforms.npz"
            before = hashlib.sha256(waveform.read_bytes()).hexdigest()
            alias = scratch / "waveform-alias"
            alias.symlink_to(waveform)
            run = cli("check-frequency-stress.py", ["--capture", capture, "--out", alias])
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("overlaps supplied input", run.stderr)
            self.assertEqual(hashlib.sha256(waveform.read_bytes()).hexdigest(), before)
            report = scratch / "report.json"
            provenance = capture / "provenance.json"
            original_provenance = provenance.read_bytes()
            run = cli("check-frequency-stress.py", ["--capture", capture, "--out", report,
                       "--summary-out", provenance])
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(report.exists())
            self.assertEqual(provenance.read_bytes(), original_provenance)
            netlist, fit = scratch / "channel.sp", scratch / "fit.npz"
            netlist.write_bytes((CHANNEL / "channel.sp").read_bytes())
            fit.write_bytes((CHANNEL / "channel.npz").read_bytes())
            original_fit = fit.read_bytes()
            run = cli("check-channel-extrapolation.py", ["--channel-spice", netlist, "--saved-fit", fit, "--out", fit])
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("overlaps supplied input", run.stderr)
            self.assertEqual(fit.read_bytes(), original_fit)


if __name__ == "__main__":
    unittest.main()
