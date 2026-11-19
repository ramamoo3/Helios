"""Exercise a candidate local shunt trip with the extracted bench half bridges."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

from extract_layout import BOOTSTRAP_PORTS, LEGS
from half_bridge_test import bridge, calibrate_recovery, run_deck
from layout_switching_test import read_extraction
from verify import ROOT


@dataclass(frozen=True)
class Circuit:
    sense_nh: float = 0.5
    shunt_mohm: float = 5.0
    filter_nf: float = 1.1
    offset_mv: float = 0.0
    comparator_ns: float = 4.0
    logic_ns: float = 6.0
    force_nh: float | None = None
    force_mohm: float | None = None

    @property
    def extracted_force_path(self):
        return self.force_nh is not None and self.force_mohm is not None


CORNERS = {
    "matched": Circuit(),
    "low_transfer_l": Circuit(sense_nh=0.25),
    "high_transfer_l": Circuit(sense_nh=0.75),
    "slow_threshold": Circuit(shunt_mohm=4.95, offset_mv=-5, comparator_ns=7, logic_ns=12),
    "early_threshold": Circuit(shunt_mohm=5.05, offset_mv=5),
    "two_nh_uncompensated": Circuit(sense_nh=2),
    "two_nh_retuned": Circuit(sense_nh=2, filter_nf=4.4),
}


def sensed_bridge(extraction, transit, leg, circuit, fast_inputs=False):
    rail = 12 if leg.startswith("p") else 24
    netlist = bridge(extraction, rail, transit, avalanche=True, leg=leg)
    netlist, count = re.subn(r"^Lpcb_return r_return 0 (\S+)$",
                            r"Lpcb_return r_return shunt_force \1", netlist, flags=re.M)
    if count != 1:
        raise ValueError("Review the shunt insertion point after routing or fixture changes")
    # Bias is already present in these cases. Avoid the startup bench's
    # artificial bootstrap clamp sourcing DC current through a failed switch.
    netlist, count = re.subn(r"^Vcold [^\n]+\nBdischarge [^\n]+$", "Rbootleak hb_cap hs_cap 1meg",
                            netlist, count=1, flags=re.M)
    if count != 1:
        raise ValueError("Review the bootstrap initialization after the fixture changes")
    if fast_inputs:
        netlist = netlist.replace("v(hi,vss)", "v(hi_masked,vss)").replace("v(li,vss)", "v(li_masked,vss)")
        # The 1 kOhm pole reaches its midpoint in approximately 30 ns, the
        # maximum HI/LI-to-output falling delay in the TI datasheet test.
        for name in ("Chi_delay", "Clo_delay"):
            netlist, count = re.subn(rf"^({name} \S+ 0) 18p$", r"\1 43.28p", netlist, flags=re.M)
            if count != 1:
                raise ValueError("Review the driver input delay after the fixture changes")
    force_nh = circuit.force_nh if circuit.extracted_force_path else circuit.sense_nh
    force_mohm = circuit.force_mohm if circuit.extracted_force_path else circuit.shunt_mohm
    netlist += f"""Lshunt shunt_force shunt_r {force_nh:.8g}n
Rshunt shunt_r 0 {force_mohm:.8g}m
Bisense iabs 0 V=abs(i(Lshunt))
"""
    if circuit.extracted_force_path:
        # Port 1 carries the return current. Port 2 is an open-circuit
        # transfer voltage and need not have the force loop's R or L.
        netlist += (f"Bkelvin kelvin 0 V={{{circuit.shunt_mohm/force_mohm:.9g}*v(shunt_r)"
                    f"+({circuit.sense_nh/force_nh:.9g})*v(shunt_force,shunt_r)}}\n")
    return netlist


def shutdown_controls(circuit, switch_enabled=True, fast_inputs=False, mask_reference="vss"):
    # In the electrical fault cases the winding path is driven by a literal zero.
    # PEER uses short RC links as a stand-in for the default-low isolator and routes.
    sense_node = "kelvin" if circuit.extracted_force_path else "shunt_force"
    disable_at_en = switch_enabled and not fast_inputs
    controls = f""".include protection.lib
.include local_shutdown.lib
Vlogic logic 0 3.3
Vpg pg 0 PWL(0 0 400n 0 410n 3.3)
Varm arm 0 PWL(0 0 500n 0 510n 3.3 600n 3.3 610n 0)
Vrun run 0 PWL(0 0 700n 0 710n 3.3)
Vwinding winding 0 0
Xwinding winding pg pg arm run upstream_peer upstream winding_sense BENCH_PROTECT
Xsense {sense_node} logic ok_a LEG_CURRENT_OK VOS={circuit.offset_mv:g}m TCOMP={circuit.comparator_ns:g}n FILTER={circuit.filter_nf:g}n
Xlocal ok_a logic pg arm run upstream peer_ready ready en_candidate BRIDGE_LOCAL_SHUTDOWN TLOGIC={circuit.logic_ns:g}n
Riso_out ready remote_peer 1k
Ciso_out remote_peer 0 18p
Xpeer logic logic pg arm run upstream_peer remote_peer ready_peer en_peer BRIDGE_LOCAL_SHUTDOWN
Riso_in ready_peer peer_ready 1k
Ciso_in peer_ready 0 18p
Edriver en {"vss" if fast_inputs else "0"} {"en_candidate" if disable_at_en else "upstream"} 0 1
"""
    if fast_inputs:
        permit = "en_candidate" if switch_enabled else "upstream"
        controls += f"""Bmask_hi hi_gate {mask_reference} V={{3.3*(v(hi)>1.65 && v({permit})>1.65)}}
Bmask_li li_gate {mask_reference} V={{3.3*(v(li)>1.65 && v({permit})>1.65)}}
Rmask_hi hi_gate hi_masked 1k
Cmask_hi hi_masked {mask_reference} 5.92p
Rmask_li li_gate li_masked 1k
Cmask_li li_masked {mask_reference} 5.92p
"""
    return controls


def fault_deck(extraction, transit, leg, failed, circuit, switch_enabled=True, *, fast_inputs=False,
               mask_reference="vss"):
    netlist = sensed_bridge(extraction, transit, leg, circuit, fast_inputs)
    netlist += shutdown_controls(circuit, switch_enabled, fast_inputs, mask_reference)
    if failed == "low":
        failed_nodes = "mid sourcel"
        driven = "hi"
        commands = """Vli li 0 PWL(0 0 800n 0 810n 3.3 2.3u 3.3 2.31u 0)
Vhi hi 0 PWL(0 0 3.3u 0 3.31u 3.3 3.55u 3.3 3.56u 0)
"""
        start, window_end, command_sample = "3.3u", "3.9u", "3.42u"
        stress = "heat_h"
    else:
        failed_nodes = "drainh sourceh"
        driven = "li"
        commands = """Vhi hi 0 0
Vli li 0 PWL(0 0 800n 0 810n 3.3 1.2u 3.3 1.21u 0)
"""
        start, window_end, command_sample = "800n", "1.3u", "920n"
        stress = "heat_l"
    fast_probe = ""
    if fast_inputs:
        # Leave the external PWM asserted throughout the observation window
        # so it cannot be the cause of a passing fault clearance.
        commands = (commands.replace("3.55u 3.3 3.56u 0", "3.94u 3.3 3.95u 0") if failed == "low"
                    else commands.replace("1.2u 3.3 1.21u 0", "1.94u 3.3 1.95u 0"))
        netlist += f"Binput_relative input_relative 0 V=v({driven}_masked,vss)\n"
        netlist += "Ben_relative en_relative 0 V=v(en,vss)\n"
        fast_probe = f""".meas tran driver_input_fall WHEN v(input_relative)=0.9 FALL=LAST TD={start}
.meas tran masked_permit_after FIND v(en_candidate) at={window_end}
.meas tran en_held_min MIN v(en_relative) from={start} to={window_end}
.meas tran raw_command_after FIND v({driven}) at={window_end}
.meas tran driver_input_min MIN v(input_relative) from={start} to={window_end}
.meas tran driver_input_max MAX v(input_relative) from={start} to={window_end}
.meas tran driver_vss_min MIN v(vss) from={start} to={window_end}
.meas tran driver_vss_max MAX v(vss) from={start} to={window_end}
"""
    return netlist + commands + f"""Rfailed {failed_nodes} 20m
.tran 250p 4u 0 250p
.meas tran peak_shunt MAX v(iabs) from={start} to={window_end}
.meas tran current_rise_1a WHEN v(iabs)=1 RISE=1 TD={start}
.meas tran current_fall_1a WHEN v(iabs)=1 FALL=LAST TD={start}
.meas tran current_after FIND v(iabs) at={window_end}
.meas tran comparator_fall WHEN v(ok_a)=1.65 FALL=1 TD={start}
.meas tran permit_fall WHEN v(en)=1.65 FALL=1 TD={start}
.meas tran peer_fall WHEN v(en_peer)=1.65 FALL=1 TD={start}
.meas tran command_fall WHEN v({driven})=1.65 FALL=LAST TD={start}
.meas tran gate_permit_at_command FIND v(en) at={command_sample}
.meas tran command_asserted FIND v({driven}) at={command_sample}
.meas tran winding_peak MAX v(winding) from={start} to={window_end}
.meas tran peer_after FIND v(en_peer) at={window_end}
.meas tran permit_after FIND v(en) at={window_end}
.meas tran device_energy_j INTEG v({stress}) from={start} to={window_end}
.meas tran peak_vds_high MAX v(dh_s) from={start} to={window_end}
.meas tran peak_vds_low MAX v(dl_s) from={start} to={window_end}
.meas tran comparator_input_min MIN v(xsense.sense) from={start} to={window_end}
.meas tran comparator_input_max MAX v(xsense.sense) from={start} to={window_end}
{fast_probe}.end
"""


def normal_deck(extraction, transit, leg, active, circuit, *, fast_inputs=False):
    netlist = sensed_bridge(extraction, transit, leg, circuit, fast_inputs)
    netlist += shutdown_controls(circuit, fast_inputs=fast_inputs)
    permit = "en_candidate" if fast_inputs else "en"
    pulse = "3.3u 0 3.31u 3.3 3.85u 3.3 3.86u 0 4.25u 0 4.26u 3.3 4.8u 3.3 4.81u 0"
    high = f"PWL(0 0 {pulse})" if active == "high" else "0"
    prime = "0 0 800n 0 810n 3.3 2.3u 3.3 2.31u 0"
    low = f"PWL({prime} {pulse})" if active == "low" else f"PWL({prime})"
    a, b = ("bus", "mid") if active == "low" else ("mid", "0")
    gate = "gl_s" if active == "low" else "gh_s"
    pulse_probe = (f".meas tran first_gate FIND v({gate}) at=3.65u\n"
                   f".meas tran second_gate FIND v({gate}) at=4.6u\n") if fast_inputs else ""
    return netlist + f"""Vhi hi 0 {high}
Vli li 0 {low}
Iload {a} {b} PWL(0 0 2.5u 0 3.1u 2.5 5.1u 2.5 5.2u 0)
.tran 250p 5.5u 0 250p
.meas tran permit_min MIN v({permit}) from=780n to=5.4u
.meas tran peak_shunt MAX v(iabs) from=780n to=5.4u
.meas tran comparator_min MIN v(xsense.sense) from=780n to=5.4u
.meas tran comparator_max MAX v(xsense.sense) from=780n to=5.4u
{pulse_probe}.end
"""


INTERLOCK = """Helios local shutdown and re-arm
.include local_shutdown.lib
Vok ok 0 PWL(0 3.3 790n 3.3 800n 0 850n 0 860n 3.3)
Vpg pg 0 PWL(0 0 150n 0 160n 3.3 1700n 3.3 1710n 0 1750n 0 1760n 3.3)
Varm arm 0 PWL(0 0 250n 0 260n 3.3 300n 3.3 310n 0 900n 0 910n 3.3 950n 3.3 960n 0
+ 1300n 0 1310n 3.3 1350n 3.3 1360n 0 2100n 0 2110n 3.3 2150n 3.3 2160n 0)
Vrun run 0 PWL(0 0 500n 0 510n 3.3 1050n 3.3 1060n 0 1100n 0 1110n 3.3
+ 1250n 3.3 1260n 0 1400n 0 1410n 3.3 2000n 3.3 2010n 0 2250n 0 2260n 3.3)
Vpass pass 0 3.3
Vpeer peer 0 PWL(0 3.3 2430n 3.3 2440n 0 2470n 0 2480n 3.3)
Xshutdown ok pass pg arm run pass peer ready en BRIDGE_LOCAL_SHUTDOWN
.tran 250p 2.7u 0 250p
.meas tran startup_blocked FIND v(en) at=190n
.meas tran armed_run FIND v(en) at=650n
.meas tran held_run_blocked FIND v(en) at=880n
.meas tran arm_while_run_blocked FIND v(en) at=980n
.meas tran run_cycle_blocked FIND v(en) at=1180n
.meas tran fresh_arm_enables FIND v(en) at=1500n
.meas tran bias_recovery_blocked FIND v(en) at=1900n
.meas tran after_bias_fresh_arm FIND v(en) at=2300n
.meas tran peer_loss_recovery_blocked FIND v(en) at=2600n
.end
"""


def run(args):
    extraction = read_extraction(args.extraction)
    if tuple(extraction["ports"]) != BOOTSTRAP_PORTS:
        raise ValueError("This test needs the board extraction with bootstrap ports")
    with TemporaryDirectory() as directory:
        work = Path(directory)
        for include in ("protection.lib", "local_shutdown.lib"):
            shutil.copyfile(ROOT / include, work / include)
        calibration = calibrate_recovery(args.ngspice, work)
        transit = calibration["transit_ns"]
        interlock = run_deck(args.ngspice, work, "interlock", INTERLOCK)
        for name, value in interlock.items():
            enables = name in ("armed_run", "fresh_arm_enables", "after_bias_fresh_arm")
            state = value > 3 if enables else value < 0.1
            if not state:
                raise ValueError(f"Local interlock state failed: {name} = {value:g} V")
        faults = {}
        switching = {}
        jobs = {}
        for leg in LEGS:
            for side in ("low", "high"):
                name = f"{leg}_failed_{side}"
                jobs[name] = (faults, fault_deck(extraction, transit, leg, side, CORNERS["matched"]))
        jobs["sa_failed_low_bypassed"] = (
            faults, fault_deck(extraction, transit, "sa", "low", CORNERS["matched"], False))
        for name, circuit in CORNERS.items():
            if name != "matched":
                jobs[f"sa_failed_low_{name}"] = (faults, fault_deck(extraction, transit, "sa", "low", circuit))
            for active in ("low", "high"):
                jobs[f"sa_normal_{active}_{name}"] = (
                    switching, normal_deck(extraction, transit, "sa", active, circuit))
        for active in ("low", "high"):
            jobs[f"pa_normal_{active}_matched"] = (
                switching, normal_deck(extraction, transit, "pa", active, CORNERS["matched"]))
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = [(name, section, pool.submit(run_deck, args.ngspice, work, name, deck))
                       for name, (section, deck) in jobs.items()]
            for name, section, job in pending:
                section[name] = job.result()
                print(name, f"{section[name]['peak_shunt']:.2f} A peak", flush=True)
    for m in faults.values():
        classify_fault(m)
    for m in switching.values():
        m["stayed_enabled"] = m["permit_min"] > 3
    evidence = {
        "board_sha256": extraction["board_sha256"],
        "extraction_sha256": hashlib.sha256(args.extraction.read_bytes()).hexdigest(),
        "shutdown_model_sha256": hashlib.sha256((ROOT / "local_shutdown.lib").read_bytes()).hexdigest(),
        "diode_fit": calibration,
        "corner_settings": {name: vars(circuit) for name, circuit in CORNERS.items()},
        "interlock": interlock,
        "faults": faults,
        "normal": switching,
    }
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8", newline="\n")
    nominal_faults = [faults[f"{leg}_failed_{side}"] for leg in LEGS for side in ("low", "high")]
    if any(not m["interrupted_with_request_high"] for m in nominal_faults):
        raise ValueError("At least one nominal local fault remained energized")
    nominal_normal = [m for name, m in switching.items() if name.endswith("_matched")]
    if any(not m["stayed_enabled"] for m in nominal_normal):
        raise ValueError("Nominal protection tripped during normal switching")
    if faults["sa_failed_low_bypassed"]["interrupted_with_request_high"]:
        raise ValueError("The bypass control should leave its local gate command enabled")


def classify_fault(m):
    if "current_rise_1a" in m and "current_fall_1a" in m and m["current_after"] < 1:
        m["clearing_ns"] = (m["current_fall_1a"] - m["current_rise_1a"]) * 1e9
    m["interrupted_with_request_high"] = (
        m["command_asserted"] > 3 and m["gate_permit_at_command"] < 0.1 and m["permit_after"] < 0.1
        and m["peer_after"] < 0.1 and m["winding_peak"] == 0 and "clearing_ns" in m
        and m["current_fall_1a"] < m["command_fall"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    run(parser.parse_args())
