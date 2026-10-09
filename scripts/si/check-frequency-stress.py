"""Record finite-window amplitudes, settling, and timestep sensitivity.

Reads supplied captures without modifying them. RMS removes differential DC;
phase comparisons retain absolute timestamps, without individual alignment.
"""

import argparse
import json
from pathlib import Path

from audit_paths import check_report_paths
from frequency_audit import audit_capture, capture_summary, timestep_comparison, window_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--compare-timestep", nargs=2, metavar=("COARSE", "REFINED"))
    parser.add_argument("--summary-out")
    arguments = parser.parse_args()
    directories = arguments.capture + (arguments.compare_timestep or [])
    inputs = [path for directory in directories for path in Path(directory).iterdir() if path.is_file()]
    try:
        check_report_paths([arguments.out, arguments.summary_out], inputs)
        report = {"captures": [audit_capture(directory) for directory in arguments.capture]}
        if arguments.compare_timestep:
            report["timestepComparison"] = timestep_comparison(*arguments.compare_timestep)
    except ValueError as error:
        parser.error(str(error))
    Path(arguments.out).parent.mkdir(parents=True, exist_ok=True)
    Path(arguments.out).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if arguments.summary_out:
        Path(arguments.summary_out).parent.mkdir(parents=True, exist_ok=True)
        Path(arguments.summary_out).write_text(json.dumps(capture_summary(report), indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
