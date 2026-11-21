"""Write a trial with split return planes and wider inner winding routes."""

import argparse
import math
from pathlib import Path
import re
from uuid import UUID, uuid5

from extract_layout import DEFAULT_BOARD
from verify import children, first, read_schematic


PLANES = (
    ("/P0", "In1.Cu", "Primary return", 35.5, 94.4),
    ("/S0", "In2.Cu", "Secondary return", 97.6, 156.5),
)
OUTLINE_ID = UUID("b2bc37b5-3d6b-5681-ad1e-547c5b3cca83")
WINDING_NETS = ("/CT_RETURN", "/PRI_B", "/SEC_A", "/SEC_B")
MOUNTS = ((52, 47), (147, 62), (52, 132), (152, 140))
FIDUCIALS = ((48.5, 43.5), (139, 44), (144, 142))


def place(template, reference, x, y):
    path = DEFAULT_BOARD.parent / "Helios_Bench.pretty" / f"{template}.kicad_mod"
    footprint = path.read_text(encoding="ascii")
    body = footprint[footprint.index('  (descr'):]
    instance = (f'  (footprint "Helios_Bench:{template}" (layer "F.Cu") (at {x:g} {y:g}) '
                f'(uuid "{uuid5(OUTLINE_ID, reference)}")\n')
    return instance + body.replace('"REF**"', f'"{reference}"', 1)


def keepout(reference, x, y):
    # The 32-sided boundary circumscribes the 6.4 mm hardware keepout.
    radius = 3.2 / math.cos(math.pi/32)
    points = " ".join(f"(xy {x + radius*math.cos(t*math.tau/32):.5f} {y + radius*math.sin(t*math.tau/32):.5f})"
                      for t in range(32))
    return f'''  (zone (net 0) (net_name "") (layers "F.Cu" "In1.Cu" "In2.Cu" "B.Cu")
    (uuid "{uuid5(OUTLINE_ID, reference+' keepout')}") (name "{reference} hardware") (hatch edge 0.5)
    (connect_pads (clearance 0)) (min_thickness 0.25)
    (keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed))
    (fill (thermal_gap 0.3) (thermal_bridge_width 0.3)) (polygon (pts {points})))
'''


def widen_winding_routes(source, nets):
    ids = "|".join(nets[net] for net in WINDING_NETS)
    width = rf'(?m)^(  \(segment [^\n]*\(width )1\.(?:2|25)(?=\) \(layer "In2\.Cu"\) \(net (?:{ids})\))'
    source, count = re.subn(width, r"\g<1>1.6", source)
    if count != 20:
        raise ValueError("Review which winding segments carry power on the revised board")
    old = (f'  (segment (start 115.4 59.4) (end 108.7 52.7) (width 1.6) '
           f'(layer "In2.Cu") (net {nets["/SEC_B"]}) (uuid "fef45fbd-5c4c-5364-9364-ceb721200f72"))')
    if source.count(old) != 1:
        raise ValueError("Review the SEC_B approach to the transformer")
    # The shifted diagonal clears the adjacent unnumbered transformer land.
    route = ("115.4 59.4", "115.4 58.6", "109.5 52.7", "108.7 52.7")
    replacement = "\n".join(
        f'  (segment (start {a}) (end {b}) (width 1.6) (layer "In2.Cu") '
        f'(net {nets["/SEC_B"]}) (uuid "{uuid5(OUTLINE_ID, a + " to " + b)}"))'
        for a, b in zip(route, route[1:])
    )
    return source.replace(old, replacement)


def write_trial(output, baseline):
    board = read_schematic(baseline)
    if any(not children(zone, "keepout") for zone in children(board, "zone")):
        raise ValueError("Update the plane trial for the existing board pours")
    outline = next(rect for rect in children(board, "gr_rect") if first(rect, "layer")[1] == "Edge.Cuts")
    if (first(outline, "start")[1:] != ["35", "42"] or first(outline, "end")[1:] != ["157", "145"]):
        raise ValueError("Update the plane geometry for the new bench outline")
    nets = {value[2]: value[1] for value in children(board, "net")}
    source = baseline.read_text(encoding="utf-8").rstrip().removesuffix(")")
    source = widen_winding_routes(source, nets)
    fixtures = []
    for i, (x, y) in enumerate(MOUNTS, 1):
        fixtures.extend((place("Bench_mount_M2_5", f"H{i}", x, y), keepout(f"H{i}", x, y)))
    for i, (x, y) in enumerate(FIDUCIALS, 1):
        fixtures.append(place("Bench_fiducial_1mm", f"FID{i}", x, y))
    zones = []
    for net, layer, name, left, right in PLANES:
        zones.append(f'''  (zone (net {nets[net]}) (net_name "{net}") (layer "{layer}") (uuid "{uuid5(OUTLINE_ID, net)}")
    (name "{name}") (hatch edge 0.5) (connect_pads (clearance 0.25)) (min_thickness 0.20)
    (fill yes (thermal_gap 0.28) (thermal_bridge_width 0.35) (island_removal_mode 0))
    (polygon (pts (xy {left} 42.5) (xy {right} 42.5) (xy {right} 144.5) (xy {left} 144.5))))
''')
    with output.open("x", encoding="utf-8", newline="\n") as trial:
        trial.write(source + "".join(fixtures + zones) + ")\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new .kicad_pcb path in a scratch project")
    parser.add_argument("--baseline", type=Path, required=True, help="archived trace-only bench PCB")
    args = parser.parse_args()
    write_trial(args.output, args.baseline)
