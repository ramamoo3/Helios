"""Compare the routed leg across SPICE engines with recorded driver-pin inputs."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

import isolated_rear_bypass as rear
from isolated_driver_test import CONTROL


ROOT = rear.ROOT
REPLAY = rear.dfn.replay
LABELS = ("nominal_high_resistive", "nominal_high_short", "nominal_low_short")
PROBES = (
    "high_bias_min", "high_bias_max", "high_rear_min", "min_vdd", "max_vdd",
    "vds_hi_scan", "vds_lo_scan", "max_vgs_high", "max_vgs_low", "min_vgs_high",
    "min_vgs_low", "peak_shunt", "device_energy_j", "current_rise_1a",
    "current_fall_1a", "current_after",
)
PIN_NODES = (("dis", "dis"), ("hi", "hi_masked"), ("lo", "li_masked"))
PROFILES = ("gear_lte", "gear_nonlinear")
CONTROL_PROFILES = (*PROFILES, "trap_nonlinear")
OPTIONS = ".OPTIONS TIMEINT METHOD=GEAR RELTOL=.004 ABSTOL=10n"
TOLERANCE_V = .005


def replace_required(source, pattern, replacement, expected=1):
    updated, count = re.subn(pattern, replacement, source, flags=re.M | re.I)
    if count != expected:
        raise ValueError(f"Review the translation of {pattern}: expected {expected}, found {count}")
    return updated


def xyce_mosfet(source):
    # Xyce assigns BSIM3 to level 9. The PSpice level-7 library supplies the
    # same coefficients and dimension values used here.
    source = replace_required(source, r"(LEVEL\s*=\s*)7\b", r"\g<1>9")
    source = replace_required(
        source, r"^\s*\.model RTEMP RES \(TC1=\{ptrc1\} TC2=\{ptrc2\}\)",
        "\n.MODEL RTEMP RES (TC1=7.00e-3 TC2=2.0e-5)",
    )

    def table_pairs(match):
        rows = re.findall(r"\(\s*([^\s,()]+)\s+([^\s,()]+)\s*\)", match[0])
        if len(rows) != 101:
            raise ValueError("The vendor capacitance table changed")
        return "".join(f"+ ({x},{y})\n" for x, y in rows)

    table_rows = r"^(?:\+[ \t]*\([ \t]*\S+[ \t]+\S+[ \t]*\)[ \t]*\n(?:[ \t]*\n)*){101}"
    source = replace_required(source, table_rows, table_pairs, expected=3)
    width = re.search(r"^\s*\.PARAM\s+pwidthP\s*=([^\s]+)", source, re.M | re.I)
    if width is None:
        raise ValueError("The vendor MOSFET width parameter changed")
    return source.replace("{pwidthP}", width[1]).replace("{perimP}", str(Decimal(width[1])*Decimal("2.1")))


def piecewise(points):
    # Split each line segment until the retained PWL reproduces the accepted
    # ngspice input samples to within TOLERANCE_V.
    keep = {0, len(points)-1}
    pending = [(0, len(points)-1)]
    while pending:
        start, end = pending.pop()
        if end-start < 2:
            continue
        t0, v0 = points[start]
        t1, v1 = points[end]
        error, index = max((abs(v0+(v1-v0)*(points[k][0]-t0)/(t1-t0)-points[k][1]), k)
                           for k in range(start+1, end))
        if error > TOLERANCE_V:
            keep.add(index)
            pending.extend(((start, index), (index, end)))
    return tuple(points[index] for index in sorted(keep))


def capture_commands(args, work, label, deck):
    deck = replace_required(deck, r"^\.tran 250p (\S+) 0 250p$", r".tran 500p \1 0 500p")
    deck = deck.removesuffix(".end\n") + f""".control
set wr_singlescale
set numdgt=15
run
wrdata {label}.dat v(dis,vss) v(hi_masked,vss) v(li_masked,vss)
.endc
.end
"""
    measurements = REPLAY.run_case(args.ngspice, work, label+"-capture", deck)
    samples = [tuple(map(float, line.split())) for line in (work/f"{label}.dat").read_text().splitlines() if line.strip()]
    if len(samples) < 3 or any(len(sample) != 4 for sample in samples):
        raise ValueError("Expected time and three driver-pin voltages")
    if any(a[0] >= b[0] for a, b in zip(samples, samples[1:])):
        raise ValueError("Capture has a non-increasing time field")
    stimuli = []
    counts = []
    for column, (signal, node) in enumerate(PIN_NODES, 1):
        points = piecewise([(sample[0], sample[column]) for sample in samples])
        lines = [f"Vstim_{signal} {node} vss PWL("]
        for start in range(0, len(points), 4):
            lines.append("+ "+" ".join(f"{t:.16g} {v:.11g}" for t, v in points[start:start+4]))
        lines[-1] += ")"
        stimuli.extend(lines)
        counts.append(len(points))
    return "\n".join(stimuli), {
        "input_rows": len(samples), "pwl_points_dis_hi_lo": counts,
        "closed_loop_ngspice_500ps": {name: measurements[name] for name in PROBES if name in measurements},
    }


def open_loop(deck, pin_sources):
    # Preserve Cmodule, the bias rails, shunt, copper, MOSFETs, and loads.
    # Disable, PWM and the previously closed-loop trip now come from PWL data.
    deck = replace_required(
        deck, r"^Rdisable[^\n]+\nSpermit[^\n]+\n\.model PERMIT_SW[^\n]+\nBpermit_local[^\n]+\n", "",
    )
    start, end = deck.index(".include protection.lib"), deck.index("Cmodule vss")
    deck = deck[:start] + deck[end:]
    deck = re.sub(r"^(Binput_relative|Ben_relative|Vhi|Vli) [^\n]+\n", "", deck, flags=re.M)
    deck = "\n".join(line for line in deck.split("\n")
                     if not line.startswith(".meas ") or line.split()[2] in PROBES)
    deck = replace_required(deck, r"^\.tran 250p (\S+) 0 250p$", r".tran 500p \1 0 500p")
    return deck.removesuffix(".end\n") + pin_sources + "\n.end\n"


def xyce_deck(deck, profile):
    options = OPTIONS + (" ERROPTION=1 DELMAX=500p" if profile == "gear_nonlinear" else "")
    deck = replace_required(deck, r"^\.options [^\n]+$", options)
    deck = deck.replace(".temp 25", ".OPTIONS DEVICE TEMP=25")
    deck = deck.replace("par('v(vdd)-v(vss)')", "v(vdd,vss)")
    # These probes only drove unused measure nodes. Xyce does not expose the
    # currents of individual members of our coupled-inductor network.
    deck = re.sub(r"^B(?:high_tvs|tvs_current|feed|positive_channel) [^\n]+\n", "", deck, flags=re.M | re.I)
    return deck.removesuffix(".end\n") + ".PRINT TRAN V(a_v) V(dh_s) V(dl_s) V(iabs)\n.end\n"


def xyce_case(args, work, name, source):
    path = work/(name+".cir")
    path.write_text(source, encoding="ascii", newline="\n")
    error = None
    try:
        done = subprocess.run([args.xyce, "-linsolv", "klu", path.name], cwd=work, capture_output=True,
                              text=True, errors="replace", timeout=args.timeout)
        log = done.stdout + done.stderr
        if done.returncode:
            errors = [line.strip() for line in log.splitlines()
                      if re.search(r"time\s*step.*too small|Netlist error|Simulation aborted", line, re.I)]
            error = errors[-1] if errors else f"Xyce exit code {done.returncode}"
    except subprocess.TimeoutExpired as timeout:
        log = "\n".join(stream.decode(errors="replace") if isinstance(stream, bytes) else stream or ""
                        for stream in (timeout.stdout, timeout.stderr))
        error = f"Xyce exceeded {args.timeout} seconds"
    measurement = path.with_suffix(".cir.mt0")
    values = {}
    missing = []
    if measurement.is_file():
        for line in measurement.read_text().splitlines():
            match = re.fullmatch(r"(\w+)\s*=\s*(\S+)", line.strip())
            if match:
                key, raw = match.groups()
                if raw == "FAILED":
                    missing.append(key.lower())
                else:
                    values[key.lower()] = float(raw)
    incomplete = bool(error or missing or not values)
    result = {"completed": not incomplete, "measures": values}
    if incomplete:
        trace = path.with_suffix(".cir.prn")
        if trace.is_file():
            with trace.open("rb") as output:
                output.seek(max(0, trace.stat().st_size-4096))
                times = re.findall(rb"^[ \t]*\d+[ \t]+([-+\d.eE]+)[ \t]", output.read(), flags=re.M)
            if times:
                result["last_printed_time_s"] = float(times[-1])
        result["error"] = error or "Missing measures"
        result["failed_measures"] = missing
    result["ignored_vendor_parameters"] = sorted(set(
        re.findall(r"No model parameter (\w+) found", log, flags=re.I),
    ))
    return result


def control_deck(profile, source=CONTROL):
    method = "TRAP" if profile == "trap_nonlinear" else "GEAR"
    options = f".OPTIONS TIMEINT METHOD={method} RELTOL=0.005"
    if profile.endswith("nonlinear"):
        options += " ERROPTION=1 DELMAX=2n"
    source = source.replace(".options method=gear reltol=0.005", options)
    return source.removesuffix(".end\n") + ".PRINT TRAN V(high_gate)\n.end\n"


def scheduler_spacing_deck():
    # BENCH_BLANK is in 10 ns ticks. Apply it at the driver pins in both
    # directions while preserving the standalone fixture's rise/fall slopes.
    ticks = int(re.search(r"\bBENCH_BLANK\s*=\s*(\d+)", (ROOT/"bench-startup.h").read_text())[1])
    gap_us = Decimal(ticks) / 100
    forward = Decimal("2.2") + gap_us
    reverse = Decimal("3.1") + gap_us
    slope = Decimal(".01")
    source = replace_required(CONTROL, r"2\.22u 0 2\.23u 3\.3", f"{forward}u 0 {forward+slope}u 3.3")
    source = replace_required(source, r"3\.4u 0 3\.41u 3\.3", f"{reverse}u 0 {reverse+slope}u 3.3")
    source = replace_required(source, r"^\.tran 2n 234u 0 2n$", f".tran 2n {reverse+Decimal('.7')}u 0 2n")
    source = source[:source.index(".meas tran did_disable")] + (
        ".meas tran low_off WHEN v(gb)=2 FALL=1 TD=3.1u\n"
        f".meas tran high_rise WHEN v(high_gate)=2 RISE=1 TD={reverse}u\n.end\n"
    )
    return source, ticks*10


def bench_decks(args, work):
    source = rear.EXTRACTION
    data = json.loads(source.read_text(encoding="utf-8"))
    if data["board_sha256"] != REPLAY.digest(rear.BOARD) or data["ports"] != list(rear.NODES):
        raise ValueError("The rear-bypass layout and compact model differ")
    base = ROOT/"bench-bootstrap-impedance.json"
    shunt = ROOT/"bench-shunt-transfer.json"
    filt = ROOT/"bench-shunt-filter-results.json"
    selected = json.loads(filt.read_text(encoding="utf-8"))
    if selected["extraction_sha256"] != REPLAY.digest(base) or selected["shunt_sha256"] != REPLAY.digest(shunt):
        raise ValueError("The shunt calibration files differ")
    mount = json.loads(shunt.read_text(encoding="utf-8"))["cases"]["nominal"]
    circuit = REPLAY.circuit_from(mount, selected["selected_filter_nf"])
    capture = rear.Capture()
    REPLAY.add_cases(capture, work, args, data, REPLAY.read_extraction(base), circuit,
                     nodes=rear.NODES, revise_bias=rear.bias_deck, corners=REPLAY.BIAS_CORNERS[:1])
    return {case: capture.decks[case][1] for case in LABELS}


def simulation_error(error, work):
    lines = str(error).replace(str(work), "simulation").splitlines()
    return next((line.strip() for line in lines if "timestep" in line.lower()), lines[-1])


def run(args):
    results = {}
    with TemporaryDirectory() as staging, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(staging)
        xyce = work/"xyce"
        xyce.mkdir()
        rear.dfn.stage_models(args, work)
        model = (work/"csd19531q5a.lib").read_text(encoding="ascii")
        translated = xyce_mosfet(model)
        (xyce/"csd19531q5a.lib").write_text(translated, encoding="ascii", newline="\n")
        for name in ("ti-isolated.lib", "commutation_clamp.lib"):
            shutil.copyfile(work/name, xyce/name)
        plants = {}
        for label, source in bench_decks(args, work).items():
            failures = []
            for _ in range(2):
                try:
                    pins, details = capture_commands(args, work, label, source)
                except (RuntimeError, subprocess.TimeoutExpired) as error:
                    failures.append(simulation_error(error, work))
                    continue
                plants[label] = open_loop(source, pins)
                results[label] = {"capture_completed": True, **details, "xyce": {}}
                break
            else:
                results[label] = {"capture_completed": False}
            if failures:
                results[label]["capture_errors"] = failures
            print(label, "input capture saved", flush=True)
        controls = {"ngspice_driver": {"completed": True, "measures":
                                      REPLAY.run_case(args.ngspice, work, "driver", CONTROL)}}
        spacing, spacing_ns = scheduler_spacing_deck()
        controls["ngspice_driver_scheduler_gap"] = {"completed": True, "measures":
                                                   REPLAY.run_case(args.ngspice, work, "driver-gap", spacing)}
        jobs = {}
        for profile in CONTROL_PROFILES:
            jobs[pool.submit(xyce_case, args, xyce, "driver-"+profile, control_deck(profile))] = ("control", profile)
            name = profile+"_scheduler_gap"
            jobs[pool.submit(xyce_case, args, xyce, name, control_deck(profile, spacing))] = ("control", name)
        mosfet = REPLAY.SANITY.removesuffix(".end\n")
        for name, options in (
            ("xyce_mosfet_default", ""),
            ("xyce_mosfet_gear", ".OPTIONS TIMEINT METHOD=GEAR ERROPTION=1 DELMAX=1n\n"),
        ):
            deck = mosfet + options + ".PRINT TRAN V(d)\n.end\n"
            jobs[pool.submit(xyce_case, args, xyce, name, deck)] = ("control", name)
        controls["ngspice_mosfet"] = {"completed": True, "measures":
                                     REPLAY.run_case(args.ngspice, work, "mosfet", REPLAY.SANITY)}
        for label, plant in plants.items():
            job = pool.submit(REPLAY.run_case, args.ngspice, work, label+"-replay", plant)
            jobs[job] = (label, "ngspice_replay")
            for profile in PROFILES:
                job = pool.submit(xyce_case, args, xyce, label+"-"+profile, xyce_deck(plant, profile))
                jobs[job] = (label, profile)
        for job in as_completed(jobs):
            label, kind = jobs[job]
            try:
                value = job.result()
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                value = {"completed": False, "error": simulation_error(error, work)}
            if label == "control":
                controls[kind] = value
            elif kind == "ngspice_replay":
                results[label][kind] = {"completed": value.get("completed", True), **{
                    key: value[key] for key in (*PROBES, "error") if key in value
                }}
            else:
                results[label]["xyce"][kind] = value
            print(label, kind, "saved", flush=True)
    for value in controls.values():
        m = value.get("measures", {})
        if "high_off" in m and "low_rise" in m:
            value["threshold_non_overlap_ns"] = (m["low_rise"]-m["high_off"])*1e9
        if "low_off" in m and "high_rise" in m:
            value["reverse_threshold_non_overlap_ns"] = (m["high_rise"]-m["low_off"])*1e9
    native = controls["ngspice_mosfet"]["measures"]
    port = controls["xyce_mosfet_gear"]
    port["static_control_matches_ngspice"] = port["completed"] and all(
        abs(port["measures"][key] - native[key]) <= tolerance
        for key, tolerance in (("on_drop", .0005), ("off_voltage", .01))
    )
    inputs = (rear.BOARD, rear.EXTRACTION, Path(__file__), Path(rear.__file__), args.driver_archive,
              args.mosfet_archive, *(ROOT/name for name in (*REPLAY.MODELS, "bench-bootstrap-impedance.json",
                      "bench-shunt-transfer.json", "bench-shunt-filter-results.json", "isolated_dfn_test.py",
                      "isolated_bypass_test.py", "isolated_driver_test.py", "isolated_layout_replay.py",
                      "bench-startup.h")))
    report = {
        "scope": "Open-loop cross-check with recorded input pin voltages. Protection logic is evaluated only in the ngspice capture.",
        "pwl_voltage_tolerance_v": TOLERANCE_V, "maximum_step_ps": 500,
        "xyce_timeout_per_deck_s": args.timeout, "scheduler_command_gap_ns": spacing_ns,
        "xyce_version": subprocess.check_output([args.xyce, "-v"], text=True).strip(),
        "inputs_sha256": {path.name: REPLAY.digest(path) for path in inputs},
        "controls": controls, "cases": results,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xyce", default="Xyce")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--driver-archive", type=Path, required=True)
    parser.add_argument("--mosfet-archive", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120, help="seconds per Xyce deck")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT/"bench-secondary-isolated-dfn-rear-bypass-xyce.json")
    args = parser.parse_args()
    args.mode = "vendor"
    if args.jobs < 1 or args.timeout < 1:
        parser.error("Choose a positive worker count and timeout")
    run(args)
