"""Measure the inductive second-pulse overshoot and its solver sensitivity."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import isolated_rear_bypass as rear
from isolated_driver_test import replace_line, validate
from vendor_overlap_test import trace_samples
from vendor_test import PSPICE_OPTIONS


SIGNALS = (
    "v(dl_s)", "v(dh_s)", "v(gh_s)", "v(gl_s)", "v(mid)", "v(sourcel)", "v(bus)", "v(drainh)",
    "v(hs_s)", "v(a_v)", "v(en_candidate)", "i(lload)", "i(vlocal_clamp)", "v(xlocal_clamp.junction)",
)
INDUCTIVE_CASES = ("nominal_high", "nominal_low", "hot_high", "hot_low")
SCHOTTKY_PART = "STPST10H100SF"


def stage_comparison_model(work):
    model = rear.COMPARE.read_text(encoding="utf-8")
    smooth = (".func positive(x) {0.5*(x+sqrt(x*x+1e-6))}\n"
              ".func gateclip(x,h) {positive(x)-positive(x-h)}\n")
    model = model.replace("Bpull_up", smooth + "Bpull_up")
    model = model.replace("min(4,max(0,v(SUP,OUT)/RPULL))", "gateclip(v(SUP,OUT)/RPULL,4)")
    model = model.replace("min(6,max(0,v(OUT,RET)/0.55))", "gateclip(v(OUT,RET)/0.55,6)")
    path = work / rear.COMPARE.name
    path.write_text(model, encoding="utf-8", newline="\r\n")
    return path


def stage_steering_model(archive, work):
    pattern = rf"(?msi)^\.subckt {SCHOTTKY_PART} .*?^\.ends[^\r\n]*"
    with ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name.lower().endswith(".lib"):
                match = re.search(pattern, bundle.read(name).decode("latin-1"))
                if match:
                    path = work / "steering.lib"
                    path.write_text(match[0].replace("\r", "") + "\n", encoding="ascii", newline="\n")
                    return path
    raise ValueError(f"The ST model archive does not contain {SCHOTTKY_PART}")


def make_deck(deck, method, step_ps, case, high_gate_ohm, snubber_nf, steering, capture,
              schottky=False, steering_loop_nh=0.45):
    source = rear.compare_driver(deck)
    source = replace_line(source, "Rghi", f"Rghi hri hro {high_gate_ohm:g}")
    options = f"method={method} maxord=2 reltol=0.006 abstol=20n vntol=50u trtol=7 itl4=500 rshunt=1e12"
    source = re.sub(r"(?m)^\.options .*$", ".options " + options, source, count=1)
    source, count = re.subn(r"(?m)^\.tran 250p 5.5u 0 250p$", f".tran {step_ps}p 5.5u 0 {step_ps}p", source)
    if count != 1:
        raise ValueError("Review the original inductive transient settings")
    source = source.removesuffix(".end\n") + """Lgatech gh ghcl 0.45n
Lgatecl gl glcl 0.45n
Dgatech sourceh ghcl GATECL
Dgatecl sourcel glcl GATECL
.model GATECL D(BV=14.5 IBV=1m Is=2n N=1.4 RS=.22 Cjo=30p)
Vlocal_clamp mid dclamp_input 0
Xlocal_clamp dclamp_input sourcel local_clamp_heat BENCH_TVS LLOOP=0.45n VBR=35 RD=0.18 C0=2.2n
"""
    if case.endswith("_high"):
        source += """Bextra_clamp extra_clamp_peak 0 V=abs(i(Vlocal_clamp))
.meas tran extra_clamp_peak_a MAX v(extra_clamp_peak)
.meas tran extra_clamp_j INTEG v(local_clamp_heat) from=3u to=5.5u
"""
    if snubber_nf:
        source += f"""Xtrial_snub mid sourcel trial_snub_power BENCH_SNUBBER LLOOP=0.5n R=1 C={snubber_nf:g}n
.meas tran local_snubber_j INTEG v(trial_snub_power) from=3u to=5.5u
"""
    if steering != "none":
        source += f"Lsteer mid sd_k {steering_loop_nh:g}n\n"
        if schottky:
            # The first and third pins of the ST subcircuit are common anodes.
            source += f"Xsteer sourcel sd_k sourcel {SCHOTTKY_PART}\n.include steering.lib\n"
        else:
            source += """Dsteer sourcel sd_k STEERING_MODEL
.model STEERING_MODEL D(IS=50n N=1.15 RS=18m CJO=200p BV=100 IBV=1m)
"""
    if steering == "both":
        source += f"Lsteer_hi drainh sd_k_hi {steering_loop_nh:g}n\n"
        if schottky:
            source += f"Xsteer_hi sourceh sd_k_hi sourceh {SCHOTTKY_PART}\n"
        else:
            source += "Dsteer_hi sourceh sd_k_hi STEERING_MODEL\n"
    if capture == "measurements":
        return source + ".end\n"
    source = re.sub(r"(?mi)^\.meas .*?\n", "", source)
    vectors = " ".join(SIGNALS)
    return source + f""".save {vectors}
.control
set wr_singlescale
set wr_vecnames
option numdgt=16
run
wrdata trace.dat {vectors}
quit
.endc
.end
"""


def analyze(samples):
    times, values = zip(*samples)
    if times[-1] < 5.5e-6 - 1e-12:
        raise ValueError("The trace did not reach the last transient time")
    peak = max(range(len(values)), key=lambda i: values[i][0])
    above_limit = 0.0
    for (a, x), (b, y) in zip(samples, samples[1:]):
        low, high = sorted((x[0], y[0]))
        if low > 54:
            above_limit += b - a
        elif high > 54:
            above_limit += (b - a) * (high - 54) / (high - low)
    # Preserve the samples surrounding the peak so very short excursions
    # can be distinguished from a sustained overvoltage.
    around_peak = [{"time_ns": times[i]*1e9, **dict(zip(SIGNALS, values[i], strict=True))}
                   for i in range(max(0, peak-1), min(len(values), peak+2))]
    max_vds = max(max(v[:2]) for v in values)
    max_abs_vgs = max(max(abs(v[2]), abs(v[3])) for v in values)
    return {
        "completed": True, "sample_count": len(samples), "samples_around_low_side_peak": around_peak,
        "peak_vds_v": max_vds, "peak_absolute_vgs_v": max_abs_vgs,
        "total_low_side_time_above_54_v_ns": above_limit*1e9,
        "samples_low_side_above_54_v": sum(x[0] > 54 for x in values),
        "drain_within_54_v": max_vds <= 54, "gate_within_16_v": max_abs_vgs <= 16,
    }


def run_profile(args, work, base):
    path, trace = work / "trial.cir", work / "trace.dat"
    source = make_deck(base, args.method, args.step_ps, args.case, args.high_gate_ohm,
                       args.snubber_nf, args.steering, args.capture,
                       schottky=args.schottky_archive is not None, steering_loop_nh=args.steering_loop_nh)
    path.write_text(source, encoding="ascii", newline="\n")
    try:
        process = subprocess.run([args.ngspice, *PSPICE_OPTIONS, "-b", str(path)], cwd=work,
                                 capture_output=True, text=True, errors="replace", timeout=args.timeout)
    except subprocess.TimeoutExpired:
        result = {"completed": False, "error": f"Solver exceeded {args.timeout:g} seconds"}
    else:
        log = process.stdout + "\n" + process.stderr
        try:
            if process.returncode or re.search(r"aborted|timestep too small|measurement.*failed", log, re.I):
                reason = next((line.strip() for line in log.splitlines() if "timestep too small" in line.lower()),
                              f"Solver exit {process.returncode} without complete results")
                raise ValueError(reason)
            if args.capture == "trace":
                if not trace.exists():
                    raise ValueError("Solver did not produce a waveform")
                result = analyze(list(trace_samples(trace, list(SIGNALS), SIGNALS)))
            else:
                values = re.findall(r"^\s*(\w+)\s*=\s*([-+\d.eE]+)(?:\s|$)", log, re.M)
                measurements = validate({key: float(value) for key, value in values}, "inductive")
                result = {"completed": True, **measurements}
        except (ValueError, IndexError, KeyError) as error:
            result = {"completed": False, "error": str(error)}
    result["deck_sha256"] = rear.dfn.replay.digest(path)
    return result


def run(args):
    base, shunt, selection = (rear.ROOT / name for name in (
        "bench-bootstrap-impedance.json", "bench-shunt-transfer.json", "bench-shunt-filter-results.json"))
    selected = json.loads(selection.read_bytes())
    if (selected["extraction_sha256"] != rear.dfn.replay.digest(base)
            or selected["shunt_sha256"] != rear.dfn.replay.digest(shunt)):
        raise ValueError("The shunt filter and reference fixtures differ")
    extraction = json.loads(rear.EXTRACTION.read_bytes())
    if extraction["board_sha256"] != rear.dfn.replay.digest(rear.BOARD) or extraction["ports"] != list(rear.NODES):
        raise ValueError("Select the matching rear-bypass PCB and extraction")
    mount = json.loads(shunt.read_bytes())["cases"]["nominal"]
    circuit = rear.dfn.replay.circuit_from(mount, selected["selected_filter_nf"])
    dependencies = (Path(__file__), rear.BOARD, rear.EXTRACTION, rear.COMPARE, base, shunt, selection,
                    args.driver_archive, args.mosfet_archive, Path(rear.__file__),
                    *(rear.ROOT / name for name in (*rear.dfn.replay.MODELS, "isolated_layout_replay.py",
                                                   "isolated_dfn_test.py", "isolated_driver_test.py")))
    if args.schottky_archive is not None:
        dependencies += (args.schottky_archive,)
    fingerprints = {path.name: rear.dfn.replay.digest(path) for path in dependencies}
    with TemporaryDirectory() as folder:
        work = Path(folder)
        rear.dfn.stage_models(args, work)
        staged = stage_comparison_model(work)
        steering_model = stage_steering_model(args.schottky_archive, work) if args.schottky_archive else None
        capture = rear.Capture(39)
        corner_name = args.case.split("_")[0]
        corners = [corner for corner in rear.dfn.replay.BIAS_CORNERS if corner[0] == corner_name]
        rear.dfn.replay.add_cases(capture, work, args, extraction, rear.dfn.replay.read_extraction(base),
                                 circuit, nodes=rear.NODES, revise_bias=rear.bias_deck, corners=corners)
        _, source = capture.decks[f"{args.case}_inductive"]
        return {
            "scope": "Routed rear-bypass inductive switching diagnostic with a reduced gate-driver model",
            "settings": {
                **{key: getattr(args, key) for key in ("case", "method", "step_ps", "high_gate_ohm", "snubber_nf",
                                                      "steering", "steering_loop_nh", "capture", "timeout")},
                "steering_model": SCHOTTKY_PART if steering_model else "generic",
            },
            "inputs_sha256": fingerprints,
            "staged_driver_sha256": rear.dfn.replay.digest(staged),
            "staged_steering_sha256": rear.dfn.replay.digest(steering_model) if steering_model else None,
            "result": run_profile(args, work, source),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver-archive", type=Path, required=True)
    parser.add_argument("--mosfet-archive", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--case", choices=INDUCTIVE_CASES, default="nominal_high")
    parser.add_argument("--method", choices=("gear", "trap"), default="gear")
    parser.add_argument("--step-ps", type=int, choices=(125, 250, 500), default=250)
    parser.add_argument("--high-gate-ohm", type=int, choices=(15, 27, 39), default=15)
    parser.add_argument("--snubber-nf", type=float, choices=(0, 1, 2.2), default=0)
    parser.add_argument("--steering", choices=("none", "q6", "both"), default="none")
    parser.add_argument("--schottky-archive", type=Path, help=f"ST Power Schottky PSpice archive containing {SCHOTTKY_PART}")
    parser.add_argument("--steering-loop-nh", type=float, choices=(0.45, 1.0, 2.0), default=0.45)
    parser.add_argument("--capture", choices=("trace", "measurements"), default="trace")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    parser.set_defaults(mode="compare")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("Choose a positive solver timeout")
    if args.schottky_archive and args.steering == "none":
        parser.error("The Schottky model requires --steering q6 or --steering both")
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    result = report["result"]
    if not result["completed"]:
        print(result["error"])
    elif args.capture == "trace":
        print(f"Peak drain voltage {result['peak_vds_v']:.3f} V")
    else:
        print(f"Peak drain voltage {max(result['vds_hi_scan'], result['vds_lo_scan']):.3f} V")
