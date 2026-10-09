"""Native DC harness regressions use independent synthetic circuits only."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/si/validate-winbond-dc.py"
spec = importlib.util.spec_from_file_location("winbond_dc", SCRIPT.with_name("winbond_dc.py"))
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)
NGSPICE = os.environ.get("SI_NGSPICE") or shutil.which("ngspice")


def fixture(directory, resistance=40, stage=False, stuck=False, behavioral=False, mid_sweep_negative=False):
    directory.mkdir()
    name = "z38hd3_dqobuf" if stage else "output"
    calibration = "cal_pd<5> cal_pu_n<5>" if stage else ""
    sources = "Vcal_pd cal_pd<5> 0 dc vpd5\nVcal_pu cal_pu_n<5> 0 dc vpu5" if stage else ""
    driver = "VDRIVER source vss 0.75" if stuck else "EDRIVER source vss dat vss 1"
    resistor = f"RDRIVER source dq {{{resistance}*ln}}"
    if behavioral:
        resistor = f"RDRIVER source dq {{{resistance}*ln+0*v(source,dq)}} m=2"
    if mid_sweep_negative:
        resistor = f"RDRIVER source dq {{{resistance}*ln*(1-2*(v(dq)>0.5)*(v(dq)<1))}}"
    (directory / "W631GG6MB").write_text(f"""* Independent fixture; no vendor coefficients
.subckt z38hd3_dqbuft dat dq dqen a1 a5 a2 a6 a9 ena odt odten bias vdd vddq ref vss vssq
Xdriver dat dq vdd vss {calibration} {name}
{sources}
.ends
.subckt {name} dat dq vdd vss {calibration} params: ln=1
{driver}
{resistor}
RMON vdd monitor 1meg
MMON monitor dat vss vss fixture_n w=1u l=0.18u m=2 nf=1
.ends
.model fixture_n nmos level=54
""")
    (directory / "model_tt").write_text("* No vendor process model in this fixture\n.param vpd5={1.5/2} vpu5={1.5-0.25}\n")
    (directory / "ds_odt_param").write_text(""".lib ds034
.param vem1={3*0.5} vem5={1.5/3} vem2=0 vem6=0 vem9=0
.endl ds034
""")


class CompatibilityTests(unittest.TestCase):
    def test_formal_length_rename_preserves_logarithm_and_numeric_tokens(self):
        source = """* ln untouched comment
.subckt tiny a b
+ params: LN=2 lp=3u
R1 a b {LN*1e-6 + ln(2)*1e-6 + ln (4)*1e-6} $ ln comment
.ends tiny
X1 a b tiny ln=2
.subckt unrelated a b
R2 a b {ln(2)}
.ends
"""
        compatible, changes = dc.rename_length_parameter(source)
        self.assertEqual(len(changes), 3)
        self.assertIn("length_n=2 lp=3u", compatible)
        self.assertIn("{length_n*1e-6 + ln(2)*1e-6 + ln (4)*1e-6}", compatible)
        self.assertIn("tiny length_n=2", compatible)
        self.assertIn("$ ln comment", compatible)
        self.assertIn("* ln untouched comment", compatible)
        self.assertEqual(dc.rename_length_parameter(compatible), (compatible, []))
        self.assertEqual(
            __import__("re").findall(r"\d+(?:\.\d+)?", source),
            __import__("re").findall(r"\d+(?:\.\d+)?", compatible),
        )

    def test_incomplete_and_wrong_coordinate_sweeps_fail(self):
        config = {"sweep_start": -0.15, "sweep_stop": 1.65, "sweep_step": 0.01,
                  "max_current": 1, "supply": 1.5, "rail_margin": 0.15}
        log = "device rload\n resistance 1000\n"
        rows = [[-0.15 + i * 0.01, -0.15 + i * 0.01, 0.01, -0.01] for i in range(181)]
        self.assertEqual(dc.check_results(rows, log, config, True)[0], [])
        self.assertTrue(dc.check_results(rows[:-1], log, config, True)[0])
        rows[-1][1] = 1.64
        self.assertTrue(dc.check_results(rows, log, config, True)[0])

    def test_length_call_rename_uses_the_actual_instance_target(self):
        source = ".subckt tiny a b ln=1\nR1 a b {ln}\nX3 a b external ln='ln'\n.ends\nX1 tiny out other ln=2\nX2 a b tiny params: ln = 3\n"
        compatible, _ = dc.rename_length_parameter(source)
        self.assertIn("X1 tiny out other ln=2", compatible)
        self.assertIn("X2 a b tiny params: length_n = 3", compatible)
        self.assertIn("X3 a b external ln='length_n'", compatible)

    def test_zero_exit_and_echo_are_insufficient_for_native_completion(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            fake = scratch / "fake-ngspice"
            fake.write_text("#!/bin/sh\necho WINBOND_OP_COMPLETE\nexit 0\n")
            fake.chmod(0o755)
            result = dc.run_native(fake, "fixture", scratch / "run", 5, {}, False)
            self.assertEqual(result["returncode"], 0)
            self.assertFalse(result["pass"])
            self.assertTrue(any("missing native" in error for error in result["errors"]))

    def test_protected_or_unresolved_active_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            source = scratch / "source"
            source.mkdir()
            for body in (".PROT freelib\n", ".param resistance=·\n"):
                (source / "W631GG6MB").write_text(body)
                with self.assertRaises(ValueError):
                    dc.prepare_model(source, scratch / "compatible")

    def test_inline_comment_glyphs_do_not_mask_multiplication(self):
        self.assertEqual(dc.active_text("+ scale_res_p1=1 *res = 100 ·"), "+ scale_res_p1=1 ")
        self.assertEqual(dc.active_text(".param r='1 * 2' * unresolved ·"), ".param r='1 * 2' ")
        self.assertEqual(dc.active_text("R1 a b {2 * 3} $ ·"), "R1 a b {2 * 3} ")
        self.assertEqual(dc.active_text("R1 a b klm0res*2.7u"), "R1 a b klm0res*2.7u")

    def test_overlapping_output_cannot_delete_the_supplied_source(self):
        with tempfile.TemporaryDirectory() as scratch:
            outer = Path(scratch) / "output"
            source = outer / "source"
            source.mkdir(parents=True)
            model = source / "W631GG6MB"
            model.write_text("* supplied source must survive\n")
            sibling = outer / "keep.txt"
            sibling.write_text("preserve existing output\n")
            for destination in (outer, source, source / "output", Path(scratch) / "alias"):
                if destination.name == "alias":
                    destination.symlink_to(outer, target_is_directory=True)
                with self.assertRaises(ValueError):
                    dc.prepare_model(source, destination)
                self.assertEqual(model.read_text(), "* supplied source must survive\n")
                self.assertTrue(sibling.exists())

    def test_second_native_run_cannot_reuse_first_run_data(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            fake = scratch / "fake-ngspice"
            fake.write_text("""#!/usr/bin/env python3
from pathlib import Path
if not Path('initial-bench.cir').exists():
    Path('op.raw').write_text('first run only')
    Path('op.tsv').write_text('0 1.2 1.5 1.5 1.5 1.5 0 0 0 0 0.5 0.75 0\\n')
    print('1 : rload dq 0 1000')
    print('device rload')
    print('resistance 1000')
print('WINBOND_OP_COMPLETE')
""")
            fake.chmod(0o755)
            config = {"supply": 1.5, "rail_margin": 0.15, "max_current": 1}
            result = dc.run_native(fake, "show all : all\n", scratch / "run", 5, config, False)
            self.assertEqual(result["returncode"], 0)
            self.assertFalse(result["pass"])
            self.assertEqual(result["rows"], 0)
            self.assertTrue((scratch / "run/initial-op.raw").is_file())
            self.assertTrue(any("missing native raw" in error for error in result["errors"]))
            self.assertTrue(any("missing native data" in error for error in result["errors"]))

    def test_cli_overlap_refusal_leaves_supplied_directory_unchanged(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            fixture(root / "source")
            source = root / "source"
            before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
            for destination in (source, source / "nested-output", root):
                run = subprocess.run([sys.executable, str(SCRIPT), str(source), "--out", str(destination)],
                                     capture_output=True, text=True, timeout=5)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("must not overlap", run.stdout)
                self.assertEqual(before, {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()})
                self.assertFalse((source / "nested-output").exists())


@unittest.skipUnless(NGSPICE, "ngspice is optional for native Winbond DC diagnostics")
class NativeDCTests(unittest.TestCase):
    def run_fixture(self, resistance, **options):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        fixture(root / "model", resistance, **options)
        run = subprocess.run(
            [sys.executable, str(SCRIPT), str(root / "model"), "--ngspice", NGSPICE,
             "--out", str(root / "dc")], capture_output=True, text=True, timeout=90,
        )
        return run, root, json.loads((root / "dc/validation.json").read_text())

    def test_passive_driver_completes_four_temperatures_and_data_states(self):
        run, root, report = self.run_fixture(40)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr + json.dumps(report))
        self.assertTrue(report["pass"])
        self.assertFalse(report["signoff"])
        self.assertEqual(len(report["cases"]), 4)
        self.assertEqual({case["temperatureC"] for case in report["cases"]}, {27, 85})
        self.assertEqual({case["datV"] for case in report["cases"]}, {0, 1.5})
        for case in report["cases"]:
            resolved = case["op"]["resolvedVoltagesAndSupplyCurrent"]
            self.assertAlmostEqual(resolved["v(a1)"], 1.5)
            self.assertAlmostEqual(resolved["v(a5)"], 0.5)
            self.assertAlmostEqual(resolved["v(dq)"], case["datV"] * 1000 / 1040, places=7)
            self.assertEqual(case["sweep"]["rows"], 181)
            devices = case["op"]["evaluatedDevices"]
            self.assertTrue(any(values.get("w") == 1e-6 for values in devices.values()))
            self.assertTrue(any(values.get("nf") == 1 for values in devices.values()))
            self.assertTrue((root / "dc" / case["name"] / "op/op.raw").is_file())
        transformed = (root / "dc/compatible-model/W631GG6MB").read_text()
        self.assertIn("{40*length_n}", transformed)
        self.assertTrue(report["inputs"][0]["inputSha256"])
        self.assertNotEqual(report["inputs"][0]["inputSha256"], report["inputs"][0]["compatibleSha256"])

    def test_negative_resistance_converges_but_impossible_output_fails(self):
        run, _, report = self.run_fixture(-2000)
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(report["pass"])
        high = next(case for case in report["cases"] if case["datV"] == 1.5)
        self.assertEqual(high["op"]["returncode"], 0)
        self.assertEqual(high["op"]["rows"], 1)
        self.assertAlmostEqual(high["op"]["resolvedVoltagesAndSupplyCurrent"]["v(dq)"], -1.5)
        self.assertTrue(any("electrically impossible" in error for error in high["op"]["errors"]))
        self.assertTrue(any("resistance=-2000" in error for error in high["op"]["errors"]))

    def test_stuck_midrail_output_fails_the_logic_check(self):
        run, _, report = self.run_fixture(40, stuck=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertTrue(any("logic check" in error for case in report["cases"] for error in case["op"]["errors"]))

    def test_extracted_stage_uses_native_resolved_calibration(self):
        run, _, report = self.run_fixture(40, stage=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr + json.dumps(report))
        self.assertEqual(len(report["cases"]), 8)
        self.assertEqual(len(report["stageComparisons"]), 4)
        for comparison in report["stageComparisons"]:
            self.assertAlmostEqual(comparison["stageMinusCompleteDqV"], 0)
            calibration = comparison["resolvedCalibrationComparison"]
            self.assertEqual(calibration["v(cal_pd<5>)"]["completeV"], 0.75)
            self.assertEqual(calibration["v(cal_pu_n<5>)"]["stageV"], 1.25)
            self.assertTrue(all(values["differenceV"] == 0 for values in calibration.values()))

    def test_behavioral_resistance_accounts_for_native_multiplicity(self):
        run, _, report = self.run_fixture(40, behavioral=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr + json.dumps(report))
        high = next(case for case in report["cases"] if case["datV"] == 1.5)
        self.assertAlmostEqual(high["op"]["resolvedVoltagesAndSupplyCurrent"]["v(dq)"], 1.5 * 1000 / 1020, places=7)
        behavioral = [values for values in high["op"]["evaluatedDevices"].values() if "effectiveResistanceOhm" in values]
        self.assertTrue(behavioral)
        self.assertAlmostEqual(behavioral[0]["effectiveResistanceOhm"], 20, places=3)
        self.assertEqual(behavioral[0]["m"], 2)

    def test_receiver_unit_boundary_preserves_resistor_coefficients(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            fixture(root / "model", 40)
            circuit = root / "model/W631GG6MB"
            body = circuit.read_text().replace("RDRIVER source dq {40*ln}", "XRCV vss source dq gcres w=0.12u l=2.6u")
            circuit.write_text(body)
            corner = root / "model/model_tt"
            primitive = """* Independent micron-unit resistor, not a vendor model
.subckt gcres bulk in out w=1 l=1
.param dw=0.01
RGEOM in out {l/(w-2*dw)}
.ends gcres
"""
            corner.write_text(primitive)
            reports = {}
            for adapted in (False, True):
                out = root / ("adapted" if adapted else "original")
                command = [sys.executable, str(SCRIPT), str(root / "model"), "--ngspice", NGSPICE,
                           "--out", str(out), "--jobs", "2"]
                if adapted:
                    command.append("--receiver-geometry-microns")
                run = subprocess.run(command, capture_output=True, text=True, timeout=90)
                reports[adapted] = json.loads((out / "validation.json").read_text())
                self.assertEqual(run.returncode, 0 if adapted else 1, run.stdout + run.stderr)
                self.assertEqual((out / "compatible-model/model_tt").read_bytes(), primitive.encode())
                self.assertIn("w=0.12u l=2.6u", (out / "compatible-model/W631GG6MB").read_text())
            self.assertFalse(reports[False]["pass"])
            self.assertTrue(reports[True]["pass"])
            self.assertTrue(reports[True]["receiverGeometryAdaptation"]["enabled"])
            self.assertFalse(reports[True]["receiverGeometryAdaptation"]["numericCoefficientsChanged"])
            transformations = next(item["transformations"] for item in reports[True]["inputs"] if item["file"] == "W631GG6MB")
            self.assertTrue(any(item["from"] == "gcres" and item["to"] == "gcres_si" for item in transformations))
            self.assertTrue(any(item["from"] == "" and "w*1e6" in item["to"] for item in transformations))

    def test_negative_resistance_inside_sweep_cannot_pass_positive_endpoints(self):
        run, _, report = self.run_fixture(40, mid_sweep_negative=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertTrue(all(case["op"]["pass"] for case in report["cases"]))
        for case in report["cases"]:
            self.assertEqual(case["sweep"]["rows"], 181)
            self.assertFalse(case["sweep"]["pass"])
            resistor = next(values for values in case["sweep"]["evaluatedDevices"].values() if "minimumEffectiveResistanceOhm" in values)
            self.assertEqual(resistor["effectiveResistanceOhm"], 40)
            self.assertEqual(resistor["minimumEffectiveResistanceOhm"], -40)
            self.assertEqual(resistor["maximumEffectiveResistanceOhm"], 40)


if __name__ == "__main__":
    unittest.main()
