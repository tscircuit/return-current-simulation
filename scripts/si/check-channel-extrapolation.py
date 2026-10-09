"""Evaluate the supplied scikit-rf complex-pole SPICE export against its saved fit.

Frequencies outside the saved band are rational-model extrapolation. A sampled
passivity check does not establish physical accuracy or whole-band passivity.
"""

import argparse
import json
from pathlib import Path

from audit_paths import check_report_paths
from channel_extrapolation import audit_channel, evaluate_response, read_elements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-spice", required=True)
    parser.add_argument("--saved-fit", required=True)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()
    try:
        check_report_paths([arguments.out], [arguments.channel_spice, arguments.saved_fit])
        report = audit_channel(arguments.channel_spice, arguments.saved_fit)
    except ValueError as error:
        parser.error(str(error))
    Path(arguments.out).parent.mkdir(parents=True, exist_ok=True)
    Path(arguments.out).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
