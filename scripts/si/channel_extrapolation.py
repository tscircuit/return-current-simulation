"""Evaluate the saved scikit-rf SPICE export without fitting new coefficients.

For this export, normalized incident/reflected waves are
    a = V / sqrt(Z0) + I * sqrt(Z0), b = V / sqrt(Z0) - I * sqrt(Z0).
Each complex-pole state obeys
    q*x_re - beta*x_im = a, q*x_im + beta*x_re = 0,
where q = j*2*pi*f + alpha, alpha = 1/Rp, and beta = Gp_re_im.
Thus x_re/a = q/(q*q+beta*beta), x_im/a = -beta/(q*q+beta*beta),
and S_ij = Fd_ij + sqrt(Z0)*sum(Gr_re*x_re/a + Gr_im*x_im/a).

The reconstructed response is checked against the existing saved fitted NPZ.
Evaluation above the saved frequency band is rational-model extrapolation.
A sampled passivity check does not establish physical channel accuracy.
"""

import hashlib
from pathlib import Path
import re

import numpy as np


def read_elements(path):
    elements = {}
    subcircuit, ports, closed = None, None, False
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        tokens = line.lower().split()
        if tokens[0] == ".subckt" and subcircuit is None and len(tokens) >= 4:
            subcircuit, ports = tokens[1], tokens[2:]
        elif tokens[0] == ".ends" and subcircuit is not None and not closed:
            if tokens[1:] not in ([], [subcircuit]):
                raise ValueError("Unsupported SPICE topology: mismatched .ends")
            closed = True
        elif tokens[0].startswith(".") or subcircuit is None or closed:
            raise ValueError(f"Unsupported SPICE topology at line {line_number}: {line}")
        elif tokens[0] in elements:
            raise ValueError(f"Unsupported SPICE topology: duplicate element {tokens[0]}")
        else:
            elements[tokens[0]] = tokens
    if subcircuit is None or not closed:
        raise ValueError("Unsupported SPICE topology: expected one complete .subckt")
    impedances, _ = validate_topology(elements)
    if ports != [f"p{port}" for port in range(1, len(impedances) + 1)]:
        raise ValueError("Unsupported SPICE topology: expected ordered p1, p2, ... subcircuit ports")
    return elements


def coefficient(elements, name):
    if name not in elements:
        raise ValueError(f"Unsupported SPICE topology: missing element {name}")
    try:
        number = float(elements[name][-1])
    except (ValueError, IndexError) as error:
        raise ValueError(f"Unsupported SPICE topology: {name} needs a numeric coefficient") from error
    if not np.isfinite(number):
        raise ValueError(f"Unsupported SPICE topology: nonfinite coefficient in {name}")
    return number


def validate_topology(elements):
    """Recognize the complete complex-pole export; reject unmodeled components."""
    ports = sorted(int(match[1]) for name in elements if (match := re.fullmatch(r"r(\d+)", name)))
    if not ports or ports != list(range(1, len(ports) + 1)):
        raise ValueError("Unsupported SPICE topology: expected contiguous numbered port resistors")
    impedances = [coefficient(elements, f"r{port}") for port in ports]
    if any(impedance <= 0 for impedance in impedances) or not np.allclose(impedances, impedances[0], rtol=1e-12, atol=0):
        raise ValueError("Unsupported SPICE topology: expected equal positive port impedances")
    expected, states = {}, {}
    for port, impedance in zip(ports, impedances):
        expected[f"v{port}"] = ([f"p{port}", f"s{port}"], 0)
        expected[f"r{port}"] = ([f"s{port}", "0"], impedance)
        states[port] = sorted(int(match[1]) for name in elements
                              if (match := re.fullmatch(rf"rp(\d+)_re_re_a{port}", name)))
        if states[port] != list(range(1, len(states[port]) + 1)):
            raise ValueError("Unsupported SPICE topology: expected contiguous complex-pole states")
        for state in states[port]:
            real, imaginary = f"x{state}_re_a{port}", f"x{state}_im_a{port}"
            resistance = coefficient(elements, f"rp{state}_re_re_a{port}")
            if resistance <= 0:
                raise ValueError("Unsupported SPICE topology: complex-pole damping must be positive")
            beta = coefficient(elements, f"gp{state}_re_im_a{port}")
            expected[f"cx{state}_re_a{port}"] = ([real, "0"], 1)
            expected[f"cx{state}_im_a{port}"] = ([imaginary, "0"], 1)
            expected[f"gx{state}_re_a{port}"] = (["0", real, f"p{port}", "0"], 1 / np.sqrt(impedance))
            expected[f"fx{state}_re_a{port}"] = (["0", real, f"v{port}"], np.sqrt(impedance))
            expected[f"rp{state}_re_re_a{port}"] = (["0", real], resistance)
            expected[f"rp{state}_im_im_a{port}"] = (["0", imaginary], resistance)
            expected[f"gp{state}_re_im_a{port}"] = (["0", real, imaginary, "0"], beta)
            expected[f"gp{state}_im_re_a{port}"] = (["0", imaginary, real, "0"], -beta)
        for output in ports:
            direct = coefficient(elements, f"fd{output}_{port}")
            expected[f"fd{output}_{port}"] = (["0", f"s{output}", f"v{port}"], direct)
            expected[f"gd{output}_{port}"] = (["0", f"s{output}", f"p{port}", "0"], direct / impedance)
            for state in states[port]:
                for part in ("re", "im"):
                    expected[f"gr{state}_{part}_{output}_{port}"] = (
                        ["0", f"s{output}", f"x{state}_{part}_a{port}", "0"], None)
    unexpected = sorted(set(elements) - set(expected))
    if unexpected:
        raise ValueError(f"Unsupported SPICE topology: unmodeled elements {', '.join(unexpected)}")
    for name, (terminals, expected_coefficient) in expected.items():
        actual_coefficient = coefficient(elements, name)
        if elements[name][1:-1] != terminals:
            raise ValueError(f"Unsupported SPICE topology: unexpected connections for {name}")
        if expected_coefficient is not None and not np.isclose(actual_coefficient, expected_coefficient, rtol=1e-12, atol=0):
            raise ValueError(f"Unsupported SPICE topology: coefficient mismatch for {name}")
    return impedances, states


def evaluate_response(frequencies, elements):
    frequencies = np.atleast_1d(np.asarray(frequencies, dtype=float))
    if frequencies.ndim != 1 or not np.isfinite(frequencies).all() or (frequencies < 0).any():
        raise ValueError("Frequency samples must be finite, nonnegative and one-dimensional")
    impedances, states = validate_topology(elements)
    angular_frequency = 2j * np.pi * frequencies
    port_count = len(impedances)
    response = np.zeros((len(frequencies), port_count, port_count), complex)
    for output_port in range(1, port_count + 1):
        impedance = impedances[output_port - 1]
        for input_port in range(1, port_count + 1):
            scattering = np.full(
                len(frequencies), coefficient(elements, f"fd{output_port}_{input_port}"), complex
            )
            for state in states[input_port]:
                alpha = 1 / coefficient(elements, f"rp{state}_re_re_a{input_port}")
                beta = coefficient(elements, f"gp{state}_re_im_a{input_port}")
                real_coefficient = coefficient(elements, f"gr{state}_re_{output_port}_{input_port}")
                imaginary_coefficient = coefficient(elements, f"gr{state}_im_{output_port}_{input_port}")
                q = angular_frequency + alpha
                scattering += np.sqrt(impedance) * (
                    real_coefficient * q - imaginary_coefficient * beta
                ) / (q * q + beta * beta)
            response[:, output_port - 1, input_port - 1] = scattering
    return response



def audit_channel(channel_spice, saved_fit):
    elements = read_elements(channel_spice)
    with np.load(saved_fit) as saved:
        saved_frequencies = saved["f"]
        reconstructed = evaluate_response(saved_frequencies, elements)
        if (len(saved_frequencies) < 2 or not (np.diff(saved_frequencies) > 0).all()
                or reconstructed.shape != saved["fit"].shape or not np.isfinite(saved["fit"]).all()):
            raise ValueError("Saved fit needs increasing frequencies and a finite matching scattering matrix")
        if reconstructed.shape[1:] != (2, 2):
            raise ValueError("Channel audit requires the supplied two-port topology")
        reconstruction_error = float(abs(reconstructed - saved["fit"]).max())
        minimum_saved_hz, maximum_saved_hz = map(float, (saved_frequencies.min(), saved_frequencies.max()))
    if reconstruction_error >= 1e-10:
        raise ValueError("SPICE topology reconstruction differs from the saved fit")
    frequencies = [400e6, 5e9, 7e9, 20e9, 60e9, 100e9]
    samples = []
    for frequency, response in zip(frequencies, evaluate_response(frequencies, elements)):
        samples.append({
            "frequencyHz": frequency,
            "s21Magnitude": float(abs(response[1, 0])),
            "s21Db": float(20 * np.log10(abs(response[1, 0]))) if abs(response[1, 0]) > 0 else None,
            "maximumScatteringSingularValue": float(np.linalg.svd(response, compute_uv=False).max()),
            "reciprocityDifferenceAbs": float(abs(response[1, 0] - response[0, 1])),
            "outsideSavedBand": not minimum_saved_hz <= frequency <= maximum_saved_hz,
        })
    grid = np.geomspace(1e6, 1e12, 10001)
    singular_values = np.linalg.svd(evaluate_response(grid, elements), compute_uv=False).max(axis=1)
    report = {
        "channelSpiceSha256": hashlib.sha256(Path(channel_spice).read_bytes()).hexdigest(),
        "savedFitSha256": hashlib.sha256(Path(saved_fit).read_bytes()).hexdigest(),
        "savedFrequencyBandHz": [minimum_saved_hz, maximum_saved_hz],
        "maximumReconstructionDifferenceVsSavedFit": reconstruction_error,
        "formula": "S_ij = Fd_ij + sqrt(Z0) * sum((Gr_re*q - Gr_im*beta)/(q*q + beta*beta)); q=j*2*pi*f+1/Rp",
        "samples": samples,
        "sampledPassivity": {
            "frequencyBandHz": [float(grid[0]), float(grid[-1])],
            "sampleCount": len(grid),
            "maximumScatteringSingularValue": float(singular_values.max()),
            "frequencyAtMaximumHz": float(grid[np.argmax(singular_values)]),
        },
        "limitations": [
            "Above 5 GHz these are rational-fit extrapolations, not independent EM samples.",
            "No coefficients or physical parameters were changed.",
            "Sampled passivity is a numerical model check, not an accuracy or whole-band proof.",
        ],
    }
    return report
