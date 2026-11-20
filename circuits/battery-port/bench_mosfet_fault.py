"""Compare TO-220 switches in the routed secondary-A protection fixture."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from bench_mosfet_margin import PARTS, file_from_archive
from half_bridge_test import DEVICE
from local_shutdown_test import CORNERS, fault_deck, normal_deck
from vendor_test import PSPICE_OPTIONS
from verify import ROOT, run_spice


FETS = ("CSD18534KCS.lib", "CSD19535KCS.lib")
CORNERS_TO_TEST = ((25, 9.926, 100, "matched"), (100, 9.3, 60, "slow_threshold"))
RETRY_OPTIONS = {
    "gear-with-shunts": "method=gear maxord=2 reltol=0.01 abstol=50n vntol=100u itl4=500 rshunt=1e12",
    "trapezoidal": "method=trap maxord=2 reltol=0.007 abstol=20n vntol=50u itl4=500",
}
DIAGNOSTICS = {
    "bootstrap_min_v": ("MIN", "v(boot_pin)"),
    "gate_high_peak_v": ("MAX", "v(gh_s)"),
    "gate_low_peak_v": ("MAX", "v(gl_s)"),
    "gate_high_min_v": ("MIN", "v(gh_s)"),
    "gate_low_min_v": ("MIN", "v(gl_s)"),
    "drain_high_peak_v": ("MAX", "v(dh_s)"),
    "drain_low_peak_v": ("MAX", "v(dl_s)"),
    "high_terminal_absorbed_j": ("INTEG", "v(heat_h)"),
    "low_terminal_absorbed_j": ("INTEG", "v(heat_l)"),
}


def fixture(extraction, part, side, short, corner, step):
    temperature, bias, bootstrap_nf, protection = corner
    deck = (fault_deck if short else normal_deck)(
        extraction, 0, "sa", side, CORNERS[protection], fast_inputs=True
    )
    device = DEVICE.replace("@body_model@", re.search(r"(?m)^\.model BODY .*", deck)[0])
    if deck.count(device) != 1:
        raise ValueError("Review the TO-220 fixture device substitution")
    deck = deck.replace(device, '.include ti-fet.lib\n.temp ' + str(temperature))
    for switch, drain, gate, source, power in (
        ("high", "drainh", "gh", "sourceh", "heat_h"),
        ("low", "mid", "gl", "sourcel", "heat_l"),
    ):
        before = f"X{switch} {drain} {gate} {source} {power} CHARGE_FET DTT={{DTT}}"
        after = (f"Vsense_{switch} {drain} {drain}_device 0\n"
                 f"X{switch} {drain}_device {gate} {source} {part}\n"
                 f"Bpower_{switch} {power} 0 V={{max(0,v({drain},{source})*i(Vsense_{switch}))}}")
        if deck.count(before) != 1:
            raise ValueError("Review the terminal-current probe insertion point")
        deck = deck.replace(before, after)
    deck = deck.replace("Vbias bias 0 9.926", f"Vbias bias 0 {bias:g}")
    deck = deck.replace("Cboot hb_cap hs_cap 100n", f"Cboot hb_cap hs_cap {bootstrap_nf}n")
    deck = re.sub(r"(?m)^\.tran 250p (\S+) 0 250p$", rf".tran {step} \1 0 {step}", deck)
    start, stop = (("800n", "1.3u") if side == "high" else ("3.3u", "3.9u")) if short else ("3.3u", "5.1u")
    # Preserve complete wave-window stress evidence even if a trip never crosses 1 A.
    deck = re.sub(r"(?m)^\.meas tran \S+ (?:WHEN|TRIG) .*\n", "", deck)
    diagnostics = "".join(f".meas tran {name} {mode} {node} from={start} to={stop}\n"
                          for name, (mode, node) in DIAGNOSTICS.items())
    return deck.removesuffix(".end\n") + "Bbootstrap boot_pin 0 V=v(hb_cap,hs_cap)\n" + diagnostics + ".end\n"


def run_case(args, work, extraction, part, side, short, corner, step):
    label = f"{part} {corner[0]}C {'short' if short else 'inductive'} {side} {step}"
    deck = work / (label.replace(" ", "-") + ".cir")
    source = fixture(extraction, part, side, short, corner, step)
    failures = {}
    for profile, options in (("nominal", None), *RETRY_OPTIONS.items()):
        trial = source if options is None else re.sub(r"(?m)^\.options .*$", f".options {options}", source, count=1)
        deck.write_text(trial, encoding="ascii")
        try:
            measurements = run_spice(args.ngspice, deck, cwd=work, options=PSPICE_OPTIONS)
            missing = [name for name in DIAGNOSTICS if not math.isfinite(measurements.get(name, math.nan))]
            if missing:
                raise RuntimeError(f"Missing stress measurements: {', '.join(missing)}")
        except (RuntimeError, TimeoutExpired) as error:
            detail = str(error).replace(str(work), "simulation")
            failures[profile] = next((line.strip() for line in detail.splitlines()
                                      if "timestep too small" in line.lower()), detail[-500:])
            continue
        break
    else:
        return label, {"completed": False, "solver_failures": failures}
    return label, {"completed": True, "temperature_c": corner[0], "bias_v": corner[1],
                   "bootstrap_nf": corner[2], "solver_profile": profile, "solver_failures": failures,
                   "measurements": measurements}


def run(args):
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    if extraction["board_sha256"] != hashlib.sha256(args.board.read_bytes()).hexdigest():
        raise ValueError("The reference extraction and board fingerprints differ")
    archives = (args.baseline, args.candidate)
    with TemporaryDirectory() as path, ThreadPoolExecutor(max_workers=4) as pool:
        jobs = []
        for part, filename, archive in zip(PARTS, FETS, archives, strict=True):
            work = Path(path) / part
            work.mkdir()
            model = file_from_archive(archive, filename)
            model, count = re.subn(rb"(?im)^([ \t]*\.param[ \t]+\w+)[ \t]+([^=\s].*)$", rb"\1=\2", model)
            if count != 6 or f".SUBCKT {part}".encode() not in model:
                raise ValueError(f"Check the parameter declarations in {archive.name}")
            (work / "ti-fet.lib").write_bytes(model)
            for include in ("protection.lib", "local_shutdown.lib"):
                shutil.copyfile(ROOT / include, work / include)
            for corner in CORNERS_TO_TEST:
                for side in ("low", "high"):
                    for short in (False, True):
                        for step in ("250p", "125p"):
                            jobs.append(pool.submit(run_case, args, work, extraction, part, side, short, corner, step))
        cases = {}
        for job in jobs:
            label, case = job.result()
            cases[label] = case
            print(label, "completed" if case["completed"] else "inconclusive", flush=True)
    sources = (args.extraction, args.board, *archives, Path(__file__), *(ROOT / name for name in (
        "bench_mosfet_margin.py", "half_bridge_test.py", "local_shutdown_test.py", "layout_switching_test.py",
        "protection.lib", "local_shutdown.lib", "vendor_test.py", "verify.py",
    )))
    return {
        "scope": "Secondary-A trace-only copper with TI power devices and the continuous screening driver",
        "qualifications": "Fault shunt, driver and source impedances are fixture assumptions. Positive terminal energy includes reactive energy.",
        "inputs_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--extraction", required=True, type=Path)
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
