"""Check all four bootstrap supplies and the first PWM pulses with TI models."""
import argparse
from pathlib import Path
import shutil
import tempfile

from startup_test import command_sources, compile_trace
from vendor_test import PSPICE_OPTIONS, stage_vendor_models
from verify import run_spice


ROOT = Path(__file__).resolve().parent
PROFILES = {
    "nominal": "reltol=0.008 abstol=100n vntol=30u gmin=1e-9 rshunt=1e10",
    "alternate": "reltol=0.02 abstol=100n vntol=100u gmin=1e-9",
    "layout_retry": "reltol=0.02 abstol=100n vntol=100u gmin=1e-9 trtol=3",
}


def write_deck(path, case, values, direction, pwm, profile, fault=None, *,
               fixture=None, max_step="1n", diagnostics=()):
    if fixture is None:
        fixture = (ROOT / "vendor-dab-startup.cir").read_text(encoding="ascii")
    solver = f".options method=gear maxord=2 {PROFILES[profile]} itl4=500"
    text = "\n".join(solver if line.startswith(".options ") else line
                     for line in fixture.splitlines())
    lines = [".param " + " ".join(f"{key}={value}" for key, value in values.items())] if values else []
    lines.extend(["Vcold cold 0 PWL(0 3.3 8.5u 3.3 8.6u 0)",
             "Varm arm 0 PWL(0 0 4u 0 4.01u 3.3 7u 3.3 7.01u 0)",
             "Vrun run 0 PWL(0 0 8u 0 8.01u 3.3)",
             "Vpc pre 0 PWL(0 0 9u 0 9.01u 3.3 16u 3.3 16.01u 0)"])
    for domain in ("pri_ok", "sec_ok"):
        stimulus = "PWL(0 3.3 12u 3.3 12.01u 0 14u 0 14.01u 3.3)" if domain == fault else "3.3"
        lines.append(f"V{domain} {domain} 0 {stimulus}")
    lines.extend(pwm)
    lines.extend([".save v(bootmin) v(bootmax) v(highmax) v(lowmin) v(lowmax) v(ip)"
                  " v(hpa) v(hpb) v(hsa) v(hsb) v(both) v(enp) v(ens)",
                  f".tran 1n 40u 0 {max_step}",
                  ".meas tran cold_boot MAX v(bootmax) from=8.2u to=8.4u",
                  ".meas tran prime_high MAX v(highmax) from=9u to=16u",
                  ".meas tran prime_low MIN v(lowmin) from=9.8u to=11.9u"])
    if fault:
        for signal in ("enp", "ens", "highmax", "lowmax"):
            lines.append(f".meas tran after_{signal} MAX v({signal}) from=12.5u to=39u")
    else:
        lines.extend([".meas tran charged MIN v(bootmin) from=15u to=16u",
                      ".meas tran blank_high MAX v(highmax) from=16.6u to=16.9u",
                      ".meas tran blank_low MAX v(lowmax) from=16.6u to=16.9u",
                      ".meas tran prime_ip MAX v(ip) from=9u to=16u",
                      ".meas tran prime_in MIN v(ip) from=9u to=16u",
                      ".meas tran first_ip MAX v(ip) from=17u to=39u",
                      ".meas tran first_in MIN v(ip) from=17u to=39u",
                      ".meas tran on_p MIN v(enp) from=8.9u to=39u",
                      ".meas tran on_s MIN v(ens) from=8.9u to=39u",
                      ".meas tran gate_bump MAX v(both) from=17u to=39u"])
        primary, secondary = (0, 0.6) if direction > 0 else (0.6, 0)
        for leg, start in [("hpa", 18 + primary), ("hpb", 28 + primary),
                           ("hsa", 18 + secondary), ("hsb", 28 + secondary)]:
            lines.append(f".meas tran first_{leg} MIN v({leg}) from={start}u to={start+8}u")
    path.write_text(text + f"\n* Case {case}\n" + "\n".join([*lines, *diagnostics, ".end", ""]),
                    encoding="ascii")


def check_case(results, case, fault):
    if not (results["cold_boot"] < 0.05 and results["prime_high"] < 0.1 and
            results["prime_low"] > 8.5):
        raise ValueError(f"Bootstrap did not start from the expected gate states in {case}: {results}")
    if fault:
        if max(results[f"after_{signal}"] for signal in ("enp", "ens", "highmax", "lowmax")) >= 0.1:
            raise ValueError(f"Precharge fault did not latch both bridges off in {case}: {results}")
        print(f"{case}: all eight gates stayed off after bias returned", flush=True)
        return
    first_gate = min(results[f"first_{leg}"] for leg in ("hpa", "hpb", "hsa", "hsb"))
    prime_current = max(results["prime_ip"], -results["prime_in"])
    first_current = max(results["first_ip"], -results["first_in"])
    if not (results["charged"] > 8.5 and first_gate > 8 and prime_current < 0.25 and
            first_current < 3.5 and min(results["on_p"], results["on_s"]) > 3.2 and
            max(results["blank_low"], results["blank_high"]) < 0.1):
        raise ValueError(f"Bootstrap sequence outside acceptance limits in {case}: {results}")
    print(f"{case}: {results['charged']:.3f} V min bootstrap, {first_gate:.3f} V min first gate, "
          f"{first_current:.3f} A winding peak, {results['gate_bump']:.3f} V gate bump", flush=True)


def check(ngspice, cc, driver, mosfet):
    cases = [
        ("nominal discharge", {}, 120, "nominal", None),
        ("nominal discharge, alternate tolerance", {}, 120, "alternate", None),
        ("nominal charge", {}, -120, "nominal", None),
        ("discharge with large effective capacitor",
         {"VBAT": 11.4, "VLINK": 25.2, "VBIAS": 9.3, "CBOOT": "120n"}, 120, "nominal", None),
        ("charge with derated capacitor",
         {"VBAT": 12.6, "VLINK": 22.8, "VBIAS": 9.3, "CBOOT": "60n"}, -120, "nominal", None),
        ("primary bias loss during precharge", {}, 120, "nominal", "pri_ok"),
        ("secondary bias loss during precharge", {}, -120, "nominal", "sec_ok"),
    ]
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        stage_vendor_models(driver, mosfet, scratch)
        shutil.copyfile(ROOT / "protection.lib", scratch / "protection.lib")
        program = compile_trace(cc, scratch)
        waveforms = {d: command_sources(program, d, start_ns=17000, frames=2, amplitude=3.3,
                                        nodes=("pp", "pn", "sp_in", "sn_in")) for d in (120, -120)}
        deck = scratch / "dab-startup.cir"
        for label, values, direction, profile, fault in cases:
            write_deck(deck, label, values, direction, waveforms[direction], profile, fault)
            check_case(run_spice(ngspice, deck, cwd=scratch, options=PSPICE_OPTIONS), label, fault)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--driver", required=True, type=Path, help="TI SLUM720 LIB file")
    parser.add_argument("--mosfet", required=True, type=Path, help="TI SLPM046B LIB file")
    args = parser.parse_args()
    check(args.ngspice, args.cc, args.driver, args.mosfet)
