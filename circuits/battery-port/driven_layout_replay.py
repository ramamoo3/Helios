"""Replay the secondary leg using its coupled power, gate and bootstrap copper."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from commutation_clamp_test import MODELS, Build, digest, evaluate
from compact_layout_replay import SANITY, precharge_only, run_case, run_switching, vendor_deck
from driven_layout_extract import BOARD, PORTS
from layout_switching_test import read_extraction
from leg_receiver_test import with_receiver
from local_shutdown_test import fault_deck, normal_deck
from secondary_layout_replay import routed_fixture
from shunt_filter_test import circuit_from
from verify import ROOT


NODES = (
    ("bus", "drainh"), ("sourceh", "hs_takeoff"), ("hs_takeoff", "switch_tee"),
    ("switch_tee", "mid"), ("sourcel", "low_src_tee"), ("low_src_tee", "shunt_force"),
    ("shunt_rail", "0"), ("switch_tee", "tvs_pad_k"), ("tvs_pad_a", "low_src_tee"),
    ("hs", "hs_junction"), ("hs_junction", "hs_takeoff"),
    ("vss", "vss_takeoff"), ("vss_takeoff", "low_src_tee"),
    ("ho", "hri"), ("hro", "gh"), ("lo", "lri"), ("lro", "gl"),
    ("hb", "hb_cap"), ("hs_cap", "hs_junction"), ("vdd", "vdd_cap"), ("vss_cap", "vss_takeoff"),
)
IMPLEMENTATIONS = ("switching_driver", "ti_driver")


def port_network(extraction):
    r = extraction["frequencies_hz"]["100000"]["resistance_ohm"]
    l = extraction["frequencies_hz"]["1e+07"]["inductance_h"]
    lines = []
    for i, (port, (a, b)) in enumerate(zip(PORTS, NODES, strict=True)):
        lines.extend((f"Rpcb_{port} {a} r_{port} {r[i][i]:.10g}",
                      f"Lpcb_{port} r_{port} {b} {l[i][i]:.10g}"))
        for j in range(i):
            k = (l[i][j] + l[j][i]) / (2 * math.sqrt(l[i][i] * l[j][j]))
            lines.append(f"K{port}_{PORTS[j]} Lpcb_{port} Lpcb_{PORTS[j]} {k:.10g}")
    return "\n".join(lines)


def external_driver(source):
    start, stop = "Dboot vdd hb DSCREENING\n", "Blo_sink lo vss I={(1-v(ld))*v(lo,vss)}\n"
    before, marker, remainder = source.partition(start)
    _, end, after = remainder.partition(stop)
    if not (marker and end):
        raise ValueError("Review the reduced-order driver insertion point")
    return (before + ".include ti-driver.lib\n"
            "Xdriver li_masked hi_masked en vdd vss hb ho hs lo UCC27282\n" + after)


def build_deck(source, network, extraction, build, fault, temperature, driver):
    source = routed_fixture(source, network, extraction["loops_at_10mhz_nh"], build, fault)
    if source.count("Cbias vdd vss 14.4u") != 1:
        raise ValueError("Review the driver bypass insertion point")
    source = source.replace("Cbias vdd vss 14.4u", "Cbias vdd vss 14.4u\n"
                            "Rbias_cap vdd_cap c204_top 25m\nC204 c204_top vss_cap 100n")
    if driver == "ti_driver":
        source = external_driver(source)
    source = vendor_deck(source, temperature)
    return source.removesuffix(".end\n") + (
        "Btvs_current probe_tvs 0 V=abs(i(Lpcb_tvs_cathode))\n"
        ".meas tran tvs_peak_terminal_a MAX v(probe_tvs)\n.end\n"
    )


def resistive_load(source, side):
    a, b = ("bus", "mid") if side == "low" else ("mid", "0")
    # This control has comparable on-current but lets the off-state current
    # decay to zero, so it isolates solver behavior from diode commutation.
    source, count = re.subn(r"^Iload .+$",
                            f"Vload_en load_en 0 PWL(0 0 2.5u 0 3.1u 1 5.1u 1 5.2u 0)\n"
                            f"Bload {a} {b} I={{v({a},{b})*v(load_en)/9.6}}", source, flags=re.M)
    if count != 1:
        raise ValueError("Review the load control insertion point")
    return source


def record(task, kind, work):
    try:
        m = task.result()
        if kind == "precharge":
            m["precharge_high_drain_terminal"] = m.pop("precharge_high_channel")
            m["passed"] = (m["precharge_off_gate"] < 0.1 and m["commanded_low_gate"] > 5
                           and -0.3 <= m["min_boot"] <= m["max_boot"] <= 16)
            return m
        m = evaluate(m, kind == "short")
        if kind != "short":
            for key in ("precharge_high", "commanded_high"):
                m[key + "_drain_terminal"] = m.pop(key + "_channel")
        m["limits"]["bootstrap_at_least_minus_0p3_v"] = m["min_boot"] >= -0.3
        m["vds_at_most_80_v"] = max(m["vds_hi_scan"], m["vds_lo_scan"]) <= 80
        m["passed"] = m["basic_check"] and all(m["limits"].values())
        return m
    except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
        message = str(error).replace(str(work), "simulation")
        return {"passed": False, "error": message if len(message) < 1800 else message[-1800:]}


def driver_control(work, ngspice):
    deck = (ROOT / "vendor-halfbridge.cir").read_text(encoding="ascii")
    deck = deck.replace("ti-mosfet.lib", "csd19531q5a.lib").replace("CSD18534KCS", "CSD19531Q5A")
    result = run_case(ngspice, work, "combined_ti_control", deck)
    if (min(result["high_on"], result["low_on"]) < 8
            or result["high_off"] <= result["en_off"]
            or max(result["overlap_hi"], result["overlap_lo"]) >= 0.1):
        raise ValueError(f"Unexpected result in the TI driver and MOSFET load control: {result}")
    return result


def submit_cases(pool, implementations, work, args, extraction, reference, circuit):
    network = port_network(extraction)
    pending = []
    for driver in implementations:
        for name, temp, package in (("nominal", 25, 1), ("hot", 100, 2)):
            build = Build(compact=False, pin_bootstrap=False, tvs_loop_nh=package)
            corner = circuit
            if name == "hot":
                build = replace(build, tvs_knee_v=39, tvs_slope_ohm=0.14, tvs_cjo_nf=3.3,
                                snubber_nf=4.23, snubber_ohm=2.31)
                corner = replace(circuit, filter_nf=circuit.filter_nf * 1.1,
                                 shunt_mohm=circuit.shunt_mohm * 0.99, offset_mv=-5,
                                 comparator_ns=7, logic_ns=12)
            for side in ("low", "high"):
                for kind, builder in (("normal", normal_deck), ("short", fault_deck)):
                    fault = kind == "short"
                    label = f"{driver}_{name}_{side}_{kind}"
                    source = builder(reference, 0, "sa", side, corner if fault else circuit, fast_inputs=True)
                    source = with_receiver(source, bias_v=12.3 if name == "hot" else 12)
                    source = build_deck(source, network, extraction, build, fault, temp, driver)
                    runner = run_case if fault else run_switching
                    pending.append((label, kind, pool.submit(runner, args.ngspice, work, label, source)))
                    if driver == "ti_driver" and name == "nominal" and not fault:
                        label = f"{driver}_{name}_{side}_resistive"
                        pending.append((label, "resistive", pool.submit(run_switching, args.ngspice, work, label,
                                                                        resistive_load(source, side))))
                    if side == "low" and not fault:
                        label = f"{driver}_{name}_precharge"
                        pending.append((label, "precharge", pool.submit(run_case, args.ngspice, work, label,
                                                                        precharge_only(source))))
    return pending


def run(args):
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    if extraction["board_sha256"] != digest(args.board) or tuple(extraction["ports"]) != PORTS:
        raise ValueError("The coupled extraction does not match the driver board")
    reference = read_extraction(args.reference)
    selected = json.loads(args.filter.read_text(encoding="utf-8"))
    if selected["extraction_sha256"] != digest(args.reference) or selected["shunt_sha256"] != digest(args.shunt):
        raise ValueError("The shunt filter and reference models differ")
    shunt = json.loads(args.shunt.read_text(encoding="utf-8"))["cases"]["nominal"]
    circuit = circuit_from(shunt, selected["selected_filter_nf"])
    with TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(directory)
        with ZipFile(args.vendor_archive) as archive:
            vendor = archive.read("CSD19531Q5A.lib").decode("ascii")
        vendor = re.sub(r"^(\s*\.param\s+\w+)[ \t]+(?=[^= \t\r\n])", r"\1=", vendor, flags=re.M | re.I)
        (work / "csd19531q5a.lib").write_text(vendor, encoding="ascii", newline="\n")
        shutil.copyfile(args.driver_model, work / "ti-driver.lib")
        for model in MODELS:
            shutil.copyfile(ROOT / model, work / model)
        controls = {"mosfet": run_case(args.ngspice, work, "mosfet_control", SANITY),
                    "combined_ti": driver_control(work, args.ngspice)}
        print("Independent TI model controls completed.", flush=True)
        cases = {}
        for label, kind, task in submit_cases(pool, IMPLEMENTATIONS, work, args, extraction, reference, circuit):
            cases[label] = record(task, kind, work)
            status = "inconclusive" if "error" in cases[label] else "completed"
            print(f"{label}: {status}", flush=True)
    result = {
        "inputs_sha256": {path.name: digest(path) for path in (
            args.board, args.extraction, args.reference, args.shunt, args.filter, args.vendor_archive,
            args.driver_model, *(ROOT / model for model in MODELS), Path(__file__),
            ROOT / "driven_layout_extract.py", ROOT / "compact_layout_replay.py",
            ROOT / "secondary_layout_replay.py", ROOT / "commutation_clamp_test.py",
            ROOT / "layout_switching_test.py", ROOT / "leg_receiver_test.py",
            ROOT / "local_shutdown_test.py", ROOT / "half_bridge_test.py", ROOT / "shunt_filter_test.py",
            ROOT / "vendor_test.py", ROOT / "vendor-halfbridge.cir",
        )},
        "controls": controls,
        "cases": cases,
        "tvs_copper_below_2p5_nh": extraction["loops_at_10mhz_nh"]["tvs_external"] <= 2.5,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    if not (result["tvs_copper_below_2p5_nh"] and all(case["passed"] for case in cases.values())):
        raise SystemExit("The coupled driver study has open criteria. Results saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-secondary-driven-impedance.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--vendor-archive", type=Path, required=True, help="TI SLPM077C ZIP")
    parser.add_argument("--driver-model", type=Path, required=True, help="Unzipped TI SLUM720 LIB")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
