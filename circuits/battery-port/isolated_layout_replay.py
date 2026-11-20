"""Replay the routed isolated driver with both TVS junction fits."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from commutation_clamp_test import Build, MODELS, digest
from compact_layout_replay import SANITY, run_case, run_switching
from isolated_driver_test import driver_control, inductive_load, isolated_deck, replace_line, validate
from isolated_layout_extract import BOARD, POWER
from layout_switching_test import read_extraction
from leg_receiver_test import with_receiver
from local_shutdown_test import fault_deck, normal_deck
from protected_layout_replay import NODES as PROTECTED_NODES
from driven_layout_replay import resistive_load
from shunt_filter_test import circuit_from
from verify import ROOT


NODES = {
    **{name: PROTECTED_NODES[name] for name in POWER},
    "tvs_cathode": ("mid", "tvs_pad_k"),
    "hs": ("hs", "hs_junction"),
    "hs_bypass": ("hs_junction", "hs_cap"),
    "hs_source": ("hs_cap", "hs_takeoff"),
    "vss": ("vss", "vss_cap"),
    "vss_source": ("vss_cap", "low_src_tee"),
    "ho": ("ho", "hri"),
    "gh": ("hro", "gh"),
    "lo": ("lo", "lri"),
    "gl": ("lro", "gl"),
    "high_fast_feed": ("hb", "hb_cap"),
    "high_bulk_feed": ("hb", "hi_bulk_p"),
    "high_bulk_return": ("hi_bulk_n", "hs"),
    "low_fast_feed": ("vdd", "vdd_cap"),
    "low_bulk_feed": ("vdd", "lo_bulk_p"),
    "low_bulk_return": ("lo_bulk_n", "vss"),
}
BIAS_CORNERS = (("nominal", 25, 12, 1), ("hot", 100, 11.7, 2))


def network(data, nodes=NODES):
    resistance = data["frequencies_hz"]["100000"]["resistance_ohm"]
    inductance = data["frequencies_hz"]["1e+07"]["inductance_h"]
    result = []
    ports = data["ports"]
    for i, port in enumerate(ports):
        a, b = nodes[port]
        result.extend((f"Rpcb_{port} {a} r_{port} {resistance[i][i]:.10g}",
                       f"Lpcb_{port} r_{port} {b} {inductance[i][i]:.10g}"))
        for j, other in enumerate(ports[:i]):
            mutual = (inductance[i][j] + inductance[j][i]) / 2
            k = mutual / math.sqrt(inductance[i][i] * inductance[j][j])
            result.append(f"K{port}_{other} Lpcb_{port} Lpcb_{other} {k:.10g}")
    return "\n".join(result)


def add_routed_bias(source, high_tvs, hot):
    source = replace_line(
        source, "Xisolated",
        "Xisolated dis dt vss li_masked hi_masked lo ho vcci vcci vdd hb vss hs n13 n12 n7 UCC21520_TRANS",
    )
    for name in ("Ciso_high", "Rbias_cap", "C204", "Cbias"):
        source = replace_line(source, name, "")
    high_params = (f"LLOOP={high_tvs.tvs_loop_nh:g}n VBR={high_tvs.tvs_knee_v:g} "
                   f"RD={high_tvs.tvs_slope_ohm:g} C0={high_tvs.tvs_cjo_nf:g}n")
    source, count = re.subn(r"^(Xtvs_high [^\n]+\n\+ )[^\n]+", rf"\g<1>{high_params}", source, flags=re.M)
    if count != 1:
        raise ValueError("Review the high-side TVS insertion point")
    decoupling = []
    for name, supply, ret, bulk in (
        ("high_fast", "hb_cap", "hs_cap", False),
        ("low_fast", "vdd_cap", "vss_cap", False),
        ("high_bulk", "hi_bulk_p", "hi_bulk_n", True),
        ("low_bulk", "lo_bulk_p", "lo_bulk_n", True),
    ):
        capacitance = ("1.65u" if hot else "2.2u") if bulk else ("75n" if hot else "100n")
        package_nh = 0.55 if bulk else 0.35
        decoupling.extend((f"Lpkg_{name} {supply} {name}_r {package_nh:g}n",
                           f"Rpkg_{name} {name}_r {name}_c 30m",
                           f"Cpin_{name} {name}_c {ret} {capacitance}"))
    return source.removesuffix(".end\n") + "\n".join(decoupling) + """
Bhigh_tvs tvs_hi_i 0 V=abs(i(Lpcb_tvs_high_cathode))
.meas tran high_tvs_terminal_a MAX v(tvs_hi_i)
.end
"""


def add_cases(pool, work, args, extraction, reference, circuit, *,
              nodes=NODES, revise_bias=None, corners=BIAS_CORNERS, short_profiles=False):
    copper = network(extraction, nodes)
    tasks = {}
    for label, temperature, bias, package in corners:
        hot = temperature == 100
        # Fit the published maximum VBR and stated 10/1000 us clamping point.
        knee = 37.8 * (1 + 0.00096 * (temperature - 25))
        slope = (49.9 - 37.8) / 30.5
        low_tvs = Build(compact=False, pin_bootstrap=False, tvs_loop_nh=package,
                        tvs_knee_v=knee, tvs_slope_ohm=slope * (1.10 if hot else 1),
                        tvs_cjo_nf=1.8 if hot else 2.2)
        high_tvs = Build(compact=False, pin_bootstrap=False, tvs_loop_nh=package)
        fault_circuit = circuit
        if hot:
            high_tvs = replace(high_tvs, tvs_knee_v=39, tvs_slope_ohm=0.14, tvs_cjo_nf=3.3)
            low_tvs = replace(low_tvs, snubber_nf=4.23, snubber_ohm=2.31)
            fault_circuit = replace(circuit, filter_nf=circuit.filter_nf * 1.1,
                                    shunt_mohm=circuit.shunt_mohm * .99,
                                    offset_mv=-5, comparator_ns=7, logic_ns=12)
        for side in ("low", "high"):
            for kind in ("short",) if short_profiles else ("short", "inductive", "resistive"):
                fault = kind == "short"
                builder = fault_deck if fault else normal_deck
                source = builder(reference, 0, "sa", side, fault_circuit if fault else circuit, fast_inputs=True)
                source = with_receiver(source, bias_v=bias)
                source = isolated_deck(source, copper, extraction, low_tvs, fault, temperature, bias)
                source = add_routed_bias(source, high_tvs, hot)
                if revise_bias is not None:
                    source = revise_bias(source, bias, hot)
                source = replace_line(source, "Rghi", "Rghi hri hro 8.2")
                source = replace_line(source, "Rglo", "Rglo lri lro 8.2")
                if fault and side == "low":
                    source = replace_line(source, "Vli", "Vli li 0 0")
                if kind == "inductive":
                    source = inductive_load(source, side)
                elif kind == "resistive":
                    source = resistive_load(source, side)
                name = f"{label}_{side}_{kind}"
                runner = run_case if fault else run_switching
                if short_profiles:
                    for method, step in (("gear", "125p"), ("gear", "500p"), ("trap", "500p")):
                        case = f"{name}_{method}_{step}"
                        trial = source.replace(".tran 250p 4u 0 250p", f".tran {step} 4u 0 {step}")
                        if trial == source:
                            raise ValueError("Review the fault deck transient settings")
                        trial = trial.replace("method=gear", f"method={method}")
                        tasks[pool.submit(runner, args.ngspice, work, case, trial)] = (case, kind)
                else:
                    tasks[pool.submit(runner, args.ngspice, work, name, source)] = (name, kind)
    return tasks


def run(args, *, nodes=NODES, revise_bias=None, additional_sources=(), driver_reference=None):
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    if extraction["board_sha256"] != digest(args.board) or tuple(extraction["ports"]) != tuple(nodes):
        raise ValueError("Select the corresponding isolated-driver board and extraction")
    selected = json.loads(args.filter.read_text(encoding="utf-8"))
    if selected["extraction_sha256"] != digest(args.reference) or selected["shunt_sha256"] != digest(args.shunt):
        raise ValueError("The shunt filter and reference fixtures differ")
    reference = read_extraction(args.reference)
    mount = json.loads(args.shunt.read_text(encoding="utf-8"))["cases"]["nominal"]
    circuit = circuit_from(mount, selected["selected_filter_nf"])
    with TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(folder)
        with ZipFile(args.driver_archive) as archive:
            driver_model = archive.read("UCC21520_PSPICE_TRANS/UCC21520_TRANS.lib")
        driver_file = work / "ti-isolated.lib"
        driver_file.write_bytes(driver_model)
        with ZipFile(args.mosfet_archive) as archive:
            model = archive.read("CSD19531Q5A.lib").decode("ascii")
        model = re.sub(r"^(\s*\.param\s+\w+)[ \t]+(?=[^= \t\r\n])", r"\1=", model, flags=re.M | re.I)
        (work / "csd19531q5a.lib").write_text(model, encoding="ascii")
        for model in MODELS:
            shutil.copyfile(ROOT / model, work / model)
        controls = {
            "isolated_driver": driver_control(args.ngspice, work, False),
            "mosfet": run_case(args.ngspice, work, "mosfet_control", SANITY),
        }
        corners = BIAS_CORNERS
        if driver_reference:
            driver_file.write_bytes(driver_reference(driver_model))
            corners = BIAS_CORNERS[1:]
            driver_digest = digest(driver_file)
        short_profiles = getattr(args, "short_profiles", False)
        if short_profiles:
            corners = BIAS_CORNERS[:1]
        cases = {}
        tasks = add_cases(pool, work, args, extraction, reference, circuit,
                          nodes=nodes, revise_bias=revise_bias, corners=corners, short_profiles=short_profiles)
        for task in as_completed(tasks):
            name, kind = tasks[task]
            try:
                cases[name] = validate(task.result(), kind)
            except (RuntimeError, ValueError, KeyError, OSError, TimeoutExpired) as error:
                cases[name] = {"passed": False, "error": str(error).replace(str(work), "simulation")[-2000:]}
            print(f"{name}: {'inconclusive' if 'error' in cases[name] else 'completed'}", flush=True)
    paths = (args.board, args.extraction, args.reference, args.shunt, args.filter, args.driver_archive,
             args.mosfet_archive, Path(__file__), *additional_sources, *(ROOT / name for name in (
                 *MODELS, "verify.py", "isolated_layout_extract.py", "isolated_driver_test.py",
                 "protected_layout_extract.py", "protected_layout_replay.py", "driven_layout_replay.py",
                 "compact_layout_replay.py", "secondary_layout_replay.py", "commutation_clamp_test.py",
                 "local_shutdown_test.py", "leg_receiver_test.py", "half_bridge_test.py", "shunt_filter_test.py")))
    copper_nh = extraction["loops_at_10mhz_nh"]
    nominal_clamp_loop = {"D1": copper_nh["tvs_external"] + 1, "D2": copper_nh["tvs_high_copper"] + 1}
    result = {
        "inputs_sha256": {path.name: digest(path) for path in paths},
        "controls": controls,
        "nominal_total_clamp_loop_nh_with_assumed_package": nominal_clamp_loop,
        "cases": dict(sorted(cases.items())),
    }
    if driver_reference:
        result["diagnostic"] = "25 C on three UCC21520 internal devices, external corner 100 C"
        result["modified_driver_sha256"] = driver_digest
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not (all(x <= 2.5 for x in nominal_clamp_loop.values()) and all(c["passed"] for c in cases.values())):
        raise SystemExit("The routed isolated driver still has open criteria. Results saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-secondary-isolated-routed-impedance.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--driver-archive", type=Path, required=True, help="TI SLUM543 ZIP")
    parser.add_argument("--mosfet-archive", type=Path, required=True, help="TI SLPM077C ZIP")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--short-profiles", action="store_true", help="compare nominal short-fault solver profiles")
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
