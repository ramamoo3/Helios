"""Run the full DAB startup fixture using FastHenry port impedances."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from extract_layout import BOOTSTRAP_PORTS, DEFAULT_BOARD, PORTS
from startup_test import command_sources, compile_trace
from vendor_overlap_test import (CASES, DEVICE_PATH, END, LEGS, START, check_channel_probes,
                                 reduce_trace, trace_samples)
from vendor_startup_test import ROOT, write_deck
from vendor_test import PSPICE_OPTIONS, stage_vendor_models
from verify import run_spice


CONNECTIONS = (
    ("bus", "drainh"), ("sourceh", "mid"), ("sourcel", "0"),
    ("hs", "sourceh"), ("vss", "sourcel"), ("ho", "hri"),
    ("hro", "gh"), ("lo", "lri"), ("lro", "gl"),
)
BOOTSTRAP_CONNECTIONS = (
    *CONNECTIONS[:3], ("hs", "hs_junction"), *CONNECTIONS[4:],
    ("hs_junction", "sourceh"), ("hb", "hb_cap"), ("hs_cap", "hs_junction"),
)

# Continuous-output driver for numerical screening with the same TI MOSFET models.
# Gate-switch conductances are normalized to keep the bootstrap and bias currents explicit.
SCREENING_DRIVER = """Dboot vdd hb DSCREENING
.model DSCREENING D(Is=10n N=1.35 Rs=1.5 Cjo=15p)
Bhi_state hi_state 0 V={0.5*(1+tanh((v(hi,vss)-1.65)/0.15))}
Blo_state lo_state 0 V={0.5*(1+tanh((v(li,vss)-1.65)/0.15))}
Bpermit allow 0 V={0.25*(1+tanh((v(en,vss)-1.65)/0.15))*(1+tanh((v(vdd,vss)-5)/0.2))}
Bh_fraction hin 0 V={0.5*v(allow)*v(hi_state)*(1-v(lo_state))*(1+tanh((v(hb,hs)-5)/0.2))}
Bl_fraction lin 0 V={v(allow)*v(lo_state)*(1-v(hi_state))}
Rhi_delay hin hd 1k
Rlo_delay lin ld 1k
Chi_delay hd 0 18p
Clo_delay ld 0 18p
Bho_supply ho hb I={v(hd)*v(ho,hb)/2}
Bho_sink ho hs I={(1-v(hd))*v(ho,hs)}
Blo_supply lo vdd I={v(ld)*v(lo,vdd)/2}
Blo_sink lo vss I={(1-v(ld))*v(lo,vss)}"""

# First-order MOSFET fit using typical static resistance and capacitance data.
SCREENING_MOSFET = """.subckt PRINTED_FET d g s
Ld d di 0.05n
Lg g gi 2.1n
Ls si s 0.47n
Mdevice di gi si BENCH_VDMOS
.model BENCH_VDMOS VDMOS (Vto=1.9 Kp=100 Rd=4.9m Rs=1.5m Rg=1.5
+ Cgs=1495p Cgdmin=5p Cgdmax=800p Cjo=1n Is=1n Vj=0.8 M=0.5)
.ends PRINTED_FET
"""


def port_network(matrices, ports=PORTS):
    connections = BOOTSTRAP_CONNECTIONS if tuple(ports) == BOOTSTRAP_PORTS else CONNECTIONS
    r = matrices["100000"]["resistance_ohm"]
    l = matrices["1e+07"]["inductance_h"]
    lines = []
    for index, (port, (a, b)) in enumerate(zip(ports, connections, strict=True)):
        lines.extend((f"Rpcb_{port} {a} r_{port} {r[index][index]:.8g}",
                      f"Lpcb_{port} r_{port} {b} {l[index][index]:.8g}"))
        for other in range(index):
            coupling = (l[index][other] + l[other][index]) / (2 * math.sqrt(l[index][index] * l[other][other]))
            lines.append(f"K{port}_{ports[other]} Lpcb_{port} Lpcb_{ports[other]} {coupling:.8g}")
    return "\n".join(lines)


def layout_fixture(source, extraction, screening, screening_devices):
    start, marker, body = source.partition(".subckt LEG ")
    circuit, end, rest = body.partition(".ends LEG")
    if not (marker and end and circuit.count(DEVICE_PATH) == 1):
        raise ValueError("Review the layout injection points after the vendor fixture changes")
    # Bracket the unextracted board-bulk feed. Effective MLCC values are study inputs.
    start = start.replace("Crail_p p 0 470u", "Lbulk_p p pb_esr 15n\nRbulk_p pb_esr pb_c 40m\nCrail_p pb_c 0 470u")
    start = start.replace("Crail_s s 0 2200u", "Lbulk_s s sb_esr 15n\nRbulk_s sb_esr sb_c 25m\nCrail_s sb_c 0 2200u")
    if screening_devices:
        start += SCREENING_MOSFET
    base = circuit.replace("CB=100n", "CB=100n LCAP=700n")
    native_driver = "Xdriver li hi en vdd 0 hb ho mid lo UCC27282"
    base = base.replace(native_driver, SCREENING_DRIVER if screening
                        else "Xdriver li hi en vdd vss hb ho hs lo UCC27282")
    ports = extraction["ports"]
    hb, hs = ("hb_cap", "hs_cap") if tuple(ports) == BOOTSTRAP_PORTS else ("hb", "hs")
    base = base.replace("Cboot hb mid", f"Cboot {hb} {hs}")
    base = base.replace("Bdischarge hb mid I={v(hb,mid)", f"Bdischarge {hb} {hs} I={{v({hb},{hs})")
    base = base.replace("v(hb,mid)", "v(hb,hs)")
    base = base.replace("Rghi ho gh", "Rghi hri hro").replace("Rglo lo gl", "Rglo lri lro")
    base = base.replace("Rghs gh mid", "Rghs gh sourceh").replace("Rgls gl 0", "Rgls gl sourcel")
    base = base.replace("V=v(gh,mid)", "V=v(gh,sourceh)").replace("V=v(gl)", "V=v(gl,sourcel)")
    parts = []
    vectors = []
    probes = []
    measures = []
    mosfet = "PRINTED_FET" if screening_devices else "CSD18534KCS"
    for leg, _, midpoint in LEGS:
        network = port_network(extraction["legs"][leg]["frequencies_hz"], ports)
        devices = f"""{network}
Llocal bus local_r 0.6n
Rlocal local_r local_c 10m
Clocal local_c 0 {{LCAP}}
Xhigh drainh gh sourceh {mosfet}
Xlow mid gl sourcel {mosfet}
Bhs_level hs_level 0 V=v(hs,vss)
Bvds_high vds_high 0 V=v(drainh,sourceh)
Bvds_low vds_low 0 V=v(mid,sourcel)
Bfeed_abs feed_abs 0 V=abs(i(Lpcb_feed))
Bcap_abs cap_abs 0 V=abs(i(Llocal))"""
        parts.append(f".subckt LEG_{leg} " + base.replace(DEVICE_PATH, devices) + f".ends LEG_{leg}")
        rest = "\n".join(line.replace(" LEG ", f" LEG_{leg} ") + " LCAP={CLOCAL}" if line.startswith(f"X{leg} ")
                         else line for line in rest.split("\n"))
        for side in ("high", "low"):
            model = f"@m.x{leg}.x{side}.m1"
            vectors.extend((f"{model}[id]", f"{model}[vds]"))
        vectors.extend((f"v(x{leg}.drainh)", f"v(x{leg}.sourceh)", f"v({midpoint})", f"v(x{leg}.sourcel)"))
        for name, function, node in (
            ("hs", "MIN", f"x{leg}.hs_level"), ("vgs_hi", "MAX", f"h{leg}"),
            ("vgs_lo", "MAX", f"l{leg}"), ("vgs_hi_min", "MIN", f"h{leg}"),
            ("vgs_lo_min", "MIN", f"l{leg}"),
            ("vds_hi", "MAX", f"x{leg}.vds_high"), ("vds_lo", "MAX", f"x{leg}.vds_low"),
            ("feed_a", "MAX", f"x{leg}.feed_abs"), ("cap_a", "MAX", f"x{leg}.cap_abs"),
        ):
            probes.append(f"v({node})")
            measures.append(f".meas tran {leg}_{name} {function} v({node}) from={START} to={END}")
    return (start + "\n".join(parts) + rest, [] if screening_devices else vectors,
            (".save " + " ".join(dict.fromkeys(probes)), *measures))


def switching_case(args, case, fault, fault_start, scratch, source, pwm, vectors, measures):
    label = case.label
    directory = scratch / label
    directory.mkdir()
    for name in ("ti-driver.lib", "ti-mosfet.lib", "protection.lib"):
        shutil.copyfile(scratch / name, directory / name)
    saved = " ".join(vectors)
    controls = (".save " + saved, ".control", "set wr_singlescale", "set wr_vecnames", "option numdgt=16",
                "run", f"wrdata switching.dat {saved}", "quit", ".endc") if vectors else ()
    deck = directory / "switching.cir"
    # 0.35 uF and 0.70 uF bound two assumed effective values for the nominal 1 uF ceramics.
    values = {key: value for key, value in case.parameters.items() if key not in ("LFEED", "LSHARED")}
    values["CLOCAL"] = "350n" if "high" in label else "700n"
    write_deck(deck, label, values, case.direction, pwm, case.profile, fault=fault,
               fixture=source, max_step=case.max_step, diagnostics=(*measures, *controls),
               fault_start_us=fault_start)
    try:
        result = run_spice(args.ngspice, deck, cwd=directory, options=PSPICE_OPTIONS)
        result["precharge_off_gate_under_0p1v"] = result["prime_high"] < 0.1
        if fault:
            result["remains_inhibited"] = max(result[f"after_{probe}"]
                                               for probe in ("enp", "ens", "highmax", "lowmax")) < 0.1
        elif vectors:
            peak, charge, vds, leg = reduce_trace(trace_samples(directory / "switching.dat", vectors, vectors))
            result.update(overlap_a=peak, overlap_c=charge, overlap_leg=leg, vds_v=vds)
        return {"case": label, "measurements": result}
    except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
        detail = str(error).replace(str(directory), label)
        return {"case": label, "error": detail}


def read_extraction(path):
    extraction = json.loads(path.read_text(encoding="utf-8"))
    if tuple(extraction["ports"]) not in (PORTS, BOOTSTRAP_PORTS):
        raise ValueError("Unexpected extraction port order")
    board = DEFAULT_BOARD.read_bytes()
    # The original extraction predates these three hidden purchasing fields.
    # Match the original full digest after removing only their exact CAD syntax.
    pre_bom = re.sub(
        rb'(?m)^\t\t\(property "(?:Manufacturer|MPN|Voltage Rating)" "[^"\r\n]+" '
        rb'\(at 0 0 0\) \(layer "F\.Fab"\) \(hide yes\) \(effects \(font \(size 1 1\)\)\)\)\r?\n',
        b"", board,
    )
    if extraction["board_sha256"] not in (hashlib.sha256(board).hexdigest(), hashlib.sha256(pre_bom).hexdigest()):
        raise ValueError("Extraction was generated from a different board revision")
    return extraction


def run(args):
    extraction = read_extraction(args.extraction)
    source, vectors, measures = layout_fixture((ROOT / "vendor-dab-startup.cir").read_text(encoding="ascii"),
                                               extraction, args.screening_driver, args.screening_devices)
    cases = [(case, None, 12) for case in CASES if "LFEED" in case.parameters]
    if args.screening_driver:
        refinement_cases = {"charge-layout", "discharge-layout-high", "charge-layout-high"}
        corners = [(replace(case, label=case.label + "-half-step", max_step="500p"), fault, start)
                   for case, fault, start in cases if case.label in refinement_cases]
        faults = [(replace(cases[i][0], label=f"{domain}-bias-fault-{stage}"), domain, start)
                  for i, domain in enumerate(("pri_ok", "sec_ok"))
                  for stage, start in (("precharge", 12), ("active", 23))]
        cases.extend(corners + faults)
    if args.case:
        cases = [entry for entry in cases if entry[0].label in args.case]
        if {case.label for case, *_ in cases} != set(args.case):
            raise ValueError("At least one case name is unavailable with the selected device models")
    with TemporaryDirectory() as directory:
        scratch = Path(directory)
        stage_vendor_models(args.driver, args.mosfet, scratch)
        shutil.copyfile(ROOT / "protection.lib", scratch / "protection.lib")
        check_channel_probes(args.ngspice, scratch)
        program = compile_trace(args.cc, scratch)
        pwm = {d: command_sources(program, d, start_ns=17000, frames=2,
                                  amplitude=3.3, nodes=("pp", "pn", "sp_in", "sn_in")) for d in (120, -120)}
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            jobs = [pool.submit(switching_case, args, case, fault, fault_start, scratch, source,
                                pwm[case.direction], vectors, measures)
                    for case, fault, fault_start in cases]
            results = []
            for job in jobs:
                result = job.result()
                results.append(result)
                status = "completed"
                if "error" in result:
                    status = "INCONCLUSIVE"
                elif not result["measurements"].get("remains_inhibited", True):
                    status = "FAILED INHIBIT"
                elif not result["measurements"]["precharge_off_gate_under_0p1v"]:
                    status = "completed, precharge off-gate limit exceeded"
                print(result["case"], status, flush=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    if any("error" in result or not result["measurements"].get("remains_inhibited", True)
           for result in results):
        raise SystemExit("See the result file for inconclusive cases or failed inhibits")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--mosfet", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--case", action="append", help="run only the named case, repeat for multiple cases")
    parser.add_argument("--screening-driver", action="store_true",
                        help="use a continuous gate-driver approximation for numerical screening")
    parser.add_argument("--screening-devices", action="store_true",
                        help="use datasheet-fit VDMOS devices with the screening driver")
    args = parser.parse_args()
    if args.screening_devices and not args.screening_driver:
        parser.error("--screening-devices requires --screening-driver")
    run(args)
