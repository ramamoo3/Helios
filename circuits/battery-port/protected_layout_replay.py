"""Run the routed dual TVS and bootstrap Schottky in the secondary-leg fixture."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from commutation_clamp_test import MODELS, Build, digest
from compact_layout_replay import SANITY, precharge_only, run_case, run_switching
from driven_layout_extract import PORTS as DRIVER_PORTS
from driven_layout_replay import NODES as DRIVER_NODES, build_deck, driver_control, record
from layout_switching_test import read_extraction
from leg_receiver_test import with_receiver
from local_shutdown_test import fault_deck, normal_deck
from protected_layout_extract import BOARD, PORTS
from shunt_filter_test import circuit_from
from verify import ROOT


NODES = {
    **dict(zip(DRIVER_PORTS, DRIVER_NODES, strict=True)),
    "feed": ("bus", "bus_tee"),
    "feed_switch": ("bus_tee", "drainh"),
    "tvs_high_cathode": ("bus_tee", "tvs_high_k"),
    "tvs_high_anode": ("tvs_high_a", "hs_takeoff"),
    "boot_clamp_anode": ("hs_junction", "boot_diode_a"),
    "boot_clamp_cathode": ("boot_diode_k", "hb_cap"),
}
# Curve fit at 25 C to the PMEG3020ER typical forward-voltage and capacitance
# points. Package inductance, temperature law and reverse leakage are estimates.
BOOT_DIODE = ".model BOOT_SCHOTTKY D(IS=48u N=1.16 RS=24m CJO=290p VJ=0.55 M=0.52 EG=0.69 XTI=2 BV=30 IBV=0.6m)"


def coupled_network(extraction):
    resistance = extraction["frequencies_hz"]["100000"]["resistance_ohm"]
    inductance = extraction["frequencies_hz"]["1e+07"]["inductance_h"]
    branches = []
    for i, name in enumerate(PORTS):
        a, b = NODES[name]
        branches.extend((f"Rpcb_{name} {a} r_{name} {resistance[i][i]:.10g}",
                         f"Lpcb_{name} r_{name} {b} {inductance[i][i]:.10g}"))
        for j, other in enumerate(PORTS[:i]):
            mutual = (inductance[i][j] + inductance[j][i]) / 2
            k = mutual / math.sqrt(inductance[i][i] * inductance[j][j])
            branches.append(f"K{name}_{other} Lpcb_{name} Lpcb_{other} {k:.10g}")
    return "\n".join(branches)


def add_protection(deck, build):
    return deck.removesuffix(".end\n") + f"""Xtvs_high tvs_high_k tvs_high_a p_tvs_high BENCH_TVS
+ LLOOP={build.tvs_loop_nh:g}n VBR={build.tvs_knee_v:g} RD={build.tvs_slope_ohm:g} C0={build.tvs_cjo_nf:g}n
Lpkg_boot boot_diode_a boot_anode_pin 0.65n
Dboot_protect boot_anode_pin boot_diode_k BOOT_SCHOTTKY
{BOOT_DIODE}
Btvs_high_peak high_tvs_current 0 V=abs(i(Lpcb_tvs_high_cathode))
Bhb_vss hb_vss 0 V=v(hb,vss)
Bboot_diode_v boot_diode_v 0 V=v(boot_diode_k,boot_anode_pin)
.meas tran tvs_high_terminal_a MAX v(high_tvs_current)
.meas tran boot_diode_a MAX i(Lpkg_boot)
.meas tran boot_diode_reverse_v MAX v(boot_diode_v)
.meas tran hb_to_vss_min MIN v(hb_vss)
.end
"""


def diode_control(executable, work):
    deck = f"""PMEG3020ER forward-fit control
.temp 25
Icheck 0 a PWL(0 0.1 1u 0.1 1.05u 1 2u 1 2.05u 2 3u 2)
Dtest a 0 BOOT_SCHOTTKY
{BOOT_DIODE}
.tran 5n 3u
.meas tran at_100ma FIND v(a) at=0.7u
.meas tran at_1a FIND v(a) at=1.7u
.meas tran at_2a FIND v(a) at=2.7u
.end
"""
    result = run_case(executable, work, "boot_diode_control", deck)
    for name, volts in (("at_100ma", .230), ("at_1a", .320), ("at_2a", .365)):
        if abs(result[name] - volts) > .01:
            raise ValueError(f"The bootstrap diode model missed the forward fit at {name}")
    return result


def submit_cases(pool, work, args, extraction, reference, circuit):
    network = coupled_network(extraction)
    jobs = {}
    for kind in ("short", "precharge", "normal"):
        for driver in ("ti_driver", "switching_driver"):
            for corner, temperature, package in (("nominal", 25, 1), ("hot", 100, 2)):
                build = Build(compact=False, pin_bootstrap=False, tvs_loop_nh=package)
                sense = circuit
                if temperature == 100:
                    build = replace(build, tvs_knee_v=39, tvs_slope_ohm=0.14, tvs_cjo_nf=3.3,
                                    snubber_nf=4.23, snubber_ohm=2.31)
                    if kind == "short":
                        sense = replace(circuit, filter_nf=circuit.filter_nf * 1.1,
                                        shunt_mohm=circuit.shunt_mohm * 0.99, offset_mv=-5,
                                        comparator_ns=7, logic_ns=12)
                for side in (("low",) if kind == "precharge" else ("low", "high")):
                    builder = fault_deck if kind == "short" else normal_deck
                    source = builder(reference, 0, "sa", side, sense, fast_inputs=True)
                    source = with_receiver(source, bias_v=12.3 if temperature == 100 else 12)
                    source = build_deck(source, network, extraction, build, kind == "short", temperature, driver)
                    source = add_protection(source, build)
                    if kind == "precharge":
                        source = precharge_only(source)
                    name = f"{driver}_{corner}_{side}_{kind}"
                    runner = run_switching if kind == "normal" else run_case
                    jobs[pool.submit(runner, args.ngspice, work, name, source)] = (name, kind)
    return jobs


def run(args):
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    if extraction["board_sha256"] != digest(args.board) or tuple(extraction["ports"]) != PORTS:
        raise ValueError("The protected board and extraction differ")
    reference = read_extraction(args.reference)
    selection = json.loads(args.filter.read_text(encoding="utf-8"))
    if selection["extraction_sha256"] != digest(args.reference) or selection["shunt_sha256"] != digest(args.shunt):
        raise ValueError("The shunt filter and reference fixtures differ")
    shunt = json.loads(args.shunt.read_text(encoding="utf-8"))["cases"]["nominal"]
    circuit = circuit_from(shunt, selection["selected_filter_nf"])
    with TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(folder)
        with ZipFile(args.vendor_archive) as archive:
            vendor = archive.read("CSD19531Q5A.lib").decode("ascii")
        vendor = re.sub(r"^(\s*\.param\s+\w+)[ \t]+(?=[^= \t\r\n])", r"\1=", vendor, flags=re.M | re.I)
        (work / "csd19531q5a.lib").write_text(vendor, encoding="ascii")
        shutil.copyfile(args.driver_model, work / "ti-driver.lib")
        for model in MODELS:
            shutil.copyfile(ROOT / model, work / model)
        controls = {"mosfet": run_case(args.ngspice, work, "mosfet_control", SANITY),
                    "ti_combined": driver_control(work, args.ngspice),
                    "bootstrap_diode": diode_control(args.ngspice, work)}
        print("Three independent device-model controls completed.", flush=True)
        pending = submit_cases(pool, work, args, extraction, reference, circuit)
        cases = {}
        for task in as_completed(pending):
            name, kind = pending[task]
            case = record(task, kind, work)
            if "limits" in case:
                case["limits"]["hb_absolute_at_least_minus_0p3_v"] = case["hb_to_vss_min"] >= -0.3
                case["limits"]["boot_diode_reverse_at_most_30_v"] = case["boot_diode_reverse_v"] <= 30
                case["passed"] = case["basic_check"] and all(case["limits"].values())
            cases[name] = case
            status = "inconclusive" if "error" in case else "completed"
            print(f"{name}: {status}", flush=True)
    tvs_limits = {port: extraction["loops_at_10mhz_nh"][port] <= 2.5
                  for port in ("tvs_external", "tvs_high_copper")}
    inputs = (args.board, args.extraction, args.reference, args.shunt, args.filter, args.vendor_archive,
              args.driver_model, Path(__file__), *(ROOT / name for name in MODELS),
              *(ROOT / name for name in (
                  "protected_layout_extract.py", "driven_layout_extract.py", "driven_layout_replay.py",
                  "compact_layout_extract.py", "compact_layout_replay.py", "secondary_layout_replay.py",
                  "commutation_clamp_test.py", "layout_switching_test.py", "leg_receiver_test.py",
                  "local_shutdown_test.py", "half_bridge_test.py", "shunt_filter_test.py",
                  "vendor_test.py", "vendor-halfbridge.cir", "verify.py")))
    result = {"inputs_sha256": {path.name: digest(path) for path in inputs},
              "controls": controls, "tvs_copper_within_total_budget": tvs_limits,
              "cases": dict(sorted(cases.items()))}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not (all(tvs_limits.values()) and all(case["passed"] for case in cases.values())):
        raise SystemExit("The routed protection candidate has open criteria. Results saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-secondary-protected-impedance.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--vendor-archive", type=Path, required=True)
    parser.add_argument("--driver-model", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
