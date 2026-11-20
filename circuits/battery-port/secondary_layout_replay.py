"""Replay the clamp screening fixture using the routed secondary-leg extraction."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from commutation_clamp_test import MODELS, Build, add_clamp, digest, evaluate
from half_bridge_test import calibrate_recovery, run_deck
from layout_switching_test import BOOTSTRAP_CONNECTIONS, read_extraction
from leg_receiver_test import with_receiver
from local_shutdown_test import fault_deck, normal_deck
from secondary_layout_extract import BOARD, PORTS
from shunt_filter_test import circuit_from
from verify import ROOT


def copper_network(extraction):
    # The existing bridge ports stay in their original order. Split the
    # commutation return around the four-terminal shunt and route each TVS arm.
    connections = (
        *BOOTSTRAP_CONNECTIONS[:2], ("sourcel", "shunt_force"), *BOOTSTRAP_CONNECTIONS[3:],
        ("shunt_rail", "0"), ("mid", "tvs_pad_k"), ("tvs_pad_a", "sourcel"),
    )
    matrices = extraction["frequencies_hz"]
    r = matrices["100000"]["resistance_ohm"]
    l = matrices["1e+07"]["inductance_h"]
    model = []
    for i, (port, (a, b)) in enumerate(zip(PORTS, connections, strict=True)):
        model.extend((f"Rpcb_{port} {a} r_{port} {r[i][i]:.9g}",
                      f"Lpcb_{port} r_{port} {b} {l[i][i]:.9g}"))
        for j in range(i):
            coupling = (l[i][j] + l[j][i]) / (2 * math.sqrt(l[i][i] * l[j][j]))
            model.append(f"K{port}_{PORTS[j]} Lpcb_{port} Lpcb_{PORTS[j]} {coupling:.9g}")
    return "\n".join(model)


def scaled_network(extraction, factors):
    """Change one group of partial impedances while preserving passivity."""
    data = deepcopy(extraction)
    weights = [math.sqrt(factors.get(port, 1)) for port in PORTS]
    for matrix in data["frequencies_hz"].values():
        for key in ("resistance_ohm", "inductance_h"):
            matrix[key] = [[value * weights[i] * weights[j] for j, value in enumerate(row)]
                           for i, row in enumerate(matrix[key])]
    return copper_network(data)


def routed_fixture(deck, network, loops, build, is_fault, high_tvs_nh=0):
    deck, count = re.subn(r"^Rpcb_feed .*\n(?:(?:Rpcb_|Lpcb_|K).*\n)+",
                          network + "\n", deck, flags=re.M)
    if count != 1:
        raise ValueError("The routed network could not replace the original board extraction")
    deck, count = re.subn(r"^Rshunt shunt_r 0 ", "Rshunt shunt_r shunt_rail ", deck, flags=re.M)
    if count != 1 or deck.count("v(shunt_r)") != 1:
        raise ValueError("Review the series shunt and Kelvin voltage probes")
    deck = deck.replace("v(shunt_r)", "v(shunt_r,shunt_rail)")
    deck = add_clamp(deck, build, is_fault)
    deck = deck.replace("Xtvs mid sourcel ", "Xtvs tvs_pad_k tvs_pad_a ")
    for label, side in (("high", "hi"), ("low", "lo")):
        # The components add 0.8 nH as a sensitivity assumption. Snubber
        # coupling to other paths is unavailable from the independent solves.
        l_h = loops[label + "_snubber_copper"] + 0.8
        deck, count = re.subn(rf"^(Xsnub_{side} .* LLOOP=)[^ ]+", rf"\g<1>{l_h:.8g}n", deck, flags=re.M)
        if count != 1:
            raise ValueError(f"Review the {side} snubber branch in the screening fixture")
    if high_tvs_nh:
        device = (f"BENCH_TVS LLOOP={high_tvs_nh:g}n VBR={build.tvs_knee_v:g} "
                  f"RD={build.tvs_slope_ohm:g} C0={build.tvs_cjo_nf:g}n")
        deck = deck.removesuffix(".end\n") + f"Xtvs_high drainh sourceh p_tvs_high {device}\n.end\n"
    return deck


def run(args):
    actual = json.loads(args.extraction.read_text(encoding="utf-8"))
    if actual["board_sha256"] != digest(args.board) or tuple(actual["ports"]) != PORTS:
        raise ValueError("The requested board and physical port extraction differ")
    reference = read_extraction(args.reference)
    filter_study = json.loads(args.filter.read_text(encoding="utf-8"))
    if filter_study["shunt_sha256"] != digest(args.shunt) or filter_study["extraction_sha256"] != digest(args.reference):
        raise ValueError("The shunt filter selection and the reference fixture differ")
    shunt = json.loads(args.shunt.read_text(encoding="utf-8"))["cases"]
    cap = filter_study["selected_filter_nf"]
    netlist = copper_network(actual)
    cases = {}
    params = {}
    with TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(tmp)
        for name in MODELS:
            shutil.copyfile(ROOT / name, work / name)
        transit = calibrate_recovery(args.ngspice, work)["transit_ns"]
        pending = []
        # 0.05 nH isolates the copper sensitivity. Positive package values
        # are scenario assumptions because the SMC datasheet specifies no ESL.
        for name, package, hot in (("copper_only", 0.05, False), ("nominal", 1, False),
                                   ("hot", 1, True), ("hot_higher_esl", 2, True)):
            build = Build(compact=False, pin_bootstrap=False, tvs_loop_nh=package)
            nominal = circuit_from(shunt["nominal"], cap)
            fault_circuit = nominal
            if hot:
                build = replace(build, tvs_knee_v=39, tvs_slope_ohm=0.14, tvs_cjo_nf=3.3,
                                snubber_nf=4.23, snubber_ohm=2.31)
                fault_circuit = replace(nominal, filter_nf=cap * 1.1, shunt_mohm=nominal.shunt_mohm * 0.99,
                                        offset_mv=-5, comparator_ns=7, logic_ns=12)
            params[name] = {"tvs_package_assumed_nh": package, "hot_clamp": hot}
            for side in ("low", "high"):
                for kind, builder in (("normal", normal_deck), ("short", fault_deck)):
                    fault = kind == "short"
                    case = f"{name}_{side}_{kind}"
                    deck = builder(reference, transit, "sa", side, fault_circuit if fault else nominal,
                                   fast_inputs=True)
                    deck = with_receiver(deck, bias_v=12.3 if hot and fault else 12)
                    deck = routed_fixture(deck, netlist, actual["loops_at_10mhz_nh"], build, fault)
                    pending.append((case, fault, pool.submit(run_deck, args.ngspice, work, case, deck)))
        corner = replace(build, tvs_loop_nh=1)
        compact = {"feed": 0.45, "switch": 0.45, "return": 0.45, "return_rail": 0.45}
        clamp = {"tvs_cathode": 0.35, "tvs_anode": 0.35}
        kelvin = {"vss": 0.25, "hs": 0.8, "hs_source": 0.4, "boot_feed": 0.35, "boot_return": 0.35}
        together = {**compact, **clamp, **kelvin}
        controls = {
            "clamp_only": (clamp, False, 0),
            "commutation_only": (compact, False, 0),
            "snubbers_only": ({}, True, 0),
            "all_shorter_paths": (together, True, 0),
            "dual_clamp": ({}, False, 2.5),
            "dual_clamp_shorter_paths": (together, True, 2.5),
        }
        for name, (factors, short_snubs, high_tvs) in controls.items():
            adjusted = scaled_network(actual, factors)
            loops = dict(actual["loops_at_10mhz_nh"])
            if short_snubs:
                loops.update(high_snubber_copper=0.6, low_snubber_copper=0.6)
            params[name] = {"tvs_package_assumed_nh": 1, "hot_clamp": True,
                            "port_impedance_multipliers": factors, "shorter_snubber_control": short_snubs,
                            "high_side_tvs_assumed_nh": high_tvs}
            for side in ("low", "high"):
                case = f"{name}_{side}_short"
                deck = fault_deck(reference, transit, "sa", side, fault_circuit, fast_inputs=True)
                deck = with_receiver(deck, bias_v=12.3)
                deck = routed_fixture(deck, adjusted, loops, corner, True, high_tvs)
                pending.append((case, True, pool.submit(run_deck, args.ngspice, work, case, deck)))
        for case, fault, job in pending:
            try:
                cases[case] = evaluate(job.result(), fault)
            except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
                cases[case] = {"passed": False, "error": str(error).replace(str(work), "simulation")}
            print(f"{case}: {'pass' if cases[case]['passed'] else 'fail'}", flush=True)
    result = {
        "board_sha256": digest(args.board),
        "extraction_sha256": digest(args.extraction),
        "reference_sha256": digest(args.reference),
        "filter_sha256": digest(args.filter),
        "shunt_sha256": digest(args.shunt),
        "model_sha256": {name: digest(ROOT / name) for name in (*MODELS, "secondary_layout_extract.py",
                         "secondary_layout_replay.py", "commutation_clamp_test.py",
                         "half_bridge_test.py", "layout_switching_test.py", "local_shutdown_test.py",
                         "leg_receiver_test.py")},
        "snubber_component_assumed_nh": 0.8,
        "scenarios": params,
        "cases": cases,
        "tvs_copper_below_2p5_nh": actual["loops_at_10mhz_nh"]["tvs_external"] <= 2.5,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    if not result["tvs_copper_below_2p5_nh"] or not all(m["passed"] for m in cases.values()):
        raise SystemExit("The routed study misses the clamp-loop or waveform criteria. Measurements saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-secondary-layout-impedance.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
