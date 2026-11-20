"""Extract the routed isolated gate driver, clamps, and bias capacitors."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil

from compact_layout_extract import SNUBBERS, projected
from driven_layout_extract import register
from extract_layout import Layout
from protected_layout_extract import PATHS as PROTECTED_PATHS
from secondary_layout_extract import solve
from verify import ROOT, check_bench_via_clearance, children, first, read_schematic


BOARD = ROOT / "battery-port-secondary-isolated-routed.kicad_pcb"
POWER = ("feed", "feed_switch", "high_source", "switch_trunk", "switch_land",
         "low_source", "source_to_shunt", "return_rail", "tvs_cathode", "tvs_anode",
         "tvs_high_cathode", "tvs_high_anode")
PATHS = {
    **{name: PROTECTED_PATHS[name] for name in POWER},
    "tvs_cathode": (("Q6", "3"), ("D1", "1")),
    "hs": (("U201", "9"), ("U201", "high_return_tee")),
    "hs_bypass": (("U201", "high_return_tee"), ("C201", "2")),
    "hs_source": (("C201", "2"), ("Q5", "hs_takeoff")),
    "vss": (("U201", "14"), ("C203", "2")),
    "vss_source": (("C203", "2"), ("Q6", "source_star")),
    "ho": (("U201", "10"), ("R206", "1")),
    "gh": (("R206", "2"), ("Q5", "2")),
    "lo": (("U201", "15"), ("R207", "1")),
    "gl": (("R207", "2"), ("Q6", "2")),
    "high_fast_feed": (("U201", "11"), ("C201", "1")),
    "high_bulk_feed": (("U201", "11"), ("C202", "1")),
    "high_bulk_return": (("C202", "2"), ("U201", "9")),
    "low_fast_feed": (("U201", "16"), ("C203", "1")),
    "low_bulk_feed": (("U201", "16"), ("C204", "1")),
    "low_bulk_return": (("C204", "2"), ("U201", "14")),
}
PORTS = tuple(PATHS)
LOOPS = {
    "commutation_copper": dict.fromkeys(POWER[:8], 1),
    "tvs_external": {"tvs_cathode": 1, "tvs_anode": 1, "low_source": -1},
    "tvs_high_copper": {"feed_switch": -1, "tvs_high_cathode": 1, "tvs_high_anode": 1, "high_source": -1},
    "high_gate": {"ho": 1, "gh": 1, "high_source": 1, "hs": -1, "hs_bypass": -1, "hs_source": -1},
    "low_gate": {"lo": 1, "gl": 1, "low_source": 1, "vss": -1, "vss_source": -1},
    "high_fast_bypass": {"high_fast_feed": 1, "hs_bypass": -1, "hs": -1},
    "high_bulk_bypass": {"high_bulk_feed": 1, "high_bulk_return": 1},
    "low_fast_bypass": {"low_fast_feed": 1, "vss": -1},
    "low_bulk_bypass": {"low_bulk_feed": 1, "low_bulk_return": 1},
}


def routed_ports(layout, board, paths=PATHS):
    rear_parts = {next(item[2] for item in children(part, "property") if item[1] == "Reference")
                  for part in children(board, "footprint") if first(part, "layer")[1] == "B.Cu"}
    rear_ports = ("D1", "D2", "C202", "C204")
    if not set(rear_ports) <= rear_parts:
        raise ValueError("Expected the TVS and bulk bypass footprints on the rear copper")
    for ref in rear_ports:
        for number in ("1", "2"):
            key = (ref, number)
            point, net, area = layout.pads[key]
            layout.pads[key] = ((*point[:2], "B.Cu"), net, area)
    for ref, name, pin, xy in (
        ("Q5", "hs_takeoff", "1", (35.35, 27.905)),
        ("Q5", "bus_tee", "3", (28.85, 26.0)),
        ("Q6", "clamp_tee", "3", (35.35, 33.635)),
        ("Q6", "source_finger", "1", (29.2, 33.635)),
        ("Q6", "source_star", "1", (28.32, 33.635)),
        ("U201", "high_return_tee", "9", (38.93, 26.555)),
    ):
        register(layout, ref, name, pin, xy)
    routes = [layout.route(*pins) for pins in paths.values()]
    usage = Counter(edge for _, _, route in routes for edge in route)
    if any(count > 1 for count in usage.values()):
        raise ValueError("Split the physical shared paths at the corresponding copper junctions")
    return routes


def extract(args, paths=PATHS, loop_terms=LOOPS):
    check_bench_via_clearance(args.board)
    board = read_schematic(args.board)
    layout = Layout(board, args.via_wall_mm)
    ports = tuple(paths)
    routes = routed_ports(layout, board, paths)
    matrices = solve(args, layout, ports, routes)
    inductance = matrices["1e+07"]["inductance_h"]
    loops = {
        name: 1e9 * projected(inductance, [terms.get(port, 0) for port in ports])
        for name, terms in loop_terms.items()
    }
    for name, pins in SNUBBERS.items():
        if name == "low_snubber_copper":
            pins = (*pins[:2], (pins[2][0], ("Q6", "source_finger")))
        order = ("drain", "between", "source")
        snubber = solve(args, layout, order, [layout.route(*pair) for pair in pins])
        loops[name] = 1e9 * projected(snubber["1e+07"]["inductance_h"], (1, 1, 1))
    result = {
        "board_sha256": hashlib.sha256(args.board.read_bytes()).hexdigest(),
        "board_thickness_mm": float(first(first(board, "general"), "thickness")[1]),
        "via_wall_mm": args.via_wall_mm,
        "mesh_filaments_across_width": args.mesh,
        "ports": ports,
        "length_mm": {name: sum(math.dist(layout.xyz(e.start), layout.xyz(e.end)) for e in path)
                      for name, (_, _, path) in zip(ports, routes, strict=True)},
        "loops_at_10mhz_nh": loops,
        "frequencies_hz": matrices,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(loops, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--mesh", type=int, default=7)
    parser.add_argument("--via-wall-mm", type=float, default=0.02)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solver = shutil.which(args.fasthenry)
    if not solver or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
        parser.error("Select a FastHenry executable, positive mesh and positive via wall thickness")
    args.fasthenry = str(Path(solver).resolve())
    extract(args)
