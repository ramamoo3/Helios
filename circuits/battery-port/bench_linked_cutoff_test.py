"""Exercise both independent cutoff latches around the bench DAB model."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from verify import ROOT, run_spice


CASES = (
    ("discharge-primary-short", 0.10, "p", ""),
    ("discharge-secondary-short", 0.10, "s", ""),
    ("charge-primary-short", -0.10, "p", ""),
    ("charge-secondary-short", -0.10, "s", ""),
    ("secondary-bias-loss", 0.10, "", "bias-loss"),
    ("peer-link-loss", 0.10, "", "peer-loss"),
    ("pwm-inhibit-bypassed", 0.10, "p", "pwm-stuck"),
    ("secondary-cutoff-bypassed", 0.10, "s", "bypassed"),
    ("secondary-precharge-stuck-on", 0.10, "s", "precharge-stuck"),
    ("secondary-both-precharge-switches-stuck", 0.10, "s", "both-precharge-stuck"),
)

ACTIVE_FAULT = "PWL(0 0 2m 0 2.00001m 3.3 2.25m 3.3 2.25001m 0)"
LOSS_OF_PERMIT = "PWL(0 3.3 2m 3.3 2.00001m 0 2.25m 0 2.25001m 3.3)"


def make_rail(rail, volts, bulk, peer, control, bridge_cap_nf):
    precharge = "3.3" if rail == "s" and control in ("precharge-stuck", "both-precharge-stuck") else "v(pre)"
    guard = "3.3" if rail == "s" and control == "both-precharge-stuck" else "v(pre_guard)"
    pg = LOSS_OF_PERMIT if rail == "s" and control == "bias-loss" else "3.3"
    bypass = "Rbypassed source_s bus_s 10m" if rail == "s" and control == "bypassed" else ""
    return f"""Vsource_{rail} supply_{rail} 0 {volts}
Rsource_{rail} supply_{rail} bulk_{rail} 60m
Rbulk_{rail} bulk_{rail} cap_{rail} 25m
Cbulk_{rail} cap_{rail} 0 {bulk}u
Lfeeder_{rail} bulk_{rail} feed_{rail} 0.2u
Vsense_{rail} feed_{rail} source_{rail} 0
Bamps_{rail} amps_{rail} 0 V=i(Vsense_{rail})
Bmag_{rail} mag_{rail} 0 V=abs(v(amps_{rail}))
Xcut_{rail} source_{rail} bus_{rail} enable_{rail} BENCH_DC_CUT
Bdiff_{rail} diff_{rail} 0 V=abs(v(source_{rail},bus_{rail}))
Vpg_{rail} pg_{rail} 0 {pg}
Xtrip_{rail} amps_{rail} pg_{rail} arm request {peer} ready_{rail} enable_{rail} BENCH_DC_CUT_LINKED
Bpre_{rail} pre_{rail} 0 V={precharge}
Bpre_guard_{rail} pre_guard_{rail} 0 V={guard}
Spre_{rail} source_{rail} pre_guard_in_{rail} pre_{rail} 0 AUX
Spre_guard_{rail} pre_guard_in_{rail} precharge_{rail} pre_guard_{rail} 0 AUX
Rprecharge_{rail} precharge_{rail} bus_{rail} 200
Cceramic_{rail} bus_{rail} 0 {bridge_cap_nf}n
Rbleed_{rail} bus_{rail} 0 100k
{bypass}
.meas tran before_{rail}_a AVG i(Vsense_{rail}) from=1.9m to=2m
.meas tran before_{rail}_v AVG v(bus_{rail}) from=1.9m to=2m
.meas tran peak_{rail}_a MAX v(mag_{rail}) from=2m to=2.02m
.meas tran early_{rail}_a MAX v(mag_{rail}) from=2.02m to=2.15m
.meas tran peak_{rail}_cut_v MAX v(diff_{rail}) from=2m to=2.25m
.meas tran early_{rail}_en MAX v(enable_{rail}) from=2.02m to=2.15m
.meas tran late_{rail}_en FIND v(enable_{rail}) at=2.45m
.meas tran late_{rail}_a FIND v(mag_{rail}) at=2.45m
"""


def deck(shift, fault_rail, control, step, bridge_cap_nf=700):
    link = LOSS_OF_PERMIT if control == "peer-loss" else "3.3"
    fault_switch = ACTIVE_FAULT if fault_rail else "0"
    permit = "3.3" if control == "pwm-stuck" else "min(v(enable_p),v(enable_s))"
    return f"""Helios linked DC cutoff with both DAB supplies
.include local_shutdown.lib
.include bench_disconnect.lib
.include dab.lib
.options method=gear maxord=2 reltol=0.001
.model AUX SW(RON=0.01 ROFF=1e9 VT=1.65 VH=0.1)
Varm arm 0 PWL(0 0 1.50m 0 1.50001m 3.3 1.51m 3.3 1.51001m 0)
Vrequest request 0 PWL(0 0 1.65m 0 1.65001m 3.3)
Vpre pre 0 PWL(0 3.3 1.64m 3.3 1.64001m 0)
Vpre_timeout pre_window 0 PWL(0 3.3 1.645m 3.3 1.64501m 0)
Bpre_guard pre_guard 0 V={{3.3*(v(pre_window)>1.65 && v(request)<1.65)}}
Vlink link 0 {link}
Bpeer_p tx_p 0 V=v(ready_s)*v(link)/3.3
Rpeer_p tx_p peer_p 1k
Cpeer_p peer_p 0 100p
Rpeer_s ready_p peer_s 1k
Cpeer_s peer_s 0 100p
{make_rail("p", 12, 470, "peer_p", control, bridge_cap_nf)}
{make_rail("s", 24, 2200, "peer_s", control, bridge_cap_nf)}
* Raw commands remain available after the fault. Both hardware permits
* are required at the bridge input, independently of the PWM request.
Bpwm_guard pwm_raw 0 V={permit}
Rguard pwm_raw pwm_permit 1k
Cguard pwm_permit 0 25p
Xdab bus_p 0 bus_s 0 pwm_permit DAB_PERMITTED D={shift:g} NSEC=2 LK=10u LM=1m RP=20m RHI=9.5m
+ START=1.8m STOP=2.16m
Bactual_pwm actual_pwm 0 V=max(max(v(xdab.cpa),v(xdab.cpb)),max(v(xdab.csa),v(xdab.csb)))
Vfault fault 0 {fault_switch}
Sfault bus_{fault_rail or "s"} fault_probe fault 0 AUX
Vfault_probe fault_probe fault_r 0
Rfault fault_r 0 20m
Bfault_mag fault_mag 0 V=abs(i(Vfault_probe))
Bfault_power fault_w 0 V=max(v(bus_{fault_rail or "s"})*i(Vfault_probe),0)
.tran {step} 2.50m 1.7m {step}
.meas tran held_request FIND v(request) at=2.45m
.meas tran early_pwm_permit MAX v(pwm_permit) from=2.02m to=2.15m
.meas tran early_pwm_drive MAX v(actual_pwm) from=2.02m to=2.15m
.meas tran early_fault_a MAX v(fault_mag) from=2.02m to=2.15m
.meas tran fault_energy_j INTEG v(fault_w) from=2m to=2.25m
.end
"""


def analyze(m, phase_shift, control):
    direction = 1 if phase_shift > 0 else -1
    checks = {
        "normal_transfer": direction*m["before_p_a"] > 0.3 and direction*m["before_s_a"] < -0.15
        and 11 < m["before_p_v"] < 13 and 23 < m["before_s_v"] < 25,
        "both_cutoffs_latched_open": m["held_request"] > 3
        and max(m["early_p_en"], m["early_s_en"], m["late_p_en"], m["late_s_en"]) < 0.1,
        "pwm_inhibited": max(m["early_pwm_permit"], m["early_pwm_drive"]) < 0.1,
        "primary_source_cut": max(m["early_p_a"], m["late_p_a"]) < 0.02,
        "secondary_source_cut": max(m["early_s_a"], m["late_s_a"]) < 0.02,
        "fault_current_cut": m["early_fault_a"] < 0.02,
        "stack_voltage_below_screen": max(m["peak_p_cut_v"], m["peak_s_cut_v"]) < 60,
    }
    expected_failures = {
        "bypassed": {"secondary_source_cut", "fault_current_cut"},
        "both-precharge-stuck": {"secondary_source_cut", "fault_current_cut"},
        "pwm-stuck": {"pwm_inhibited", "fault_current_cut"},
    }.get(control, set())
    return {"measurements": m, "checks": checks, "expected_failures": sorted(expected_failures),
            "matches_expectations": {name for name, passed in checks.items() if not passed} == expected_failures}


def run(args):
    includes = ("bench_disconnect.lib", "local_shutdown.lib", "dab.lib", "dab-control.inc", "dab-power.inc")
    sources = (Path(__file__), ROOT / "verify.py", *(ROOT / name for name in includes))
    report = {
        "scope": "Two independently powered bench rails with an ideal DAB transformer and switching stages. "
        "Logic gates and returns share a simulator reference. Physical isolation, timing and device limits are outside this fixture.",
        "bridge_capacitance_nf_per_rail": args.bridge_cap_nf,
        "inputs_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "cases": {},
    }
    with TemporaryDirectory() as folder:
        work = Path(folder)
        for name in includes:
            shutil.copyfile(ROOT / name, work / name)
        for name, shift, fault_rail, control in CASES:
            runs = {}
            for step in ("100n", "50n"):
                path = work / f"{name}-{step}.cir"
                path.write_text(deck(shift, fault_rail, control, step, args.bridge_cap_nf), encoding="ascii")
                runs[step] = analyze(run_spice(args.ngspice, path, cwd=work), shift, control)
            report["cases"][name] = {"phase_shift": shift, "fault_rail": fault_rail,
                                     "control": control, "runs": runs}
            print(name, "expected behavior" if all(r["matches_expectations"] for r in runs.values()) else "open",
                  flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bridge-cap-nf", type=int, default=700, help="total ceramic capacitance downstream of each cutoff")
    args = parser.parse_args()
    if args.bridge_cap_nf <= 0:
        parser.error("Choose a positive bridge capacitance in nF")
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    if any(not run["matches_expectations"] for case in report["cases"].values() for run in case["runs"].values()):
        raise SystemExit("Unexpected linked cutoff behavior. See the result file.")
