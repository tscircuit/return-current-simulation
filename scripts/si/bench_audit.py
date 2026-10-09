"""Read-only input, budget and refinement checks for assumed bench captures."""

import argparse
import json
from pathlib import Path
import sys

from audit_paths import check_report_paths
from bench_audit_checks import audit_bench, capture_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--routed-only", action="store_true", help="audit completed routed clean/noisy/refinement captures without matched references")
    arguments = parser.parse_args()
    try:
        paths = capture_paths(Path(arguments.root).resolve(), arguments.routed_only)
        capture_directories = [directory for pair in paths.values() for directory in pair.values()]
        destination = Path(arguments.out).resolve()
        if any(destination.is_relative_to(directory) for directory in capture_directories):
            raise ValueError("Audit output must be outside the supplied capture directories")
        inputs = [path for directory in capture_directories for path in directory.rglob("*") if path.is_file()]
        check_report_paths([destination], inputs)
        report = audit_bench(arguments.root, arguments.routed_only)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"pass": report["pass"], "report": str(destination), "signoff": False}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
