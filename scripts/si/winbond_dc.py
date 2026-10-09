"""Diagnose a locally supplied, recovered Winbond model using native ngspice.

Vendor text is never bundled by this script. Results are DC sanity evidence,
not proof of HSPICE equivalence or validation of a routing eye.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
import shutil
import subprocess


IO_NODES = "dat dq enable a1 a5 a2 a6 a9 enable 0 0 bias vdd vdd ref 0 0"
OP_VECTORS = [
    "v(dq)", "v(vdd)", "v(dat)", "v(enable)", "v(a1)", "v(a5)",
    "v(a2)", "v(a6)", "v(a9)", "v(bias)", "v(ref)", "i(vdd)",
]
SWEEP_VECTORS = ["v(dq)", "i(vclamp)", "i(vdd)"]
NATIVE_ERROR = re.compile(
    r"(?im)^\s*(?:error\b|fatal\b|panic\b|segmentation fault\b|"
    r"doAnalyses:.*(?:failed|singular|convergence|timestep))|"
    r"(?im:simulation(?:s)? aborted|analysis failed|warning from checkvalid:.*(?:not available|zero length))"
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def logical_lines(text):
    """Yield SPICE continuation groups without losing physical line positions."""
    group = []
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        if line.lstrip().startswith("+") and group:
            group.append((line_number, line))
        else:
            if group:
                yield group
            group = [(line_number, line)]
    if group:
        yield group


def active_text(line):
    """Find HSPICE comments while preserving quoted/braced multiplication."""
    quote, braces = None, 0
    for index, character in enumerate(line):
        if quote:
            if character == quote:
                quote = None
        elif character in "'\"":
            quote = character
        elif character == "{":
            braces += 1
        elif character == "}":
            braces = max(0, braces - 1)
        elif not braces:
            if character == "$":
                return line[:index]
            if character == "*" and (index == 0 or line[index - 1].isspace()):
                return line[:index]
    return line


def instance_tokens(line):
    """Positional X-instance tokens, stopping before its named parameters."""
    if not re.match(r"(?i)^\s*x\S*\s", line):
        return []
    parameters = re.search(r"(?i)(?<!\S)(?:params:|[^\s=]+\s*=)", line)
    return line[:parameters.start()].split() if parameters else line.split()


def rename_length_parameter(text):
    """Rename only declared subcircuit length symbols and matching call keys."""
    groups = list(logical_lines(text))
    renamed_subcircuits = set()
    for group in groups:
        joined = " ".join(active_text(line).lstrip("+ ") for _, line in group)
        declaration = re.match(r"(?i)^\s*\.subckt\s+(\S+)", joined)
        if declaration and re.search(r"(?i)\bln\s*=", joined):
            renamed_subcircuits.add(declaration[1].lower())
    result, changes, affected = [], [], False
    for group in groups:
        joined = " ".join(active_text(line).lstrip("+ ") for _, line in group)
        declaration = re.match(r"(?i)^\s*\.subckt\s+(\S+)", joined)
        if declaration:
            affected = declaration[1].lower() in renamed_subcircuits
        call = instance_tokens(joined)
        matching_call = bool(call) and call[-1].lower() in renamed_subcircuits
        for line_number, line in group:
            active = active_text(line)
            spans = []
            if affected or matching_call:
                for match in re.finditer(r"(?i)\bln\b(?!\s*\()", active):
                    is_key = bool(re.match(r"\s*=", active[match.end():]))
                    if call and is_key and not matching_call:
                        continue
                    if affected or re.match(r"\s*=", active[match.end():]):
                        spans.append(match.span())
                        changes.append({
                            "line": line_number, "column": match.start() + 1,
                            "from": match[0], "to": "length_n",
                            "reason": "rename subcircuit formal length parameter",
                        })
            for start, end in reversed(spans):
                line = line[:start] + "length_n" + line[end:]
            result.append(line)
        if re.match(r"(?i)^\s*\.ends\b", joined):
            affected = False
    return "".join(result), changes


RECEIVER_WRAPPERS = {
    "gcres": """\n* Diagnostic SI-to-micron boundary; original resistor coefficients unchanged
.subckt gcres_si bulk in out w=1u l=1u
XBOUNDARY bulk in out gcres w='w*1e6' l='l*1e6'
.ends gcres_si
""",
    "ynresx": """\n* Diagnostic SI-to-micron boundary; original resistor coefficients unchanged
.subckt ynresx_si bulk in out wb w=1u l=1u ser=1 fc=1
XBOUNDARY bulk in out wb ynresx w='w*1e6' l='l*1e6' ser=ser fc=fc
.ends ynresx_si
""",
}


def receiver_geometry_microns(text):
    """Adapt receiver call units, preserving primitive bodies and literals."""
    result, changes, families = [], [], set()
    for group in logical_lines(text):
        joined = " ".join(active_text(line).strip().lstrip("+").strip() for _, line in group)
        call = re.match(r"(?i)^\s*x\S*\s", joined)
        family = re.search(r"(?i)(?<!\S)(gcres|ynresx)(?=\s+(?:params:\s*)?[wl]\s*=)", joined) if call else None
        for line_number, line in group:
            if family:
                name = family[1].lower()
                match = re.search(r"(?i)(?<!\S)" + name + r"(?!\S)", active_text(line))
                if match:
                    replacement = name + "_si"
                    changes.append({"line": line_number, "column": match.start() + 1,
                                    "from": match[0], "to": replacement,
                                    "reason": "receiver SI geometry to vendor micron contract at subcircuit boundary"})
                    line = line[:match.start()] + replacement + line[match.end():]
                    families.add(name)
            result.append(line)
    if not families:
        raise ValueError("receiver geometry adaptation requested, but no gcres/ynresx calls found")
    adapted = "".join(result)
    for family in sorted(families):
        if re.search(r"(?im)^\s*\.subckt\s+" + family + r"_si\b", text):
            raise ValueError(f"receiver wrapper already defined: {family}_si")
        wrapper = RECEIVER_WRAPPERS[family]
        changes.append({"line": len(adapted.splitlines()) + 1, "column": 1, "from": "", "to": wrapper,
                        "reason": "append unit conversion wrapper; original resistor model bodies unchanged"})
        adapted += wrapper
    return adapted, changes


def prepare_model(source, destination, adapt_receiver=False, circuit_file="W631GG6MB"):
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise ValueError(f"model directory does not exist: {source}")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("supplied model and compatibility output directories must not overlap")
    if destination.exists():
        shutil.rmtree(destination)
    provenance = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        changes = []
        try:
            body = raw.decode("utf-8")
            for line in body.splitlines():
                active = active_text(line)
                if re.match(r"(?i)^\s*\.prot\b", active) or "·" in active:
                    raise ValueError(f"unrecovered active model text in {path}")
            compatible, changes = rename_length_parameter(body)
            if adapt_receiver and str(path.relative_to(source)) == circuit_file:
                compatible, geometry_changes = receiver_geometry_microns(compatible)
                changes.extend(geometry_changes)
            transformed = compatible.encode("utf-8")
        except UnicodeDecodeError:
            transformed = raw
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(transformed)
        provenance.append({
            "file": str(path.relative_to(source)), "inputSha256": sha256(raw),
            "compatibleSha256": sha256(transformed), "transformations": changes,
        })
    return provenance


def spice_path(path):
    value = str(path)
    if "'" in value or "\n" in value:
        raise ValueError("SPICE file paths cannot contain apostrophes or newlines")
    return "'" + value + "'"


def subcircuits(text):
    """Return formal pins and active logical lines from the supplied circuit."""
    result, current = {}, None
    for group in logical_lines(text):
        line = " ".join(active_text(part).strip().lstrip("+").strip() for _, part in group).strip()
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0].lower() == ".subckt":
            pins = []
            for token in tokens[2:]:
                if "=" in token or token.lower() == "params:":
                    break
                pins.append(token)
            current = {"pins": pins, "lines": []}
            result[tokens[1].lower()] = current
        elif tokens[0].lower() == ".ends":
            current = None
        elif current is not None:
            current["lines"].append(line)
    return result


def diagnostic_targets(model_text, io_subckt, stage_subckt=None, stage_nodes=None):
    """Extract the vendor's stage wiring and calibration source expressions."""
    circuits = subcircuits(model_text)
    complete = {"name": "complete-io", "subckt": io_subckt, "nodes": IO_NODES,
                "op_vectors": OP_VECTORS.copy(), "extra_sources": ""}
    targets = [complete]
    if stage_nodes:
        targets.append({"name": "output-stage", "subckt": stage_subckt,
                        "nodes": stage_nodes, "op_vectors": OP_VECTORS.copy(), "extra_sources": ""})
        return targets
    stage_subckt = stage_subckt or "z38hd3_dqobuf"
    if stage_subckt.lower() not in circuits:
        return targets
    if io_subckt.lower() not in circuits:
        raise ValueError(f"missing complete I/O subcircuit: {io_subckt}")
    io = circuits[io_subckt.lower()]
    pin_mapping = dict(zip(io["pins"], IO_NODES.split()))
    call = next((instance_tokens(line) for line in io["lines"]
                 if instance_tokens(line) and instance_tokens(line)[-1].lower() == stage_subckt.lower()), None)
    if not call:
        raise ValueError("output stage is not directly instantiated by the complete I/O buffer")
    nodes = call[1:-1]
    if len(nodes) != len(circuits[stage_subckt.lower()]["pins"]):
        raise ValueError("output-stage formal/actual pin counts disagree")
    internal_nodes = {node for node in nodes if node not in pin_mapping and node != "0"}
    sources = [line for line in io["lines"] if line.lower().startswith("v")
               and len(line.split()) >= 4 and line.split()[1] in internal_nodes and line.split()[2] == "0"]
    if {line.split()[1] for line in sources} != internal_nodes:
        raise ValueError("output-stage internal controls lack recovered ideal calibration sources")
    ordered_controls = list(dict.fromkeys(node for node in nodes if node in internal_nodes))
    complete["op_vectors"] += [f"v(xio.{node})" for node in ordered_controls]
    targets.append({
        "name": "output-stage", "subckt": stage_subckt,
        "nodes": " ".join(pin_mapping.get(node, node) for node in nodes),
        "extra_sources": "\n".join(sources),
        "op_vectors": OP_VECTORS + [f"v({node})" for node in ordered_controls],
        "calibrationSourceProvenance": sources,
    })
    return targets


def compare_stages(cases):
    comparisons = []
    for complete in cases:
        if not complete["name"].startswith("complete-io-"):
            continue
        stage = next((case for case in cases if case["name"].startswith("output-stage-")
                      and case["temperatureC"] == complete["temperatureC"] and case["datV"] == complete["datV"]), None)
        if not stage:
            continue
        io_values = complete["op"].get("resolvedVoltagesAndSupplyCurrent", {})
        stage_values = stage["op"].get("resolvedVoltagesAndSupplyCurrent", {})
        if "v(dq)" not in io_values or "v(dq)" not in stage_values:
            continue
        calibration = {}
        for vector, value in io_values.items():
            if vector.startswith("v(xio."):
                stage_vector = vector.replace("v(xio.", "v(", 1)
                if stage_vector in stage_values:
                    calibration[stage_vector] = {"completeV": value, "stageV": stage_values[stage_vector],
                                                  "differenceV": stage_values[stage_vector] - value}
        comparisons.append({"temperatureC": complete["temperatureC"], "datV": complete["datV"],
                            "completeDqV": io_values["v(dq)"], "stageDqV": stage_values["v(dq)"],
                            "stageMinusCompleteDqV": stage_values["v(dq)"] - io_values["v(dq)"],
                            "resolvedCalibrationComparison": calibration})
    return comparisons


def run_cases(binary, model, config, targets, out):
    work = [(target, temperature, dat) for target in targets
            for temperature in (27, 85) for dat in (0, config["supply"])]

    def run_case(item):
        target, temperature, dat = item
        name = f"{target['name']}-t{temperature}-dat{'high' if dat else 'low'}"
        case = {"name": name, "temperatureC": temperature, "datV": dat,
                "subckt": target["subckt"], "nodes": target["nodes"]}
        for sweep in (False, True):
            mode = "sweep" if sweep else "op"
            deck = make_deck(model, config, target, dat, temperature, sweep)
            case_config = dict(config, dat=dat, temperature=temperature)
            queries = [line for line in case["op"]["nativeDeviceQueries"] if "@rload[" not in line] if sweep else None
            case[mode] = run_native(binary, deck, out / name / mode, config["timeout"], case_config, sweep, target["op_vectors"], queries)
        case["pass"] = case["op"]["pass"] and case["sweep"]["pass"]
        return case

    with ThreadPoolExecutor(max_workers=config["jobs"]) as pool:
        return list(pool.map(run_case, work))


def make_deck(model, config, target, dat, temperature, sweep):
    for value in (config["subckt"], config["strength"]):
        if not re.fullmatch(r"[\w.-]+", value):
            raise ValueError(f"invalid SPICE identifier: {value}")
    mode = "SWEEP" if sweep else "OP"
    load = "VCLAMP dq 0 0" if sweep else f"RLOAD dq 0 {config['load_ohm']:g}"
    analysis = (
        f"dc VCLAMP {config['sweep_start']:g} {config['sweep_stop']:g} {config['sweep_step']:g}"
        if sweep else "op"
    )
    vectors = SWEEP_VECTORS if sweep else target.get("op_vectors", OP_VECTORS)
    # Calibration sources use the selected vendor .lib parameters directly.
    # Their resolved node voltages are read from the native OP, never inferred
    # by a separate parser of vendor .param text.
    return f"""Winbond native DC diagnostic: {target['name']} DAT={dat:g} T={temperature:g}
.include {spice_path(model / config['model_file'])}
.include {spice_path(model / config['corner'])}
.lib {spice_path(model / 'ds_odt_param')} {config['strength']}
.temp {temperature:g}
VDD vdd 0 {config['supply']:g}
VDAT dat 0 {dat:g}
VEN enable 0 {config['supply']:g}
VA1 a1 0 {{vem1}}
VA5 a5 0 {{vem5}}
VA2 a2 0 {{vem2}}
VA6 a6 0 {{vem6}}
VA9 a9 0 {{vem9}}
VBIAS bias 0 0.5
VREF ref 0 {config['supply'] / 2:g}
{target.get('extra_sources', '')}
XIO {target['nodes']} {target['subckt']}
{load}
.control
set wr_singlescale
set wr_vecnames
set numdgt=15
{analysis}
listing e
show all : all
write {mode.lower()}.raw all
wrdata {mode.lower()}.tsv {' '.join(chr(34) + vector + chr(34) for vector in vectors)}
echo WINBOND_{mode}_COMPLETE
quit
.endc
.end
"""


def read_table(path, vectors):
    if not path.is_file():
        raise ValueError(f"missing native data file: {path.name}")
    rows = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        try:
            row = [float(field) for field in fields]
        except ValueError:
            if rows or any(re.match(r"^[+-]?(?:\d|\.\d|nan|inf)", field, re.I) for field in fields):
                raise ValueError(f"malformed native data in {path.name}")
            continue  # wr_vecnames header
        if len(row) != len(vectors) + 1 or not all(math.isfinite(v) for v in row):
            raise ValueError(f"nonfinite or incomplete native data in {path.name}")
        rows.append(row)
    return rows


def evaluated_devices(log):
    """Read ngspice show tables, including repeated groups of device columns."""
    devices, result = [], {}
    for line in log.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0].lower() == "device":
            devices = fields[1:]
            for name in devices:
                result.setdefault(name, {})
        elif devices and fields[0].lower() in {"resistance", "w", "l", "m", "nf", "i", "v"}:
            if len(fields) != len(devices) + 1:
                continue
            try:
                values = [float(v) for v in fields[1:]]
            except ValueError:
                continue
            for name, value in zip(devices, values):
                result[name][fields[0].lower()] = value
    result = {name: values for name, values in result.items() if values}
    exact = {}
    for line in log.splitlines():
        match = re.match(r'\s*"?@([rmb][^\s\[]+)\[(resistance|w|l|m|nf|i|v)\]"?\s*=\s*(\S+)', line, re.I)
        if match:
            try:
                exact.setdefault(match[1], {})[match[2].lower()] = float(match[3])
            except ValueError:
                continue
    if exact:
        result = exact  # show's fixed-width name columns truncate long hierarchy paths
    # ngspice elaborates expression-valued R into an ASRC current source.
    # ASRC's reported i excludes its multiplicity; v/(i*m) is the physical R.
    # Keep its expanded expression as evidence when voltage/current are zero.
    for line in log.splitlines():
        match = re.match(
            r"\s*\d+\s*:\s*(b\S+)\s+\S+\s+\S+\s+i\s*=\s*v\([^)]*\)\s*/", line, re.I
        )
        if match and match[1] in result:
            values = result[match[1]]
            values["expandedResistanceExpression"] = line.split(":", 1)[1].strip()
            # ASRCask returns a previous-Newton current. At dormant branches,
            # solver residuals can overwhelm leakage and reverse its sign.
            if all(key in values for key in ("v", "i", "m")) and abs(values["i"] * values["m"]) > 1e-9 and abs(values["v"]) > 1e-8:
                values["effectiveResistanceOhm"] = values["v"] / (values["i"] * values["m"])
            else:
                values["effectiveResistanceUnavailable"] = "below 1 nA or 10 nV resolution of ASRC previous-Newton current"
    native_resistance_names = {}
    for line in log.splitlines():
        marker = re.match(r'\s*WINBOND_EVALUATED_R\s+"?(b\S+?)"?\s+(wb_res_\d+)\s*$', line, re.I)
        if marker:
            native_resistance_names[marker[2]] = marker[1]
        value = re.match(r"\s*(wb_res_\d+)(?:\[length\([^)]*\)-1\])?\s*=\s*(\S+)", line, re.I)
        if value and value[1] in native_resistance_names:
            try:
                resistance = float(value[2])
            except ValueError:
                continue
            values = result.setdefault(native_resistance_names[value[1]], {})
            values["effectiveResistanceOhm"] = resistance
            values["effectiveResistanceMethod"] = "native flattened denominator divided by ASRC multiplicity"
            values.pop("effectiveResistanceUnavailable", None)
        extreme = re.match(r"\s*vec(min|max)\((wb_res_\d+)\)\s*=\s*(\S+)", line, re.I)
        if extreme and extreme[2] in native_resistance_names:
            try:
                resistance = float(extreme[3])
            except ValueError:
                continue
            key = "minimumEffectiveResistanceOhm" if extreme[1].lower() == "min" else "maximumEffectiveResistanceOhm"
            result.setdefault(native_resistance_names[extreme[2]], {})[key] = resistance
    return result


def resistance_expression(line, temperature):
    match = re.search(r"\bi\s*=\s*v\([^)]*\)\s*/\s*(\()", line, re.I)
    if not match:
        return None
    start, depth = match.start(1), 0
    for index in range(start, len(line)):
        if line[index] == "(":
            depth += 1
        elif line[index] == ")":
            depth -= 1
            if depth == 0:
                expression = line[start:index + 1]
                expression = re.sub(r"(?i)\btemper\b", str(temperature), expression)
                # '<' and '>' in bus names are shell-style control redirections
                # unless every voltage node argument is quoted.
                expression = re.sub(r"(?i)\bv\s*\(([^)]*)\)",
                                    lambda m: "v(" + ",".join('"' + node.strip() + '"' for node in m[1].split(",")) + ")", expression)
                # Control commands also interpret bare comparison operators
                # as redirects. The equivalent word operators avoid that.
                pieces = re.split(r'("[^"]*")', expression)
                for part in range(0, len(pieces), 2):
                    for symbol, word in ((">=", "ge"), ("<=", "le"), (">", "gt"), ("<", "lt")):
                        pieces[part] = pieces[part].replace(symbol, " " + word + " ")
                return "".join(pieces)
    raise ValueError("unbalanced flattened behavioral resistor denominator")


def device_queries(log):
    """Query actual flattened instance names instead of truncated show labels."""
    commands, seen, resistance_index = [], set(), 0
    temperature = re.search(r"Doing analysis at TEMP\s*=\s*([+-]?[\d.eE]+)", log)
    for line in log.splitlines():
        match = re.match(r"\s*\d+\s*:\s*([rmb]\S+)\s", line, re.I)
        if not match or match[1] in seen:
            continue
        name = match[1]
        seen.add(name)
        if name.lower().startswith("b"):
            if not re.search(r"\bi\s*=\s*v\([^)]*\)\s*/", line, re.I):
                continue
            parameters = ("v", "i", "m")
        elif name.lower().startswith("m"):
            parameters = ("w", "l", "m", "nf")
        else:
            parameters = ("resistance", "w", "l", "m")
        commands.append("print " + " ".join(f'"@{name}[{parameter}]"' for parameter in parameters))
        if name.lower().startswith("b") and temperature:
            expression = resistance_expression(line, temperature[1])
            vector = f"wb_res_{resistance_index}"
            commands += [f'let {vector} = {expression}/"@{name}[m]"',
                         f'echo WINBOND_EVALUATED_R "{name}" {vector}',
                         f'print {vector}', f'print vecmin({vector})', f'print vecmax({vector})']
            resistance_index += 1
    return "\n".join(commands)


def check_results(rows, log, config, sweep):
    errors = []
    if sweep:
        count = round((config["sweep_stop"] - config["sweep_start"]) / config["sweep_step"]) + 1
        if len(rows) != count:
            errors.append(f"incomplete DQ sweep: {len(rows)} of {count} rows")
        for index, row in enumerate(rows):
            expected = config["sweep_start"] + index * config["sweep_step"]
            if abs(row[0] - expected) > 1e-7 or abs(row[1] - expected) > 1e-7:
                errors.append(f"wrong DQ sweep coordinate at row {index}")
                break
            if any(abs(current) > config["max_current"] for current in row[2:]):
                errors.append(f"implausible native current at DQ={row[1]:g} V")
                break
    elif len(rows) != 1:
        errors.append(f"operating point needs exactly one row, received {len(rows)}")
    elif not -config["rail_margin"] <= rows[0][1] <= config["supply"] + config["rail_margin"]:
        errors.append(f"electrically impossible loaded DQ operating point: {rows[0][1]:g} V")
    elif abs(rows[0][len(OP_VECTORS)]) > config["max_current"]:
        errors.append(f"implausible supply current: {rows[0][len(OP_VECTORS)]:g} A")
    if not sweep and len(rows) == 1 and "dat" in config:
        resolved = dict(zip(OP_VECTORS, rows[0][1:]))
        for vector, expected in (("v(vdd)", config["supply"]), ("v(enable)", config["supply"]), ("v(dat)", config["dat"])):
            if abs(resolved[vector] - expected) > 1e-6:
                errors.append(f"wrong resolved control {vector}: {resolved[vector]:g} V, expected {expected:g} V")
        high = config["dat"] > config["supply"] / 2
        if (high and resolved["v(dq)"] <= config["supply"] / 2) or (not high and resolved["v(dq)"] >= config["supply"] / 2):
            errors.append("failed minimal noninverting DAT/DQ logic check at VDD/2 (diagnostic threshold, not vendor VIH/VIL)")
    devices = evaluated_devices(log)
    if not devices:
        errors.append("missing evaluated device values from native show all")
    for name, values in devices.items():
        for parameter, value in values.items():
            physical_parameter = (
                parameter in {"resistance", "effectiveResistanceOhm", "minimumEffectiveResistanceOhm", "maximumEffectiveResistanceOhm", "m"}
                or (name.lower().startswith("m") and parameter in {"w", "l", "nf"})
            )
            if physical_parameter and (not math.isfinite(value) or value < 0 or (parameter in {"w", "l", "m", "nf"} and value == 0)):
                errors.append(f"impossible evaluated device {name}: {parameter}={value:g}")
    return errors, devices


def run_native(binary, deck, directory, timeout, config, sweep, op_vectors=None, native_queries=None):
    directory.mkdir(parents=True, exist_ok=True)
    for filename in ("op.raw", "op.tsv", "sweep.raw", "sweep.tsv"):
        (directory / filename).unlink(missing_ok=True)
    (directory / ".spiceinit").write_text("set ngbehavior=hsa\n")
    if native_queries:
        if sweep:
            native_queries = [re.sub(r"^print (wb_res_\d+)$", r"print \1[length(\1)-1]", line) for line in native_queries]
        deck = deck.replace("show all : all\n", "show all : all\n" + "\n".join(native_queries) + "\n")
    (directory / "bench.cir").write_text(deck)
    command = [str(binary), "-b", "bench.cir"]
    errors = []
    try:
        run = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=timeout)
        log, returncode = run.stdout + run.stderr, run.returncode
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        log, returncode = decode(exc.stdout) + decode(exc.stderr), None
        errors.append(f"native simulation exceeded {timeout:g} seconds")
    queries = "\n".join(native_queries) if native_queries else device_queries(log) if returncode == 0 and not NATIVE_ERROR.search(log) else ""
    if queries and not native_queries:
        # The first native expansion supplies the exact hierarchy. The second
        # run changes only output commands, preserving the circuit and inputs.
        (directory / "initial-bench.cir").write_text(deck)
        (directory / "initial-ngspice.log").write_text(log)
        for filename in ("op.raw", "op.tsv", "sweep.raw", "sweep.tsv"):
            path = directory / filename
            if path.exists():
                path.replace(directory / ("initial-" + filename))
        deck = deck.replace("show all : all\n", "show all : all\n" + queries + "\n")
        (directory / "bench.cir").write_text(deck)
        try:
            run = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=timeout)
            log, returncode = run.stdout + run.stderr, run.returncode
        except subprocess.TimeoutExpired as exc:
            log, returncode = str(exc), None
            errors.append(f"native evaluated-device queries exceeded {timeout:g} seconds")
    (directory / "ngspice.log").write_text(log)
    mode = "SWEEP" if sweep else "OP"
    if returncode != 0:
        errors.append(f"native process return code: {returncode}")
    if NATIVE_ERROR.search(log):
        errors.append("native ngspice reported an error; inspect ngspice.log")
    if f"WINBOND_{mode}_COMPLETE" not in log:
        errors.append(f"missing native {mode.lower()} completion marker")
    if "temperature" in config:
        resolved_temperature = re.search(r"Doing analysis at TEMP\s*=\s*([+-]?[\d.eE]+)", log)
        if not resolved_temperature or abs(float(resolved_temperature[1]) - config["temperature"]) > 1e-6:
            errors.append("native analysis temperature does not match the requested bench")
    if not (directory / f"{mode.lower()}.raw").is_file():
        errors.append("missing native raw circuit results")
    rows, devices = [], {}
    try:
        rows = read_table(directory / f"{mode.lower()}.tsv", SWEEP_VECTORS if sweep else op_vectors or OP_VECTORS)
        electrical_errors, devices = check_results(rows, log, config, sweep)
        errors.extend(electrical_errors)
        for name in re.findall(r'echo WINBOND_EVALUATED_R "([^\"]+)"', queries):
            if not {"effectiveResistanceOhm", "minimumEffectiveResistanceOhm", "maximumEffectiveResistanceOhm"} <= devices.get(name, {}).keys():
                errors.append(f"missing native evaluated resistance values for {name}")
    except ValueError as exc:
        errors.append(str(exc))
    result = {"pass": not errors, "errors": errors, "returncode": returncode,
              "command": command, "deckSha256": sha256(deck.encode()),
              "rows": len(rows), "evaluatedDevices": devices, "nativeDeviceQueries": queries.splitlines()}
    if rows and not sweep:
        result["resolvedVoltagesAndSupplyCurrent"] = dict(zip(op_vectors or OP_VECTORS, rows[0][1:]))
    (directory / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
