"""Screen the secondary-A commutation loop with the filled return mesh in FastHenry."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

import shapely as geo

from bench_plane_dc import COPPER_RHO, filled_plane, plane_mesh, return_copper, sheet_geometry
from extract_layout import DEFAULT_BOARD, LEGS, Layout, leg_routes, read_matrices
from verify import children, read_schematic


PORTS = ("feed", "switch", "return")
DOMAIN, LAYER = "/S0", "In2.Cu"
OPTIONS = ("-s", "iterative", "-m", "multi", "-p", "seg", "-t", "1e-5", "-b", "1e-7", "-c", "250")
SERIES_OPTIONS = ("-s", "iterative", "-m", "multi", "-p", "diag", "-t", "1e-4", "-b", "1e-7", "-c", "250")


def write_deck(path, board, pitch, series_10mhz=False):
    layout = Layout(board, .020)
    net = {n[2]: n[1] for n in children(board, "net")}.get(DOMAIN, DOMAIN)
    routes = leg_routes(layout, LEGS["sa"])[:3]
    copper = {edge for *_, edges in routes[:2] for edge in edges}
    copper.update(return_copper(layout, net))
    nodes, branches, contacts = {}, [], []

    def node(xyz):
        return nodes.setdefault(xyz, f"n{len(nodes)}")

    def add(a, b, width, thickness, width_filaments, height_filaments):
        orientation = " wx=1 wy=0 wz=0" if a[:2] == b[:2] else ""
        branches.append(f"e{len(branches)} {node(a)} {node(b)} w={width:.9g} h={thickness:.9g} "
                        f"nwinc={width_filaments} nhinc={height_filaments}{orientation}")

    plane_traces = []
    for edge in sorted(copper, key=lambda item: (item.start, item.end)):
        if pitch and edge.start[2] == edge.end[2] == LAYER:
            plane_traces.append(geo.LineString((edge.start[:2], edge.end[:2])).buffer(edge.width/2, quad_segs=8))
        else:
            add(layout.xyz(edge.start), layout.xyz(edge.end), edge.width, edge.thickness, 7, 2)
    if pitch:
        fill = filled_plane(board, net, LAYER)
        sheet, lands = sheet_geometry(layout, net, LAYER, fill, plane_traces)
        thickness = layout.thickness[LAYER]
        cells, tree, a, b, resistance = plane_mesh(sheet, pitch, COPPER_RHO/thickness)
        centres = [(*centroid.coords[0], layout.z[LAYER]) for centroid in geo.centroid(cells)]
        connected = set(a) | set(b)
        for start, end, ohm in zip(a, b, resistance, strict=True):
            u, v = centres[start], centres[end]
            width = COPPER_RHO * math.dist(u, v) / (thickness * ohm)
            add(u, v, width, thickness, 1, 1)
        for key, annulus in lands.items():
            hits = tree.query(annulus, predicate="intersects")
            hits = hits[geo.area(geo.intersection(cells[hits], annulus)) > 1e-9]
            attach = [index for index in hits if index in connected]
            if not attach:
                raise ValueError(f"Plane mesh missed the plated land at {key}")
            stem = node(layout.xyz(key))
            contacts.extend(f".equiv {node(centres[index])} {stem}" for index in attach if node(centres[index]) != stem)

    ports = [(node(layout.xyz(a)), node(layout.xyz(b))) for a, b, _ in routes]
    frequencies = ".freq fmin=1e5 fmax=1e7 ndec=1"
    if series_10mhz:
        (cap_positive, drain_high), (source_high, drain_low), (source_low, cap_negative) = ports
        # Series current is the same in feed, switch and return. The two
        # equivalent nodes model ideal semiconductor connections, as in 1' Z 1.
        contacts += [f".equiv {drain_high} {source_high}", f".equiv {drain_low} {source_low}"]
        external = [f".external {cap_positive} {cap_negative} loop"]
        frequencies = ".freq fmin=1e7 fmax=1e7 ndec=1"
    else:
        external = [f".external {a} {b} {name}" for name, (a, b) in zip(PORTS, ports, strict=True)]
    definitions = [f"{key} x={x:.9g} y={y:.9g} z={z:.9g}" for (x, y, z), key in nodes.items()]
    source = ["Helios secondary-A commutation loop", ".units mm", ".default sigma=58000",
              *definitions, *branches, *contacts, *external, frequencies, ".end", ""]
    path.write_text("\n".join(source), encoding="ascii", newline="\n")
    return {"nodes": len(nodes), "conductors": len(branches), "contact_connections": len(contacts)}


def read_series_loop(path):
    lines = path.read_text(encoding="ascii").splitlines()
    if (len(lines) != 3 or not lines[0].endswith("port name: loop")
            or lines[1] != "Impedance matrix for frequency = 1e+07 1 x 1"):
        raise ValueError("Expected a single 10 MHz series impedance")
    real, imaginary = lines[2].split()
    value = complex(real+imaginary)
    if not (math.isfinite(value.real) and math.isfinite(value.imag) and value.real > 0 and value.imag > 0):
        raise ValueError("Nonpositive or nonfinite 10 MHz loop impedance")
    return {"1e+07": {"resistance_mohm": value.real*1e3, "inductance_nh": value.imag*1e9/(math.tau*1e7)}}


def run_one(args, scratch, board, pitch):
    deck = scratch / "loop.inp"
    record = write_deck(deck, board, pitch, args.series_10mhz)
    options = SERIES_OPTIONS if args.series_10mhz else OPTIONS
    try:
        process = subprocess.run([args.fasthenry, str(deck), *options], cwd=scratch,
                                 capture_output=True, text=True, errors="replace", timeout=args.timeout)
    except subprocess.TimeoutExpired:
        return {**record, "completed": False, "error": f"Timeout after {args.timeout} s"}
    evidence = process.stdout + process.stderr
    record["warnings"] = sorted(set(re.findall(r"(?im)^.*warning:.*$", evidence)))[:12]
    if process.returncode:
        return {**record, "completed": False, "error": f"FastHenry exit {process.returncode}", "log_tail": evidence[-700:]}
    try:
        if args.series_10mhz:
            return {**record, "completed": True, "loop": read_series_loop(scratch / "Zc.mat")}
        response = read_matrices(scratch / "Zc.mat", PORTS, relative_reciprocity=3e-4)
    except (ValueError, FileNotFoundError) as error:
        return {**record, "completed": False, "error": str(error).replace(str(scratch), "simulation")}
    return {**record, "completed": True, "frequencies": response, "loop": {
        frequency: {"resistance_mohm": sum(map(sum, matrix["resistance_ohm"])) * 1000,
                    "inductance_nh": sum(map(sum, matrix["inductance_h"])) * 1e9}
        for frequency, matrix in response.items()}}


def run(args):
    baseline, trial = map(read_schematic, (args.baseline, args.filled))
    cases = {}
    for pitch in (None, *args.pitch_mm):
        key = f"trial {pitch:g} mm" if pitch else "baseline"
        with TemporaryDirectory() as directory:
            cases[key] = run_one(args, Path(directory), trial if pitch else baseline, pitch)
        print(key, "complete" if cases[key]["completed"] else cases[key]["error"], flush=True)
    files = (args.baseline, args.filled, Path(__file__), *(Path(__file__).with_name(p) for p in
             ("bench_plane_dc.py", "extract_layout.py", "verify.py")))
    return {"scope": "Secondary-A loop diagnostic using resistive-mesh-derived filaments with ideal bridged pads",
            "inputs_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in zip(
                ("baseline PCB", "filled trial PCB", "solver", "copper mesh", "layout parser", "KiCad parser"), files)},
            "solver_options": SERIES_OPTIONS if args.series_10mhz else OPTIONS,
            "series_10mhz": args.series_10mhz, "relative_reciprocity_floor": 3e-4, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filled", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--pitch-mm", nargs="+", type=float, default=[2, 1])
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--series-10mhz", action="store_true", help="join the three path ports for a single 10 MHz solve")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not shutil.which(args.fasthenry) or args.timeout < 1 or any(not math.isfinite(p) or p <= 0 for p in args.pitch_mm):
        parser.error("Choose a FastHenry executable, positive timeout and positive mesh pitch")
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
