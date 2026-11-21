"""Screen a bench commutation loop with the filled return mesh in FastHenry."""

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

from bench_plane_dc import COPPER_RHO, PLANES, filled_plane, plane_mesh, return_copper, sheet_geometry
from extract_layout import DEFAULT_BOARD, LEGS, Layout, leg_routes, read_matrices
from verify import children, read_schematic


PORTS = ("feed", "switch", "return")
OPTIONS = ("-s", "iterative", "-m", "multi", "-p", "seg", "-t", "1e-5", "-b", "1e-7", "-c", "250")
SERIES_OPTIONS = ("-s", "iterative", "-m", "multi", "-p", "diag", "-t", "1e-4", "-b", "1e-7", "-c", "250")


def write_deck(path, board, pitch, series_10mhz=False, leg="sa"):
    layout = Layout(board, .020)
    domain = "/P0" if leg.startswith("p") else "/S0"
    layer = PLANES[domain]
    net = {n[2]: n[1] for n in children(board, "net")}.get(domain, domain)
    routes = leg_routes(layout, LEGS[leg])[:3]
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
        if pitch and edge.start[2] == edge.end[2] == layer:
            plane_traces.append(geo.LineString((edge.start[:2], edge.end[:2])).buffer(edge.width/2, quad_segs=8))
        else:
            add(layout.xyz(edge.start), layout.xyz(edge.end), edge.width, edge.thickness, 7, 2)
    if pitch:
        fill = filled_plane(board, net, layer)
        sheet, lands = sheet_geometry(layout, net, layer, fill, plane_traces)
        thickness = layout.thickness[layer]
        cells, tree, a, b, resistance = plane_mesh(sheet, pitch, COPPER_RHO/thickness)
        centres = [(*centroid.coords[0], layout.z[layer]) for centroid in geo.centroid(cells)]
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
    source = [f"Helios {leg.upper()} commutation loop", ".units mm", ".default sigma=58000",
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
    record = write_deck(deck, board, pitch, args.series_10mhz, args.leg)
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
    filled = read_schematic(args.filled)
    label = "trial" if args.baseline is not None else "filled"
    work = [(f"{label} {pitch:g} mm", filled, pitch) for pitch in args.pitch_mm]
    files = {"filled PCB": args.filled, "solver": Path(__file__), "copper mesh": Path(__file__).with_name("bench_plane_dc.py"),
             "layout parser": Path(__file__).with_name("extract_layout.py"), "KiCad parser": Path(__file__).with_name("verify.py")}
    if args.baseline is not None:
        baseline = read_schematic(args.baseline)
        if any(not children(z, "keepout") for z in children(baseline, "zone")):
            raise ValueError("Choose a trace-only baseline PCB")
        work.insert(0, ("baseline", baseline, None))
        files["baseline PCB"] = args.baseline
    cases = {}
    for key, board, pitch in work:
        with TemporaryDirectory() as directory:
            cases[key] = run_one(args, Path(directory), board, pitch)
        print(key, "complete" if cases[key]["completed"] else cases[key]["error"], flush=True)
    return {"scope": "Loop diagnostic using resistive-mesh-derived filaments with ideal bridged pads", "leg": args.leg,
            "inputs_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
            "solver_options": SERIES_OPTIONS if args.series_10mhz else OPTIONS,
            "series_10mhz": args.series_10mhz, "relative_reciprocity_floor": 3e-4, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filled", type=Path, nargs="?", default=DEFAULT_BOARD)
    parser.add_argument("--baseline", type=Path, help="optional trace-only PCB for comparison")
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--leg", choices=tuple(LEGS), default="sa")
    parser.add_argument("--pitch-mm", nargs="+", type=float, default=[2, 1])
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--series-10mhz", action="store_true", help="join the three path ports for a single 10 MHz solve")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not shutil.which(args.fasthenry) or args.timeout < 1 or any(not math.isfinite(p) or p <= 0 for p in args.pitch_mm):
        parser.error("Choose a FastHenry executable, positive timeout and positive mesh pitch")
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
