"""Extract the force and Kelvin impedance of the candidate WSK2512 land pattern."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from extract_layout import point, read_matrices
from verify import ROOT, children, read_schematic


FOOTPRINT = ROOT / "Helios_Bench.pretty" / "Shunt_Vishay_WSK2512_5mR.kicad_mod"
PORTS = ("force", "kelvin")
COPPER = 58000  # S/mm
TARGET_OHM = 0.005
# The vendor STEP model for 0.005–0.2 ohm gives these conductor boundaries.
WIDTH_BINS = (-1.590, -0.828, -0.320, 0.320, 0.828, 1.590)
EDGE = 3.175
NOTCH = 2.286
WELD = 1.985
TERMINAL_H = 0.635
ALLOY_H = 0.245
FOIL_H = 0.035


@dataclass(frozen=True)
class Mount:
    contact_x: float = 2.75
    solder_mm: float = 0.065
    force_lead_mm: float = 0.5
    sense_lead_mm: float = 0.25


MOUNTS = {
    "nominal": Mount(),
    "inboard_contact": Mount(contact_x=2.53, solder_mm=0.040),
    "outboard_contact": Mount(contact_x=3.00, solder_mm=0.100),
    "long_fanout": Mount(force_lead_mm=1.5, sense_lead_mm=0.75),
}


class Deck:
    def __init__(self, mesh):
        self.mesh = mesh
        self.nodes = {}
        self.beams = []

    def beam(self, a, b, width, height, sigma=COPPER):
        for p in (a, b):
            if p not in self.nodes:
                self.nodes[p] = f"n{len(self.nodes)}"
        orientation = " wx=0 wy=1 wz=0" if a[:2] == b[:2] else ""
        self.beams.append(f"e{len(self.beams)} {self.nodes[a]} {self.nodes[b]} w={width:.8g} "
                          f"h={height:.8g} sigma={sigma:.9g}{orientation}")

    def sheet(self, xs, lanes, height, sigma, present):
        # The grid spreads terminal current in the plate. Lane width sets the
        # longitudinal section and local station spacing sets the transverse section.
        for (y, width) in lanes:
            for a, b in zip(xs, xs[1:]):
                if present(a, y) and present(b, y):
                    self.beam((a, y, height[0]), (b, y, height[0]), width, height[1], sigma)
        for i, x in enumerate(xs):
            tributary = ((x-xs[i-1] if i else 0) + (xs[i+1]-x if i+1 < len(xs) else 0)) / 2
            for (a, _), (b, _) in zip(lanes, lanes[1:]):
                if present(x, a) and present(x, b):
                    self.beam((x, a, height[0]), (x, b, height[0]), tributary, height[1], sigma)

    def write(self, path, ports):
        lines = ["Helios WSK2512 candidate mounted shunt", ".units mm",
                 f".default nwinc={self.mesh} nhinc={self.mesh} rw=2 rh=2"]
        for (x, y, z), name in self.nodes.items():
            lines.append(f"{name} x={x:.8g} y={y:.8g} z={z:.8g}")
        for name, (origin, destination) in zip(PORTS, ports, strict=True):
            self.beams.append(f".external {self.nodes[origin]} {self.nodes[destination]} {name}")
        lines += self.beams + [".freq fmin=1e5 fmax=1e7 ndec=1", ".end"]
        path.write_text("\n".join(lines) + "\n", encoding="ascii")


def geometry(path, lands, mount, mesh, alloy_sigma):
    deck = Deck(mesh)
    lanes = [((a+b)/2, b-a) for a, b in zip(WIDTH_BINS, WIDTH_BINS[1:])]
    alloy_z = TERMINAL_H - ALLOY_H / 2
    terminal_z = TERMINAL_H / 2
    pcb_z = -(mount.solder_mm + FOIL_H / 2)
    deck.sheet((-WELD, 0.0, WELD), lanes, (alloy_z, ALLOY_H), alloy_sigma, lambda *_: True)
    external = {}
    for direction, pad_ids in ((-1, ("1", "2")), (1, ("4", "3"))):
        stations = sorted(direction*x for x in (WELD, NOTCH, mount.contact_x, EDGE))
        deck.sheet(stations, lanes, (terminal_z, TERMINAL_H), COPPER,
                   lambda x, y: abs(x) <= NOTCH or not 0.320 < direction*y < 0.828)
        for y, width in lanes:
            weld_x = direction*WELD
            deck.beam((weld_x, y, terminal_z), (weld_x, y, alloy_z), width, 0.20)
        for index, pad_id in enumerate(pad_ids):
            (x, y), (length, width) = lands[pad_id]
            contact_y, lane_width = min(lanes, key=lambda lane: abs(lane[0]-y))
            contact_x = direction*mount.contact_x
            if abs(contact_x-x) > length/2 or abs(contact_y-y) > width/2:
                raise ValueError(f"Solder contact misses pad {pad_id}")
            edge = (x + direction*length/2, contact_y, pcb_z)
            contact = (contact_x, contact_y, pcb_z)
            terminal = (contact_x, contact_y, terminal_z)
            deck.beam(contact, terminal, min(width, lane_width), 0.40, 7000)
            deck.beam(contact, edge, width, FOIL_H)
            lead = mount.force_lead_mm if index == 0 else mount.sense_lead_mm
            external[pad_id] = (edge[0] + direction*lead, edge[1], pcb_z)
            deck.beam(edge, external[pad_id], 1.2 if index == 0 else 0.25, FOIL_H)
    deck.write(path, [(external["1"], external["4"]), (external["2"], external["3"])])


def run_solver(solver, directory, lands, mount, mesh, alloy_sigma):
    source = directory / "coupon.inp"
    geometry(source, lands, mount, mesh, alloy_sigma)
    process = subprocess.run([solver, str(source), "-s", "ludecomp", "-m", "direct"],
                             cwd=directory, capture_output=True, text=True, timeout=120)
    if process.returncode:
        raise RuntimeError(f"FastHenry failed:\n{process.stdout}\n{process.stderr}")
    return read_matrices(directory / "Zc.mat", PORTS)


def calibrated_models(solver):
    lands = {p[1]: (point(p, "at"), point(p, "size"))
             for p in children(read_schematic(FOOTPRINT), "pad")}
    alloy_sigma = (2*WELD) / (TARGET_OHM * ALLOY_H * (WIDTH_BINS[-1]-WIDTH_BINS[0]))
    with TemporaryDirectory() as scratch:
        directory = Path(scratch)
        for _ in range(3):
            coarse = run_solver(solver, directory, lands, MOUNTS["nominal"], 3, alloy_sigma)
            measured = coarse["100000"]["resistance_ohm"][1][0]
            if measured <= 0:
                raise ValueError("Expected positive Kelvin polarity on the 5 mΩ coupon")
            alloy_sigma *= measured/TARGET_OHM
        cases = {}
        for name, mount in MOUNTS.items():
            exact = run_solver(solver, directory, lands, mount, 5, alloy_sigma)
            transfer_ohm = exact["100000"]["resistance_ohm"][1][0]
            transfer_nh = exact["1e+07"]["inductance_h"][1][0] * 1e9
            cases[name] = {"mount": vars(mount), "impedance": exact,
                           "kelvin_resistance_mohm": transfer_ohm * 1e3,
                           "kelvin_inductance_nh": transfer_nh,
                           "ideal_filter_nf": 11 * transfer_nh / (transfer_ohm * 1e3)}
            print(name, f"{transfer_ohm*1e3:.3f} milliohm Kelvin, {transfer_nh:.3f} nH Kelvin", flush=True)
    nominal = cases["nominal"]
    if not math.isclose(nominal["kelvin_resistance_mohm"], 5, abs_tol=0.05):
        raise ValueError("The fitted nominal model missed the 5 mΩ Kelvin target")
    return {
        "footprint_sha256": hashlib.sha256(FOOTPRINT.read_bytes()).hexdigest(),
        "ports": PORTS,
        "alloy_conductivity_s_per_mm": alloy_sigma,
        "coarse_mesh_nominal": coarse,
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fasthenry", default="fasthenry")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solver = shutil.which(args.fasthenry)
    if not solver:
        parser.error("FastHenry console executable unavailable")
    data = calibrated_models(str(Path(solver).resolve()))
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
