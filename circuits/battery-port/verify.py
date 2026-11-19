"""Check the Helios pin maps and bench layout, then run the SPICE test decks."""
import argparse
from collections import defaultdict
from itertools import product
from pathlib import Path
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from startup_test import check_startup

ROOT = Path(__file__).resolve().parent
SENSE = """
PACK_V J1.1 R1.1
KELVIN_P J1.2 U1.2
KELVIN_N J1.3 U1.3
PACK_0 J1.4 J2.4 U1.4 U1.6 R4.2 C1.2 C2.2 C3.2
V3V3 J2.1 U1.5 U1.7 C2.1
I_ADC J2.2 R5.2 C3.1
V_ADC J2.3 R3.2 R4.1 C1.1
R1.2 R2.1
R2.2 R3.1
U1.8 R5.1
NC U1.1
"""
POWER = """
PACK_SW_P Q1.2 Q3.2
PACK_0 Q2.3 Q4.3
PRI_A Q1.3 Q2.2 L1.1
PRI_B Q3.3 Q4.2 T1.2
L1.2 T1.1
SEC_A Q5.3 Q6.2 T1.3
SEC_B Q7.3 Q8.2 T1.4
LINK_P Q5.2 Q7.2
LINK_N Q6.3 Q8.3
""" + "\n".join(f"G{i} Q{i}.1" for i in range(1, 9))

DRIVER = """
BIAS_10V U2.1 C4.1 C5.1
NC U2.2
BOOT U2.3 C6.1 #FLG1.1
HO_RAW U2.4 R6.1
SW U2.5 C6.2 R8.2
PERMIT U2.6 R10.1
PWM_H U2.7
PWM_L U2.8
DRV_0 U2.9 U2.11 C4.2 C5.2 R9.2 R10.2
LO_RAW U2.10 R7.1
GATE_H R6.2 R8.1
GATE_L R7.2 R9.1
"""


DETECTOR = """
FROM_L1 T2.4
TO_T1 T2.3
CT_OUT T2.1 R11.1 R12.1
MID T2.2 R11.2 R14.2 R15.1 C7.1
ISENSE R12.2 U3.2 U3.5
P3V3 R13.1 C8.1 U3.8
V_HI R13.2 R14.1 U3.3
V_LO R15.2 R16.1 U3.6
P0 R16.2 C7.2 C8.2 U3.4
HI_OK U3.1
LO_OK U3.7
"""
TRIPLOGIC = """
HI_OK U4.1
LO_OK U4.2
WINDOW_OK U4.3 U4.9
PRI_OK U4.4 R19.1
SEC_OK_P U4.5
BOTH_OK U4.6 U4.10
CLEAR_N U4.8 U5.6
ARMED U5.5 U4.12
RUN U4.13 U6.2 R18.1
PERMIT_P U4.11
RUN_N U6.4 U5.2
NC-U5.3 U5.3
ARM U5.1 R17.1
NC-U6.1 U6.1
P3V3 U4.14 U5.8 U5.7 U6.5 C9.1 C10.1 C11.1
P0 U4.7 U5.4 U6.3 R17.2 R18.2 R19.2 C9.2 C10.2 C11.2
"""
ISOLATION = """
P3V3 U7.1 U7.3 U8.8 C12.1 C15.1
S3V3 U7.8 U8.1 U8.3 C13.1 C14.1
P0 U7.4 U8.5 C12.2 C15.2 R21.2
S0 U7.5 U8.4 C13.2 C14.2 R20.2
PERMIT_P U7.2
PERMIT_S U7.6
SEC_OK U8.2 R20.1
SEC_OK_P U8.6 R21.1
NC-U7.7 U7.7
NC-U8.7 U8.7
"""


BIAS = """
RAW U9.8 U9.5 C16.1
RTN U9.4 U9.6 U9.9 U10.2 U10.4 U11.2 R23.2 C16.2 C17.2 C18.2 C19.2 C20.2
DRIVE U9.1 R22.1 U10.1 U10.3 C17.1 C20.1
FB U9.2 R22.2 R23.1
PG10 U9.3 R24.2 U11.3
NC-U9.7 U9.7
NC-U11.4 U11.4
LOGIC U10.5 U11.5 U11.6 R24.1 R25.1 C18.1 C19.1
OK U11.1 R25.2
"""
PWM = """
P3V3 U12.1 C21.1
P0 U12.4 C21.2 R26.2 R27.2 R28.2 R29.2
S3V3 U12.8 U13.5 C22.1 C23.1
S0 U12.5 U13.3 C22.2 C23.2
P_POS R26.1
P_NEG R27.1
S_POS_IN U12.2 R28.1
S_NEG_IN U12.3 R29.1
S_POS U12.7
S_NEG U12.6
PERMIT_S U13.1
SEC_OK U13.2
SEC_EN U13.4
"""
BENCH_IO = """
PACK12 J3.1 R30.1
P0 J3.2 J5.9 C24.2 C26.2 C28.2
LINK24 J4.1 C25.1 C27.1 C29.1
S0 J4.2 C25.2 C27.2 C29.2
PRIMARY12 R30.4 C24.1 C26.1 C28.1
KP R30.2
KN R30.3
P_POS J5.1
P_NEG J5.2
S_POS_IN J5.3
S_NEG_IN J5.4
RUN J5.5
ARM J5.6
I_ADC J5.7
V_ADC J5.8
PERMIT_P J5.10
PRE_REQ J5.11
PRE_ACK_P J5.12
PRE_ACK_S J5.13
"""


PRECHARGE = """
P3V3 U40.14 U41.14 U42.14 U43.14 U48.1 C40.1 C41.1 C42.1 C43.1 C48.1
P0 U40.7 U40.9 U40.11 U40.13 U41.7 U41.9 U41.10 U41.12 U41.13 U42.7 U43.7 U48.4 R40.2 R41.2 R42.2 C40.2 C41.2 C42.2 C43.2 C48.2
S3V3 U44.14 U45.14 U46.14 U47.14 U48.8 C44.1 C45.1 C46.1 C47.1 C49.1
S0 U44.7 U44.9 U44.11 U44.13 U45.7 U45.9 U45.10 U45.12 U45.13 U46.7 U47.7 U48.5 C44.2 C45.2 C46.2 C47.2 C49.2
P_POS U40.1 U41.5 U42.9
P_NEG U40.3 U41.2 U42.12
S_POS U44.1 U45.5 U46.9
S_NEG U44.3 U45.2 U46.12
PERMIT_P U43.13
SEC_EN U47.13
PRE_REQ U40.5 U41.1 U41.4 U48.3 R40.1
PRE_ACK_P U43.11 R41.1
PRE_ACK_S U48.2 R42.1
PA_H U43.3
PA_L U42.3 U43.9
PB_H U43.6
PB_L U42.6 U43.10
SA_H U47.3
SA_L U46.3 U47.9
SB_H U47.6
SB_L U46.6 U47.10
P_NP U40.2 U42.1 U42.13
P_NN U40.4 U42.4 U42.10
P_NPC U40.6 U43.2 U43.5
NC-U40.8 U40.8
NC-U40.10 U40.10
NC-U40.12 U40.12
P_XN U41.3 U42.2
P_XP U41.6 U42.5
NC-U41.8 U41.8
NC-U41.11 U41.11
P_PX U42.8 U43.1
P_NX U42.11 U43.4
P_ACK U43.8 U43.12
S_NP U44.2 U46.1 U46.13
S_NN U44.4 U46.4 U46.10
PRE_S U44.5 U45.1 U45.4 U48.6
S_NPC U44.6 U47.2 U47.5
NC-U44.8 U44.8
NC-U44.10 U44.10
NC-U44.12 U44.12
S_XN U45.3 U46.2
S_XP U45.6 U46.5
NC-U45.8 U45.8
NC-U45.11 U45.11
S_PX U46.8 U47.1
S_NX U46.11 U47.4
S_ACK U47.8 U47.12
S_LOCAL_ACK U47.11 U48.7
"""


def check_precharge_logic():
    pins = {}
    for line in PRECHARGE.strip().splitlines():
        net, *terminals = line.split()
        pins.update((pin, net) for pin in terminals)
    quad = [(1, 2, 3), (4, 5, 6), (9, 10, 8), (12, 13, 11)]
    commands = {(True, False, False): (True, False, False, True),
                (False, True, False): (False, True, True, False),
                (False, False, True): (False, True, False, True)}
    inputs = ("P_POS", "P_NEG", "S_POS", "S_NEG", "PRE_REQ", "PERMIT_P", "SEC_EN")
    for pattern in product((False, True), repeat=len(inputs)):
        signals = dict(zip(inputs, pattern))
        signals.update(P0=False, S0=False, P3V3=True, S3V3=True)

        def read(unit, pin):
            return signals[pins[f"U{unit}.{pin}"]]

        def set_pin(unit, pin, value):
            signals[pins[f"U{unit}.{pin}"]] = value

        set_pin(48, 6, read(48, 3))
        for prefix, base, enable in (("P", 40, "PERMIT_P"), ("S", 44, "SEC_EN")):
            for inp, out in ((1, 2), (3, 4), (5, 6), (9, 8), (11, 10), (13, 12)):
                set_pin(base, out, not read(base, inp))
            for a, b, y in quad:
                set_pin(base + 1, y, read(base + 1, a) ^ read(base + 1, b))
            for unit in (base + 2, base + 3):
                for a, b, y in quad:
                    set_pin(unit, y, read(unit, a) and read(unit, b))

            pos, neg = signals[prefix + "_POS"], signals[prefix + "_NEG"]
            pre = signals["PRE_REQ"]
            actual = tuple(signals[prefix + output] for output in ("A_H", "A_L", "B_H", "B_L"))
            if actual != commands.get((pos, neg, pre), (False,) * 4):
                raise ValueError(f"Unsafe {prefix} gate decode for {pattern}: {actual}")
            ack = "PRE_ACK_P" if prefix == "P" else "S_LOCAL_ACK"
            if signals[ack] != (signals[enable] and pre and not pos and not neg):
                raise ValueError(f"Unexpected {prefix} acknowledgement for {pattern}")

        set_pin(48, 2, read(48, 7))
        if signals["PRE_ACK_S"] != signals["S_LOCAL_ACK"]:
            raise ValueError(f"Incorrect isolated precharge acknowledgement for {pattern}")
    print("Precharge gate truth table passed for all 128 combinations")


def read_schematic(path):
    stack = [[]]
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', path.read_text(encoding="utf-8-sig")):
        if token == "(":
            child = []
            stack[-1].append(child)
            stack.append(child)
        elif token == ")":
            stack.pop()
        else:
            stack[-1].append(token.strip('"'))
    if len(stack) != 1 or len(stack[0]) != 1:
        raise ValueError(f"Invalid schematic tree in {path}")
    return stack[0][0]


def children(tree, key):
    return [v for v in tree if isinstance(v, list) and v[0] == key]


def first(tree, key):
    return children(tree, key)[0]


def coord(tree):
    return tuple(round(float(v) * 1000) for v in tree[1:3])


def check_bench_via_clearance(path):
    """Detect via holes in SMD solder lands, including vias on the pad's net."""
    board = read_schematic(path)
    vias = [
        (*map(float, first(via, "at")[1:3]), float(first(via, "drill")[1]) / 2,
         set(first(via, "layers")[1:]))
        for via in children(board, "via")
    ]
    overlaps = []
    for footprint in children(board, "footprint"):
        ref = next(prop[2] for prop in children(footprint, "property") if prop[1] == "Reference")
        layer = first(footprint, "layer")[1]
        fx, fy, *rotation = map(float, first(footprint, "at")[1:])
        angle = math.radians(rotation[0]) if rotation else 0
        cosine, sine = math.cos(angle), math.sin(angle)
        for pad in children(footprint, "pad"):
            if pad[2] != "smd" or layer not in first(pad, "layers")[1:]:
                continue
            px, py, *rotation = map(float, first(pad, "at")[1:])
            x, y = fx + cosine * px + sine * py, fy - sine * px + cosine * py
            # PCB pad angles are absolute. Their offsets are relative to the footprint.
            angle = math.radians(rotation[0]) if rotation else 0
            pad_cos, pad_sin = math.cos(angle), math.sin(angle)
            width, height = map(float, first(pad, "size")[1:3])
            if pad[3] == "roundrect":
                radius = min(width, height) * float(first(pad, "roundrect_rratio")[1])
            elif pad[3] == "rect":
                radius = 0
            elif pad[3] in ("circle", "oval"):
                radius = min(width, height) / 2
            else:
                raise ValueError(f"Unsupported SMD land shape at {ref}.{pad[1]}: {pad[3]}")
            # The land is a rectangle with its edges and corners expanded by the radius.
            half_width, half_height = width / 2 - radius, height / 2 - radius
            for vx, vy, drill_radius, via_layers in vias:
                if layer not in via_layers:
                    continue
                dx, dy = vx - x, vy - y
                local_x = abs(pad_cos * dx - pad_sin * dy)
                local_y = abs(pad_sin * dx + pad_cos * dy)
                distance = math.hypot(max(local_x - half_width, 0), max(local_y - half_height, 0))
                if distance <= radius + drill_radius:
                    overlaps.append(f"{ref}.{pad[1]} at ({vx:g}, {vy:g}) mm")
    if overlaps:
        raise ValueError("Via holes intersect SMD solder lands: " + ", ".join(overlaps))
    print(f"Bench PCB: all {len(vias)} via holes clear SMD solder lands", flush=True)


def check_sheet(name, expected):
    base = ROOT / f"battery-port-{name}"
    ET.parse(base.with_suffix(".svg"))
    sheet = read_schematic(base.with_suffix(".kicad_sch"))
    nodes = defaultdict(set)
    nets = defaultdict(set)

    def edge(a, b):
        nodes[a].add(b)
        nodes[b].add(a)

    library = {s[1]: s for s in children(first(sheet, "lib_symbols"), "symbol")}
    external = {s[1]: s for s in children(read_schematic(ROOT / "Helios.kicad_sym"), "symbol")}
    for lib_id, cached in library.items():
        if cached[2:] != external[lib_id.split(":")[1]][2:]:
            raise ValueError(f"{lib_id} differs from the project symbol library")
    for symbol in children(sheet, "symbol"):
        ref = next(p[2] for p in children(symbol, "property") if p[1] == "Reference")
        at = first(symbol, "at")
        if at[3] != "0" or children(symbol, "mirror"):
            raise ValueError("Update the pin projection for rotated or mirrored symbols")
        x, y = coord(at)
        for unit in children(library[first(symbol, "lib_id")[1]], "symbol"):
            for pin in children(unit, "pin"):
                dx, dy = coord(first(pin, "at"))
                key = ref + "." + first(pin, "number")[1]
                edge(key, (x + dx, y - dy))

    for label in children(sheet, "label"):
        edge(label[1], coord(first(label, "at")))
    for port in children(sheet, "hierarchical_label"):
        edge("port:" + port[1], coord(first(port, "at")))
    marks = children(sheet, "no_connect")
    for mark in marks:
        point = coord(first(mark, "at"))
        pins = [p for p in nodes[point] if isinstance(p, str) and "." in p]
        if len(pins) != 1:
            raise ValueError(f"NC flag must identify one pin at {point}")
        edge("NC" if len(marks) == 1 else "NC-" + pins[0], point)

    # Both sheets use split wires at every branch, junction and label anchor.
    for wire in children(sheet, "wire"):
        a, b = children(first(wire, "pts"), "xy")
        edge(coord(a), coord(b))

    seen = set()
    for terminal in list(nodes):
        if isinstance(terminal, str) and terminal not in seen:
            todo = [terminal]
            while todo:
                n = todo.pop()
                if n in seen:
                    continue
                seen.add(n)
                if isinstance(n, str):
                    nets[terminal].add(n)
                todo.extend(nodes[n] - seen)
    for group in nets.values():
        for item in group.copy():
            if item.startswith("port:"):
                if item[5:] not in group:
                    raise ValueError(f"Disconnected hierarchy port: {name}/{item}")
                group.remove(item)
    actual = {frozenset(group) for group in nets.values()}
    wanted = {frozenset(line.split()) for line in expected.splitlines() if line.strip()}
    if actual != wanted:
        raise ValueError(f"{name} pin-map mismatch. Missing {wanted - actual}, extra {actual - wanted}")
    pin_count = sum(bool(re.fullmatch(r"[A-Z]+\d+\.\d+", s)) for group in actual for s in group)
    print(f"{name}: all {pin_count} pins on expected nets", flush=True)


def check_bench_hierarchy():
    project = "battery-port-bench"
    root = read_schematic(ROOT / f"{project}.kicad_sch")
    root_id = first(root, "uuid")[1]
    # Each top-level wire connects a local net label directly to a sheet pin.
    labels = {coord(first(label, "at")): label[1] for label in children(root, "label")}
    connected = {}
    for wire in children(root, "wire"):
        ends = [coord(p) for p in children(first(wire, "pts"), "xy")]
        anchors = [p for p in ends if p in labels]
        if len(anchors) != 1:
            raise ValueError(f"Expected one labeled wire endpoint: {ends}")
        other = next(p for p in ends if p != anchors[0])
        if other in connected:
            raise ValueError(f"Ambiguous parent wiring at {other}")
        connected[other] = labels[anchors[0]]

    expected = {
        "Bench terminals": ("bench-io", BENCH_IO, {}),
        "Bench power stage": ("bench-power", None, {"PACK_SW_P": "PRIMARY12", "PACK_0": "P0",
            "LINK_P": "LINK24", "LINK_N": "S0"}),
        "Pack telemetry": ("sense", None, {"PACK_V": "PACK12", "KELVIN_P": "KP",
            "KELVIN_N": "KN", "PACK_0": "P0", "V3V3": "P3V3"}),
        "Transformer current trip": ("detector", None, {"FROM_L1": "CT_OUTBOUND", "TO_T1": "CT_RETURN"}),
        "Latch and re-arm": ("triplogic", None, {}),
        "Isolated permission": ("trip-isolation", None, {}),
        "PWM and local inhibit": ("pwm", PWM, {}),
    }
    expected["Bootstrap precharge and gate decode"] = ("precharge", None, {})
    required = {
        "precharge": "P3V3 P0 S3V3 S0 P_POS P_NEG S_POS S_NEG PERMIT_P SEC_EN PRE_REQ PRE_ACK_P PRE_ACK_S PA_H PA_L PB_H PB_L SA_H SA_L SB_H SB_L",
        "bench-power": "PACK_SW_P PACK_0 LINK_P LINK_N PRI_A PRI_B SEC_A SEC_B CT_OUTBOUND CT_RETURN G1 G2 G3 G4 G5 G6 G7 G8",
        "sense": "PACK_V KELVIN_P KELVIN_N PACK_0 V3V3 I_ADC V_ADC",
        "detector": "FROM_L1 TO_T1 HI_OK LO_OK P3V3 P0",
        "triplogic": "HI_OK LO_OK PRI_OK SEC_OK_P RUN ARM PERMIT_P P3V3 P0",
        "trip-isolation": "P3V3 S3V3 P0 S0 PERMIT_P PERMIT_S SEC_OK SEC_OK_P",
        "bias": "RAW RTN DRIVE LOGIC OK",
        "driver": "BIAS_10V DRV_0 PWM_H PWM_L PERMIT SW GATE_H GATE_L",
    }
    for domain, prefix, raw, ok, permit, base in [
        ("Primary", "P", "PACK12", "PRI_OK", "PERMIT_P", 1),
        ("Secondary", "S", "LINK24", "SEC_OK", "SEC_EN", 5),
    ]:
        expected[domain + " bias"] = ("bias", None, {"RAW": raw, "RTN": prefix+"0",
            "DRIVE": prefix+"10", "LOGIC": prefix+"3V3", "OK": ok})
        for leg, offset in [("A", 0), ("B", 2)]:
            expected[domain+" "+leg] = ("driver", None, {"BIAS_10V": prefix+"10",
                "DRV_0": prefix+"0", "PWM_H": prefix+leg+"_H", "PWM_L": prefix+leg+"_L",
                "PERMIT": permit, "SW": ("PRI_" if prefix == "P" else "SEC_")+leg,
                "GATE_H": f"G{base+offset}", "GATE_L": f"G{base+offset+1}"})

    refs = set()
    parent_pins = 0
    for sheet in children(root, "sheet"):
        fields = {p[1]: p[2] for p in children(sheet, "property")}
        kind, all_nets, overrides = expected.pop(fields["Sheetname"])
        if fields["Sheetfile"] != f"battery-port-{kind}.kicad_sch":
            raise ValueError(f"Wrong sheet file for {fields['Sheetname']}")
        child = read_schematic(ROOT / fields["Sheetfile"])
        parent = {p[1]: connected.pop(coord(first(p, "at"))) for p in children(sheet, "pin")}
        ports = {p[1] for p in children(child, "hierarchical_label")}
        required_ports = ({row.split()[0] for row in all_nets.strip().splitlines()}
                          if all_nets else set(required[kind].split()))
        wanted = {port: overrides.get(port, port) for port in required_ports}
        if parent != wanted or ports != required_ports:
            raise ValueError(f"{fields['Sheetname']}: unexpected interface or routing: {parent}")
        parent_pins += len(parent)
        path = "/" + root_id + "/" + first(sheet, "uuid")[1]
        for symbol in children(child, "symbol"):
            paths = [p for proj in children(first(symbol, "instances"), "project")
                     if proj[1] == project for p in children(proj, "path") if p[1] == path]
            if len(paths) != 1:
                raise ValueError(f"Missing or duplicate project annotation at {path}")
            ref = first(paths[0], "reference")[1]
            if ref in refs:
                raise ValueError(f"Duplicate reference {ref}")
            refs.add(ref)
    if expected or connected:
        raise ValueError("Bench hierarchy contains missing sheets or unused parent wires")
    components = sum(not ref.startswith("#") for ref in refs)
    print(f"Bench hierarchy passed: {parent_pins} sheet pins, {components} component references")


def run_spice(executable, deck, *, cwd=ROOT, options=()):
    run = subprocess.run([executable, *options, "-b", str(deck)], cwd=cwd, capture_output=True,
                         text=True, errors="replace", timeout=180)
    output = run.stdout + "\n" + run.stderr
    if run.returncode or re.search(r"aborted|timestep too small|measurement.*failed", output, re.I):
        raise RuntimeError(f"{deck} failed:\n{output[-2000:]}")
    measurements = re.findall(r"^\s*(\w+)\s*=\s*([-+\d.eE]+)(?:\s|$)", output, re.M)
    return {key: float(value) for key, value in measurements}


def near(measured, target, tolerance):
    if not math.isfinite(measured) or abs(measured - target) > tolerance:
        raise ValueError(f"{measured} outside {target} +/- {tolerance}")


def ideal_power(pack, link, ratio, inductance, shift):
    return pack * (link / ratio) * shift * (1 - abs(shift)) / (2 * 50_000 * inductance)


def check_simulations(executable):
    parts = run_spice(executable, "bench-parts-test.cir")
    for case, expected_watts in [("forward", 17.20), ("reverse", -17.82)]:
        near(24 * parts[f"{case}_bus"], expected_watts, 0.5)
        near(max(parts[f"{case}_max"], -parts[f"{case}_min"]), 1.92, 0.12)
    for case in ("plow", "phigh"):
        steady = max(parts[f"{case}_max"], -parts[f"{case}_min"])
        abrupt = max(parts[f"{case}_startmax"], -parts[f"{case}_startmin"])
        limited = max(parts[f"{case}start_startmax"], -parts[f"{case}start_startmin"])
        if not (steady < 3 and limited < 3 and abrupt > 4.04):
            raise ValueError(f"{case}: unexpected current peaks {steady}, {limited}, {abrupt}")
        print(f"{case}: {steady:.2f} A settled, {abrupt:.2f} A abrupt start, "
              f"{limited:.2f} A with reduced initial shift", flush=True)

    bias = run_spice(executable, "bench-bias-test.cir")
    for key in ["late_supply", "premature_arm", "gate_rail_trip", "logic_rail_trip",
                "gate_recover_hold", "logic_recover_hold"]:
        near(bias[key], 0, 0.01)
    for key in ["running", "logic_survives", "next_run", "final_run"]:
        near(bias[key], 3.3, 0.01)
    for key in ["pdrive_on", "gate_survives"]:
        near(bias[key], 9.926, 0.01)
    near(bias["ok_high"], 3.0, 0.01)
    pwm = run_spice(executable, "bench-pwm-test.cir")
    for key in ["diag1", "diag2", "command_still_high"]:
        near(pwm[key], 3.3, 0.01)
    for key in ["overlap_peak", "local_veto"]:
        near(pwm[key], 0, 0.01)
    for key in ["gap_ab", "gap_ba"]:
        near(pwm[key], 200e-9, 20e-9)
    print(f"Bench bias and PWM passed: {bias['pdrive_on']:.3f} V drive, "
          f"{pwm['gap_ab']*1e9:.0f}/{pwm['gap_ba']*1e9:.0f} ns modeled dead time", flush=True)

    protection = run_spice(executable, "protection-test.cir")
    for key in ["startup", "pos_before_arm", "pos_held_arm", "run_arm_block",
                "neg_before_arm", "neg_held_arm", "lost_bias"]:
        near(protection[key], 0, 0.01)
    for key in ["ordinary", "fresh_arm", "next_arm"]:
        near(protection[key], 3.3, 0.01)
    for key in ["pos_dt", "neg_dt"]:
        if not 0 < protection[key] < 150e-9:
            raise ValueError(f"Unexpected illustrative model delay in {key}: {protection[key]}")
    print("Bench detector, latch and isolated permits passed. Modeled delays "
          f"{protection['pos_dt']*1e9:.0f} / {protection['neg_dt']*1e9:.0f} ns", flush=True)

    driver = run_spice(executable, "driver-test.cir")
    for name in ["high_on", "low_on", "low_restored"]:
        near(driver[name], 10, 0.02)
    for name in ["trip_high_off", "overlap_high", "overlap_low", "bias_low_off"]:
        near(driver[name], 0, 0.01)
    print("Bench gate-drive model passed: high/low Vgs, overlap, trip and lost bias", flush=True)

    trip = run_spice(executable, "trip-test.cir")
    for name in ["initial_block", "positive_trip", "negative_trip", "held_arm_block", "bias_trip"]:
        near(trip[name], 0, 0.001)
    for name in ["normal_peak", "rearmed", "second_rearm"]:
        near(trip[name], 1, 0.001)
    print("PWM interlock passed: startup, both current polarities, bias loss and re-arm", flush=True)

    sense = run_spice(executable, "sense-test.cir")
    scale = 8.2 / 176.2
    for key, volts in [("voltage_40", 40), ("voltage_nom", 51.2), ("voltage_60", 60)]:
        near(sense[key], volts * scale, 0.001)
    for key, amps in [("current_minus75", -75), ("current_zero", 0), ("current_plus75", 75)]:
        near(sense[key], 1.65 + amps * 0.010, 0.001)
    near(sense["vfilter_mid"], (51.2 + 60) * 0.5 * scale, 0.003)
    print("Sensing passed: 40 / 51.2 / 60 V, -75 / 0 / +75 A and RC step", flush=True)

    converter = run_spice(executable, "dab-test.cir")
    for key, pack, link, ratio, inductance, shift in [
        ("small_discharge_i", 12, 24, 2, 10e-6, 0.2),
        ("small_charge_i", 12, 24, 2, 10e-6, -0.2),
        ("full_discharge_i", 51.2, 700, 14, 1.5e-6, 0.2),
        ("full_charge_i", 51.2, 700, 14, 1.5e-6, -0.2),
        ("low_link_i", 40, 700, 14, 1.5e-6, 0.2),
        ("high_link_i", 60, 700, 14, 1.5e-6, 0.2),
    ]:
        target = ideal_power(pack, link, ratio, inductance, shift)
        near(link * converter[key], target, 0.05 * abs(target))
        print(f"{key} at {pack} V: {link * converter[key]:+.1f} W into link")
    near(converter["zero_link_i"], 0, 0.05)
    for mode in ["charge", "discharge"]:
        losses = -(converter[f"battery_{mode}_i"] * 51.2 + converter[f"full_{mode}_i"] * 700)
        if not 0 < losses < 150:
            raise ValueError(f"Unexpected two-rail power balance in {mode}: {losses} W")
    for name in ["low_transfer_rms", "high_transfer_rms"]:
        if not 40 < converter[name] < 90:
            raise ValueError(f"Unexpected winding RMS current in {name}: {converter[name]}")

    low = run_spice(executable, "dab-low-pack.cir")
    watts = low["boost_link_i"] * 700
    near(watts, ideal_power(40, 700, 14, 1.5e-6, 0.285), 100)
    near(-low["boost_pack_i"], 68, 3)
    near(low["boost_transfer_rms"], 79, 4)
    near(low["boost_transfer_max"], 110, 6)
    near(low["boost_transfer_min"], -110, 6)
    print(f"40 V increased shift: {watts:.1f} W into link, {-low['boost_pack_i']:.1f} A "
          f"pack average, {low['boost_transfer_rms']:.1f} A winding RMS, "
          f"{max(low['boost_transfer_max'], -low['boost_transfer_min']):.1f} A peak")

    pair = run_spice(executable, "two-port-test.cir")
    near(pair["a_before"], 0.96, 0.05)
    near(pair["b_before"], 0.66, 0.05)
    near(pair["a_after"], pair["a_before"], 0.03)
    near(pair["b_after"], 0, 0.001)
    near(pair["bus_before"], 24.13, 0.10)
    near(pair["bus_before"] - pair["bus_after"], 0.39, 0.08)
    print(f"Two ports: {pair['a_before']:.3f} / {pair['b_before']:.3f} A before inhibit, "
          f"{pair['a_after']:.3f} / {pair['b_after']:.3f} A afterwards. "
          f"Bus {pair['bus_before']:.2f} -> {pair['bus_after']:.2f} V")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice", help="path to batch simulator")
    parser.add_argument("--cc", default="cc", help="C99 compiler (cc, gcc, clang or zig)")
    parser.add_argument("--schematics-only", action="store_true")
    args = parser.parse_args()
    check_sheet("sense", SENSE)
    check_sheet("power", POWER)
    check_sheet("driver", DRIVER)
    check_sheet("detector", DETECTOR)
    check_sheet("triplogic", TRIPLOGIC)
    check_sheet("trip-isolation", ISOLATION)
    check_sheet("bias", BIAS)
    check_sheet("pwm", PWM)
    check_sheet("bench-io", BENCH_IO)
    check_sheet("precharge", PRECHARGE)
    check_precharge_logic()
    check_sheet("bench-power", POWER.replace("L1.2 T1.1", "CT_OUTBOUND L1.2\nCT_RETURN T1.1"))
    check_bench_hierarchy()
    check_bench_via_clearance(ROOT / "battery-port-bench.kicad_pcb")
    if not args.schematics_only:
        check_startup(args.cc, args.ngspice, run_spice)
        check_simulations(args.ngspice)
