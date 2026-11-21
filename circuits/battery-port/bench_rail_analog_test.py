"""Run the Helios bench precharge, cutoff-bias and failed-cutoff simulations."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from verify import ROOT, run_spice
from vendor_test import PSPICE_OPTIONS


RAILS = {"primary": (10.8, 12.6, 470), "secondary": (21.6, 25.2, 2200)}
FUSE_URL = ("https://www.littelfuse.com/assetdocs/littelfuse-datasheet-297-mini32v"
            "?assetguid=42c9dd21-a88e-4328-8e67-2f832444faf1")


def firmware_timing():
    source = (ROOT / "firmware/stm32g474.c").read_text(encoding="utf-8")
    return {name: int(re.search(rf"\b{name}\s*=\s*(\d+)", source).group(1))
            for name in ("DC_REQUEST_US", "DC_RELEASE_SETTLE_US")}


def precharge_deck(volts, added_ua, cap_uf, total_ohms, timer_us, request_us, release_us, step):
    turn_on = 510
    turn_off = 500 + min(timer_us, request_us) + 1
    arm = 500 + request_us + release_us

    def scale(top_ohms, high):
        direction = 1 if high else -1
        bottom = 10_000 * (1 + 0.001 * direction)
        top = top_ohms * (1 - 0.001 * direction)
        return bottom / (top + bottom) / (10_000 / (top_ohms + 10_000))

    low = f"{scale(392_000, False):.10f}*v(br)-{scale(422_000, True):.10f}*v(lo)"
    high = f"{scale(365_000, False):.10f}*v(hi)-{scale(392_000, True):.10f}*v(br)"
    return f"""Helios switched rail precharge and post-pulse voltage hold
.options method=gear reltol=0.0005
Vbulk bulk 0 {volts}
Vdrive drive 0 PWL(0 0 {turn_on-1}u 0 {turn_on}u 3.3 {turn_off-1}u 3.3 {turn_off}u 0)
.model PRE SW(Ron=0.03 Roff=1e12 Vt=1.65 Vh=0.05)
Spre bulk rtop drive 0 PRE
Vpre rtop r1 0
Rpre1 r1 r2 {total_ohms/2}
Rpre2 r2 bridge {total_ohms/2}
Cbridge bridge 0 {cap_uf}u IC=0
* Schematic divider plus an external off-state current sensitivity.
Bload bridge 0 I={{{added_ua}u*min(max(v(bridge)/0.2,0),1)}}
Rbr bridge br 392k
Rbr_bot br 0 10k
Rbulk_lo bulk lo 422k
Rbulk_lo_bot lo 0 10k
Rbulk_hi bulk hi 365k
Rbulk_hi_bot hi 0 10k
Cbr br 0 100p
Clo lo 0 100p
Chi hi 0 100p
* Margin includes independent 0.1% divider corners and 10 mV sensing error.
Bmargin mrg 0 V={{min({low},{high})-10m}}
Brpower rp 0 V={{i(Vpre)*i(Vpre)*{total_ohms/2}}}
.tran {step} {arm+100}u 0 {step} uic
.meas tran arm_v FIND v(bridge) AT={arm}u
.meas tran pulse_end_v FIND v(bridge) AT={turn_off-2}u
.meas tran arm_margin_v FIND v(mrg) AT={arm}u
.meas tran peak_pre_a MAX i(Vpre) FROM=500u TO={turn_off}u
.meas tran resistor_peak_w MAX v(rp) FROM=500u TO={turn_off}u
.meas tran resistor_energy_j INTEG v(rp) FROM=500u TO={turn_off}u
.end
"""


def cold_deck(pump_ua, prebiased, request_us, release_us, step):
    end = 42_000 + request_us
    arm = end + release_us
    return f"""Helios LTC7001 bootstrap cold-start screen
.options method=gear reltol=0.0005
* Source-relative voltages. 1 uF per driver as drawn. This bootstrap
* charging current is a sensitivity, not a guaranteed current at cold TS.
Bpump 0 bst I={{{pump_ua}u*min(max((12-v(bst))/0.1,0),1)}}
Cbst bst 0 1u IC=0
Rbst_leak bst 0 100meg
Vrequest request 0 PWL(0 0 42m 0 42.001m 3.3 {end}u 3.3 {end+1}u 0)
Varm arm 0 PWL(0 0 {arm}u 0 {arm+1}u 3.3)
Vmatch match 0 {int(prebiased)*3.3}
Bavailable available 0 V={{3.3*(v(bst)>3.1)}}
Bpre_gated pre 0 V={{min(v(request),v(available))}}
* Represents the voltage-match and latch terms in CUT_READY.
Blogical ready 0 V={{min(v(match),v(arm))}}
Bactual cutoff 0 V={{min(v(ready),v(available))}}
.tran {step} 900m 0 {step} uic
.meas tran bst_at_request_v FIND v(bst) AT=42m
.meas tran bst_at_arm_v FIND v(bst) AT={arm+100}u
.meas tran precharge_permit_v MAX v(pre) FROM=42m TO={end+5}u
.meas tran logical_ready_v FIND v(ready) AT={arm+100}u
.meas tran gate_permit_v FIND v(cutoff) AT={arm+100}u
.meas tran bst_uvlo_s WHEN v(bst)=3.1 RISE=1
.meas tran bst_full_s WHEN v(bst)=11 RISE=1
.end
"""


def brownout_deck(rail, drop, attack_us, detect_us, retained_sink, step):
    fault = 1000
    recover = 1900
    drive_dip = f"PWL(0 9.93 {fault}u 9.93 {fault+attack_us}u 0 {recover}u 0 {recover+10}u 9.93)"
    logic_dip = f"PWL(0 3.3 {fault}u 3.3 {fault+attack_us}u 0 {recover}u 0 {recover+10}u 3.3)"
    driver = """
* RC delay on bad bias models TPS3808/PG response. A separate
* 12 ms RC threshold models the minimum published open-CT hold.
.subckt BROWN_BIAS DRIVE LOGIC PG params: FALL=20u
Bbad bad 0 V={1*(v(DRIVE)<8.93 || v(LOGIC)<3.07)}
Rdet bad stop 1k
Cdet stop 0 {FALL/(1k*0.69314718)}
Von one 0 1
Rrecovery one timer 17.312Meg
Ctimer timer 0 1n
Sreset timer 0 stop 0 RESET
.model RESET SW(Ron=4 Roff=1e13 Vt=0.5 Vh=0.01)
Bpg PG 0 V={3.3*(v(stop)<0.5 && v(timer)>0.5 && v(LOGIC)>1.65)}
.ends BROWN_BIAS
* Warm floating driver with a 4-ohm sink, a pair of gate loads, and
* a selectable loss of the active sink when VCC collapses below 5.8 V.
.subckt BROWN_GATE VCC CMD G1 G2 params: RETAIN=1
Vfloat hold 0 11
Bup up 0 V={3.3*(v(CMD)>1.65 && v(VCC)>6.4)}
Bdn dn 0 V={3.3*(v(up)<1.65 && (RETAIN || v(VCC)>5.8))}
Sup hold tgup up 0 UP
Sdn gates 0 dn 0 DOWN
.model UP SW(Ron=7 Roff=1e10 Vt=1.65 Vh=0.05)
.model DOWN SW(Ron=4 Roff=1e10 Vt=1.65 Vh=0.05)
Rup tgup gates 100
Rg1 gates G1 4.7
Rg2 gates G2 4.7
Cgate1 G1 0 4.8n
Cgate2 G2 0 4.8n
Rgs1 G1 0 4.7Meg
Rgs2 G2 0 4.7Meg
.ends BROWN_GATE
"""
    values = {"pdrive": "9.93", "sdrive": "9.93", "plogic": "3.3", "slogic": "3.3"}
    values[rail + drop] = drive_dip if drop == "drive" else logic_dip
    supplies = "\n".join(f"V{key} {key} 0 {value}" for key, value in values.items())
    return f"""Helios warm brownout, two cutoff gate loads
.include local_shutdown.lib
.options method=gear maxord=2 reltol=0.001
{driver}
{supplies}
Vtrue yes 0 3.3
Xp pdrive plogic pok BROWN_BIAS FALL={detect_us}u
Xs sdrive slogic sok BROWN_BIAS FALL={detect_us}u
* DC operating point starts with regulated logic and charged floating supplies.
Varm arm 0 PWL(0 0 300u 0 300.01u 3.3 302u 3.3 302.01u 0)
Vrun run 0 PWL(0 0 550u 0 550.01u 3.3)
* The earlier latch subcircuit is used for the steady-RUN trip and recovery
* screen with both rails initially healthy. No new ARM edge is applied.
Xlp yes yes pok arm run yes peer_p pkeep pen BRIDGE_LOCAL_SHUTDOWN
Xls yes yes sok arm run yes peer_s skeep sen BRIDGE_LOCAL_SHUTDOWN
Rps pkeep peer_s 1k
Cps peer_s 0 433p
Rsp skeep peer_p 1k
Csp peer_p 0 433p
Xgp pdrive pen pg1 pg2 BROWN_GATE RETAIN={retained_sink}
Xgs sdrive sen sg1 sg2 BROWN_GATE RETAIN={retained_sink}
Bhighest highest 0 V={{max(max(v(pg1),v(pg2)),max(v(sg1),v(sg2)))}}
Blowest lowest 0 V={{min(min(v(pg1),v(pg2)),min(v(sg1),v(sg2)))}}
Bpwm pwm 0 V={{min(v(pen),v(sen))}}
.tran {step} 16m 0 {step}
.meas tran normal_min_vgs MIN v(lowest) FROM=0.8m TO=0.99m
.meas tran pwm_off_s WHEN v(pwm)=1.65 FALL=1 TD=1m
.meas tran post_fault_gate_v FIND v(highest) AT=1.5m
.meas tran recovered_pg_v FIND v({rail}ok) AT=15m
.meas tran recovered_gate_v MAX v(highest) FROM=15m TO=16m
.meas tran recovered_pwm_v MAX v(pwm) FROM=15m TO=16m
.end
"""


def fuse_deck(volts, bulk_uf, limit, placement, transition_us, tail_limit, step):
    fault = 500
    current = (f"PWL(0 {limit} {fault+transition_us}u {limit} {fault+transition_us+1}u {tail_limit})"
               if transition_us else str(limit))
    upstream = "17.75m" if placement == "upstream" else "1u"
    branch = "17.75m" if placement == "after-bulk" else "1u"
    return f"""Helios failed-short cutoff, capacitor and source fault energy
.options method=gear reltol=0.001
Vsource supply 0 {volts}
Vlimit limit 0 {current}
Bsource supply feed I={{min(max(v(supply,feed)/60m,0),v(limit))}}
Vs feed fuse_in 0
Rfuse_in fuse_in bulk {upstream}
Rbleed bulk 0 10meg
Rcesr bulk reservoir 25m
Cbulk reservoir 0 {bulk_uf}u IC={volts}
Rbranch bulk cutoff {branch}
* Shunt plus shorted cutoff and feeder resistance. Copper/inductance are fixtures.
Rfailed cutoff line 15m
Lfeed line bus 0.2u
Vfault fault 0 PWL(0 0 {fault-1}u 0 {fault}u 3.3)
Bshort bus fb I={{v(bus,fb)*(1e-10+500*(1+tanh((v(fault)-1.65)/0.08)))}}
Vbranch fb load 0
Rfault load 0 20m
Bsrc_a2 src_a2 0 V={{i(Vs)*i(Vs)}}
Bfault_a2 fault_a2 0 V={{i(Vbranch)*i(Vbranch)}}
Bfault_w fault_w 0 V={{i(Vbranch)*i(Vbranch)*20m}}
.tran {step} 2.6m 0 {step} uic
.meas tran pre_fault_cap_v FIND v(reservoir) AT=400u
.meas tran peak_source_a MAX i(Vs) FROM=500u TO=2500u
.meas tran peak_fault_a MAX i(Vbranch) FROM=500u TO=2500u
.meas tran tail_source_a FIND i(Vs) AT=2400u
.meas tran source_i2t_a2s INTEG v(src_a2) FROM=500u TO=2500u
.meas tran branch_i2t_a2s INTEG v(fault_a2) FROM=500u TO=2500u
.meas tran fault_energy_j INTEG v(fault_w) FROM=500u TO=2500u
.end
"""


def vendor_pair(executable, scratch, model):
    # Adapt whitespace-only PSpice assignments using the same syntax as the coupon replays.
    original = model.read_text(encoding="ascii")
    adjusted = re.sub(r"^(\s*\.param\s+\w+)[ \t]+(?=[^= \t\r\n])", r"\1=", original, flags=re.M | re.I)
    (scratch / "csd19531q5a.lib").write_text(adjusted, encoding="ascii")
    results = {"model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(), "cases": {}}
    path = scratch / "vendor-cutoff.cir"
    for temperature in (25, 100):
        for gate in (0, 4, 11):
            path.write_text(f"""CSD19531Q5A pair static gate-retention check
.include csd19531q5a.lib
.temp {temperature}
Vin in 0 24
Vgs g source {gate}
Xup in g source CSD19531Q5A
Xdown out g source CSD19531Q5A
Rload out 0 10
.tran 1u 10u
.meas tran load_v FIND v(out) AT=5u
.end
""", encoding="ascii")
            measured = run_spice(executable, path, cwd=scratch, options=PSPICE_OPTIONS)
            if not (measured["load_v"] < 0.01 if gate == 0 else measured["load_v"] > 20):
                raise ValueError(f"Vendor pair output failed its DC check: {temperature} C, {gate} V {measured}")
            results["cases"][f"{temperature}c-{gate}v"] = measured
    return results


def run(executable, scratch, mosfet_model=None):
    firmware = firmware_timing()
    inputs = (Path(__file__).name, "firmware/stm32g474.c", "battery-port-rail-protection.kicad_sch",
              "battery-port-rail-interlocks.kicad_sch", "battery-port-protected-io.kicad_sch",
              "battery-port-bias.kicad_sch", "local_shutdown.lib")
    results = {
        "scope": "Datasheet-based SPICE sensitivity models for the bench rails. Load, timing capacitor, "
                 "bootstrap charge, active sink retention and source fault current are model inputs.",
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs},
        "firmware_timing_us": firmware,
        "reference_fuse": {"datasheet": FUSE_URL, "rating_a": 5, "voltage_vdc": 32, "typical_melt_i2t_a2s": 37,
                           "opening_time_s_at_multiple": {"1.1": [360000, None], "1.35": [0.75, 600],
                                                          "2": [0.15, 5], "6": [0.03, 0.1]}},
        "precharge": {}, "cold_start": {}, "brownout": {}, "fuse": {},
    }

    def record(section, name, deck, parameters, steps):
        path = scratch / f"{section}-{name}.cir"
        runs = {}
        for step in steps:
            path.write_text(deck(*parameters, step), encoding="ascii")
            runs[step] = run_spice(executable, path, cwd=ROOT)
        results[section][name] = {"inputs": parameters, "steps": runs}
        return list(runs.values())

    for rail, (minimum, maximum, bulk) in RAILS.items():
        for schedule, request, release in (
            ("firmware", firmware["DC_REQUEST_US"], firmware["DC_RELEASE_SETTLE_US"]),
            ("original-long-coast", 10000, 2000),
        ):
            for load in (0, 100, 500, 1000, 2000):
                for effective in (1, 2.2):
                    for guard in (3200, 5100, 6800):
                        name = f"{rail}-{schedule}-{load}ua-{effective}uf-{guard}us"
                        runs = record("precharge", name, precharge_deck,
                                      (minimum, load, effective, 210, guard, request, release), ("4u", "2u"))
                        for measured in runs:
                            measured["voltage_match"] = measured["arm_margin_v"] > 0
                        if (load == 0 and not all(run["voltage_match"] for run in runs)) or (
                                schedule == "firmware" and load <= 1000 and
                                not all(run["voltage_match"] for run in runs)):
                            raise ValueError(f"Unexpected no-load or short-coast outcome: {name} {runs}")
                        if (rail == "primary" and schedule == "original-long-coast" and load == 100 and
                                any(run["voltage_match"] for run in runs)):
                            raise ValueError(f"Original timing control should miss the window: {name}")
                        if abs(runs[0]["arm_margin_v"] - runs[1]["arm_margin_v"]) > 0.0005:
                            raise ValueError(f"Voltage margin is timestep sensitive: {name} {runs}")
        for name, load, cap, guard, resistor in (("short-guard", 0, 2.2, 1000, 210),
                                                ("shorted-bus-load", 200000, 1, 6800, 190)):
            runs = record("precharge", f"{rail}-{name}", precharge_deck,
                          (maximum, load, cap, resistor, guard, firmware["DC_REQUEST_US"],
                           firmware["DC_RELEASE_SETTLE_US"]), ("4u", "2u"))
            if any(run["arm_margin_v"] >= 0 for run in runs):
                raise ValueError(f"Invalid bus should block ARM: {rail} {name}")
        print(f"{rail}: loaded precharge cases compared with the original firmware timing", flush=True)
        for current, placement, transition, tail in ((3, "upstream", 0, 3), (5.5, "upstream", 0, 5.5),
                                                     (10, "upstream", 0, 10), (30, "upstream", 0, 30),
                                                     (10, "after-bulk", 0, 10), (10, "upstream", 100, 0),
                                                     (10, "upstream", 100, 3)):
            name = f"{rail}-{current}a-{placement}-tail{tail}a-at{transition}us"
            runs = record("fuse", name, fuse_deck, (maximum, bulk, current, placement, transition, tail),
                          ("500n", "250n"))
            if any(abs(run["tail_source_a"] - tail) > 0.01 or
                   abs(run["pre_fault_cap_v"] - maximum) > 0.02 for run in runs):
                raise ValueError(f"Failed-cutoff source-current regression: {name}")
            if abs(runs[0]["peak_fault_a"] - runs[1]["peak_fault_a"]) > 2:
                raise ValueError(f"Failed-cutoff current peak is timestep sensitive: {name}")

    for current in (15, 30):
        for prebiased in (False, True):
            name = f"{current}ua-" + ("prebiased" if prebiased else "empty")
            runs = record("cold_start", name, cold_deck,
                          (current, prebiased, firmware["DC_REQUEST_US"], firmware["DC_RELEASE_SETTLE_US"]),
                          ("40u", "20u"))
            if any(run["precharge_permit_v"] >= 0.1 or run["gate_permit_v"] >= 0.1 or
                   (run["logical_ready_v"] > 3) != prebiased for run in runs):
                raise ValueError(f"Unexpected cold-start control result: {name}")

    for rail, drop, edge, delay, sink in (("p", "drive", 1, 20, 1), ("s", "logic", 1, 20, 1),
                                         ("s", "logic", 80, 100, 1), ("p", "drive", 1, 20, 0)):
        name = f"{rail}-{drop}-{edge}us-det{delay}us-sink{sink}"
        runs = record("brownout", name, brownout_deck, (rail, drop, edge, delay, sink), ("500n", "250n"))
        for measured in runs:
            if not (measured["normal_min_vgs"] > 9 and measured["pwm_off_s"] < 0.0012 and
                    (measured["post_fault_gate_v"] < 1.8) == bool(sink) and
                    measured["recovered_pg_v"] > 3 and measured["recovered_gate_v"] < 1.8 and
                    measured["recovered_pwm_v"] < 0.1):
                raise ValueError(f"Unexpected warm-brownout outcome: {name} {runs}")
    if mosfet_model:
        results["vendor_pair"] = vendor_pair(executable, scratch, mosfet_model)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--mosfet-model", type=Path, help="optional TI CSD19531Q5A.lib from SLPM077C")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as directory:
        report = run(args.ngspice, Path(directory), args.mosfet_model)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    for section in ("precharge", "cold_start", "brownout", "fuse"):
        print(f"{section}: {len(report[section])} cases at two maximum steps")
