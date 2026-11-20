"""Check two-direction bench rail interruption and capacitor placement."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from verify import ROOT, run_spice


PRECHARGE = 1.65e-3
FAULT = 2.0e-3
FAULT_CLEAR = 2.25e-3
LOCAL_UF = 0.7
CASES = (
    ("forward-short", 24.0, 2200, 0.2, 200, False, "short"),
    ("reverse-short", 24.0, 2200, 0.2, 200, True, "short"),
    ("primary-slow-trip", 12.6, 470, 1.0, 400, False, "short"),
    ("secondary-slow-trip", 25.2, 2200, 1.0, 400, False, "short"),
    ("bias-loss", 24.0, 2200, 0.2, 200, False, "bias"),
    ("bulk-downstream", 24.0, 2200, 0.2, 200, False, "bulk-downstream"),
    ("failed-disconnect", 24.0, 2200, 0.2, 200, False, "bypassed"),
)


def make_deck(volts, bulk_uf, inductance_uh, delay_ns, reverse, mode, step):
    upstream, downstream = ("b", "a") if reverse else ("a", "b")
    bulk_node = downstream if mode == "bulk-downstream" else "source"
    precharge_r = 200 if mode != "bulk-downstream" else 1e9
    bulk_initial = f".ic v({downstream})={volts:g}" if mode == "bulk-downstream" else ""
    bypass = "Rbypass a b 10m" if mode == "bypassed" else ""
    pg = (f"PWL(0 3.3 {FAULT:g} 3.3 {FAULT+1e-8:g} 0 {FAULT_CLEAR:g} 0 {FAULT_CLEAR+1e-8:g} 3.3)"
          if mode == "bias" else "3.3")
    trigger = "0" if mode == "bias" else (
        f"PWL(0 0 {FAULT:g} 0 {FAULT+1e-8:g} 3.3 "
        f"{FAULT_CLEAR:g} 3.3 {FAULT_CLEAR+1e-8:g} 0)"
    )
    return f"""Helios independent DC cutoff, {mode}
.include local_shutdown.lib
.include bench_disconnect.lib
.options method=gear maxord=2 reltol=0.001
Vsource input 0 {volts:g}
Rsource input source 60m
Rbulk {bulk_node} bulk_cap 25m
Cbulk bulk_cap 0 {bulk_uf:g}u
Lfeeder source feeder {inductance_uh:g}u
Vsense feeder {upstream} 0
Bamps amps 0 V={"-" if reverse else ""}i(Vsense)
Bcurrent_mag current_mag 0 V=abs(v(amps))
Vpg pg 0 {pg}
Varm arm 0 PWL(0 0 1.50m 0 1.50001m 3.3 1.51m 3.3 1.51001m 0)
Vrun request 0 PWL(0 0 {PRECHARGE:g} 0 {PRECHARGE+1e-8:g} 3.3)
Vpre pre 0 PWL(0 3.3 1.64m 3.3 1.64001m 0)
Spre {upstream} precharge_node pre 0 AUX
Rprecharge precharge_node {downstream} {precharge_r:g}
.model AUX SW(RON=0.01 ROFF=1e9 VT=1.65 VH=0.1)
Xcut a b enable BENCH_DC_CUT
Xtrip amps pg arm request ready enable BENCH_DC_CUT_CONTROL DELAY={delay_ns:g}n
Cboard {downstream} 0 {LOCAL_UF:g}u
Vload load 0 PWL(0 0 1.75m 0 1.75001m 3.3)
Sload {downstream} load_resistor load 0 AUX
Rload load_resistor 0 12
Vfault_req fault_on 0 {trigger}
Sfault {downstream} fault_sense fault_on 0 AUX
Vfault_sense fault_sense short_path 0
Rfault short_path 0 20m
{bulk_initial}
{bypass}
Bfault_power fault_power 0 V=max(v({downstream})*i(Vfault_sense),0)
Bcut_v cut_voltage 0 V=abs(v(a,b))
.tran {step} 2.50m 1.7m {step}
.meas tran normal_v FIND v({downstream}) at=1.9m
.meas tran normal_a FIND i(Vsense) at=1.9m
.meas tran peak_a MAX v(current_mag) from=1.9999m to=2.25m
.meas tran peak_cut_voltage MAX v(cut_voltage) from=1.9999m to=2.25m
.meas tran fault_energy_j INTEG v(fault_power) from=2m to=2.25m
.meas tran early_source_a FIND v(amps) at=2.02m
.meas tran early_fault_a FIND i(Vfault_sense) at=2.02m
.meas tran early_enable FIND v(enable) at=2.02m
.meas tran late_request FIND v(request) at=2.45m
.meas tran late_enable FIND v(enable) at=2.45m
.meas tran late_source_a FIND v(amps) at=2.45m
.end
"""


def analyze(measurements, volts, mode):
    m = measurements
    checks = {
        "normal_load_energized": m["normal_v"] > 0.95*volts and 0.8 < m["normal_a"] < 3,
        "independent_trip_latched": m["late_request"] > 3 and m["early_enable"] < 0.1 and m["late_enable"] < 0.1,
        "source_cut": abs(m["early_source_a"]) < 0.02 and abs(m["late_source_a"]) < 0.02,
        "local_fault_current_cut": abs(m["early_fault_a"]) < 0.02,
        "clamp_screen_below_60_v": m["peak_cut_voltage"] < 60,
    }
    expected_failures = {
        "bulk-downstream": {"local_fault_current_cut"},
        "bypassed": {"source_cut", "local_fault_current_cut"},
    }.get(mode, set())
    observed_failures = {name for name, passed in checks.items() if not passed}
    return {"measurements": m, "checks": checks, "expected_failures": sorted(expected_failures),
            "matches_expectations": observed_failures == expected_failures}


def run(args):
    paths = (Path(__file__), ROOT / "bench_disconnect.lib", ROOT / "local_shutdown.lib")
    report = {
        "scope": "One 12 V or 24 V bench rail with an independent modeled trip and reverse-blocking series switch. "
                 "Source impedance, on-resistance, timing and clamp parameters are assumptions.",
        "inputs_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "cases": {},
    }
    with TemporaryDirectory() as directory:
        scratch = Path(directory)
        for library in paths[1:]:
            shutil.copyfile(library, scratch / library.name)
        for name, volts, bulk, inductance, delay, reverse, mode in CASES:
            results = {}
            for step in ("100n", "50n"):
                circuit = scratch / f"{name}-{step}.cir"
                circuit.write_text(make_deck(volts, bulk, inductance, delay, reverse, mode, step), encoding="ascii")
                results[step] = analyze(run_spice(args.ngspice, circuit, cwd=scratch), volts, mode)
            report["cases"][name] = {"source_voltage_v": volts, "bulk_uf": bulk, "feeder_uh": inductance,
                                     "trip_delay_ns": delay, "reverse": reverse, "mode": mode, "runs": results}
            print(name, "expected behavior" if all(r["matches_expectations"] for r in results.values()) else "open",
                  flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    if any(not run["matches_expectations"] for case in report["cases"].values() for run in case["runs"].values()):
        raise SystemExit("The independent rail fixture has unexpected results. See the report.")
