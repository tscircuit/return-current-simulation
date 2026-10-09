"""Convert a locally supplied TI IBIS file using KiCad's ngspice-backed converter.

Vendor files and converted I/V tables stay in the requested work directory.
Package matrices unsupported by KiCad are disabled in the compatibility copy;
selected physical package parasitics are attached separately in the eye model.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("ibis")
parser.add_argument("--out", required=True)
parser.add_argument("--kicad-cli", default="kicad-cli")
parser.add_argument("--spice-scripts")
args = parser.parse_args()
out = Path(args.out).resolve()
out.mkdir(parents=True, exist_ok=True)
raw = Path(args.ibis).read_bytes()
text = raw.decode("ascii")
# KiCad 9 cannot parse the symbolic row labels in the vendor sparse package
# matrix. Keep the manufacturer's complete I/O model and waveform sections.
text = re.split(r"(?im)^\[Define Package Model\]", text)[0]
text = (
    re.sub(
        r"(?im)^\[Package Model\].*$",
        "| Package matrix disabled for KiCad compatibility",
        text,
    )
    + "\n[End]\n"
)
compat = out / "compatible.ibs"
compat.write_text(text)
root = str(uuid4())
defs = """(lib_symbols
(symbol "Simulation_SPICE:IBIS_DRIVER"
 (pin_names (offset 0)) (in_bom yes) (on_board yes)
 (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
 (property "Value" "IBIS_DRIVER" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
 (symbol "IBIS_DRIVER_1_1"
  (pin power_in line (at -2.54 0 0) (length 2.54) (name "GND" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
  (pin bidirectional line (at 2.54 0 180) (length 2.54) (name "IN/OUT" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
 )))"""
schematic = f'(kicad_sch (version 20250114) (generator "eeschema") (uuid {root}) (paper "A4")\n{defs}\n'
for index, pin, model, delay in [
    (1, "P1", "Model_655", "0"),
    (2, "P2", "Model_847", "10n"),
]:
    properties = {
        "Reference": f"U{index}",
        "Value": "IBIS_DRIVER",
        "Sim.Device": "IBIS",
        "Sim.Type": "RECTDRIVER",
        "Sim.Library": str(compat),
        "Sim.Name": "am335x_zcz",
        "Sim.Ibis.Pin": pin,
        "Sim.Ibis.Model": model,
        "Sim.Params": f"ton=10n toff=10n td={delay} n=2",
        "Sim.Pins": "1=GND 2=IN/OUT",
    }
    fields = "\n".join(
        f'(property "{k}" "{v}" (at {index * 30} 30 0) (effects (font (size 1.27 1.27)) (hide yes)))'
        for k, v in properties.items()
    )
    schematic += f"""(symbol (lib_id "Simulation_SPICE:IBIS_DRIVER") (at {index * 30} 30 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid {uuid4()})
 {fields}
 (pin "1" (uuid {uuid4()})) (pin "2" (uuid {uuid4()}))
 (instances (project "edges" (path "/{root}" (reference "U{index}") (unit 1)))))\n"""
schematic += ")\n"
sch = out / "edges.kicad_sch"
sch.write_text(schematic)
env = os.environ.copy()
env["XDG_CACHE_HOME"] = str(out / "cache")
env["XDG_CONFIG_HOME"] = str(out / "config")
env["XDG_DATA_HOME"] = str(out / "data")
if args.spice_scripts:
    env["SPICE_SCRIPTS"] = str(Path(args.spice_scripts).resolve())
netlist = out / "edges.cir"
run = subprocess.run(
    [
        args.kicad_cli,
        "sch",
        "export",
        "netlist",
        "--format",
        "spice",
        "-o",
        str(netlist),
        str(sch),
    ],
    env=env,
    capture_output=True,
    text=True,
)
(out / "conversion.log").write_text(run.stdout + run.stderr)
if run.returncode:
    raise RuntimeError(run.stdout + run.stderr)
models = re.findall(r'(?m)^\.include "([^"]+)"', netlist.read_text())
assert len(models) == 2, "Expected exactly two converted driver models"
checks = []
for source, name in zip(models, ["positive.sp", "negative.sp"]):
    body = Path(source).read_text()
    summary = {}
    for weighting in ["ku", "kd"]:
        match = re.search("V" + weighting + r"[^\n]+", body)
        assert match, "Missing switching source; verify ngspice/XSPICE installation"
        weights = np.array(
            [float(v) for v in match[0].split("pwl (")[1].split(")")[0].split()]
        ).reshape(-1, 2)
        assert (
            len(weights) > 100
            and np.all(np.diff(weights[:, 0]) > 0)
            and np.isfinite(weights).all()
        ), "Invalid or empty converted switching source"
        assert weights[:, 1].min() > -0.1 and weights[:, 1].max() < 1.2, (
            "Unphysical isolated switching weights"
        )
        summary[weighting] = {
            "points": len(weights),
            "minimum": float(weights[:, 1].min()),
            "maximum": float(weights[:, 1].max()),
        }
    shutil.copyfile(source, out / name)
    checks.append(summary)
(out / "conversion.json").write_text(
    json.dumps(
        {
            "vendorIbisSha256": hashlib.sha256(raw).hexdigest(),
            "converter": "KiCad sch export netlist; ngspice-backed IBIS converter",
            "packageMatrixDisabled": True,
            "isolatedEdgeOnOffNs": 10,
            "models": ["Model_655", "Model_847"],
            "pins": ["P1", "P2"],
            "registerAssumption": "0x18B, TI model selection-guide example, not confirmed board registers",
            "switchingChecks": checks,
            "vendorFilesRedistributed": False,
        },
        indent=2,
    )
)
print(json.dumps(checks, indent=2))
