"""Extract the routed secondary study's return and clamp paths with FastHenry."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from extract_layout import BOOTSTRAP_PORTS, Layout, read_matrices, write_geometry
from verify import ROOT, read_schematic


BOARD = ROOT / "battery-port-secondary-layout.kicad_pcb"
PORTS = (*BOOTSTRAP_PORTS, "return_rail", "tvs_cathode", "tvs_anode")

PATHS = {
    "feed": (("C27", "1"), ("Q5", "2")),
    "switch": (("Q5", "3"), ("Q6", "2")),
    "return": (("Q6", "3"), ("R30", "1")),
    "hs": (("U202", "5"), ("Q5", "3")),
    "vss": (("U202", "11"), ("Q6", "3")),
    "ho": (("U202", "4"), ("R206", "1")),
    "gh": (("R206", "2"), ("Q5", "1")),
    "lo": (("U202", "10"), ("R207", "1")),
    "gl": (("R207", "2"), ("Q6", "1")),
    "boot_feed": (("U202", "3"), ("C206", "1")),
    "boot_return": (("U202", "5"), ("C206", "2")),
    "return_rail": (("R30", "4"), ("C27", "2")),
    "tvs_cathode": (("Q6", "2"), ("D1", "1")),
    "tvs_anode": (("D1", "2"), ("Q6", "3")),
}

LOOPS = {
    "commutation_copper": {"feed": 1, "switch": 1, "return": 1, "return_rail": 1},
    "tvs_external": {"tvs_cathode": 1, "tvs_anode": 1},
    "bootstrap_copper": {"boot_feed": 1, "boot_return": 1, "hs": -1},
    "high_gate": {"ho": 1, "gh": 1, "hs": -1, "hs_source": -1},
    "low_gate": {"lo": 1, "gl": 1, "vss": -1},
}

SNUBBERS = {
    "high_snubber_copper": ((("Q5", "2"), ("R1", "1")), (("R1", "2"), ("C1", "1")), (("C1", "2"), ("Q5", "3"))),
    "low_snubber_copper": ((("Q6", "2"), ("R2", "1")), (("R2", "2"), ("C2", "1")), (("C2", "2"), ("Q6", "3"))),
}


def extract_routes(layout):
    top = {"feed", "switch", "return", "tvs_cathode", "tvs_anode"}
    route = {name: layout.route(*pins, top_only=name in top) for name, pins in PATHS.items()}
    driver, source, to_source = route["hs"]
    _, cap, to_cap = route["boot_return"]
    tee = driver
    shared = 0
    for source_edge, cap_edge in zip(to_source, to_cap):
        if source_edge != cap_edge:
            break
        shared += 1
        tee = source_edge.end if tee == source_edge.start else source_edge.start
    if not 0 < shared < min(len(to_source), len(to_cap)):
        raise ValueError("Expected a single physical HS tee at the bootstrap capacitor return")
    route["hs"] = (driver, tee, to_source[:shared])
    route["hs_source"] = (tee, source, to_source[shared:])
    route["boot_return"] = (cap, tee, to_cap[shared:][::-1])
    return route


def loop_value(matrix, paths):
    weights = [paths.get(port, 0) for port in PORTS]
    return sum(weights[i]*matrix[i][j]*weights[j] for i in range(len(weights)) for j in range(len(weights)))


def solve(args, layout, order, routes):
    with TemporaryDirectory() as tmp:
        work = Path(tmp)
        source = work / "secondary.inp"
        write_geometry(source, layout, routes, args.mesh, order)
        command = [args.fasthenry, str(source), "-s", "ludecomp", "-m", "direct"]
        process = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=180)
        if process.returncode or not (work / "Zc.mat").is_file():
            raise RuntimeError(f"FastHenry failed:\n{process.stdout}\n{process.stderr}")
        return read_matrices(work / "Zc.mat", order)


def run(args):
    layout = Layout(read_schematic(args.board), args.via_wall_mm)
    route = extract_routes(layout)
    matrices = solve(args, layout, PORTS, [route[p] for p in PORTS])
    loops = {name: 1e9*loop_value(matrices["1e+07"]["inductance_h"], paths) for name, paths in LOOPS.items()}
    snubbers = {}
    for name, pins in SNUBBERS.items():
        order = ("drain", "between", "source")
        branches = solve(args, layout, order, [layout.route(*pair) for pair in pins])
        loops[name] = 1e9*sum(sum(row) for row in branches["1e+07"]["inductance_h"])
        snubbers[name] = branches
    result = {
        "board_sha256": hashlib.sha256(args.board.read_bytes()).hexdigest(),
        "thickness_mm": layout.thickness,
        "via_wall_mm": args.via_wall_mm,
        "mesh_filaments_across_width": args.mesh,
        "ports": list(PORTS),
        "length_mm": {
            name: sum(math.dist(layout.xyz(edge.start), layout.xyz(edge.end)) for edge in segments)
            for name, (_, _, segments) in route.items()
        },
        "loops_at_10mhz_nh": loops,
        "frequencies_hz": matrices,
        "snubber_extractions": snubbers,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result["loops_at_10mhz_nh"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--mesh", type=int, default=5)
    parser.add_argument("--via-wall-mm", type=float, default=0.02)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solver = shutil.which(args.fasthenry)
    if not solver or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
        parser.error("Select a FastHenry executable, positive mesh and positive via wall thickness")
    args.fasthenry = str(Path(solver).resolve())
    run(args)
