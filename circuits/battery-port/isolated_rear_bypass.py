"""Extract and replay the routed rear bypass on the 24 V DFN bench leg."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

import isolated_dfn_test as dfn
from isolated_driver_test import replace_line
from verify import ROOT, check_bench_via_clearance, children, first, read_schematic


STEM = "bench-secondary-isolated-dfn-rear-bypass"
BOARD = ROOT / "battery-port-secondary-isolated-dfn-rear-bypass.kicad_pcb"
EXTRACTION = ROOT / f"{STEM}-impedance.json"
COMPARE = ROOT / "isolated-bench-driver.lib"
PATHS = {
    **dfn.PATHS,
    "high_bulk_feed": (("C207", "1"), ("C202", "1")),
    "high_bulk_return": (("C202", "2"), ("C207", "2")),
    "rear_feed": (("U201", "11"), ("C207", "1")),
    "rear_return": (("C207", "2"), ("U201", "9")),
}
NODES = {
    **dfn.NODES,
    "high_bulk_feed": ("rear_cap_p", "hi_bulk_p"),
    "high_bulk_return": ("hi_bulk_n", "rear_cap_n"),
    "rear_feed": ("hb", "rear_cap_p"),
    "rear_return": ("rear_cap_n", "hs"),
}
REAR_LOOP = {"rear_feed": 1, "rear_return": 1}
LOOPS = {
    **dfn.LOOPS,
    "rear_fast_bypass": REAR_LOOP,
    "high_bulk_bypass": {**dfn.LOOPS["high_bulk_bypass"], **REAR_LOOP},
}


def extract(args):
    check_bench_via_clearance(args.board)
    board = read_schematic(args.board)
    layout = dfn.copper.Layout(board, args.via_wall_mm)
    parts = {next(prop[2] for prop in children(part, "property") if prop[1] == "Reference"): part
             for part in children(board, "footprint")}
    for ref in ("D1", "C207"):
        if first(parts[ref], "layer")[1] != "B.Cu":
            raise ValueError(f"{ref} must be on the back copper")
    cathode_net = layout.pads["D1", "1"][1]
    junction = (32.655, 35.53, "B.Cu")
    if junction not in layout.graphs[cathode_net]:
        raise ValueError("The short DFN cathode junction moved")
    layout.pads["D1", "k_junction"] = (junction, cathode_net, 0)
    x, y, angle = map(float, first(parts["D1"], "at")[1:])
    cathodes = [pad for pad in children(parts["D1"], "pad") if pad[1] == "1"]
    if angle or len(cathodes) != 2:
        raise ValueError("Review the DFN cathode orientation and count")
    for index, pad in enumerate(cathodes, 1):
        px, py = map(float, first(pad, "at")[1:3])
        if first(pad, "net")[1] != cathode_net:
            raise ValueError("The two DFN cathodes must share the same net")
        layout.pads["D1", f"k{index}"] = ((round(x+px, 6), round(y+py, 6), "B.Cu"), cathode_net, 0)
    for number in ("1", "2"):
        key = ("C207", number)
        point, net, size = layout.pads[key]
        layout.pads[key] = ((*point[:2], "B.Cu"), net, size)
    ports = tuple(PATHS)
    traces = dfn.copper.routed_ports(layout, board, PATHS)
    models = dfn.copper.solve(args, layout, ports, traces)
    matrix = models["1e+07"]["inductance_h"]
    loops = {name: 1e9 * dfn.copper.projected(matrix, [weights.get(port, 0) for port in ports])
             for name, weights in LOOPS.items()}
    for name, pins in dfn.copper.SNUBBERS.items():
        if name == "low_snubber_copper":
            pins = (*pins[:2], (pins[2][0], ("Q6", "source_finger")))
        fit = dfn.copper.solve(args, layout, ("drain", "between", "source"), [layout.route(*pair) for pair in pins])
        loops[name] = 1e9 * dfn.copper.projected(fit["1e+07"]["inductance_h"], (1, 1, 1))
    hf = LOOPS["high_fast_bypass"]
    mutual = 1e9 * sum(matrix[i][j] * hf.get(a, 0) * REAR_LOOP.get(b, 0)
                       for i, a in enumerate(ports) for j, b in enumerate(ports))
    # At high frequency, estimate the parallel combination with nominal 0402
    # part ESL. The transient uses every coupled route and both capacitors.
    front_l, rear_l = (loops[name] + .35 for name in ("high_fast_bypass", "rear_fast_bypass"))
    equivalent = (front_l * rear_l - mutual**2) / (front_l + rear_l - 2*mutual)
    data = {
        "board_sha256": dfn.replay.digest(args.board),
        "board_thickness_mm": float(first(first(board, "general"), "thickness")[1]),
        "via_wall_mm": args.via_wall_mm,
        "mesh_filaments_across_width": args.mesh,
        "ports": ports,
        "length_mm": {name: sum(math.dist(layout.xyz(edge.start), layout.xyz(edge.end)) for edge in path)
                      for name, (_, _, path) in zip(ports, traces, strict=True)},
        "loops_at_10mhz_nh": loops,
        "fast_bypass_loop_mutual_nh": mutual,
        "fast_parallel_estimate_with_package_nh": equivalent,
        "frequencies_hz": models,
    }
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**loops, "fast_parallel_estimate_with_package_nh": equivalent}, indent=2), flush=True)


def bias_deck(source, voltage, hot):
    source = dfn.bypass.revise_bias(source, voltage, hot)
    capacitance = "55n" if hot else "75n"
    return source.removesuffix(".end\n") + f"""Lpkg_high_rear rear_cap_p rear_f_r .35n
Rpkg_high_rear rear_f_r rear_f_c .03
Cpin_high_rear rear_f_c rear_cap_n {capacitance}
Bbias_rear bias_rear 0 V=v(rear_cap_p,rear_cap_n)
.meas tran high_rear_min MIN v(bias_rear)
.meas tran high_rear_max MAX v(bias_rear)
.end
"""


def compare_driver(source):
    source = replace_line(source, "Xisolated",
                          "Xisolated dis vss li_masked hi_masked lo ho vcci vdd hb vss hs HELIOS_ISOLATED_COMPARE")
    return source.replace(".include ti-isolated.lib", f".include {COMPARE.name}")


class Capture(dfn.Capture):
    def submit(self, runner, executable, work, name, source):
        super().submit(runner, executable, work, name, source)
        _, deck = self.decks[name]
        self.decks[name] = (runner, replace_line(deck, "Rglo", "Rglo lri lro 27"))
        return name


def run(args):
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    if extraction["board_sha256"] != dfn.replay.digest(args.board) or extraction["ports"] != list(NODES):
        raise ValueError("Select the matching rear-bypass PCB and 33-port extraction")
    base = ROOT / "bench-bootstrap-impedance.json"
    shunt = ROOT / "bench-shunt-transfer.json"
    filter_path = ROOT / "bench-shunt-filter-results.json"
    filter_result = json.loads(filter_path.read_text(encoding="utf-8"))
    if any(filter_result[key] != dfn.replay.digest(path)
           for key, path in (("extraction_sha256", base), ("shunt_sha256", shunt))):
        raise ValueError("The shunt filter and reference files differ")
    mount = json.loads(shunt.read_text(encoding="utf-8"))["cases"]["nominal"]
    circuit = dfn.replay.circuit_from(mount, filter_result["selected_filter_nf"])
    archived_inputs = (
        args.board, args.extraction, args.driver_archive, args.mosfet_archive, base, shunt, filter_path,
        COMPARE, Path(__file__), Path(dfn.__file__), Path(dfn.bypass.__file__),
        *(ROOT / name for name in (*dfn.replay.MODELS, "verify.py", "isolated_layout_replay.py",
                                   "isolated_layout_extract.py", "isolated_driver_test.py", "isolated_clamp_test.py",
                                   "driven_layout_replay.py", "compact_layout_replay.py", "half_bridge_test.py",
                                   "secondary_layout_replay.py", "local_shutdown_test.py", "leg_receiver_test.py",
                                   "shunt_filter_test.py")),
    )
    results = {}
    with TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        work = Path(folder)
        dfn.stage_models(args, work)
        shutil.copyfile(COMPARE, work / COMPARE.name)
        capture = Capture()
        corners = dfn.replay.BIAS_CORNERS[:1] if args.nominal else dfn.replay.BIAS_CORNERS
        dfn.replay.add_cases(capture, work, args, extraction, dfn.replay.read_extraction(base), circuit,
                             nodes=NODES, revise_bias=bias_deck, corners=corners)
        tasks = {}
        for label, (_, deck) in capture.decks.items():
            kind = label.rsplit("_", 1)[1]
            if args.quick and (kind == "inductive" or label.endswith("_low_resistive")):
                continue
            if args.mode == "compare":
                deck = compare_driver(deck)
            adjust = f".tran {args.step_ps}p"
            deck, count = re.subn(r"^\.tran 250p (\S+) 0 250p$", rf"{adjust} \1 0 {args.step_ps}p",
                                  deck, count=1, flags=re.M)
            if count != 1:
                raise ValueError("Review the original transient integration settings")
            tasks[pool.submit(dfn.replay.run_case, args.ngspice, work, label, deck)] = (label, kind)
        for task in as_completed(tasks):
            label, kind = tasks[task]
            try:
                results[label] = dfn.replay.validate(task.result(), kind)
            except TimeoutExpired:
                results[label] = {"passed": False, "error": "ngspice exceeded 180 seconds"}
            except (RuntimeError, ValueError, KeyError, OSError) as error:
                lines = str(error).replace(str(work), "simulation").splitlines()
                detail = next((line.strip() for line in lines if "timestep" in line.lower()), lines[-1])
                results[label] = {"passed": False, "error": detail}
            print(f"{label}: {'passed' if results[label]['passed'] else 'open'}", flush=True)
    result = {
        "driver_model": args.mode, "step_ps": args.step_ps,
        "additional_rear_capacitance_nf": {"nominal": 75, "hot": 55},
        "inputs_sha256": {path.name: dfn.replay.digest(path) for path in archived_inputs},
        "cases": dict(sorted(results.items())),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not all(r["passed"] for r in results.values()):
        raise SystemExit("Open comparison criteria. Results saved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ex = commands.add_parser("extract")
    ex.add_argument("--fasthenry", default="fasthenry")
    ex.add_argument("--mesh", type=int, default=7)
    ex.add_argument("--via-wall-mm", type=float, default=.02)
    ex.set_defaults(output=EXTRACTION)
    sim = commands.add_parser("replay")
    sim.add_argument("--driver-archive", type=Path, required=True)
    sim.add_argument("--mosfet-archive", type=Path, required=True)
    sim.add_argument("--extraction", type=Path, default=EXTRACTION)
    sim.add_argument("--ngspice", default="ngspice")
    sim.add_argument("--jobs", type=int, default=6)
    sim.add_argument("--mode", choices=("vendor", "compare"), default="vendor")
    sim.add_argument("--step-ps", type=int, choices=(125, 250, 500), default=250)
    sim.add_argument("--nominal", action="store_true", help="skip the 100 C cases")
    sim.add_argument("--quick", action="store_true", help="run the shorts and high-side resistive case")
    for command in (ex, sim):
        command.add_argument("--board", type=Path, default=BOARD)
        command.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "extract":
        solver = shutil.which(args.fasthenry)
        if not solver or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
            parser.error("Select FastHenry, a positive mesh and a positive via wall thickness")
        args.fasthenry = str(Path(solver).resolve())
        extract(args)
    else:
        if args.jobs < 1:
            parser.error("Select at least one simulation worker")
        if args.output is None:
            suffix = f"{args.mode}-{args.step_ps}ps"
            if args.nominal:
                suffix += "-nominal"
            if args.quick:
                suffix += "-quick"
            args.output = ROOT / f"{STEM}-{suffix}.json"
        run(args)


if __name__ == "__main__":
    main()
