"""Compare layout and clamp candidates on the isolated bench receiver fixture."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from extract_layout import LEGS
from half_bridge_test import calibrate_recovery, run_deck
from layout_switching_test import read_extraction
from leg_receiver_test import with_receiver
from local_shutdown_test import fault_deck, normal_deck
from shunt_filter_test import circuit_from, classify_input_turnoff, passes_switching
from verify import ROOT


RETURN_SCALE = {"hs": 0.13, "vss": 0.27, "hs_source": 0.18, "boot_feed": 0.12, "boot_return": 0.25}
MODELS = ("leg_receiver.lib", "local_shutdown.lib", "protection.lib", "commutation_clamp.lib")


@dataclass(frozen=True)
class Build:
    compact: bool = True
    return_scale: float = 1
    uncoupled_returns: bool = False
    pin_bootstrap: bool = True
    bootstrap_loop_nh: float = 0.35
    snubber_nf: float = 4.7
    snubber_ohm: float = 2.2
    snubber_loop_nh: float = 0.8
    tvs_loop_nh: float = 2
    tvs_knee_v: float = 36.8
    tvs_slope_ohm: float = 0.11262
    tvs_cjo_nf: float = 4.7
    catch: bool = False


def with_compact_returns(extraction, build):
    """Scale partial impedances by congruence to retain passive port matrices."""
    if not build.compact:
        return extraction
    model = deepcopy(extraction)
    ports = model["ports"]
    factors = [math.sqrt(min(1, RETURN_SCALE[p] * build.return_scale)) if p in RETURN_SCALE else 1
               for p in ports]
    for leg in model["legs"].values():
        for values in leg["frequencies_hz"].values():
            for key in ("inductance_h", "resistance_ohm"):
                matrix = values[key]
                values[key] = [
                    [0 if build.uncoupled_returns and i != j and (ports[i] in RETURN_SCALE or ports[j] in RETURN_SCALE)
                     else matrix[i][j] * a * b for j, b in enumerate(factors)]
                    for i, a in enumerate(factors)
                ]
    return model


def add_clamp(deck, build, fault):
    body, delimiter, _ = deck.rpartition(".end\n")
    if not delimiter:
        raise ValueError("Review the end of the receiver test fixture")
    if build.pin_bootstrap:
        original = "Cboot hb_cap hs_cap 100n"
        if body.count(original) != 1:
            raise ValueError("Review the bootstrap capacitor insertion point")
        body = body.replace(original, f"Lboot_local hb hb_l {build.bootstrap_loop_nh:g}n\n"
                            "Rboot_local hb_l hb_r 25m\nCboot hb_r hs 100n")
    body += ".include commutation_clamp.lib\n"
    end = 4 if fault else 5.5
    if build.snubber_nf:
        snubber = (f"BENCH_SNUBBER LLOOP={build.snubber_loop_nh:g}n R={build.snubber_ohm:g} "
                   f"C={build.snubber_nf:g}n")
        body += f"""Xsnub_hi drainh sourceh p_sh {snubber}
Xsnub_lo mid sourcel p_sl {snubber}
.meas tran snubber_hi_j INTEG v(p_sh) from=0 to={end:g}u
.meas tran snubber_lo_j INTEG v(p_sl) from=0 to={end:g}u
"""
    if build.tvs_loop_nh:
        body += f"""Xtvs mid sourcel p_tvs BENCH_TVS LLOOP={build.tvs_loop_nh:g}n
+ VBR={build.tvs_knee_v:g} RD={build.tvs_slope_ohm:g} C0={build.tvs_cjo_nf:g}n
.meas tran tvs_j INTEG v(p_tvs) from=0 to={end:g}u
"""
    if build.catch:
        body += """.include st-catch.lib
Lcatch sourcel catch_a 1.2n
Xcatch catch_a catch_a sourceh STPS20M60SG-TR
"""
    body += """Bboot_now boot_now 0 V=v(hb,hs)
.meas tran vds_hi_scan MAX v(dh_s)
.meas tran vds_lo_scan MAX v(dl_s)
.meas tran max_boot MAX v(boot_now)
.meas tran max_vgs_high MAX v(gh_s)
.meas tran max_vgs_low MAX v(gl_s)
.meas tran min_vgs_high MIN v(gh_s)
.meas tran min_vgs_low MIN v(gl_s)
"""
    if not fault:
        body += """Bpositive_channel channel_high 0 V=max(i(v.xhigh.vchannel),0)
.meas tran precharge_off_gate MAX v(gh_s) from=800n to=2.4u
.meas tran precharge_high_channel MAX v(channel_high) from=800n to=2.4u
.meas tran commanded_high_channel FIND v(channel_high) at=3.65u
.meas tran hi_boot_at_switch FIND v(boot_now) at=3.65u
"""
    return body + ".end\n"


def read_catch(source, work):
    with ZipFile(source) as archive:
        members = [name for name in archive.namelist() if name.upper().endswith("ST_POWER_SCHOTTKY_V10.LIB")]
        if len(members) != 1:
            raise ValueError("The ST model archive must contain the published V10 library")
        library = archive.read(members[0]).decode("latin-1")
    model = re.search(r"(?ims)^\.subckt STPS20M60SG-TR\b.*?^\.ends[^\n]*", library)
    if not model:
        raise ValueError("D2PAK Schottky model missing from the ST archive")
    statements = [line for line in model[0].splitlines() if not line.startswith("*")]
    (work / "st-catch.lib").write_text("\n".join(statements) + "\n", encoding="ascii")


def evaluate(m, fault):
    if fault:
        classify_input_turnoff(m)
        m["basic_check"] = m["interrupted_with_request_high"]
    else:
        m["basic_check"] = passes_switching(m)
    m["limits"] = {
        "hs_at_least_minus_8_v": m["min_hs"] >= -8,
        "vds_at_most_54_v": max(m["vds_hi_scan"], m["vds_lo_scan"]) <= 54,
        "bootstrap_at_most_16_v": m["max_boot"] <= 16,
        "gate_magnitude_at_most_16_v": max(m["max_vgs_high"], m["max_vgs_low"],
                                            -m["min_vgs_high"], -m["min_vgs_low"]) <= 16,
        "driver_bias_in_range": 5.5 <= m["min_vdd"] <= m["max_vdd"] <= 16,
    }
    if not fault:
        m["limits"]["precharge_off_gate_under_0p1_v"] = m["precharge_off_gate"] < 0.1
    m["passed"] = m["basic_check"] and all(m["limits"].values())
    return m


def run(args):
    board = read_extraction(args.extraction)
    mounts = json.loads(args.shunt.read_text(encoding="utf-8"))["cases"]
    shunt_filter = json.loads(args.filter.read_text(encoding="utf-8"))
    for label, path in (("shunt", args.shunt), ("extraction", args.extraction)):
        if shunt_filter[label + "_sha256"] != digest(path):
            raise ValueError(f"The filter selection uses a different {label} revision")
    cap = shunt_filter["selected_filter_nf"]
    candidate = Build()
    original = Build(compact=False, pin_bootstrap=False, snubber_nf=0, tvs_loop_nh=0)
    worst = replace(candidate, return_scale=1.4, bootstrap_loop_nh=0.7, snubber_nf=4.23,
                    snubber_loop_nh=1.4, snubber_ohm=2.31, tvs_loop_nh=4, tvs_knee_v=39,
                    tvs_slope_ohm=0.14, tvs_cjo_nf=3.3)
    designs = {
        "original": original,
        "short_returns": replace(original, compact=True),
        "snubber_and_pin_cap": replace(candidate, tvs_loop_nh=0),
        "candidate": candidate,
        "bounded_hot_clamp": replace(worst, tvs_loop_nh=2.5),
        "longer_hot_clamp": worst,
        "uncoupled_returns": replace(worst, uncoupled_returns=True),
    }
    if args.catch_archive:
        designs["candidate_with_catch"] = replace(candidate, catch=True)
        designs["longer_hot_with_catch"] = replace(worst, catch=True)
    decks = {key: (build, with_compact_returns(board, build)) for key, build in designs.items()}
    with TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(directory)
        for filename in MODELS:
            shutil.copyfile(ROOT / filename, work / filename)
        if args.catch_archive:
            read_catch(args.catch_archive, work)
        t = calibrate_recovery(args.ngspice, work)["transit_ns"]
        tasks = []
        for design, (build, model) in decks.items():
            legs = LEGS if design in ("candidate", "bounded_hot_clamp", "longer_hot_clamp") else ("sa",)
            for leg in legs:
                for side in ("low", "high"):
                    for fault in (False, True):
                        corner = design.startswith(("bounded_hot", "longer_hot", "uncoupled"))
                        mount = "long_fanout" if fault and corner else "nominal"
                        c = circuit_from(mounts[mount], cap)
                        name = f"{design}_{leg}_{side}_{'fault' if fault else 'switch'}"
                        if fault and design != "candidate":
                            c = replace(c, filter_nf=cap*1.1, shunt_mohm=c.shunt_mohm*0.99,
                                        offset_mv=-5, comparator_ns=7, logic_ns=12)
                        builder = fault_deck if fault else normal_deck
                        deck = with_receiver(builder(model, t, leg, side, c, fast_inputs=True),
                                             bias_v=12.3 if fault and design != "candidate" else 12)
                        tasks.append((design, name, fault, pool.submit(
                            run_deck, args.ngspice, work, name, add_clamp(deck, build, fault))))
        build, model = decks["bounded_hot_clamp"]
        c = circuit_from(mounts["long_fanout"], cap)
        c = replace(c, filter_nf=cap*1.1, shunt_mohm=c.shunt_mohm*0.99, offset_mv=-5,
                    comparator_ns=7, logic_ns=12)
        for step in ("125p", "500p"):
            name = f"bounded_hot_clamp_sa_high_fault_{step}s"
            deck = with_receiver(fault_deck(model, t, "sa", "high", c, fast_inputs=True),
                                 bias_v=12.3, step=step)
            tasks.append(("bounded_hot_clamp", name, True, pool.submit(
                run_deck, args.ngspice, work, name, add_clamp(deck, build, True))))
        results = {design: {} for design in designs}
        for design, name, fault, job in tasks:
            try:
                m = evaluate(job.result(), fault)
            except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
                m = {"passed": False, "error": str(error).replace(str(work), "simulation")}
            results[design][name] = m
            print(f"{name}: {'pass' if m['passed'] else 'fail'}", flush=True)
    evidence = {
        "extraction_sha256": digest(args.extraction),
        "shunt_sha256": digest(args.shunt),
        "filter_sha256": digest(args.filter),
        "model_sha256": {name: digest(ROOT / name) for name in (*MODELS, "commutation_clamp_test.py",
                         "half_bridge_test.py", "local_shutdown_test.py", "layout_switching_test.py",
                         "leg_receiver_test.py")},
        "st_archive_sha256": digest(args.catch_archive) if args.catch_archive else None,
        "return_impedance_multipliers": RETURN_SCALE,
        "builds": {design: asdict(build) for design, build in designs.items()},
        "cases": results,
    }
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8", newline="\n")
    if any(not case["passed"] for design in ("candidate", "bounded_hot_clamp")
           for case in results[design].values()):
        raise SystemExit("The candidate still has open stress or switching cases. Measurements saved.")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--catch-archive", type=Path, help="optional published ST Schottky PSpice ZIP")
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
