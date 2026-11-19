"""Extract bench commutation and gate-path impedance with FastHenry."""
import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from verify import ROOT, children, first, read_schematic


LEGS = {
    "pa": ("Q1", "Q2", "U2", "R6", "R7", "C26"),
    "pb": ("Q3", "Q4", "U102", "R106", "R107", "C28"),
    "sa": ("Q5", "Q6", "U202", "R206", "R207", "C27"),
    "sb": ("Q7", "Q8", "U302", "R306", "R307", "C29"),
}
PORTS = ("feed", "switch", "return", "hs", "vss", "ho", "gh", "lo", "gl")
DEFAULT_BOARD = ROOT / "battery-port-bench.kicad_pcb"


@dataclass(frozen=True)
class Copper:
    start: tuple
    end: tuple
    width: float
    thickness: float

    @property
    def length(self):
        x, y, _ = self.start
        ex, ey, _ = self.end
        return math.hypot(ex - x, ey - y)


def point(record, key):
    return tuple(map(float, first(record, key)[1:3]))


def split_trace(trace, candidates):
    """Split at same-layer T junctions, including junctions inside a segment."""
    x, y, layer = trace.start
    ex, ey, _ = trace.end
    dx, dy = ex - x, ey - y
    distance = trace.length
    if distance == 0:
        raise ValueError(f"Zero-length copper path at {trace.start}")
    points = [(0, trace.start), (1, trace.end)]
    for px, py, node_layer in candidates:
        if layer != node_layer:
            continue
        position = ((px - x) * dx + (py - y) * dy) / distance**2
        cross = abs((px - x) * dy - (py - y) * dx)
        if 0 < position < 1 and cross / distance < 1e-6:
            points.append((position, (px, py, layer)))
    ordered = [p for _, p in sorted(set(points))]
    return [Copper(a, b, trace.width, trace.thickness) for a, b in zip(ordered, ordered[1:]) if a != b]


class Layout:
    def __init__(self, board, plating):
        self.z = {}
        self.thickness = {}
        depth = 0.0
        stack = first(first(board, "setup"), "stackup")
        for layer in children(stack, "layer"):
            name = layer[1]
            thickness = children(layer, "thickness")
            if name.endswith(".Cu") or name.startswith("dielectric "):
                value = float(thickness[0][1])
                if name.endswith(".Cu"):
                    self.z[name] = -(depth + value / 2)
                    self.thickness[name] = value
                depth += value
        self.pads = {}
        barrels = []
        for footprint in children(board, "footprint"):
            ref = next(p[2] for p in children(footprint, "property") if p[1] == "Reference")
            x, y, *rotation = map(float, first(footprint, "at")[1:])
            angle = math.radians(rotation[0]) if rotation else 0
            cosine, sine = math.cos(angle), math.sin(angle)
            for pad in children(footprint, "pad"):
                if not children(pad, "net"):
                    continue
                px, py = point(pad, "at")
                centre = (round(x + px * cosine + py * sine, 6),
                          round(y - px * sine + py * cosine, 6), "F.Cu")
                # The main exposed pad is the largest of the driver's pad-11 shapes.
                size = math.prod(point(pad, "size"))
                key = (ref, pad[1])
                net = first(pad, "net")[1]
                if key not in self.pads or self.pads[key][2] < size:
                    self.pads[key] = (centre, net, size)
                if pad[2] == "thru_hole":
                    barrels.append((net, centre[:2], list(self.z), float(first(pad, "drill")[1])))
        self.graphs = defaultdict(lambda: defaultdict(list))
        traces = defaultdict(list)
        for segment in children(board, "segment"):
            layer = first(segment, "layer")[1]
            net = first(segment, "net")[1]
            start, end = ((*point(segment, key), layer) for key in ("start", "end"))
            traces[net].append(Copper(start, end, float(first(segment, "width")[1]), self.thickness[layer]))
        via_nodes = defaultdict(set)
        for via in children(board, "via"):
            net = first(via, "net")[1]
            layers = list(self.z)
            top, bottom = first(via, "layers")[1:]
            route_layers = layers[layers.index(top):layers.index(bottom) + 1]
            barrels.append((net, point(via, "at"), route_layers, float(first(via, "drill")[1])))
        for net, xy, route_layers, diameter in barrels:
            nodes = [(*xy, layer) for layer in route_layers]
            via_nodes[net].update(nodes)
            # Equal copper cross-section for the nominal cylindrical drill wall.
            shell_width = math.pi * (diameter + plating)
            for a, b in zip(nodes, nodes[1:]):
                self.add_edge(net, Copper(a, b, shell_width, plating))
        for net, segments in traces.items():
            candidates = {p for trace in segments for p in (trace.start, trace.end)} | via_nodes[net]
            for trace in segments:
                for section in split_trace(trace, candidates):
                    self.add_edge(net, section)

    def add_edge(self, net, edge):
        start, end = edge.start, edge.end
        distance = math.dist(self.xyz(start), self.xyz(end))
        self.graphs[net][start].append((distance, end, edge))
        self.graphs[net][end].append((distance, start, edge))

    def xyz(self, node):
        return (*node[:2], self.z[node[2]])

    def route(self, start_pin, end_pin, top_only=False):
        start, net, _ = self.pads[start_pin]
        end, end_net, _ = self.pads[end_pin]
        if end_net != net:
            raise ValueError(f"Different nets at {start_pin} and {end_pin}")
        queue = [(0.0, start)]
        best = {start: 0.0}
        previous = {}
        while queue:
            length, node = heapq.heappop(queue)
            if length != best[node]:
                continue
            if node == end:
                result = []
                while node != start:
                    node, edge = previous[node]
                    result.append(edge)
                return start, end, result[::-1]
            for distance, neighbour, edge in self.graphs[net].get(node, []):
                if top_only and neighbour[2] != "F.Cu":
                    continue
                total = length + distance
                if total < best.get(neighbour, math.inf):
                    best[neighbour] = total
                    previous[neighbour] = (node, edge)
                    heapq.heappush(queue, (total, neighbour))
        raise ValueError(f"No centreline path from {start_pin} to {end_pin}")


def leg_routes(layout, parts):
    high, low, driver, rh, rl, cap = parts
    pins = [
        ((cap, "1"), (high, "2")),
        ((high, "3"), (low, "2")),
        ((low, "3"), (cap, "2")),
        ((driver, "5"), (high, "3")),
        ((driver, "11"), (low, "3")),
        ((driver, "4"), (rh, "1")),
        ((rh, "2"), (high, "1")),
        ((driver, "10"), (rl, "1")),
        ((rl, "2"), (low, "1")),
    ]
    return [layout.route(start, end, top_only=i < 3) for i, (start, end) in enumerate(pins)]


def write_geometry(path, layout, routes, mesh):
    nodes = {}
    conductors = []
    ports = []
    for name, (start, end, copper) in zip(PORTS, routes):
        for edge in copper:
            a, b = edge.start, edge.end
            for node in (a, b):
                if node not in nodes:
                    nodes[node] = f"n{len(nodes)}"
            orientation = " wx=1 wy=0 wz=0" if a[:2] == b[:2] else ""
            conductors.append(f"e{len(conductors)} {nodes[a]} {nodes[b]} "
                              f"w={edge.width:.9g} h={edge.thickness:.9g}{orientation}")
        ports.append(f".external {nodes[start]} {nodes[end]} {name}")
    if len(conductors) != len(set(edge for *_, route in routes for edge in route)):
        raise ValueError("Overlapping conductor paths need an explicit shared port")
    text = ["Helios bench copper paths", ".units mm",
            f".default sigma=58000 nwinc={mesh} nhinc=2"]
    for node, name in nodes.items():
        x, y, z = layout.xyz(node)
        text.append(f"{name} x={x:.9g} y={y:.9g} z={z:.9g}")
    text += conductors + ports + [".freq fmin=1e5 fmax=1e7 ndec=1", ".end"]
    path.write_text("\n".join(text) + "\n", encoding="ascii")


def read_matrices(path):
    text = path.read_text(encoding="ascii")
    labels = re.findall(r"Row (\d+).+port name: (\S+)", text)
    names = [name for _, name in sorted(labels, key=lambda label: int(label[0]))]
    if sorted(names) != sorted(PORTS):
        raise ValueError(f"Unexpected FastHenry ports: {names}")
    order = [names.index(name) for name in PORTS]
    sections = re.split(r"Impedance matrix for frequency =\s+(\S+) \d+ x \d+\s*", text)
    matrices = {}
    for freq, values in zip(sections[1::2], sections[2::2]):
        frequency = float(freq)
        z = [[complex(float(r), float(x)) for r, x in re.findall(r"(\S+)\s+(\S+)j", row)]
             for row in values.strip().splitlines()]
        if len(z) != len(PORTS) or any(len(row) != len(PORTS) for row in z):
            raise ValueError(f"Incomplete impedance matrix at {freq} Hz")
        z = [[z[i][j] for j in order] for i in order]
        for i, row in enumerate(z):
            if row[i].real <= 0 or row[i].imag <= 0:
                raise ValueError(f"Nonpositive diagonal at {freq} Hz")
            for j, value in enumerate(row):
                if not math.isclose(abs(value - z[j][i]), 0.0, abs_tol=2e-7):
                    raise ValueError(f"Impedance matrix is not reciprocal at {freq} Hz")
        matrices[f"{frequency:g}"] = {
            "resistance_ohm": [[v.real for v in row] for row in z],
            "inductance_h": [[v.imag / (math.tau * frequency) for v in row] for row in z],
        }
    if len(matrices) != 3:
        raise ValueError("Expected impedance at 100 kHz, 1 MHz and 10 MHz")
    return matrices


def extract(board_path, executable, plating, mesh):
    layout = Layout(read_schematic(board_path), plating)
    result = {
        "board_sha256": hashlib.sha256(board_path.read_bytes()).hexdigest(),
        "via_wall_mm": plating,
        "mesh_filaments_across_width": mesh,
        "ports": PORTS,
        "legs": {},
    }
    with TemporaryDirectory() as directory:
        work = Path(directory)
        for leg, parts in LEGS.items():
            target = work / leg
            target.mkdir()
            deck = target / "layout.inp"
            routes = leg_routes(layout, parts)
            write_geometry(deck, layout, routes, mesh)
            process = subprocess.run([executable, str(deck), "-s", "ludecomp", "-m", "direct"],
                                     cwd=target, capture_output=True, text=True, timeout=90, check=False)
            if process.returncode:
                raise RuntimeError(f"FastHenry failed for {leg}:\n{process.stdout}\n{process.stderr}")
            matrices = read_matrices(target / "Zc.mat")
            result["legs"][leg] = {
                "length_mm": [sum(math.dist(layout.xyz(e.start), layout.xyz(e.end)) for e in route)
                              for _, _, route in routes],
                "frequencies_hz": matrices,
            }
            print(f"FastHenry {leg}: extracted {len(PORTS)} ports at three frequencies", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--via-wall-mm", type=float, default=0.020)
    parser.add_argument("--mesh", type=int, default=7)
    args = parser.parse_args()
    solver = shutil.which(args.fasthenry)
    if not solver or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0 or args.mesh < 1:
        parser.error("Select an available FastHenry executable, positive via wall and positive mesh")
    data = extract(args.board, str(Path(solver).resolve()), args.via_wall_mm, args.mesh)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
