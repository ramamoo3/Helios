"""Extract DC resistance and copper loss from the filled bench return planes."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import scipy
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import spsolve
import shapely as geo

from extract_layout import DEFAULT_BOARD, Layout
from verify import children, first, read_schematic


COPPER_RHO = 1.724e-5  # Ω mm at 20 °C
COPPER_TEMP_COEFF = 0.00393
COPPER_HEAT_CAPACITY = 3.45e-3  # J / (mm³ K)
PLANES = {"/P0": "In1.Cu", "/S0": "In2.Cu"}
PAIRS = {
    "/P0": (("J3.2", "C24.2"), ("C24.2", "Q2.3"), ("C24.2", "Q4.3"),
             ("C26.2", "Q2.3"), ("C28.2", "Q4.3")),
    "/S0": (("J4.2", "C25.2"), ("C25.2", "Q6.3"), ("C25.2", "Q8.3"),
             ("C27.2", "Q6.3"), ("C29.2", "Q8.3")),
    "/PRI_A": (("Q1.3", "L1.1"),),
    "/PRI_B": (("Q3.3", "T1.2"),),
    "/SEC_A": (("Q5.3", "T1.3"),),
    "/SEC_B": (("Q7.3", "T1.4"),),
    "/CT_RETURN": (("T2.3", "T1.1"),),
    "/CT_OUTBOUND": (("L1.2", "T2.4"),),
    "/PACK12": (("J3.1", "R30.1"),),
    "/PRIMARY12": (("R30.4", "Q1.2"), ("R30.4", "Q3.2")),
    "/LINK24": (("J4.1", "C25.1"), ("C25.1", "Q5.2"), ("C25.1", "Q7.2")),
}
LOADS_A = (2.67, 4.35)


def polygons(geometry):
    # make_valid can return a polygon plus the zero-area bridges used by KiCad
    # to serialize a polygon containing holes.
    parts = geo.get_parts(geo.get_parts(geometry))
    return parts[(geo.get_type_id(parts) == 3) & (geo.area(parts) > 1e-10)]


def filled_plane(board, net_id, layer):
    outlines = []
    for zone in children(board, "zone"):
        if children(zone, "keepout") or first(zone, "net")[1] != net_id:
            continue
        for fill in children(zone, "filled_polygon"):
            if first(fill, "layer")[1] == layer:
                vertices = [tuple(map(float, xy[1:])) for xy in first(fill, "pts")[1:]]
                outlines.extend(polygons(geo.make_valid(geo.Polygon(vertices))))
    if not outlines:
        raise ValueError(f"Missing filled copper for {net_id} on {layer}. Refill and save in KiCad.")
    return geo.union_all(outlines)


def plane_mesh(copper, pitch, sheet_ohm):
    left, bottom, right, top = copper.bounds
    x, y = np.meshgrid(np.arange(math.floor(left/pitch), math.ceil(right/pitch)),
                       np.arange(math.floor(bottom/pitch), math.ceil(top/pitch)))
    x, y = x.ravel(), y.ravel()
    boxes = geo.box(x*pitch, y*pitch, (x+1)*pitch, (y+1)*pitch)
    geo.prepare(copper)
    inside = geo.covers(copper, boxes)
    boundary = np.flatnonzero(~inside & geo.intersects(copper, boxes))
    clipped = geo.intersection(copper, boxes[boundary])
    parts, owner = geo.get_parts(clipped, return_index=True)
    subparts, old_owner = geo.get_parts(parts, return_index=True)
    keep = (geo.get_type_id(subparts) == 3) & (geo.area(subparts) > 1e-10)
    cells = np.concatenate((boxes[inside], subparts[keep]))
    original = np.concatenate((np.flatnonzero(inside), boundary[owner[old_owner[keep]]]))
    tree = geo.STRtree(cells)
    a, b = tree.query(cells, predicate="intersects")
    dx = x[original[b]] - x[original[a]]
    dy = y[original[b]] - y[original[a]]
    adjacent = (b > a) & (np.abs(dx) + np.abs(dy) == 1)
    a, b, horizontal = a[adjacent], b[adjacent], dx[adjacent] != 0
    across = geo.length(geo.intersection(cells[a], cells[b]))
    centroids = geo.centroid(cells)
    cx, cy = geo.get_x(centroids), geo.get_y(centroids)
    length = np.where(horizontal, np.abs(cx[a]-cx[b]), np.abs(cy[a]-cy[b]))
    connected = (across > 1e-9) & (length > 1e-9)
    return cells, tree, a[connected], b[connected], sheet_ohm * length[connected] / across[connected]


def sheet_geometry(layout, net, layer, fill, traces):
    contacts = {}
    holes = []
    for barrel in layout.barrels:
        if barrel.net == net and layer in barrel.layers:
            key = (*barrel.xy, layer)
            land = geo.Point(*barrel.xy).buffer(barrel.land/2, quad_segs=12)
            hole = geo.Point(*barrel.xy).buffer(barrel.drill/2, quad_segs=12)
            contacts[key] = geo.difference(land, hole)
            holes.append(hole)
    copper = geo.union_all([fill, *traces, *contacts.values()])
    return geo.difference(copper, geo.union_all(holes)), contacts


def return_copper(layout, net):
    by_span = {}
    for links in layout.graphs[net].values():
        for _, _, edge in links:
            key = tuple(sorted((edge.start, edge.end)))
            # Same-centreline traces are a copper union even if the router
            # left a narrower duplicate in the opposite direction.
            old = by_span.get(key)
            if old is None or edge.width * edge.thickness > old.width * old.thickness:
                by_span[key] = edge
    return by_span.values()


def conductor_network(layout, net, layer, fill, pitch, rho):
    nodes = {}
    from_node, to_node, resistance, kind, section = [], [], [], [], []
    plane_traces = []
    vias = {barrel.xy for barrel in layout.barrels if barrel.via and barrel.net == net}
    for edge in return_copper(layout, net):
        if fill is not None and edge.start[2] == edge.end[2] == layer:
            line = geo.LineString((edge.start[:2], edge.end[:2]))
            plane_traces.append(line.buffer(edge.width/2, quad_segs=8))
            continue
        length = math.dist(layout.xyz(edge.start), layout.xyz(edge.end))
        from_node.append(nodes.setdefault(edge.start, len(nodes)))
        to_node.append(nodes.setdefault(edge.end, len(nodes)))
        resistance.append(rho * length / (edge.thickness * edge.width))
        branch = "via" if edge.start[:2] in vias else "terminal_barrel"
        kind.append("trace" if edge.start[2] == edge.end[2] else branch)
        section.append(edge.thickness * edge.width)
    a, b, r = (np.asarray(value, dtype=dtype) for value, dtype in (
        (from_node, int), (to_node, int), (resistance, float)))
    metadata = {"trace_and_barrel_edges": len(a)}
    if fill is None:
        return nodes, len(nodes), a, b, r, np.asarray(kind), np.asarray(section), metadata

    copper, contacts = sheet_geometry(layout, net, layer, fill, plane_traces)
    cells, tree, c, d, sheet_r = plane_mesh(copper, pitch, rho/layout.thickness[layer])
    offset = len(nodes)
    a, b, r = np.concatenate((a, c+offset)), np.concatenate((b, d+offset)), np.concatenate((r, sheet_r))
    aliases = np.arange(offset + len(cells))

    def root(index):
        while aliases[index] != index:
            aliases[index] = aliases[aliases[index]]
            index = aliases[index]
        return index

    touches = Counter()
    for key, annulus in contacts.items():
        if key not in nodes:
            raise ValueError(f"Missing plated connection for same-net land {key}")
        hits = tree.query(annulus, predicate="intersects")
        hits = hits[geo.area(geo.intersection(cells[hits], annulus)) > 1e-9]
        if not len(hits):
            raise ValueError(f"Mesh lost plated contact at {key}")
        touches.update(hits.tolist())
        for hit in hits:
            aliases[root(hit + offset)] = root(nodes[key])
    _, compressed = np.unique([root(i) for i in range(len(aliases))], return_inverse=True)
    nodes = {node: int(compressed[index]) for node, index in nodes.items()}
    a, b = compressed[a], compressed[b]
    keep = a != b
    kinds = np.asarray([*kind, *(["plane"] * len(sheet_r))])
    sections = np.concatenate((section, np.zeros(len(sheet_r))))
    metadata.update({"fill_area_mm2": float(geo.area(fill)), "modeled_area_mm2": float(geo.area(copper)),
                     "mesh_cells": len(cells), "plated_contacts": len(contacts),
                     "cells_touching_multiple_contacts": sum(count > 1 for count in touches.values())})
    return nodes, int(compressed.max())+1, a[keep], b[keep], r[keep], kinds[keep], sections[keep], metadata


def analyze(layout, net, name, layer, fill, pitch):
    nodes, count, a, b, r, kinds, sections, metadata = conductor_network(layout, net, layer, fill, pitch, COPPER_RHO)
    g = 1/r
    matrix = coo_matrix((np.concatenate((g, g, -g, -g)),
                         (np.concatenate((a, b, a, b)), np.concatenate((a, b, b, a)))),
                        shape=(count, count)).tocsr()
    _, component = connected_components(matrix, directed=False)
    cases = {}
    for source, sink in PAIRS[name]:
        p, q = [nodes[layout.pads[tuple(pin.split("."))][0]] for pin in (source, sink)]
        if p == q or component[p] != component[q]:
            raise ValueError(f"Invalid mesh connectivity for {source} to {sink}")
        active = np.flatnonzero(component == component[p])
        free = active[active != q]
        rhs = np.zeros(len(free))
        rhs[np.searchsorted(free, p)] = 1.0
        v = np.zeros(count)
        v[free] = spsolve(matrix[free][:, free], rhs)
        amps = np.abs(v[a]-v[b])*g
        loss = amps**2*r
        equivalent = float(v[p])
        if equivalent <= 0 or not math.isclose(float(loss.sum()), equivalent, rel_tol=1e-7):
            raise ValueError(f"Copper energy check failed for {source} to {sink}")
        temperature_factor = 1+COPPER_TEMP_COEFF*(100-20)
        remaining = sections > 0
        max_density = float((amps[remaining]/sections[remaining]).max(initial=0))
        pulse_rise = (max_density*max(LOADS_A))**2 * COPPER_RHO * temperature_factor * 1e-6 / COPPER_HEAT_CAPACITY
        cases[f"{source} to {sink}"] = {
            "resistance_mohm_20c": equivalent*1000,
            "copper_loss_w_100c_at_current_a": {str(current): equivalent*temperature_factor*current**2
                                                for current in LOADS_A},
            "loss_fraction_by_conductor": {str(kind): float(loss[kinds == kind].sum())/equivalent
                                           for kind in np.unique(kinds)},
            "max_via_current_fraction": float(amps[kinds == "via"].max(initial=0)),
            "peak_trace_or_barrel_density_a_per_mm2_at_2_67a": max_density*LOADS_A[0],
            "trace_or_barrel_adiabatic_rise_k_for_1us_4_35a_at_100c": pulse_rise,
        }
    return {"network": metadata, "paths": cases}


def run(args):
    filled = read_schematic(args.filled)
    boards = [("filled", filled)]
    files = {"filled PCB": args.filled, "solver": Path(__file__),
             "layout parser": Path(__file__).with_name("extract_layout.py"),
             "KiCad parser": Path(__file__).with_name("verify.py")}
    if args.baseline is not None:
        baseline = read_schematic(args.baseline)
        if any(not children(z, "keepout") for z in children(baseline, "zone")):
            raise ValueError("Choose a trace-only baseline PCB")
        boards = [("baseline", baseline), ("trial", filled)]
        files["baseline PCB"] = args.baseline
    results = {}
    for label, board in boards:
        names = {value[2]: value[1] for value in children(board, "net")}
        for plating in args.plating_mm:
            layout = Layout(board, plating)
            for name in PAIRS:
                layer = PLANES.get(name)
                net = names.get(name, name)
                fill = filled_plane(board, net, layer) if label != "baseline" and layer is not None else None
                for pitch in args.pitch_mm if fill is not None else (None,):
                    key = f"{label} {name} plating {plating:g} mm"
                    if pitch is not None:
                        key += f" pitch {pitch:g} mm"
                    results[key] = analyze(layout, net, name, layer, fill, pitch)
                    if layer is not None:
                        print(key, "complete", flush=True)
    return {"scope": "DC copper screen with unit-current terminal excitations, ideal pad lands and prescribed copper temperatures",
            "inputs_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
            "versions": {"numpy": np.__version__, "scipy": scipy.__version__, "shapely": geo.__version__},
            "cases": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filled", type=Path, nargs="?", default=DEFAULT_BOARD)
    parser.add_argument("--baseline", type=Path, help="optional trace-only PCB for comparison")
    parser.add_argument("--pitch-mm", type=float, nargs="+", default=[.8, .4, .2])
    parser.add_argument("--plating-mm", type=float, nargs="+", default=[.020, .025])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(not math.isfinite(value) or value <= 0 for value in (*args.pitch_mm, *args.plating_mm)):
        parser.error("Pitch and via plating must be finite and positive")
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
