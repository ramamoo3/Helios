"""Select a provisional comparator filter using force and Kelvin impedances."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from extract_layout import BOOTSTRAP_PORTS, LEGS
from half_bridge_test import calibrate_recovery, run_deck
from layout_switching_test import read_extraction
from local_shutdown_test import Circuit, classify_fault, fault_deck, normal_deck
from shunt_transfer import FOOTPRINT
from verify import ROOT


STANDARD_NF = (0.47, 0.56, 0.68, 0.82, 1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2, 10.0)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def circuit_from(coupon, nominal_nf):
    values = coupon["impedance"]
    r = values["100000"]["resistance_ohm"]
    l = values["1e+07"]["inductance_h"]
    return Circuit(sense_nh=l[1][0] * 1e9, shunt_mohm=r[1][0] * 1e3,
                   force_nh=l[0][0] * 1e9, force_mohm=r[0][0] * 1e3, filter_nf=nominal_nf)


def classify_input_turnoff(m):
    classify_fault(m)
    m["interrupted_with_request_high"] = (
        "clearing_ns" in m and "driver_input_fall" in m and m["winding_peak"] == 0
        and m["en_held_min"] > 3 and m["raw_command_after"] > 3 and m["current_after"] < 1
        and m["masked_permit_after"] < 0.1 and m["peer_after"] < 0.1
        and -0.005 <= m["driver_input_min"] <= m["driver_input_max"] <= 3.305
        and m["driver_input_fall"] < m["current_fall_1a"] < m["command_fall"])


def passes_switching(m):
    return m["permit_min"] > 3 and min(m["first_gate"], m["second_gate"]) > 5


def input_in_range(low, high):
    return -0.2 <= low <= high <= 3.5


def run_candidate(ngspice, pool, work, board, coupons, transit, cap):
    cases = {}
    pending = []
    for mount, coupon in coupons.items():
        nominal = circuit_from(coupon, cap)
        early = replace(nominal, filter_nf=cap*0.9, offset_mv=5, shunt_mohm=nominal.shunt_mohm*1.01)
        late = replace(nominal, filter_nf=cap*1.1, offset_mv=-5, shunt_mohm=nominal.shunt_mohm*0.99,
                       comparator_ns=7, logic_ns=12)
        for side in ("low", "high"):
            for kind, deck in (
                ("switching", normal_deck(board, transit, "sa", side, early, fast_inputs=True)),
                ("short", fault_deck(board, transit, "sa", side, late, fast_inputs=True)),
            ):
                name = f"{cap:g}nf_{mount}_{kind}_{side}"
                pending.append((name, kind, pool.submit(run_deck, ngspice, work, name, deck)))
    for name, kind, job in pending:
        try:
            m = job.result()
        except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
            cases[name] = {"passed": False, "error": str(error).replace(str(work), "simulation")}
            continue
        if kind == "short":
            classify_input_turnoff(m)
            passed = m["interrupted_with_request_high"]
            input_min, input_max = m["comparator_input_min"], m["comparator_input_max"]
        else:
            passed = passes_switching(m)
            input_min, input_max = m["comparator_min"], m["comparator_max"]
        cases[name] = {"passed": passed and input_in_range(input_min, input_max), "measurements": m}
    passes = sum(case["passed"] for case in cases.values())
    print(f"{cap:g} nF: {passes}/{len(cases)} switching and short-circuit screens passed", flush=True)
    return cases


def run(args):
    board = read_extraction(args.extraction)
    if tuple(board["ports"]) != BOOTSTRAP_PORTS:
        raise ValueError("The study needs the board extraction with bootstrap ports")
    shunt = json.loads(args.shunt.read_text(encoding="utf-8"))
    if shunt["footprint_sha256"] != sha256(FOOTPRINT):
        raise ValueError("The shunt study was extracted from a different footprint")
    coupons = shunt["cases"]
    ideal = coupons["nominal"]["ideal_filter_nf"]
    if ideal <= 0:
        raise ValueError("An RC pole cannot cancel the modeled negative transfer inductance")
    caps = args.cap or sorted(STANDARD_NF, key=lambda cap: abs(math.log(cap/ideal)))[:3]
    caps = sorted(set(caps))
    with TemporaryDirectory() as scratch, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(scratch)
        for name in ("protection.lib", "local_shutdown.lib"):
            shutil.copyfile(ROOT / name, work / name)
        transit = calibrate_recovery(args.ngspice, work)["transit_ns"]
        screened = {str(cap): run_candidate(args.ngspice, pool, work, board, coupons, transit, cap)
                    for cap in dict.fromkeys([1.1, *caps])}
        passing = [cap for cap in caps if all(case["passed"] for case in screened[str(cap)].values())]
        selected = min(passing, key=lambda cap: abs(math.log(cap/ideal))) if passing else None
        confirmation = {"faults": {}, "normal": {}, "mask_bypassed_control": None, "rail_referenced_control": None}
        if selected is not None:
            circuit = circuit_from(coupons["nominal"], selected)
            for leg in LEGS:
                for side in ("low", "high"):
                    name = f"{leg}_failed_{side}"
                    m = run_deck(args.ngspice, work, name, fault_deck(board, transit, leg, side, circuit,
                                                                      fast_inputs=True))
                    classify_input_turnoff(m)
                    confirmation["faults"][name] = m
                    name = f"{leg}_normal_{side}"
                    m = run_deck(args.ngspice, work, name, normal_deck(board, transit, leg, side, circuit,
                                                                       fast_inputs=True))
                    m["stayed_enabled"] = passes_switching(m)
                    confirmation["normal"][name] = m
            bypass = fault_deck(board, transit, "sa", "low", circuit, switch_enabled=False, fast_inputs=True)
            confirmation["mask_bypassed_control"] = run_deck(args.ngspice, work, "sa_short_mask_bypassed", bypass)
            rail_reference = fault_deck(board, transit, "sa", "low", circuit, fast_inputs=True, mask_reference="0")
            confirmation["rail_referenced_control"] = run_deck(args.ngspice, work, "sa_short_rail_reference", rail_reference)
    result = {
        "board_sha256": board["board_sha256"],
        "extraction_sha256": sha256(args.extraction),
        "shunt_sha256": sha256(args.shunt),
        "model_sha256": {name: sha256(ROOT / name) for name in
                         ("local_shutdown.lib", "local_shutdown_test.py", "layout_switching_test.py",
                          "half_bridge_test.py", "shunt_filter_test.py")},
        "selected_filter_nf": selected,
        "geometry_corners": screened,
        "nominal_confirmation": confirmation,
    }
    args.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8", newline="\n")
    if selected is None:
        raise ValueError("No capacitor met the modeled normal-switching and fault conditions")
    if any(not item["interrupted_with_request_high"] or not input_in_range(
        item["comparator_input_min"], item["comparator_input_max"]) for item in confirmation["faults"].values()):
        raise ValueError("The selected capacitor failed a nominal four-leg fault confirmation")
    if any(not item["stayed_enabled"] or not input_in_range(
        item["comparator_min"], item["comparator_max"]) for item in confirmation["normal"].values()):
        raise ValueError("The selected capacitor tripped during nominal four-leg switching")
    bypass = confirmation["mask_bypassed_control"]
    if not (bypass["current_after"] > 1 and bypass["raw_command_after"] > 3 and bypass["en_held_min"] > 3):
        raise ValueError("The bypass control did not sustain the fault with the PWM request asserted")
    print(f"Selected {selected:g} nF for the candidate footprint and modeled mounts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--cap", type=float, action="append", help="screen a specified capacitor in nF")
    args = parser.parse_args()
    if any(not math.isfinite(cap) or cap <= 0 for cap in args.cap or []):
        parser.error("Capacitance in nF must be positive and finite")
    run(args)
