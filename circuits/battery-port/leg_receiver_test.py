"""Screen the VSS-referenced gate interface and rerun the selected shunt faults."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

from extract_layout import LEGS
from half_bridge_test import calibrate_recovery, run_deck
from layout_switching_test import read_extraction
from local_shutdown_test import fault_deck, normal_deck
from shunt_filter_test import circuit_from, classify_input_turnoff, passes_switching
from verify import ROOT


INTERFACE = """Helios isolated interface and restart
.include leg_receiver.lib
.include local_shutdown.lib
Vsource s3 0 PWL(0 3.3 13u 3.3 13.05u 0 15u 0 15.05u 3.3)
Vbounce vss 0 PULSE(-7 7 3.2u 2n 2n 30n 65n)
Vrx r3 vss PWL(0 3.3 7.8u 3.3 7.81u 0 8.5u 0 8.51u 3.3)
Vrxgood rxgood vss PWL(0 0 800n 0 805n 3.3 7u 3.3 7.005u 0 9u 0 9.005u 3.3)
Vgood good 0 3.3
Varm arm 0 PWL(0 0 1u 0 1.005u 3.3 1.3u 3.3 1.305u 0
+ 10u 0 10.005u 3.3 10.3u 3.3 10.305u 0)
Vrun run 0 PWL(0 0 1.5u 0 1.505u 3.3 9.5u 3.3 9.505u 0 10.5u 0 10.505u 3.3)
Vhi raw_hi 0 PWL(0 3.3 4u 3.3 4.005u 0 5u 0 5.005u 3.3)
Vli raw_li 0 PWL(0 0 4.2u 0 4.205u 3.3 4.8u 3.3 4.805u 0)
Xlocal good good bias_good arm run good good armed permit BRIDGE_LOCAL_SHUTDOWN
Xrx raw_hi raw_li permit armed s3 0 vss r3 rxgood hi li en bias_good LEG_RECEIVER
Bhi hi_rel 0 V=v(hi,vss)
Blo li_rel 0 V=v(li,vss)
Ben en_rel 0 V=v(en,vss)
.tran 0.5n 16u 0 0.5n
.meas tran startup_hi MAX v(hi_rel) from=100n to=1.4u
.meas tran startup_en MAX v(en_rel) from=100n to=950n
.meas tran armed_en FIND v(en_rel) at=1.2u
.meas tran running_hi MIN v(hi_rel) from=3.3u to=3.9u
.meas tran running_li MIN v(li_rel) from=4.3u to=4.7u
.meas tran running_li_off MAX v(li_rel) from=3.3u to=3.9u
.meas tran running_hi_off MAX v(hi_rel) from=4.3u to=4.7u
.meas tran all_hi_min MIN v(hi_rel) from=100n to=16u
.meas tran all_hi_max MAX v(hi_rel) from=100n to=16u
.meas tran cmd_fall WHEN v(raw_hi)=1.65 FALL=1
.meas tran hi_fall WHEN v(hi_rel)=0.9 FALL=1 TD=3.8u
.meas tran bias_open_hi MAX v(hi_rel) from=7.65u to=7.79u
.meas tran bias_open_en MAX v(en_rel) from=7.65u to=7.79u
.meas tran bias_unpowered_hi MAX v(hi_rel) from=8.1u to=8.4u
.meas tran bias_unpowered_pg MAX v(bias_good) from=8.1u to=8.4u
.meas tran bias_loss_hi_off WHEN v(hi_rel)=0.9 FALL=1 TD=7u
.meas tran bias_loss_en_off WHEN v(en_rel)=0.7 FALL=1 TD=7u
.meas tran bias_restored_pg FIND v(bias_good) at=9.2u
.meas tran bias_restored_no_rearm MAX v(hi_rel) from=9.2u to=9.49u
.meas tran rearmed_hi FIND v(hi_rel) at=12u
.meas tran source_unpowered_hi MAX v(hi_rel) from=13.4u to=14.9u
.meas tran source_unpowered_en MAX v(en_rel) from=13.4u to=14.9u
.end
"""


def with_receiver(deck, permit="en_candidate", bias_v=12, step="250p"):
    # Keep the existing short fixture and replace its ideal PWM masks only.
    # EN stays high in power tests to isolate the fast HI/LI response.
    deck, count = re.subn(
        r"^Bmask_hi .*\n(?:.*\n){4}Cmask_li .*\n",
        f""".include leg_receiver.lib
Vrx rx3 vss 3.3
Vrxgood rxgood vss 3.3
Xrx hi li {permit} upstream logic 0 vss rx3 rxgood hi_masked li_masked en_unused pg_unused LEG_RECEIVER
* The isolated module adds up to 50 pF across the reference boundary.
Cmodule vss 0 50p
""", deck, flags=re.M,
    )
    if count != 1:
        raise ValueError("Review the receiver insertion point after the shutdown test changes")
    deck, count = re.subn(r"^Vbias bias 0 9\.926$", f"Vbias bias vss {bias_v:g}", deck, flags=re.M)
    if count != 1:
        raise ValueError("Review the driver bias insertion point after the half-bridge changes")
    deck, count = re.subn(r"^\.tran 250p (\S+) 0 250p$", rf".tran {step} \1 0 {step}", deck, flags=re.M)
    if count != 1:
        raise ValueError("Review the timestep sweep after the half-bridge changes")
    deck = deck.removesuffix(".end\n") + """.meas tran min_vdd MIN par('v(vdd)-v(vss)')
.meas tran max_vdd MAX par('v(vdd)-v(vss)')
.meas tran min_hs MIN v(hs_s)
.end
"""
    return deck


def validate_interface(m):
    on = ("armed_en", "running_hi", "running_li", "bias_restored_pg", "rearmed_hi")
    off = ("startup_hi", "startup_en", "running_li_off", "running_hi_off", "bias_open_hi",
           "bias_open_en", "bias_unpowered_hi", "bias_unpowered_pg", "bias_restored_no_rearm",
           "source_unpowered_hi", "source_unpowered_en")
    m["cmd_to_input_off_ns"] = (m["hi_fall"] - m["cmd_fall"]) * 1e9
    m["bias_loss_to_hi_off_ns"] = (m["bias_loss_hi_off"] - 7e-6) * 1e9
    m["bias_loss_to_en_off_ns"] = (m["bias_loss_en_off"] - 7e-6) * 1e9
    if not (min(m[key] for key in on) > 2.4 and max(m[key] for key in off) < 0.1
            and -0.005 <= m["all_hi_min"] <= m["all_hi_max"] <= 3.305
            and 18.5 <= m["cmd_to_input_off_ns"] <= 30
            and 0 < m["bias_loss_to_hi_off_ns"] <= 250
            and 0 < m["bias_loss_to_en_off_ns"] <= 300):
        raise ValueError(f"Receiver timing or power-off state failed: {m}")


def run(args):
    selection = json.loads(args.filter.read_text(encoding="utf-8"))
    shunt = json.loads(args.shunt.read_text(encoding="utf-8"))
    if selection["shunt_sha256"] != hashlib.sha256(args.shunt.read_bytes()).hexdigest():
        raise ValueError("The filter study and shunt extraction belong to different revisions")
    if selection["extraction_sha256"] != hashlib.sha256(args.extraction.read_bytes()).hexdigest():
        raise ValueError("The filter study uses a different board extraction")
    coupon = shunt["cases"]["nominal"]
    circuit = circuit_from(coupon, selection["selected_filter_nf"])
    board = read_extraction(args.extraction)
    models = ["leg_receiver.lib", "local_shutdown.lib", "protection.lib"]
    with TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(directory)
        for name in models:
            shutil.copyfile(ROOT / name, work / name)
        interface = run_deck(args.ngspice, work, "receiver_interface", INTERFACE)
        validate_interface(interface)
        transit = calibrate_recovery(args.ngspice, work)["transit_ns"]
        cases = {"faults": {}, "normal": {}, "corners": {}}
        jobs = []
        for leg in LEGS:
            for side in ("low", "high"):
                for key, builder in (("faults", fault_deck), ("normal", normal_deck)):
                    source = with_receiver(builder(board, transit, leg, side, circuit, fast_inputs=True))
                    name = f"{leg}_{side}_{key}"
                    jobs.append((key, name, pool.submit(run_deck, args.ngspice, work, name, source)))
        for mount, coupon in shunt["cases"].items():
            mount_circuit = circuit_from(coupon, circuit.filter_nf)
            late = replace(mount_circuit, filter_nf=circuit.filter_nf * 1.1,
                           shunt_mohm=mount_circuit.shunt_mohm * 0.99, offset_mv=-5,
                           comparator_ns=7, logic_ns=12)
            for side in ("low", "high"):
                name = f"sa_{side}_{mount}_corner"
                source = with_receiver(fault_deck(board, transit, "sa", side, late, fast_inputs=True),
                                       bias_v=12.3)
                jobs.append(("corners", name, pool.submit(run_deck, args.ngspice, work, name, source)))
        diagnostic_jobs = {}
        for name, bias, step in (("sa_high_125ps", 12, "125p"), ("sa_high_500ps", 12, "500p"),
                                 ("sa_high_9p926v", 9.926, "250p")):
            source = with_receiver(fault_deck(board, transit, "sa", "high", circuit, fast_inputs=True),
                                   bias_v=bias, step=step)
            diagnostic_jobs[name] = pool.submit(run_deck, args.ngspice, work, name, source)
        bypass = with_receiver(fault_deck(board, transit, "sa", "low", circuit, fast_inputs=True),
                               permit="upstream")
        bypass_job = pool.submit(run_deck, args.ngspice, work, "sa_receiver_bypass", bypass)
        for key, name, job in jobs:
            m = job.result()
            if key != "normal":
                classify_input_turnoff(m)
                m["passed"] = m["interrupted_with_request_high"]
            else:
                m["passed"] = passes_switching(m)
            cases[key][name] = m
            print(f"{name}: {'pass' if m['passed'] else 'fail'}", flush=True)
        control = bypass_job.result()
        diagnostics = {name: job.result() for name, job in diagnostic_jobs.items()}
        for m in diagnostics.values():
            classify_input_turnoff(m)
    result = {
        "filter_study_sha256": hashlib.sha256(args.filter.read_bytes()).hexdigest(),
        "model_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (*models, "half_bridge_test.py", "layout_switching_test.py",
                         "local_shutdown_test.py", "leg_receiver_test.py")
        },
        "filter_nf": circuit.filter_nf,
        "interface": interface,
        "tests": cases,
        "diagnostics": diagnostics,
        "bypass_control": control,
        "absolute_limits": {
            "hs_floor_v_for_pulses_under_100ns": -14,
            "mosfet_vds_ceiling_v": 60,
            "hs_violations": [name for group in cases.values() for name, m in group.items()
                              if m["min_hs"] < -14],
            "vds_violations": [name for key in ("faults", "corners") for name, m in cases[key].items()
                               if max(m["peak_vds_low"], m["peak_vds_high"]) > 60],
        },
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    if control["current_after"] <= 1 or control["en_held_min"] <= 3 or control["raw_command_after"] <= 3:
        raise ValueError("The bypass control did not sustain the test fault")
    counts = sum(not m["passed"] for group in cases.values() for m in group.values())
    stress = result["absolute_limits"]
    if counts or stress["hs_violations"] or stress["vds_violations"]:
        raise SystemExit(f"Receiver study failed: {counts} switching or cutoff cases, "
                         f"{len(stress['hs_violations'])} HS and {len(stress['vds_violations'])} VDS violations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    parser.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
