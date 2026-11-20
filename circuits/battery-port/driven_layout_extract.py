"""Extract the coupled copper paths of the compact secondary leg and local driver."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil

from compact_layout_extract import coupled_ports, layout_ports
from extract_layout import Layout
from verify import ROOT, check_bench_via_clearance, children, first, read_schematic


BOARD = ROOT / "battery-port-secondary-driven.kicad_pcb"
PATHS = {
    "feed": (("C27", "1"), ("Q5", "3")),
    "high_source": (("Q5", "1"), ("Q5", "hs_takeoff")),
    "switch_trunk": (("Q5", "hs_takeoff"), ("Q6", "clamp_tee")),
    "switch_land": (("Q6", "clamp_tee"), ("Q6", "3")),
    "low_source": (("Q6", "source_finger"), ("Q6", "source_star")),
    "source_to_shunt": (("Q6", "source_star"), ("R30", "1")),
    "return_rail": (("R30", "4"), ("C27", "2")),
    "tvs_cathode": (("Q6", "clamp_tee"), ("D1", "1")),
    "tvs_anode": (("D1", "2"), ("Q6", "source_star")),
    "hs": (("U202", "5"), ("U202", "hs_tee")),
    "hs_source": (("U202", "hs_tee"), ("Q5", "hs_takeoff")),
    "vss_pin": (("U202", "9"), ("U202", "vss_takeoff")),
    "vss": (("U202", "vss_takeoff"), ("Q6", "source_star")),
    "ho": (("U202", "4"), ("R206", "1")),
    "gh": (("R206", "2"), ("Q5", "2")),
    "lo": (("U202", "10"), ("R207", "1")),
    "gl": (("R207", "2"), ("Q6", "2")),
    "boot_feed": (("U202", "3"), ("C206", "1")),
    "boot_return": (("C206", "2"), ("U202", "hs_tee")),
    "bias_feed": (("U202", "1"), ("C204", "1")),
    "bias_return": (("C204", "2"), ("U202", "vss_takeoff")),
}
PORTS = tuple(PATHS)
LOOPS = {
    "commutation_copper": dict.fromkeys(PORTS[:7], 1),
    "tvs_external": {"switch_land": -1, "tvs_cathode": 1, "tvs_anode": 1, "low_source": -1},
    "bootstrap_copper": {"boot_feed": 1, "boot_return": 1, "hs": -1},
    "high_gate": {"ho": 1, "gh": 1, "high_source": 1, "hs_source": -1, "hs": -1},
    "low_gate": {"lo": 1, "gl": 1, "low_source": 1, "vss": -1, "vss_pin": -1},
    "bias_bypass": {"bias_feed": 1, "bias_return": 1, "vss_pin": -1},
}


def register(layout, ref, name, pin, xy):
    node = (*xy, "F.Cu")
    net = layout.pads[ref, pin][1]
    if node not in layout.graphs[net]:
        raise ValueError(f"The copper junction for {ref} {name} moved")
    layout.pads[ref, name] = (node, net, 0)


def run(args):
    check_bench_via_clearance(args.board)
    tree = read_schematic(args.board)
    if args.core_mm is not None:
        stack = first(first(tree, "setup"), "stackup")
        core = next(layer for layer in children(stack, "layer") if layer[1] == "dielectric 2")
        first(core, "thickness")[1] = str(args.core_mm)
    layout = Layout(tree, args.via_wall_mm)
    layout_ports(layout, tree)
    register(layout, "Q5", "hs_takeoff", "1", (35.35, 27.905))
    register(layout, "Q6", "source_finger", "1", (29.2, 33.635))
    register(layout, "U202", "hs_tee", "5", (37.88, 28.0))
    register(layout, "U202", "vss_takeoff", "9", (40.5, 24.49))
    routes = [layout.route(*pins) for pins in PATHS.values()]
    usage = Counter(edge for _, _, route in routes for edge in route)
    if any(count > 1 for count in usage.values()):
        raise ValueError("Split each shared copper branch at its physical tee before extracting it")
    matrices, loops = coupled_ports(args, layout, PORTS, routes, LOOPS)
    result = {
        "board_sha256": hashlib.sha256(args.board.read_bytes()).hexdigest(),
        "via_wall_mm": args.via_wall_mm,
        "layer_z_mm": layout.z,
        "core_override_mm": args.core_mm,
        "mesh_filaments_across_width": args.mesh,
        "ports": PORTS,
        "length_mm": {port: sum(math.dist(layout.xyz(edge.start), layout.xyz(edge.end)) for edge in legs)
                      for port, (_, _, legs) in zip(PORTS, routes, strict=True)},
        "loops_at_10mhz_nh": loops,
        "frequencies_hz": matrices,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(loops, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--via-wall-mm", type=float, default=0.02)
    parser.add_argument("--core-mm", type=float, help="sensitivity override for the central dielectric")
    parser.add_argument("--mesh", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solver = shutil.which(args.fasthenry)
    if not solver or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
        parser.error("Select a FastHenry executable, positive mesh and positive via wall thickness")
    if args.core_mm is not None and (not math.isfinite(args.core_mm) or args.core_mm <= 0):
        parser.error("The sensitivity core thickness must be positive")
    args.fasthenry = str(Path(solver).resolve())
    run(args)
