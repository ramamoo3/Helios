"""Screen a dual isolated driver and independently supplied high-side bias."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from commutation_clamp_test import MODELS, Build, digest
from compact_layout_replay import SANITY, run_case, run_switching
from driven_layout_replay import build_deck, resistive_load
from layout_switching_test import read_extraction
from leg_receiver_test import with_receiver
from local_shutdown_test import fault_deck, normal_deck
from protected_layout_extract import BOARD, PORTS
from protected_layout_replay import coupled_network
from shunt_filter_test import circuit_from, classify_input_turnoff, passes_switching
from verify import ROOT


DRIVER = """Xisolated dis dt vss hi_masked li_masked ho lo vcci vcci hb vdd hs vss n13 n12 n7 UCC21520_TRANS
.include ti-isolated.lib
Vlogic_bias vcci vss 3.3
Clogic_bias vcci vss 100n
Rdead dt vss 10k
Cdead dt vss 470p
Rdisable vcci dis 2.2k
Spermit dis vss ena_local 0 PERMIT_SW
.model PERMIT_SW SW(Ron=12 Roff=100meg Vt=1.65 Vh=0.15)
Bpermit_local ena_local 0 V=v(en,vss)
"""

CONTROL = """Helios independent isolated gate driver control
.include ti-isolated.lib
.options method=gear reltol=0.005
Va a_source hs PWL(0 12 6u 12 6.5u 5 10u 5 10.5u 12)
Ra a_source a_supply 0.25
Ca a_supply hs 1u
Vb b_supply 0 12
Vlogic vcci 0 3.3
Vref hs 0 PWL(0 24 0.7u 24 0.72u 0 1u 0 1.02u 24)
Vdis dis 0 PWL(0 3.3 1.3u 3.3 1.31u 0 4.2u 0 4.21u 3.3
+ 5u 3.3 5.01u 0 5.95u 0 5.96u 3.3 210u 3.3 210.01u 0)
Vhi hi 0 PWL(0 3.3 2.2u 3.3 2.21u 0 3.4u 0 3.41u 3.3)
Vlo lo 0 PWL(0 0 2.22u 0 2.23u 3.3 3.1u 3.3 3.11u 0)
Rdt dt 0 10k
Cdt dt 0 470p
Xiso dis dt 0 hi lo hoa lob vcci vcci a_supply b_supply hs 0 n13 n12 n7 UCC21520_TRANS
Rga hoa ga 4.7
Rgb lob gb 4.7
Cga ga hs 2.2n
Cgb gb 0 2.2n
Bga high_gate 0 V=v(ga,hs)
.tran 2n 234u 0 2n
.meas tran disabled_start MAX v(high_gate) from=0.4u to=1.2u
.meas tran first_high FIND v(high_gate) at=1.9u
.meas tran low_on FIND v(gb) at=2.85u
.meas tran high_off WHEN v(high_gate)=2 FALL=1 TD=2.2u
.meas tran low_rise WHEN v(gb)=2 RISE=1 TD=2.2u
.meas tran did_disable FIND v(high_gate) at=4.35u
.meas tran before_bias_loss FIND v(high_gate) at=5.8u
.meas tran gate_during_inhibit FIND v(high_gate) at=6.8u
.meas tran high_released MAX v(high_gate) from=150u to=209u
.meas tran rearmed_high FIND v(high_gate) at=230u
.end
"""


def driver_control(ngspice, work, bias_loss):
    name = "bias_loss" if bias_loss else "constant_bias"
    source = CONTROL if bias_loss else replace_line(CONTROL, "Va", "Va a_source hs 12")
    values = run_case(ngspice, work, name, source)
    if (min(values[k] for k in ("first_high", "low_on", "before_bias_loss", "rearmed_high")) < 10
            or max(values[k] for k in ("disabled_start", "did_disable", "gate_during_inhibit", "high_released")) > .1
            or values["low_rise"] <= values["high_off"]):
        raise ValueError(f"Unexpected enable or output waveform from the UCC21520 model: {values}")
    values["output_dead_time_ns"] = (values["low_rise"] - values["high_off"]) * 1e9
    values["passed"] = True
    return values


def replace_line(source, name, replacement):
    source, count = re.subn(rf"^{re.escape(name)} .+$", replacement, source, flags=re.M)
    if count != 1:
        raise ValueError(f"Review the inherited {name} insertion point")
    return source


def isolated_deck(source, network, extraction, build, fault, temperature, bias):
    # Keep the power and gate geometry of the routed bench board as a
    # comparison fixture. The new SOIC and bias routes must be extracted later.
    source = build_deck(source, network, extraction, build, fault, temperature, "ti_driver")
    source, count = re.subn(r"^\.include ti-driver.lib\nXdriver .+\n", DRIVER, source, flags=re.M)
    if count != 1:
        raise ValueError("Review the driver insertion point")
    source = replace_line(source, "Cboot", "Ciso_high hb_cap hs_cap 1u")
    source = replace_line(source, "Rbootleak", "")
    source = source.replace("Bboot_now boot_now 0 V=v(hb,hs)\n", "")
    source = re.sub(r"^\.meas tran (?:min_boot|max_boot|hi_boot_at_switch) .+\n", "", source, flags=re.M)
    return source.removesuffix(".end\n") + f"""Vfloat source_a hs_junction {bias:g}
Rsource_a source_a vd_a 0.25
Lsource_a vd_a hb 1n
Ciso_coupling hs_junction 0 50p
Xtvs_high tvs_high_k tvs_high_a p_tvs_high BENCH_TVS
+ LLOOP={build.tvs_loop_nh:g}n VBR={build.tvs_knee_v:g} RD={build.tvs_slope_ohm:g} C0={build.tvs_cjo_nf:g}n
Ba_supply a_v 0 V=v(hb,hs)
Bhi_output a_out 0 V=v(ho,hs)
Bls_output b_out 0 V=v(lo,vss)
Bhi_in_rel hi_rel 0 V=v(hi_masked,vss)
Blow_in_rel li_rel 0 V=v(li_masked,vss)
.meas tran high_bias_min MIN v(a_v)
.meas tran high_bias_max MAX v(a_v)
.meas tran hi_pin_min MIN v(a_out)
.meas tran lo_pin_min MIN v(b_out)
.end
"""


def inductive_load(source, side):
    pulse = "PWL(0 0 3.3u 0 3.31u 3.3 4.28u 3.3 4.29u 0 4.62u 0 4.63u 3.3 4.87u 3.3 4.88u 0)"
    high, low = (pulse, "0") if side == "high" else ("0", pulse)
    a, b = ("bus", "mid") if side == "low" else ("mid", "0")
    source = replace_line(source, "Vhi", f"Vhi hi 0 {high}")
    source = replace_line(source, "Vli", f"Vli li 0 {low}")
    source = replace_line(source, "Iload", f"Lload {a} load_r 10u\nRload load_r {b} 0.10")
    source = source.replace("at=4.6u", "at=4.77u")
    return source.removesuffix(".end\n") + """.meas tran current_at_commutation FIND i(Lload) at=4.61u
.end
"""


def validate(values, kind):
    if kind == "short":
        classify_input_turnoff(values)
        basic = values["interrupted_with_request_high"]
    else:
        basic = passes_switching(values)
        if kind == "inductive":
            basic = basic and 1.8 < values["current_at_commutation"] < 2.8
    drain = max(values["vds_hi_scan"], values["vds_lo_scan"])
    gate = max(values["max_vgs_high"], values["max_vgs_low"],
               -values["min_vgs_high"], -values["min_vgs_low"])
    values["checks"] = {
        "functional": basic,
        "both_output_biases_in_range": (
            9.2 <= values["high_bias_min"] <= values["high_bias_max"] <= 16
            and 9.2 <= values["min_vdd"] <= values["max_vdd"] <= 16),
        "gate_magnitude_at_most_16_v": gate <= 16,
        "drain_at_most_54_v": drain <= 54,
    }
    values["passed"] = all(values["checks"].values())
    for name in ("precharge_high", "commanded_high"):
        if name + "_channel" in values:
            values[name + "_drain_terminal"] = values.pop(name + "_channel")
    return values


def submit(pool, work, args, extraction, reference, circuit):
    network = "\n".join(line for line in coupled_network(extraction).splitlines()
                        if "boot_clamp_" not in line)
    jobs = {}
    for name, temp, bias, package in (("nominal", 25, 12, 1), ("hot", 100, 11.7, 2)):
        build = Build(compact=False, pin_bootstrap=False, tvs_loop_nh=package)
        fault_circuit = circuit
        if temp == 100:
            build = replace(build, tvs_knee_v=39, tvs_slope_ohm=0.14, tvs_cjo_nf=3.3,
                            snubber_nf=4.23, snubber_ohm=2.31)
            fault_circuit = replace(circuit, filter_nf=circuit.filter_nf*1.1, shunt_mohm=circuit.shunt_mohm*.99,
                                    offset_mv=-5, comparator_ns=7, logic_ns=12)
        for side in ("low", "high"):
            for kind in ("short", "inductive", "current", "resistive"):
                is_fault = kind == "short"
                builder = fault_deck if is_fault else normal_deck
                raw = builder(reference, 0, "sa", side, fault_circuit if is_fault else circuit, fast_inputs=True)
                raw = with_receiver(raw, bias_v=bias)
                source = isolated_deck(raw, network, extraction, build, is_fault, temp, bias)
                if is_fault and side == "low":
                    # Same protection stimulus with the low-side preparation pulse removed.
                    source = replace_line(source, "Vli", "Vli li 0 0")
                if kind == "inductive":
                    source = inductive_load(source, side)
                elif kind == "resistive":
                    source = resistive_load(source, side)
                label = f"{name}_{side}_{kind}"
                runner = run_case if is_fault else run_switching
                jobs[pool.submit(runner, args.ngspice, work, label, source)] = (label, kind)
    return jobs


def run(args):
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    if extraction["board_sha256"] != digest(args.board) or tuple(extraction["ports"]) != PORTS:
        raise ValueError("Select the matching protected board and extraction")
    reference = read_extraction(args.reference)
    selection = json.loads(args.filter.read_text(encoding="utf-8"))
    if selection["extraction_sha256"] != digest(args.reference) or selection["shunt_sha256"] != digest(args.shunt):
        raise ValueError("The selected shunt filter and reference fixtures differ")
    mount = json.loads(args.shunt.read_text(encoding="utf-8"))["cases"]["nominal"]
    circuit = circuit_from(mount, selection["selected_filter_nf"])
    with TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(folder)
        with ZipFile(args.mosfet_archive) as archive:
            vendor = archive.read("CSD19531Q5A.lib").decode("ascii")
        vendor = re.sub(r"^(\s*\.param\s+\w+)[ \t]+(?=[^= \t\r\n])", r"\1=", vendor, flags=re.M | re.I)
        (work / "csd19531q5a.lib").write_text(vendor, encoding="ascii")
        with ZipFile(args.driver_archive) as archive:
            model = archive.read("UCC21520_PSPICE_TRANS/UCC21520_TRANS.lib")
        (work / "ti-isolated.lib").write_bytes(model)
        for model in MODELS:
            shutil.copyfile(ROOT / model, work / model)
        pending = submit(pool, work, args, extraction, reference, circuit)
        controls = {"mosfet": run_case(args.ngspice, work, "mosfet_control", SANITY)}
        for label, bias_loss in (("driver_constant_bias", False), ("driver_bias_loss", True)):
            try:
                controls[label] = driver_control(args.ngspice, work, bias_loss)
            except (RuntimeError, ValueError, KeyError, OSError, TimeoutExpired) as error:
                controls[label] = {"passed": False, "error": str(error).replace(str(work), "simulation")[-2200:]}
            print(f"{label}: {'completed' if controls[label]['passed'] else 'inconclusive'}", flush=True)
        cases = {}
        for job in as_completed(pending):
            label, kind = pending[job]
            try:
                cases[label] = validate(job.result(), kind)
            except (RuntimeError, ValueError, KeyError, OSError, TimeoutExpired) as error:
                cases[label] = {"passed": False, "error": str(error).replace(str(work), "simulation")[-2200:]}
            case = cases[label]
            print(f"{label}: {'inconclusive' if 'error' in case else 'completed'}", flush=True)
    paths = (args.board, args.extraction, args.reference, args.shunt, args.filter, args.driver_archive,
             args.mosfet_archive, Path(__file__), *(ROOT / name for name in (
                 *MODELS, "verify.py", "protected_layout_extract.py", "protected_layout_replay.py",
                 "driven_layout_replay.py", "driven_layout_extract.py", "compact_layout_replay.py",
                 "secondary_layout_replay.py", "commutation_clamp_test.py", "leg_receiver_test.py",
                 "local_shutdown_test.py", "half_bridge_test.py", "shunt_filter_test.py")))
    result = {"inputs_sha256": {path.name: digest(path) for path in paths},
              "layout": "UCC27282 board copper used as a proxy for the isolated-driver placement",
              "controls": controls, "cases": dict(sorted(cases.items()))}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not (all(case["passed"] for case in cases.values())
            and all(control["passed"] for name, control in controls.items() if name.startswith("driver_"))):
        raise SystemExit("The isolated-driver screen has open criteria. Results saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-secondary-protected-impedance.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--driver-archive", type=Path, required=True, help="TI SLUM543 ZIP")
    parser.add_argument("--mosfet-archive", type=Path, required=True, help="TI SLPM077C ZIP")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
