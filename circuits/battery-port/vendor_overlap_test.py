"""Measure MOSFET channel overlap during the first DAB switching cycles."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import math
from pathlib import Path
import shutil
from subprocess import TimeoutExpired
import tempfile

from startup_test import command_sources, compile_trace
from vendor_startup_test import PROFILES, ROOT, write_deck
from vendor_test import PSPICE_OPTIONS, stage_vendor_models
from verify import run_spice


# The two source inductances are shared by the gate and commutation loops.
# The feed inductance models the remaining local capacitor-to-bridge path.
DEVICE_PATH = "Xhigh bus gh mid CSD18534KCS\nXlow mid gl 0 CSD18534KCS"
LAYOUT_PATH = """Lpcb_feed bus drainh {LFEED}
Lpcb_high sourceh mid {LSHARED}
Lpcb_low sourcel 0 {LSHARED}
Xhigh drainh gh sourceh CSD18534KCS
Xlow mid gl sourcel CSD18534KCS"""
DAMPED_LAYOUT_PATH = """Lpcb_feed bus feed_h {LFEED}
Rpcb_feed feed_h drainh 8m
Lpcb_high sourceh sourceh_l {LSHARED}
Rpcb_high sourceh_l mid 5m
Lpcb_low sourcel sourcel_l {LSHARED}
Rpcb_low sourcel_l 0 5m
Xhigh drainh gh sourceh CSD18534KCS
Xlow mid gl sourcel CSD18534KCS"""

LEGS = (("pa", "p", "a"), ("pb", "p", "b"), ("sa", "s", "c"), ("sb", "s", "d"))
START = 17e-6
END = 39e-6

DISCHARGE_CORNER = {"VBAT": 11.4, "VLINK": 25.2, "VBIAS": 9.3, "CBOOT": "120n"}
CHARGE_CORNER = {"VBAT": 12.6, "VLINK": 22.8, "VBIAS": 9.3, "CBOOT": "60n"}


@dataclass(frozen=True)
class Case:
    label: str
    direction: int
    parameters: dict
    profile: str = "nominal"
    max_step: str = "1n"


CASES = (
    Case("discharge", 120, {}),
    Case("discharge-alternate", 120, {}, "alternate"),
    Case("charge", -120, {}),
    Case("discharge-corner", 120, DISCHARGE_CORNER),
    Case("charge-corner", -120, CHARGE_CORNER),
    Case("charge-corner-half-step", -120, CHARGE_CORNER, "nominal", "500p"),
    Case("charge-corner-alternate", -120, CHARGE_CORNER, "alternate"),
    Case("discharge-layout", 120, {"LFEED": "2n", "LSHARED": "1n"}),
    Case("charge-layout", -120, {"LFEED": "2n", "LSHARED": "1n"}),
    Case("discharge-layout-high", 120, {**DISCHARGE_CORNER, "LFEED": "10n", "LSHARED": "3n"}),
    Case("charge-layout-high", -120, {**CHARGE_CORNER, "LFEED": "10n", "LSHARED": "3n"}),
)


def fixture_and_vectors(fixture, layout, damped):
    if layout:
        if fixture.count(DEVICE_PATH) != 1:
            raise ValueError("Full-bridge fixture changed. Review the parasitic injection points.")
        fixture = (fixture.replace(DEVICE_PATH, DAMPED_LAYOUT_PATH if damped else LAYOUT_PATH)
                   .replace("Rghs gh mid", "Rghs gh sourceh")
                   .replace("Rgls gl 0", "Rgls gl sourcel")
                   .replace("V=v(gh,mid)", "V=v(gh,sourceh)")
                   .replace("V=v(gl)", "V=v(gl,sourcel)"))
    vectors = []
    for leg, bus, midpoint in LEGS:
        for side in ("high", "low"):
            model = f"@m.x{leg}.x{side}.m1"
            vectors.extend([f"{model}[id]", f"{model}[vds]"])
        drain = f"x{leg}.drainh" if layout else bus
        source = f"x{leg}.sourceh" if layout else midpoint
        vectors.extend([f"v({drain})", f"v({source})", f"v({midpoint})",
                        f"v(x{leg}.sourcel)" if layout else "v(0)"])
    # Ground isn't a transient vector. Use the literal zero when deriving Vds.
    return fixture, list(dict.fromkeys(vector for vector in vectors if vector != "v(0)")), vectors


def trace_samples(path, saved, vectors):
    with path.open(encoding="ascii") as trace:
        header = trace.readline().split()
        if header != ["time", *saved]:
            raise ValueError(f"Unexpected ngspice waveform columns: {header}")
        indices = [header.index(vector) if vector != "v(0)" else None for vector in vectors]
        for row in trace:
            time, *data = map(float, row.split())
            if len(data) != len(saved) or not all(math.isfinite(value) for value in (time, *data)):
                raise ValueError("Invalid row in ngspice waveform")
            yield time, [data[index - 1] if index is not None else 0.0 for index in indices]


def reduce_trace(samples):
    peak, charge, vds_peak, previous_overlap = ([0.0] * len(LEGS) for _ in range(4))
    active_high = [0.0] * len(LEGS)
    active_low = [0.0] * len(LEGS)
    previous_time = 0.0
    for time, values in samples:
        start, end = max(previous_time, START), min(time, END)
        for index in range(len(LEGS)):
            ih, vh, il, vl, drain, source, midpoint, return_pin = values[index * 8:index * 8 + 8]
            # BSIM3 reports channel current magnitude. Intrinsic Vds supplies the sign.
            overlap = max(0.0, min(ih, il)) if vh > 0 and vl > 0 else 0.0
            if START <= time <= END:
                active_high[index] = max(active_high[index], abs(ih))
                active_low[index] = max(active_low[index], abs(il))
                peak[index] = max(peak[index], overlap)
                vds_peak[index] = max(vds_peak[index], drain - source, midpoint - return_pin)
            if end > start:
                before = previous_overlap[index]
                slope = (overlap - before) / (time - previous_time)
                average = before + slope * (0.5 * (start + end) - previous_time)
                charge[index] += average * (end - start)
            previous_overlap[index] = overlap
        previous_time = time
    if previous_time < END or min(*active_high, *active_low) < 0.05:
        raise ValueError("Incomplete switching trace or inactive channel probes")
    return max(peak), max(charge), max(vds_peak), LEGS[peak.index(max(peak))][0]


def run_case(ngspice, case, scratch, source, pwm):
    directory = scratch / case.label
    directory.mkdir()
    for name in ("ti-driver.lib", "ti-mosfet.lib", "protection.lib"):
        shutil.copyfile(scratch / name, directory / name)
    fixture, saved, vectors = fixture_and_vectors(source, "LFEED" in case.parameters,
                                                  case.profile == "layout_retry")
    trace = directory / "switching.dat"
    controls = (".save " + " ".join(saved), ".control", "set wr_singlescale", "set wr_vecnames",
                "option numdgt=16", "run", f"wrdata {trace.name} " + " ".join(saved), "quit", ".endc")
    deck = directory / "switching.cir"
    write_deck(deck, case.label, case.parameters, case.direction, pwm, case.profile,
               fixture=fixture, max_step=case.max_step, diagnostics=controls)
    measurements = run_spice(ngspice, deck, cwd=directory, options=PSPICE_OPTIONS)
    peak, charge, vds, leg = reduce_trace(trace_samples(trace, saved, vectors))
    winding = max(measurements["first_ip"], -measurements["first_in"])
    print(f"{case.label}: {measurements['gate_bump']:.3f} V gate bump, "
          f"{peak:.4g} A overlap ({leg}), {charge*1e9:.4g} nC, "
          f"{vds:.3f} V peak Vds, {winding:.3f} A winding peak", flush=True)


def check_channel_probes(ngspice, scratch):
    # Force both channels on through a 1 V, 1 ohm source in this simulator-only control.
    deck = scratch / "probe-control.cir"
    deck.write_text("""Helios positive control for the BSIM3 channel probes
.include ti-mosfet.lib
Vbus feed 0 1
Rfeed feed bus 1
Vhigh gh mid 10
Vlow gl 0 10
Xhigh bus gh mid CSD18534KCS
Xlow mid gl 0 CSD18534KCS
.save @m.xhigh.m1[id] @m.xlow.m1[id] i(Vbus)
.tran 1n 10n
.control
run
meas tran control_high find @m.xhigh.m1[id] at=5n
meas tran control_low find @m.xlow.m1[id] at=5n
meas tran control_supply find i(Vbus) at=5n
quit
.endc
.end
""", encoding="ascii")
    measures = run_spice(ngspice, deck, cwd=scratch, options=PSPICE_OPTIONS)
    supply = -measures["control_supply"]
    if not (0.9 < supply < 1 and abs(measures["control_high"] - supply) < 1e-3 and
            abs(measures["control_low"] - supply) < 1e-3):
        raise ValueError(f"Channel probes disagreed with known supply current: {measures}")
    print(f"Channel probe positive control: both channels match {supply:.3f} A supply current", flush=True)


def check(args):
    source = (ROOT / "vendor-dab-startup.cir").read_text(encoding="ascii")
    cases = [case for case in CASES if not args.case or case.label in args.case]
    if args.damped_layout:
        cases = [replace(case, profile="layout_retry", max_step="500p")
                 for case in cases if "LFEED" in case.parameters]
        if not cases:
            raise SystemExit("Select at least one layout case with --damped-layout")
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        stage_vendor_models(args.driver, args.mosfet, scratch)
        shutil.copyfile(ROOT / "protection.lib", scratch / "protection.lib")
        check_channel_probes(args.ngspice, scratch)
        program = compile_trace(args.cc, scratch)
        waveforms = {direction: command_sources(program, direction, start_ns=17000, frames=2,
                                               amplitude=3.3, nodes=("pp", "pn", "sp_in", "sn_in"))
                     for direction in (120, -120)}
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            jobs = [(case, pool.submit(run_case, args.ngspice, case, scratch,
                                       source, waveforms[case.direction])) for case in cases]
            failed = []
            for case, job in jobs:
                try:
                    job.result()
                except (RuntimeError, ValueError, OSError, TimeoutExpired) as error:
                    failed.append(case.label)
                    detail = next((line for line in str(error).splitlines()
                                   if "timestep too small" in line.lower()), str(error))
                    print(f"{case.label}: INCONCLUSIVE\n{detail}", flush=True)
        if failed:
            raise SystemExit("Cases without a usable switching result: " + ", ".join(failed))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--driver", required=True, type=Path, help="TI SLUM720 LIB file")
    parser.add_argument("--mosfet", required=True, type=Path, help="TI SLPM046B LIB file")
    parser.add_argument("--case", action="append", choices=[case.label for case in CASES])
    parser.add_argument("--damped-layout", action="store_true",
                        help="Retry the selected layout cases with trace resistance and a 0.5 ns step")
    parser.add_argument("--jobs", type=int, default=1)
    check(parser.parse_args())
