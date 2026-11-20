"""Extract and replay the routed DFN clamp and floating driver on the bench leg."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zipfile import ZipFile

import isolated_bypass_test as bypass
import isolated_clamp_test as clamp
import isolated_layout_extract as copper
import isolated_layout_replay as replay
from verify import ROOT, check_bench_via_clearance, children, first, read_schematic


BOARD = ROOT / "battery-port-secondary-isolated-dfn.kicad_pcb"
REPORT = "bench-secondary-isolated-dfn"
EXTRACTION = ROOT / f"{REPORT}-impedance.json"
DFN_JUNCTION = (34.60, 35.55, "B.Cu")
PATHS = {
    **bypass.PATHS,
    "tvs_cathode": (("Q6", "3"), ("D1", "k_junction")),
    "tvs_low_k1": (("D1", "k_junction"), ("D1", "k1")),
    "tvs_low_k2": (("D1", "k_junction"), ("D1", "k2")),
}
NODES = {
    **bypass.NODES,
    "tvs_cathode": ("mid", "tvs_k_junction"),
    "tvs_low_k1": ("tvs_k_junction", "tvs_pad_k"),
    "tvs_low_k2": ("tvs_k_junction", "tvs_pad_k"),
}
LOOPS = {
    **bypass.LOOPS,
    "tvs_external": {
        **bypass.LOOPS["tvs_external"], "tvs_low_k1": 0.5, "tvs_low_k2": 0.5,
    },
}
PIN_BYPASS_NH = (0.2, 0.3, 0.4, 0.6)


def extract(args):
    check_bench_via_clearance(args.board)
    board = read_schematic(args.board)
    layout = copper.Layout(board, args.via_wall_mm)
    dfn = next(part for part in children(board, "footprint")
               if any(prop[1:3] == ["Reference", "D1"] for prop in children(part, "property")))
    x, y, rotation = map(float, first(dfn, "at")[1:])
    if first(dfn, "layer")[1] != "B.Cu" or rotation != 0:
        raise ValueError("Review the rear DFN element position and orientation")
    lands = [pad for pad in children(dfn, "pad") if pad[1] == "1"]
    if len(lands) != 2:
        raise ValueError("Model both DFN cathode lands")
    net = layout.pads["D1", "1"][1]
    layout.pads["D1", "k_junction"] = (DFN_JUNCTION, net, 0)
    for number, pad in enumerate(lands, 1):
        px, py = map(float, first(pad, "at")[1:3])
        if first(pad, "net")[1] != net:
            raise ValueError("The DFN cathode lands must be on the same net")
        point = (round(x + px, 6), round(y + py, 6), "B.Cu")
        layout.pads["D1", f"k{number}"] = (point, net, 0)
    ports = tuple(PATHS)
    routes = copper.routed_ports(layout, board, PATHS)
    matrices = copper.solve(args, layout, ports, routes)
    matrix = matrices["1e+07"]["inductance_h"]
    loops = {name: 1e9 * copper.projected(matrix, [terms.get(port, 0) for port in ports])
             for name, terms in LOOPS.items()}
    for name, pins in copper.SNUBBERS.items():
        if name == "low_snubber_copper":
            pins = (*pins[:2], (pins[2][0], ("Q6", "source_finger")))
        fit = copper.solve(args, layout, ("drain", "between", "source"), [layout.route(*pair) for pair in pins])
        loops[name] = 1e9 * copper.projected(fit["1e+07"]["inductance_h"], (1, 1, 1))
    data = {
        "board_sha256": replay.digest(args.board),
        "board_thickness_mm": float(first(first(board, "general"), "thickness")[1]),
        "via_wall_mm": args.via_wall_mm,
        "mesh_filaments_across_width": args.mesh,
        "ports": ports,
        "length_mm": {name: sum(math.dist(layout.xyz(e.start), layout.xyz(e.end)) for e in path)
                      for name, (_, _, path) in zip(ports, routes, strict=True)},
        "loops_at_10mhz_nh": loops,
        "frequencies_hz": matrices,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(loops, indent=2), flush=True)


def apply_parts(source, hot):
    for name, terminals, resistance in (("Rghi", "hri hro", 15), ("Rglo", "lri lro", 22)):
        source = replay.replace_line(source, name, f"{name} {terminals} {resistance}")
    for name, knee, clamp_v, pulse_a, temp_coeff, cap_nf in (
        ("Xtvs", 34.7, 45.7, 65.6, .00089, 2.2),
        ("Xtvs_high", 34.4, 45.4, 110, .00094, 4.7),
    ):
        slope = (clamp_v - knee) / pulse_a
        if hot:
            knee *= 1 + temp_coeff * 75
            slope *= 1.10
            cap_nf *= .75
        params = f"LLOOP={2 if hot else 1}n VBR={knee:.6g} RD={slope:.8g} C0={cap_nf:.6g}n"
        source, count = re.subn(rf"^({name} [^\n]+BENCH_TVS)[^\n]*\n\+ [^\n]+",
                                rf"\g<1>\n+ {params}", source, count=1, flags=re.M)
        if count != 1:
            raise ValueError(f"Review the model insertion for {name}")
    return source


def add_pin_bypass(source, inductance):
    return source.removesuffix(".end\n") + f"""Ltrial_bias hb trial_bw {inductance:g}n
Rtrial_bias trial_bw trial_bcap 0.10
Ctrial_bias trial_bcap hs 100n
.end
"""


class Capture:
    def __init__(self):
        self.decks = {}

    def submit(self, runner, executable, work, name, source):
        self.decks[name] = (runner, apply_parts(source, name.startswith("hot_")))
        return name


def read_inputs(args):
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    if extraction["board_sha256"] != replay.digest(args.board) or tuple(extraction["ports"]) != tuple(NODES):
        raise ValueError("Select the matching PCB and DFN extraction")
    reference, shunt, filt = (ROOT / name for name in ("bench-bootstrap-impedance.json",
                                                       "bench-shunt-transfer.json", "bench-shunt-filter-results.json"))
    selection = json.loads(filt.read_text(encoding="utf-8"))
    if selection["extraction_sha256"] != replay.digest(reference) or selection["shunt_sha256"] != replay.digest(shunt):
        raise ValueError("The shunt filter and reference fixtures differ")
    mount = json.loads(shunt.read_text(encoding="utf-8"))["cases"]["nominal"]
    circuit = replay.circuit_from(mount, selection["selected_filter_nf"])
    return extraction, replay.read_extraction(reference), circuit, (reference, shunt, filt)


def stage_models(args, work):
    with ZipFile(args.driver_archive) as archive:
        driver = archive.read("UCC21520_PSPICE_TRANS/UCC21520_TRANS.lib")
    if args.mode == "hot-diagnostic":
        driver = clamp.keep_driver_devices_at_25c(driver)
    (work / "ti-isolated.lib").write_bytes(driver)
    with ZipFile(args.mosfet_archive) as archive:
        model = archive.read("CSD19531Q5A.lib").decode("ascii")
    model = re.sub(r"^(\s*\.param\s+\w+)[ \t]+(?=[^= \t\r\n])", r"\1=", model, flags=re.M | re.I)
    (work / "csd19531q5a.lib").write_text(model, encoding="ascii")
    for name in replay.MODELS:
        shutil.copyfile(ROOT / name, work / name)


def replay_cases(args):
    extraction, reference, circuit, fixture_paths = read_inputs(args)
    paths = (args.board, args.extraction, args.driver_archive, args.mosfet_archive, *fixture_paths,
             Path(__file__), Path(bypass.__file__), Path(clamp.__file__), Path(replay.__file__),
             *(ROOT / name for name in (*replay.MODELS, "compact_layout_replay.py", "half_bridge_test.py",
                                         "commutation_clamp_test.py", "isolated_driver_test.py", "local_shutdown_test.py",
                                         "driven_layout_replay.py", "leg_receiver_test.py", "shunt_filter_test.py",
                                         "verify.py", "Helios_Bench.pretty/Diode_TVS_Vishay_DFN6546A.kicad_mod")))
    cases = {}
    with TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(folder)
        stage_models(args, work)
        capture = Capture()
        corners = replay.BIAS_CORNERS
        if args.mode == "pin-screen":
            corners = corners[:1]
        elif args.mode == "hot-diagnostic":
            corners = corners[1:]
        replay.add_cases(capture, work, SimpleNamespace(ngspice=args.ngspice), extraction, reference, circuit,
                         nodes=NODES, revise_bias=bypass.revise_bias, corners=corners)
        controls = {}
        if args.mode == "routed":
            controls["driver"] = replay.driver_control(args.ngspice, work, False)
            controls["mosfet"] = replay.run_case(args.ngspice, work, "mosfet_control", replay.SANITY)
        tasks = {}
        for name, (runner, source) in capture.decks.items():
            kind = name.rsplit("_", 1)[1]
            if args.mode == "pin-screen":
                if name not in ("nominal_high_resistive", "nominal_high_short", "nominal_low_short"):
                    continue
                variants = [(f"{name}_pin_{nh:g}n".replace(".", "p"), add_pin_bypass(source, nh))
                            for nh in PIN_BYPASS_NH]
            else:
                variants = [(name, source)]
            for label, deck in variants:
                tasks[pool.submit(runner, args.ngspice, work, label, deck)] = (label, kind)
        for task in as_completed(tasks):
            name, kind = tasks[task]
            try:
                cases[name] = replay.validate(task.result(), kind)
            except (RuntimeError, TimeoutExpired, OSError, KeyError, ValueError) as error:
                message = str(error).replace(str(work), "simulation")
                cases[name] = {"passed": False, "error": message[-1600:]}
            print(f"{name}: {'passed' if cases[name]['passed'] else 'open'}", flush=True)
    result = {
        "mode": args.mode,
        "inputs_sha256": {path.name: replay.digest(path) for path in paths},
        "controls": controls,
        "cases": dict(sorted(cases.items())),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not all(case["passed"] for case in cases.values()):
        raise SystemExit("Open switching or fault criteria. Results saved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extraction = commands.add_parser("extract", help="solve the 31-port copper network")
    extraction.add_argument("--fasthenry", default="fasthenry")
    extraction.add_argument("--mesh", type=int, default=7)
    extraction.add_argument("--via-wall-mm", type=float, default=0.02)
    extraction.set_defaults(output=EXTRACTION)

    sim = commands.add_parser("replay", help="check nominal and hot switching and shorts")
    sim.add_argument("--extraction", type=Path, default=EXTRACTION)
    sim.add_argument("--driver-archive", type=Path, required=True)
    sim.add_argument("--mosfet-archive", type=Path, required=True)
    sim.add_argument("--ngspice", default="ngspice")
    sim.add_argument("--jobs", type=int, default=6)
    sim.add_argument("--mode", choices=("routed", "pin-screen", "hot-diagnostic"), default="routed")
    for command in (extraction, sim):
        command.add_argument("--board", type=Path, default=BOARD)
        command.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "extract":
        exe = shutil.which(args.fasthenry)
        if not exe or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
            parser.error("Select a FastHenry executable, positive mesh and positive via wall thickness")
        args.fasthenry = str(Path(exe).resolve())
        extract(args)
    else:
        if args.jobs < 1:
            parser.error("Select at least one simulation worker")
        if args.output is None:
            args.output = ROOT / f"{REPORT}-{args.mode}.json"
        replay_cases(args)


if __name__ == "__main__":
    main()
