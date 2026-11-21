"""Check cutoff VGS feedback, passive gate discharge and backup interruption."""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from bench_rail_analog_test import fuse_deck
from verify import ROOT, run_spice


def gate_thresholds():
    limiting = []
    for common in (-4, 0, 12.6, 25.2, 60):
        for logic, offset, corners in product((3.135, 3.465), (-0.010, 0.010),
                                              product((0.999, 1.001), repeat=5)):
            gate_top, gate_bottom, source, logic_feed, ground = (
                value * corner for value, corner in zip((402e3, 10e3, 402e3, 165e3, 10.6e3), corners, strict=True)
            )
            reference = (common / source + logic / logic_feed) / (1/source + 1/logic_feed + 1/ground)
            limiting.append((reference + offset) * (1 + gate_top/gate_bottom) - common)
    if min(limiting) < 6.5 or max(limiting) > 10:
        raise ValueError(f"Unexpected VGS window {min(limiting):.2f}–{max(limiting):.2f} V")
    return {"min_v": min(limiting), "max_v": max(limiting)}


def sense_deck(common, logic, gate_1, gate_2, step):
    return f"""Helios divided physical gate feedback
Vsource source 0 {common}
Vgate1 gate1 source {gate_1}
Vgate2 gate2 source {gate_2}
Vlogic logic 0 {logic}
R851 gate1 g1 402k
R852 g1 0 10k
R853 gate2 g2 402k
R854 g2 0 10k
R855 source threshold 402k
R856 logic threshold 165k
R857 threshold 0 10.6k
B1 gate1_margin 0 V={{v(g1,threshold)}}
B2 gate2_margin 0 V={{v(g2,threshold)}}
.tran {step} 5u
.meas tran g1_margin_v FIND v(gate1_margin) AT=4u
.meas tran g2_margin_v FIND v(gate2_margin) AT=4u
.end
"""


def discharge_deck(cap_nf, active_sink, step):
    return f"""Helios split gate driver with independent Rgs discharge
.options method=gear reltol=0.0005
Vbias bias 0 12.2
Ven request 0 PWL(0 3.3 10u 3.3 10.01u 0)
Bsink sink 0 V={{{active_sink}*(3.3-v(request))}}
.model U SW(Ron=12 Roff=1e12 Vt=1.65 Vh=0.05)
.model D SW(Ron=4 Roff=1e12 Vt=1.65 Vh=0.05)
Sup bias rising request 0 U
Rcharge rising gates 100
Sdown gates 0 sink 0 D
Rgate1 gates g1 4.7
Rgate2 gates g2 4.7
Rgs1 g1 0 2222
Rgs2 g2 0 2222
Cg1 g1 0 {cap_nf}n
Cg2 g2 0 {cap_nf}n
* Doubled gate load and 1% high resistor are screening assumptions.
Bhighest high 0 V={{max(v(g1),v(g2))}}
.tran {step} 60u 0 {step}
.meas tran before_vgs FIND v(high) AT=9u
.meas tran below_1p8_s WHEN v(high)=1.8 FALL=1 TD=10u
.meas tran after_vgs FIND v(high) AT=50u
.end
"""


def backup_deck(delay_us, placement, step):
    """Use the earlier 25.2 V capacitor-fed fault fixture with an independent command."""
    deck = fuse_deck(25.2, 2200, 3, "upstream", 0, 3, step)
    opens = 500 + delay_us
    pre = "Rfuse_in fuse_in bulk 17.75m"
    post = "Rbranch bulk cutoff 1u"
    contact = (("fuse_in", "bulk", pre) if placement == "ahead-of-bulk"
               else ("bulk", "cutoff", post))
    a, b, existing = contact
    assert deck.count(existing) == 1
    independent = f"""Vbackup backup 0 PWL(0 3.3 {opens}u 3.3 {opens+1}u 0)
Bbackup {a} {b} I={{v({a},{b})*(1e-10+50*(1+tanh((v(backup)-1.65)/0.08)))}}
Bclamp {a} {b} I={{(max(v({a},{b})-33,0)+min(v({a},{b})+33,0))/0.23}}
Bbackup_v backup_v 0 V={{abs(v({a},{b}))}}
Rfeed_stability feed 0 1meg
"""
    deck = deck.replace(existing, independent)
    # A grounded voltage compliance shunt keeps the source model well
    # conditioned when the independent switch disconnects its load.
    deck = deck.replace("Vsource supply 0 25.2", "Vsource supply 0 25.02")
    deck = deck.replace("Vlimit limit 0 3\nBsource supply feed I={min(max(v(supply,feed)/60m,0),v(limit))}",
                        "Ifeed 0 feed 3\nBcompliance feed supply I={"
                        "(v(feed,supply)+sqrt(v(feed,supply)*v(feed,supply)+1e-6))/0.12}")
    deck = deck.replace("2.6m", "4.1m").replace("2500u", "4000u").replace("2400u", "3950u")
    return deck.replace(".end\n", f""".meas tran current_before_backup_a FIND i(Vbranch) AT={opens-1}u
.meas tran residual_fault_a FIND i(Vbranch) AT=3950u
.meas tran peak_backup_v MAX v(backup_v) FROM={opens}u TO=4000u
.end
""")


def run(executable, scratch):
    inputs = (Path(__file__).name, "bench_rail_analog_test.py", "battery-port-rail-gate-feedback.kicad_sch")
    results = {"scope": "Bench gate feedback and discharge models with an ideal backup interrupter placement study. "
                        "The backup actuation times are stimuli and are not a component rating.",
               "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs},
               "thresholds": gate_thresholds(), "sense": {}, "discharge": {}, "backup": {}}

    def measure(group, name, make_deck, parameters, steps):
        runs = {}
        file = scratch / f"{group}-{name}.cir"
        for step in steps:
            file.write_text(make_deck(*parameters, step), encoding="ascii")
            runs[step] = run_spice(executable, file, cwd=scratch)
        results[group][name] = {"inputs": parameters, "runs": runs}
        return runs.values()

    for common, logic, gate_pair in product((-4, 0, 25.2, 60), (3.135, 3.465), ((11, 11), (0, 11), (11, 0), (6, 6))):
        name = f"cm{common}-logic{logic}-{gate_pair[0]}v-{gate_pair[1]}v"
        runs = measure("sense", name, sense_deck, (common, logic, *gate_pair), ("100n", "50n"))
        for run in runs:
            for gate, granted in zip(gate_pair, (run["g1_margin_v"] > 0, run["g2_margin_v"] > 0), strict=True):
                if granted != (gate == 11):
                    raise ValueError(f"{name}: incorrect gate comparison {run}")

    for capacitance, sink in product((4.8, 6.0), (0, 1)):
        name = f"{capacitance}nf-sink{sink}"
        runs = measure("discharge", name, discharge_deck, (capacitance, sink), ("40n", "20n"))
        for run in runs:
            elapsed_us = (run["below_1p8_s"] - 10e-6) * 1e6
            if not (10 < run["before_vgs"] < 12.2 and elapsed_us < (1 if sink else 30) and run["after_vgs"] < 0.7):
                raise ValueError(f"{name}: gate discharge outside screen {run}")

    for delay, location in product((20, 200, 2000), ("ahead-of-bulk", "after-bulk")):
        name = f"{location}-{delay}us"
        runs = measure("backup", name, backup_deck, (delay, location), ("500n", "250n"))
        for run in runs:
            if not (run["pre_fault_cap_v"] > 25 and run["peak_source_a"] > 2.9 and
                    abs(run["residual_fault_a"]) < 0.020):
                raise ValueError(f"{name}: failed backup current screen {run}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as scratch:
        report = run(args.ngspice, Path(scratch))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{sum(len(report[group]) for group in ('sense', 'discharge', 'backup'))} cases repeated at two timesteps")
