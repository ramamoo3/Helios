"""Extract the secondary leg, both TVS branches and the HB–HS clamp together."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil

from compact_layout_extract import coupled_ports, layout_ports
from driven_layout_extract import LOOPS as DRIVER_LOOPS, PATHS as DRIVER_PATHS, register
from extract_layout import Layout
from verify import ROOT, check_bench_via_clearance, children, first, read_schematic


BOARD = ROOT / "battery-port-secondary-protected.kicad_pcb"
PATHS = {
    **DRIVER_PATHS,
    "feed": (("C27", "1"), ("Q5", "bus_tee")),
    "feed_switch": (("Q5", "bus_tee"), ("Q5", "3")),
    "tvs_high_cathode": (("Q5", "bus_tee"), ("D2", "1")),
    "tvs_high_anode": (("D2", "2"), ("Q5", "hs_takeoff")),
    "boot_clamp_anode": (("U202", "hs_tee"), ("D3", "2")),
    "boot_clamp_cathode": (("D3", "1"), ("C206", "1")),
}
PORTS = tuple(PATHS)
LOOPS = {
    **DRIVER_LOOPS,
    "commutation_copper": {**DRIVER_LOOPS["commutation_copper"], "feed_switch": 1},
    "tvs_high_copper": {"feed_switch": -1, "tvs_high_cathode": 1, "tvs_high_anode": 1, "high_source": -1},
    "boot_clamp_copper": {"hs": 1, "boot_clamp_anode": 1, "boot_clamp_cathode": 1, "boot_feed": -1},
}


def route_ports(layout, tree):
    layout_ports(layout, tree)
    for ref, key, pin, xy in (
        ("Q5", "hs_takeoff", "1", (35.35, 27.905)),
        ("Q6", "source_finger", "1", (29.2, 33.635)),
        ("U202", "hs_tee", "5", (37.88, 28.0)),
        ("U202", "vss_takeoff", "9", (40.5, 24.49)),
        ("Q5", "bus_tee", "3", (28.85, 26.0)),
    ):
        register(layout, ref, key, pin, xy)
    on_back = {
        next(prop[2] for prop in children(fp, "property") if prop[1] == "Reference")
        for fp in children(tree, "footprint") if first(fp, "layer")[1] == "B.Cu"
    }
    if not {"D2", "D3"} <= on_back:
        raise ValueError("The high-side TVS and bootstrap Schottky must be on B.Cu")
    for ref in ("D2", "D3"):
        for pin in ("1", "2"):
            position, net, area = layout.pads[ref, pin]
            layout.pads[ref, pin] = ((*position[:2], "B.Cu"), net, area)
    routes = [layout.route(*pins) for pins in PATHS.values()]
    edge_usage = Counter(edge for _, _, route in routes for edge in route)
    if any(count > 1 for count in edge_usage.values()):
        raise ValueError("Split shared traces at the physical takeoff points")
    return routes


def extract(args):
    check_bench_via_clearance(args.board)
    tree = read_schematic(args.board)
    layout = Layout(tree, args.via_wall_mm)
    routes = route_ports(layout, tree)
    matrices, loops = coupled_ports(args, layout, PORTS, routes, LOOPS)
    result = {
        "board_sha256": hashlib.sha256(args.board.read_bytes()).hexdigest(),
        "board_thickness_mm": float(first(first(tree, "general"), "thickness")[1]),
        "via_wall_mm": args.via_wall_mm,
        "layer_z_mm": layout.z,
        "mesh_filaments_across_width": args.mesh,
        "ports": PORTS,
        "length_mm": {name: sum(math.dist(layout.xyz(edge.start), layout.xyz(edge.end)) for edge in route)
                      for name, (_, _, route) in zip(PORTS, routes, strict=True)},
        "loops_at_10mhz_nh": loops,
        "frequencies_hz": matrices,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(loops, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--via-wall-mm", type=float, default=0.02)
    parser.add_argument("--mesh", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solver = shutil.which(args.fasthenry)
    if not solver or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
        parser.error("Select a FastHenry executable, positive mesh and positive via wall thickness")
    args.fasthenry = str(Path(solver).resolve())
    extract(args)
