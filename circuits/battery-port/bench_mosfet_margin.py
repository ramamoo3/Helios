"""Compare the 60 V parent MOSFET with a pin-compatible 100 V candidate."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from startup_test import command_sources, compile_trace
from vendor_startup_test import check_case, write_deck
from vendor_test import PSPICE_OPTIONS, stage_vendor_models
from verify import ROOT, run_spice


CAPACITANCES_NF = (60, 100, 150)
PARTS = ("CSD18534KCS", "CSD19535KCS")


def file_from_archive(archive, stem):
    with ZipFile(archive) as source:
        matches = [name for name in source.namelist() if Path(name).name.casefold() == stem.casefold()]
        if len(matches) != 1:
            raise ValueError(f"Expected one {stem} entry in {archive.name}")
        return source.read(matches[0])


def simulate(args, scratch, part, cap, direction, waveforms, fixtures):
    sign = "discharge" if direction > 0 else "charge"
    label = f"{part} {cap} nF {sign}"
    deck = scratch / f"{part}-{cap}-{sign}.cir"
    rails = {"VBAT": 11.4, "VLINK": 25.2} if direction > 0 else {"VBAT": 12.6, "VLINK": 22.8}
    values = {**rails, "VBIAS": 9.3, "CBOOT": f"{cap}n"}
    measurements = []
    for v, leaf in (("p", "a"), ("p", "b"), ("s", "c"), ("s", "d")):
        measurements.extend((f".meas tran vds_hi_{leaf} MAX v({v},{leaf}) from=17u to=39u",
                             f".meas tran vds_lo_{leaf} MAX v({leaf}) from=17u to=39u"))
    failures = {}
    for profile in ("nominal", "alternate"):
        write_deck(deck, label, values, direction, waveforms[direction], profile,
                   fixture=fixtures[part], diagnostics=measurements)
        try:
            trace = run_spice(args.ngspice, deck, cwd=scratch, options=PSPICE_OPTIONS)
        except (RuntimeError, TimeoutExpired) as error:
            message = str(error).replace(str(scratch), "simulation")
            failures[profile] = next((line.strip() for line in message.splitlines()
                                      if "timestep too small" in line.lower()), message[-500:])
            continue
        break
    else:
        return label, {"completed": False, "solver_failures": failures}
    try:
        check_case(trace, label, None)
    except ValueError:
        passed = False
    else:
        passed = True
    return label, {"completed": True, "startup_limits_pass": passed, "solver_profile": profile,
                   "solver_failures": failures,
                   "min_bootstrap_v": trace["charged"],
                   "min_first_high_gate_v": min(trace[f"first_{leg}"] for leg in ("hpa", "hpb", "hsa", "hsb")),
                   "peak_measured_drain_source_v": max(v for key, v in trace.items() if key.startswith("vds_")),
                   "first_winding_peak_a": max(trace["first_ip"], -trace["first_in"]),
                   "measurements": trace}


def run(args):
    source_file = ROOT / "vendor-dab-startup.cir"
    original = source_file.read_text(encoding="ascii")
    if original.count("CSD18534KCS") != 2 or original.count(".include ti-mosfet.lib") != 1:
        raise ValueError("Review the MOSFET substitution points")
    candidate = original.replace(PARTS[0], PARTS[1]).replace(".include ti-mosfet.lib", ".include ti-mosfet-100v.lib")
    with TemporaryDirectory() as directory:
        scratch = Path(directory)
        extracted_driver = scratch / "original-driver.lib"
        extracted_mosfet = scratch / "original-mosfet.lib"
        extracted_driver.write_bytes(file_from_archive(args.driver, "UCC27282_Unencypted_PSpice_Model.lib"))
        extracted_mosfet.write_bytes(file_from_archive(args.baseline, "CSD18534KCS.lib"))
        stage_vendor_models(extracted_driver, extracted_mosfet, scratch)
        added = file_from_archive(args.candidate, "CSD19535KCS.lib")
        model, count = re.subn(rb"(?im)^([ \t]*\.param[ \t]+\w+)[ \t]+([^=\s].*)$", rb"\1=\2", added)
        if count != 6 or b".SUBCKT CSD19535KCS" not in model:
            raise ValueError("Expected TI SLPM100A parameter declarations")
        (scratch / "ti-mosfet-100v.lib").write_bytes(model)
        shutil.copyfile(ROOT / "protection.lib", scratch / "protection.lib")
        program = compile_trace(args.cc, scratch)
        waveforms = {d: command_sources(program, d, start_ns=17000, frames=2, amplitude=3.3,
                                        nodes=("pp", "pn", "sp_in", "sn_in")) for d in (120, -120)}
        fixtures = dict(zip(PARTS, (original, candidate)))
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(simulate, args, scratch, part, cap, d, waveforms, fixtures)
                    for part in PARTS for cap in CAPACITANCES_NF for d in (120, -120)]
            results = {}
            for job in as_completed(jobs):
                label, data = job.result()
                results[label] = data
                print(label, "pass" if data.get("startup_limits_pass") else "open", flush=True)
    sources = (args.driver, args.baseline, args.candidate, source_file, Path(__file__),
               *(ROOT / p for p in ("vendor_startup_test.py", "protection.lib", "bench-startup.h")))
    return {"scope": "9.3 V bias startup in the parent simulation without filled-copper parasitics or fault qualification",
            "input_sha256": {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources},
            "cases": dict(sorted(results.items()))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--driver", required=True, type=Path, help="TI SLUM720 ZIP file")
    parser.add_argument("--baseline", required=True, type=Path, help="TI SLPM046B ZIP file")
    parser.add_argument("--candidate", required=True, type=Path, help="TI SLPM100A ZIP file")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
