"""Extract the compact secondary layout's power loops, including the rear clamp."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

from extract_layout import Layout
from secondary_layout_extract import solve
from verify import ROOT, check_bench_via_clearance, children, first, read_schematic


BOARD = ROOT / "battery-port-secondary-compact.kicad_pcb"
PORTS = ("feed", "switch_trunk", "switch_land", "source_to_shunt", "return_rail", "tvs_cathode", "tvs_anode")
PATHS = (
    (("C27", "1"), ("Q5", "3")),
    (("Q5", "1"), ("Q6", "clamp_tee")),
    (("Q6", "clamp_tee"), ("Q6", "3")),
    (("Q6", "source_star"), ("R30", "1")),
    (("R30", "4"), ("C27", "2")),
    (("Q6", "clamp_tee"), ("D1", "1")),
    (("D1", "2"), ("Q6", "source_star")),
)
SNUBBERS = {
    "high_snubber_copper": ((("Q5", "3"), ("R1", "1")), (("R1", "2"), ("C1", "1")), (("C1", "2"), ("Q5", "1"))),
    "low_snubber_copper": ((("Q6", "3"), ("R2", "1")), (("R2", "2"), ("C2", "1")), (("C2", "2"), ("Q6", "source_star"))),
}


def layout_ports(layout, tree):
    # Layout's original footprints were single-face devices. Move the TVS
    # terminals to their actual layer and register the two copper junctions.
    diode = next(fp for fp in children(tree, "footprint")
                 if any(prop[1:3] == ["Reference", "D1"] for prop in children(fp, "property")))
    layer = first(diode, "layer")[1]
    if layer != "B.Cu":
        raise ValueError("The compact extraction expects the TVS on the back")
    for pin in ("1", "2"):
        key = ("D1", pin)
        position, net, area = layout.pads[key]
        layout.pads[key] = ((*position[:2], layer), net, area)
    for key, pin, x, y in (("clamp_tee", "3", 35.35, 33.635), ("source_star", "1", 28.32, 33.635)):
        node = (x, y, "F.Cu")
        net = layout.pads["Q6", pin][1]
        if node not in layout.graphs[net]:
            raise ValueError(f"Review the location of the Q6 {key.replace('_', ' ')}")
        layout.pads["Q6", key] = (node, net, 0)


def projected(matrix, weights):
    return sum(a*value*b for a, row in zip(weights, matrix, strict=True)
               for b, value in zip(weights, row, strict=True))



def coupled_ports(args, layout, ports, routes, loop_terms):
    """Evaluate one coupled network and the independently routed snubber loops."""
    matrices = solve(args, layout, ports, routes)
    inductance = matrices["1e+07"]["inductance_h"]
    loops = {name: 1e9 * projected(inductance, [terms.get(port, 0) for port in ports])
             for name, terms in loop_terms.items()}
    snubber_ports = ("drain", "between", "source")
    for name, pins in SNUBBERS.items():
        if name == "low_snubber_copper":
            pins = (*pins[:2], (pins[2][0], ("Q6", "source_finger")))
        snubber = solve(args, layout, snubber_ports, [layout.route(*pair) for pair in pins])
        loops[name] = 1e9 * projected(snubber["1e+07"]["inductance_h"], (1, 1, 1))
    return matrices, loops

def run(args):
    check_bench_via_clearance(args.board)
    tree = read_schematic(args.board)
    if args.core_mm is not None:
        stack = first(first(tree, "setup"), "stackup")
        core = next(layer for layer in children(stack, "layer") if layer[1] == "dielectric 2")
        first(core, "thickness")[1] = str(args.core_mm)
    layout = Layout(tree, args.via_wall_mm)
    layout_ports(layout, tree)
    routes = [layout.route(*pins) for pins in PATHS]
    impedance = solve(args, layout, PORTS, routes)
    inductance = impedance["1e+07"]["inductance_h"]
    loops = {
        "commutation_copper": 1e9 * projected(inductance, (1, 1, 1, 1, 1, 0, 0)),
        "tvs_external": 1e9 * projected(inductance, (0, 0, -1, 0, 0, 1, 1)),
        "tvs_toes_only": 1e9 * projected(inductance, (0, 0, 0, 0, 0, 1, 1)),
    }
    for name, paths in SNUBBERS.items():
        order = ("drain", "between", "source")
        data = solve(args, layout, order, [layout.route(*pins) for pins in paths])
        loops[name] = 1e9 * projected(data["1e+07"]["inductance_h"], (1, 1, 1))
    result = {
        "board_sha256": hashlib.sha256(args.board.read_bytes()).hexdigest(),
        "thickness_mm": layout.thickness,
        "via_wall_mm": args.via_wall_mm,
        "sensitivity_core_override_mm": args.core_mm,
        "mesh_filaments_across_width": args.mesh,
        "ports": list(PORTS),
        "length_mm": {name: sum(math.dist(layout.xyz(a.start), layout.xyz(a.end)) for a in route[2])
                      for name, route in zip(PORTS, routes, strict=True)},
        "loops_at_10mhz_nh": loops,
        "frequencies_hz": impedance,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(loops, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--mesh", type=int, default=7)
    parser.add_argument("--via-wall-mm", type=float, default=0.02)
    parser.add_argument("--core-mm", type=float, help="sensitivity override for the central dielectric thickness")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solver = shutil.which(args.fasthenry)
    if not solver or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
        parser.error("Select a FastHenry executable, positive mesh and positive via wall thickness")
    if args.core_mm is not None and (not math.isfinite(args.core_mm) or args.core_mm <= 0):
        parser.error("The sensitivity core thickness must be positive")
    args.fasthenry = str(Path(solver).resolve())
    run(args)
