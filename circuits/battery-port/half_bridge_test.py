"""Screen the secondary bridge with bootstrap copper, diode recovery and local faults."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from extract_layout import BOOTSTRAP_PORTS
from layout_switching_test import SCREENING_DRIVER, port_network, read_extraction
from verify import ROOT, run_spice


# Independent charge-based fit to the CSD18534KCS datasheet. The external diode
# has a calibrated diffusion transit time. Intrinsic LEVEL=1 diode recovery is off.
DEVICE = """.subckt CHARGE_FET d g s p_diss params: DTT=15n
Ld d di 0.05n
Lg g gr 2.1n
Rg gr gi 1.5
Ls si s 0.47n
Vchannel di dc 0
Mchannel dc gi si si CORE W=1u L=1u
.model CORE NMOS (LEVEL=1 VTO=1.9 KP=100 RD=4.9m RS=1.5m IS=1e-16)
Cgs gi si 1495p
Cgd gi di Q='5p*v(gi,di)+1.55n*tanh(v(gi,di)/2.2)'
Vbody si anode 0
Dbody anode di BODY
@body_model@
Bpower p_diss 0 V={max(0,v(di,si)*i(Vchannel))+max(0,v(si,di)*i(Vbody))}
.ends CHARGE_FET
"""


def body_model(transit_time, avalanche=False):
    breakdown = " BV=60 IBV=250u" if avalanche else ""
    return f".model BODY D (IS=5n N=1.3 RS=7m CJO=1n VJ=0.8 M=0.5 TT={transit_time}{breakdown})"


def run_deck(ngspice, work, name, source):
    path = work / f"{name}.cir"
    path.write_text(source, encoding="ascii", newline="\n")
    return run_spice(ngspice, path, cwd=work)


def calibrate_recovery(ngspice, work):
    """Fit the vendor's 40 A, 30 V, 300 A/us typical Qrr using a forced current ramp."""
    def recover(transit_ns):
        deck = f"""Helios diode recovery calibration
Vreverse clamp 0 -30
Dclamp clamp a REVERSE
.model REVERSE D(IS=1m RS=10m)
Iforce 0 a PWL(0 40 200n 40 400n -20 500n -20)
Vsense a anode 0
Dbody anode 0 BODY
{body_model(f"{transit_ns:.8g}n")}
Brecover rr 0 V=max(-i(Vsense),0)
.tran 100p 500n 0 100p
.meas tran qrr INTEG v(rr) from=333.333333n to=500n
.end
"""
        return run_deck(ngspice, work, "diode-calibration", deck)["qrr"]

    lower, upper = 0.0, 80.0
    target = 68e-9
    if not recover(lower) < target < recover(upper):
        raise ValueError("Diode recovery calibration failed to bracket the datasheet Qrr")
    for _ in range(13):
        middle = (lower + upper) / 2
        if recover(middle) < target:
            lower = middle
        else:
            upper = middle
    transit = (lower + upper) / 2
    qrr = recover(transit)
    if abs(qrr - target) > 0.5e-9:
        raise ValueError(f"Diode recovery calibration missed the typical value: {qrr:g} C")
    return {"transit_ns": transit, "qrr_c": qrr}


def bridge(extraction, supply_v, transit_ns, avalanche):
    network = port_network(extraction["legs"]["sa"]["frequencies_hz"], BOOTSTRAP_PORTS)
    device = DEVICE.replace("@body_model@", body_model("{DTT}", avalanche))
    return f"""Helios Q5/Q6 routed secondary half bridge
.options method=gear maxord=2 reltol=0.004 abstol=10n vntol=30u itl4=500
.param DTT={transit_ns:.8g}n
{device}
Vrail supply 0 {supply_v}
Rsource supply bus 60m
Lbulk bus bulk_r 15n
Rbulk bulk_r bulk_c 25m
Cbulk bulk_c 0 2200u
Llocal bus local_r 0.6n
Rlocal local_r local_c 10m
Clocal local_c 0 700n
Vbias bias 0 9.926
Rbias bias vdd 0.25
Cbias vdd vss 14.4u
{SCREENING_DRIVER}
{network}
Cboot hb_cap hs_cap 100n
Vcold cold 0 PWL(0 3.3 450n 3.3 460n 0)
Bdischarge hb_cap hs_cap I={{v(hb_cap,hs_cap)*(v(cold)/0.33+1e-10)}}
Rghi hri hro 4.7
Rglo lri lro 4.7
Rgh gh sourceh 10k
Rgl gl sourcel 10k
Rbleed1 bus mid 1meg
Rbleed2 mid 0 1meg
Xhigh drainh gh sourceh heat_h CHARGE_FET DTT={{DTT}}
Xlow mid gl sourcel heat_l CHARGE_FET DTT={{DTT}}
Bvgs_h gh_s 0 V=v(gh,sourceh)
Bvgs_l gl_s 0 V=v(gl,sourcel)
Bvds_h dh_s 0 V=v(drainh,sourceh)
Bvds_l dl_s 0 V=v(mid,sourcel)
Bhs hs_s 0 V=v(hs,vss)
Bfeed feed 0 V=abs(i(Lpcb_feed))
"""


def switching_deck(extraction, current, active, transit_ns, step, avalanche=True):
    source = bridge(extraction, 24, transit_ns, avalanche)
    pulse = "3.3u 0 3.31u 3.3 3.85u 3.3 3.86u 0 4.25u 0 4.26u 3.3 4.8u 3.3 4.81u 0"
    high = f"PWL(0 0 {pulse})" if active == "high" else "0"
    prime = "0 0 800n 0 810n 3.3 2.3u 3.3 2.31u 0"
    low = f"PWL({prime} {pulse})" if active == "low" else f"PWL({prime})"
    a, b = ("bus", "mid") if active == "low" else ("mid", "0")
    return source + f"""Ven en 0 3.3
Vhi hi 0 {high}
Vli li 0 {low}
Iload {a} {b} PWL(0 0 2.5u 0 3.1u {current} 5.1u {current} 5.2u 0)
.tran {step} 5.5u 0 {step}
.meas tran precharge_vgs MAX v(gh_s) from=800n to=2.4u
.meas tran peak_vds_high MAX v(dh_s) from=3.2u to=5.1u
.meas tran peak_vds_low MAX v(dl_s) from=3.2u to=5.1u
.meas tran min_hs MIN v(hs_s) from=3.2u to=5.1u
.meas tran off_gate MAX v({"gh_s" if active == "low" else "gl_s"}) from=3.2u to=5.1u
.meas tran peak_feed MAX v(feed) from=3.2u to=5.1u
.meas tran high_turnon_j INTEG v(heat_h) from=4.25u to=4.4u
.meas tran high_turnoff_j INTEG v(heat_h) from=4.8u to=4.95u
.meas tran low_turnon_j INTEG v(heat_l) from=4.25u to=4.4u
.meas tran low_turnoff_j INTEG v(heat_l) from=4.8u to=4.95u
.end
"""


def fault_deck(extraction, transit_ns, positive_control):
    stimulus = "PWL(0 0 3.34u 0 3.35u 7 4u 7)" if positive_control else "0"
    # A failed-closed Q6 returns through the local power loop. A bounded external
    # gate command ends this simulation event even when the winding CT is blind.
    return bridge(extraction, 24, transit_ns, avalanche=True) + f""".include protection.lib
Vpri pri 0 3.3
Vsec sec 0 3.3
Varm arm 0 PWL(0 0 350n 0 360n 3.3 600n 3.3 610n 0)
Vrun run 0 PWL(0 0 700n 0 710n 3.3)
Vct ipri 0 {stimulus}
Xprotect ipri pri sec arm run enp en vsense BENCH_PROTECT
Vli li 0 PWL(0 0 800n 0 810n 3.3 2.3u 3.3 2.31u 0)
Vhi hi 0 PWL(0 0 3.3u 0 3.31u 3.3 3.5u 3.3 3.51u 0)
Rfailed_q6 mid sourcel 20m
.tran 250p 4u 0 250p
.meas tran permit_before FIND v(en) at=3.2u
.meas tran permit_after FIND v(en) at=3.9u
.meas tran peak_feed MAX v(feed) from=3.3u to=3.9u
.meas tran current_below_1a WHEN v(feed)=1 FALL=LAST TD=3.34u
.meas tran command_fall WHEN v(hi)=1.65 FALL=1
.meas tran high_fet_energy_j INTEG v(heat_h) from=3.3u to=3.9u
.end
"""


def run(args):
    extraction = read_extraction(args.extraction)
    if tuple(extraction["ports"]) != BOOTSTRAP_PORTS:
        raise ValueError("This test needs the board extraction with bootstrap ports")
    with TemporaryDirectory() as directory:
        work = Path(directory)
        shutil.copyfile(ROOT / "protection.lib", work / "protection.lib")
        calibration = calibrate_recovery(args.ngspice, work)
        print(f"Diode calibration: {calibration['transit_ns']:.3f} ns, "
              f"{calibration['qrr_c']*1e9:.2f} nC", flush=True)
        transit = calibration["transit_ns"]
        switching = {}
        jobs = {
            f"{active}_{current:g}a": switching_deck(extraction, current, active, transit, "500p")
            for active in ("low", "high") for current in (0.75, 1.5, 2.5)
        }
        jobs["low_2.5a_half_step"] = switching_deck(extraction, 2.5, "low", transit, "250p")
        jobs["low_2.5a_zero_diffusion"] = switching_deck(extraction, 2.5, "low", 0, "500p")
        jobs["low_2.5a_no_avalanche"] = switching_deck(extraction, 2.5, "low", transit, "250p", avalanche=False)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            running = {name: pool.submit(run_deck, args.ngspice, work, name, deck) for name, deck in jobs.items()}
            for name, job in running.items():
                switching[name] = job.result()
                print(f"{name}: {max(switching[name]['peak_vds_high'], switching[name]['peak_vds_low']):.2f} V Vds",
                      flush=True)
        faults = {name: run_deck(args.ngspice, work, name, fault_deck(extraction, transit, control))
                  for name, control in (("local_q6_short", False), ("ct_positive_control", True))}
    # This is a single-device heat screen at an assumed continuous winding current.
    worst_pair_j = max(m[f"{channel}_turnon_j"] + m[f"{channel}_turnoff_j"]
                       for name, m in switching.items() if name != "low_2.5a_no_avalanche"
                       for channel in ("high", "low"))
    power_w = 50_000 * worst_pair_j + 2.5**2 * 0.020 * 0.5
    thermal = {"worst_measured_energy_pair_j": worst_pair_j, "frequency_hz": 50000,
               "assumed_on_current_a": 2.5, "assumed_hot_rds_ohm": 0.020, "duty": 0.5,
               "estimated_w_per_mosfet": power_w, "ambient_c": 40, "theta_ja_c_per_w": 62,
               "estimated_junction_c": 40 + power_w * 62}
    evidence = {
        "board_sha256": extraction["board_sha256"],
        "extraction_sha256": hashlib.sha256(args.extraction.read_bytes()).hexdigest(),
        "diode_fit": calibration,
        "switching": switching,
        "faults": faults,
        "thermal": thermal,
    }
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8", newline="\n")
    local, control = faults["local_q6_short"], faults["ct_positive_control"]
    if not (local["permit_before"] > 3 and control["permit_before"] > 3
            and local["permit_after"] > 3 and control["permit_after"] < 0.1):
        raise ValueError("The local fault or winding-current positive control did not exercise the intended path")
    print("Local short left winding-current permission asserted; winding-current stimulus latched it off.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--jobs", type=int, default=4)
    run(parser.parse_args())
