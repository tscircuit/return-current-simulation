"""Keep diagnostic reports from replacing the supplied scientific inputs."""

from pathlib import Path


def check_report_paths(outputs, inputs):
    inputs = [Path(path).resolve() for path in inputs]
    outputs = [Path(path).resolve() for path in outputs if path is not None]
    if len(set(outputs)) != len(outputs):
        raise ValueError("Report output paths must be distinct")
    for output in outputs:
        for supplied in inputs:
            if output == supplied or (output.exists() and supplied.exists()
                                      and output.samefile(supplied)):
                raise ValueError(f"Report output overlaps supplied input: {output}")
