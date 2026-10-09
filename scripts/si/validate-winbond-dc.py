"""Run native DC diagnostics on a locally supplied recovered Winbond model."""

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from winbond_dc import compare_stages, diagnostic_targets, prepare_model, run_cases, sha256


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("model_dir", help="locally supplied recovered vendor files")
    cli.add_argument("--out", required=True)
    cli.add_argument("--ngspice", default="ngspice")
    cli.add_argument("--model-file", default="W631GG6MB")
    cli.add_argument("--corner", default="model_tt")
    cli.add_argument("--strength", default="ds034")
    cli.add_argument("--subckt", default="z38hd3_dqbuft")
    cli.add_argument("--stage-subckt", help="recovered stage (default: auto-extract z38hd3_dqobuf)")
    cli.add_argument("--stage-nodes", help="explicit ordered bench nodes instead of extracted vendor wiring")
    cli.add_argument("--receiver-geometry-microns", action="store_true", help="opt-in gcres/ynresx SI-to-micron call boundary diagnostic; preserves resistor coefficients")
    cli.add_argument("--supply", type=float, default=1.5)
    cli.add_argument("--load-ohm", type=float, default=1000)
    cli.add_argument("--rail-margin", type=float, default=0.15)
    cli.add_argument("--max-current", type=float, default=1.0)
    cli.add_argument("--sweep-start", type=float, default=-0.15)
    cli.add_argument("--sweep-stop", type=float, default=1.65)
    cli.add_argument("--sweep-step", type=float, default=0.01)
    cli.add_argument("--timeout", type=float, default=300)
    cli.add_argument("--jobs", type=int, default=1, help="independent native cases to run concurrently")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    out = Path(args.out).resolve()
    source = Path(args.model_dir).resolve()
    if source == out or source in out.parents or out in source.parents:
        print(json.dumps({"pass": False, "report": None,
                          "errors": ["supplied model and output directories must not overlap"]}))
        return 1
    out.mkdir(parents=True, exist_ok=True)
    result = {"pass": False, "signoff": False, "scope": "native DC electrical sanity only",
              "vendorFilesRedistributed": False, "cases": [], "errors": []}
    try:
        config = vars(args).copy()
        if not all(math.isfinite(config[key]) for key in ("supply", "load_ohm", "rail_margin", "max_current", "sweep_start", "sweep_stop", "sweep_step", "timeout")):
            raise ValueError("numeric bench settings must be finite")
        if args.stage_nodes and not args.stage_subckt:
            raise ValueError("--stage-nodes requires --stage-subckt")
        if args.supply <= 0 or args.load_ohm <= 0 or args.rail_margin < 0 or args.max_current <= 0:
            raise ValueError("supply, load and current limit must be positive; rail margin nonnegative")
        if args.jobs < 1 or args.timeout <= 0:
            raise ValueError("jobs and native timeout must be positive")
        intervals = (args.sweep_stop - args.sweep_start) / args.sweep_step
        if args.sweep_step <= 0 or intervals < 1 or abs(intervals - round(intervals)) > 1e-7:
            raise ValueError("sweep must have an integral, positive number of intervals")
        binary_name = shutil.which(args.ngspice)
        if not binary_name:
            raise ValueError(f"ngspice binary not found: {args.ngspice}")
        binary = Path(binary_name).resolve()
        version = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=10)
        result["ngspice"] = {"path": str(binary), "sha256": sha256(binary.read_bytes()),
                              "version": version.stdout + version.stderr}
        compatible = out / "compatible-model"
        for required in (args.model_file, args.corner, "ds_odt_param"):
            if not (Path(args.model_dir) / required).is_file():
                raise ValueError(f"missing required supplied model file: {required}")
        result["inputs"] = prepare_model(Path(args.model_dir), compatible, args.receiver_geometry_microns, args.model_file)
        result["receiverGeometryAdaptation"] = {
            "enabled": args.receiver_geometry_microns, "families": ["gcres", "ynresx"] if args.receiver_geometry_microns else [],
            "conversion": "SI meters to microns at call boundary; factor 1e6" if args.receiver_geometry_microns else None,
            "numericCoefficientsChanged": False, "m0resAdapted": False,
            "basis": "vendor corner comment: width and length of the resistor must be set in microns; diagnostic, no licensed HSPICE equivalence oracle",
        }
        for required in (args.model_file, args.corner, "ds_odt_param"):
            if not (compatible / required).is_file():
                raise ValueError(f"missing required model file: {required}")
        if args.stage_subckt:
            if not re.fullmatch(r"[\w.-]+", args.stage_subckt) or (args.stage_nodes and not re.fullmatch(r"[\w.<>\s-]+", args.stage_nodes)):
                raise ValueError("invalid output-stage identifier or node list")
        targets = diagnostic_targets((compatible / args.model_file).read_text(), args.subckt, args.stage_subckt, args.stage_nodes)
        result["targets"] = targets
        result["outputStageComparison"] = "configured" if len(targets) > 1 else "not configured: recovered output stage not present"
        result["bench"] = config
        result["currentConvention"] = "i(vclamp)>0 flows from buffer into clamp; sweep omits RLOAD; i(vdd)<0 draws supply current"
        result["cases"] = run_cases(binary, compatible, config, targets, out)
        result["pass"] = all(case["pass"] for case in result["cases"])
        result["stageComparisons"] = compare_stages(result["cases"])
    except (ValueError, OSError, subprocess.SubprocessError, ZeroDivisionError) as exc:
        result["errors"].append(str(exc))
    (out / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "cases": len(result["cases"]),
                      "report": str(out / "validation.json"), "errors": result["errors"]}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
