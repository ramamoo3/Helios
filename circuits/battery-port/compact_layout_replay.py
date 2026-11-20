"""Replay the compact copper with TI's CSD19531Q5A and reference gate wiring."""
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
from compact_layout_extract import BOARD, PORTS
from layout_switching_test import read_extraction
from leg_receiver_test import with_receiver
from local_shutdown_test import fault_deck, normal_deck
from secondary_layout_replay import copper_network, routed_fixture
from shunt_filter_test import circuit_from
from vendor_test import PSPICE_OPTIONS
from verify import ROOT, run_spice


POWER_NODES = (
    ("bus", "drainh"),
    ("sourceh", "switch_tee"),
    ("switch_tee", "mid"),
    ("sourcel", "shunt_force"),
    ("shunt_rail", "0"),
    ("switch_tee", "tvs_pad_k"),
    ("tvs_pad_a", "sourcel"),
)
GATE_ONLY = {"hs", "vss", "ho", "gh", "lo", "gl", "hs_source", "boot_feed", "boot_return"}

VENDOR_DEVICE = """.include csd19531q5a.lib
.subckt CHARGE_FET d g s p_diss params: DTT=0
Vchannel d terminal 0
Xvendor terminal g s CSD19531Q5A
Bpower p_diss 0 V={max(0,v(d,s)*i(Vchannel))}
.ends CHARGE_FET"""

SANITY = """Helios TI MOSFET model check
.include csd19531q5a.lib
Vbus bus 0 24
Rload bus d 10
Vgate g 0 PULSE(0 10 100n 10n 10n 1u 2u)
Xvendor d g 0 CSD19531Q5A
.tran 1n 1.5u
.meas tran on_drop FIND v(d) at=800n
.meas tran off_voltage FIND v(d) at=20n
.end
"""


def mixed_network(compact, gate_reference):
    matrices = compact["frequencies_hz"]
    r = matrices["100000"]["resistance_ohm"]
    l = matrices["1e+07"]["inductance_h"]
    lines = []
    for i, (port, (a, b)) in enumerate(zip(PORTS, POWER_NODES, strict=True)):
        lines.extend((f"Rpcb_{port} {a} r_{port} {r[i][i]:.9g}",
                      f"Lpcb_{port} r_{port} {b} {l[i][i]:.9g}"))
        for j in range(i):
            k = (l[i][j] + l[j][i]) / (2 * math.sqrt(l[i][i] * l[j][j]))
            lines.append(f"K{port}_{PORTS[j]} Lpcb_{port} Lpcb_{PORTS[j]} {k:.9g}")
    for line in copper_network(gate_reference).splitlines():
        terms = line.split()
        if terms[0].startswith("K"):
            if all(term.removeprefix("Lpcb_") in GATE_ONLY for term in terms[1:3]):
                lines.append(line)
        elif terms[0].split("_", 1)[1] in GATE_ONLY:
            lines.append(line)
    return "\n".join(lines)


def vendor_deck(deck, temperature):
    deck, count = re.subn(r"^\.subckt CHARGE_FET[^\n]*\n[\s\S]*?^\.ends CHARGE_FET",
                          VENDOR_DEVICE, deck, flags=re.M | re.I)
    if count != 1:
        raise ValueError("Review the MOSFET insertion point in the secondary fixture")
    title, body = deck.split("\n", 1)
    body = body.removesuffix(".end\n") + ".meas tran min_boot MIN v(boot_now)\n.end\n"
    return f"{title}\n.temp {temperature:g}\n{body}"


def run_case(executable, directory, name, deck):
    path = directory / (name + ".cir")
    path.write_text(deck, encoding="ascii", newline="\n")
    return run_spice(executable, path, cwd=directory, options=PSPICE_OPTIONS)


def run_switching(executable, directory, name, deck):
    attempts = (
        ("gear_250ps", deck),
        ("gear_125ps", deck.replace(".tran 250p 5.5u 0 250p", ".tran 125p 5.5u 0 125p")),
        ("trapezoid_500ps", deck.replace("method=gear", "method=trap")
         .replace(".tran 250p 5.5u 0 250p", ".tran 500p 5.5u 0 500p")),
    )
    failed = {}
    for profile, source in attempts:
        try:
            values = run_case(executable, directory, name + "_" + profile, source)
            values["solver_profile"] = profile
            values["failed_solver_profiles"] = failed
            return values
        except (RuntimeError, TimeoutExpired) as error:
            raw = str(error).replace(str(directory), "simulation")
            failed[profile] = next((line.strip() for line in raw.splitlines()
                                    if re.search(r"timestep|timeout|timed out|fatal", line, re.I)), raw[-650:])
    raise ValueError(f"All normal-switching numerical profiles failed: {failed}")


def precharge_only(deck):
    names = {"min_boot", "max_boot", "precharge_off_gate", "precharge_high_channel"}
    lines = [line for line in deck.splitlines()
             if not line.startswith(".meas") or line.split()[2] in names]
    source = "\n".join(lines).replace(".tran 250p 5.5u 0 250p", ".tran 250p 2.5u 0 250p")
    return source.removesuffix(".end") + ".meas tran commanded_low_gate FIND v(gl_s) at=1.65u\n.end\n"


def run(args):
    compact = json.loads(args.extraction.read_text(encoding="utf-8"))
    reference = read_extraction(args.reference)
    gate = json.loads(args.gate_reference.read_text(encoding="utf-8"))
    shunt = json.loads(args.shunt.read_text(encoding="utf-8"))["cases"]
    selected = json.loads(args.filter.read_text(encoding="utf-8"))
    if compact["board_sha256"] != digest(args.board) or tuple(compact["ports"]) != PORTS:
        raise ValueError("The compact board and extraction differ")
    if gate["board_sha256"] != digest(args.gate_board):
        raise ValueError("The reference gate board and extraction differ")
    if selected["shunt_sha256"] != digest(args.shunt) or selected["extraction_sha256"] != digest(args.reference):
        raise ValueError("The selected filter and reference fixtures differ")
    circuit = circuit_from(shunt["nominal"], selected["selected_filter_nf"])
    network = mixed_network(compact, gate)
    cases = {}
    precharge = {}
    scenarios = {}
    with TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(tmp)
        with ZipFile(args.vendor_archive) as archive:
            model = archive.read("CSD19531Q5A.lib").decode("ascii")
        # PSpice accepts whitespace-only local assignments in this library.
        # Keep all values and expressions and use ngspice's explicit syntax.
        model = re.sub(r"^(\s*\.param\s+\w+)[ \t]+(?=[^= \t\r\n])", r"\1=", model, flags=re.M | re.I)
        (work / "csd19531q5a.lib").write_text(model, encoding="ascii", newline="\n")
        for name in MODELS:
            shutil.copyfile(ROOT / name, work / name)
        sanity = run_case(args.ngspice, work, "vendor_sanity", SANITY)
        if not 0 < sanity["on_drop"] < 0.08 or not 23.8 < sanity["off_voltage"] < 24.2:
            raise ValueError(f"The vendor MOSFET failed its independent load check: {sanity}")
        tasks = []
        precharge_tasks = {}
        for name, temp, package in (("nominal", 25, 1), ("hot", 100, 2)):
            scenarios[name] = {"temperature_c": temp, "assumed_tvs_package_nh": package}
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
                    label = f"{name}_{side}_{kind}"
                    source = builder(reference, 0, "sa", side, corner if fault else circuit, fast_inputs=True)
                    source = with_receiver(source, bias_v=12.3 if name == "hot" else 12)
                    source = routed_fixture(source, network, compact["loops_at_10mhz_nh"], build, fault)
                    source = vendor_deck(source, temp)
                    runner = run_case if fault else run_switching
                    tasks.append((label, fault, pool.submit(runner, args.ngspice, work, label, source)))
                    if side == "low" and not fault:
                        precharge_tasks[name] = pool.submit(run_case, args.ngspice, work,
                                                           name + "_precharge", precharge_only(source))
        for label, fault, task in tasks:
            try:
                measurement = evaluate(task.result(), fault)
                # The existing 54 V criterion remains visible for comparison
                # with the 60 V design. 80 V is a separate screen for this part.
                measurement["vds_at_most_80_v"] = max(measurement["vds_hi_scan"],
                                                       measurement["vds_lo_scan"]) <= 80
                measurement["bootstrap_above_negative_absolute_limit"] = measurement["min_boot"] >= -0.3
                if not fault:
                    for key in ("precharge_high_channel", "commanded_high_channel"):
                        measurement[key.replace("_channel", "_drain_terminal")] = measurement.pop(key)
                cases[label] = measurement
            except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
                cases[label] = {"passed": False, "error": str(error).replace(str(work), "simulation")}
            print(f"{label}: {'completed' if 'error' not in cases[label] else 'inconclusive'}", flush=True)
        for name, task in precharge_tasks.items():
            try:
                m = task.result()
                m["precharge_high_drain_terminal"] = m.pop("precharge_high_channel")
                m["passed"] = (m["precharge_off_gate"] < 0.1 and m["commanded_low_gate"] > 5
                               and -0.3 <= m["min_boot"] <= m["max_boot"] <= 16)
                precharge[name] = m
            except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
                precharge[name] = {"passed": False, "error": str(error).replace(str(work), "simulation")}
    result = {
        "board_sha256": digest(args.board),
        "extraction_sha256": digest(args.extraction),
        "gate_reference_sha256": digest(args.gate_reference),
        "gate_reference_board_sha256": gate["board_sha256"],
        "vendor_archive_sha256": digest(args.vendor_archive),
        "reference_sha256": digest(args.reference),
        "filter_sha256": digest(args.filter),
        "shunt_sha256": digest(args.shunt),
        "model_sha256": {name: digest(ROOT / name) for name in (*MODELS, "compact_layout_replay.py",
                          "compact_layout_extract.py", "secondary_layout_replay.py", "commutation_clamp_test.py",
                          "half_bridge_test.py", "layout_switching_test.py", "local_shutdown_test.py",
                          "leg_receiver_test.py")},
        "model_check": sanity,
        "precharge_only": precharge,
        "scenarios": scenarios,
        "cases": cases,
        "copper_only_tvs_below_2p5_nh": compact["loops_at_10mhz_nh"]["tvs_external"] <= 2.5,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    switching_passed = all(case["passed"] and case["bootstrap_above_negative_absolute_limit"]
                           for case in cases.values())
    if not (result["copper_only_tvs_below_2p5_nh"] and switching_passed
            and all(case["passed"] for case in precharge.values())):
        raise SystemExit("The compact study has open layout or waveform criteria. Measurements saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-secondary-compact-impedance.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--gate-reference", type=Path, default=ROOT / "bench-secondary-layout-impedance.json")
    parser.add_argument("--gate-board", type=Path, default=ROOT / "battery-port-secondary-layout.kicad_pcb")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--vendor-archive", type=Path, required=True, help="TI SLPM077C ZIP")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
