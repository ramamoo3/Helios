"""Extract and replay the isolated-driver clamp revision of the bench leg."""

import argparse
import math
from pathlib import Path
import re
import shutil

import isolated_layout_extract as layout
import isolated_layout_replay as replay
from isolated_driver_test import replace_line
from verify import ROOT


BOARD = ROOT / "battery-port-secondary-isolated-clamp.kicad_pcb"
EXTRACTION = ROOT / "bench-secondary-isolated-clamp-impedance.json"
PATHS = {
    **layout.PATHS,
    "tvs_high_cathode": (("Q5", "3"), ("D2", "1")),
    "high_bias_feed": (("TP4", "1"), ("C202", "1")),
    "high_bias_return": (("C202", "2"), ("TP5", "1")),
}
LOOPS = {
    **layout.LOOPS,
    "tvs_high_copper": {"tvs_high_cathode": 1, "tvs_high_anode": 1, "high_source": -1},
    "high_bias_landing": {"high_bias_feed": 1, "high_bias_return": 1},
}
NODES = {
    **replay.NODES,
    "tvs_high_cathode": ("drainh", "tvs_high_k"),
    "high_bias_feed": ("bias_tp4", "hi_bulk_p"),
    "high_bias_return": ("hi_bulk_n", "bias_tp5"),
}


def revise_bias(source, voltage, hot):
    # Both source leads land at the routed test pads. The output impedance and
    # barrier capacitance are trial values for the external supply and harness.
    replacements = {
        "Vfloat": f"Vfloat source_a bias_tp5 {voltage:g}",
        "Lsource_a": "Lsource_a vd_a bias_tp4 1n",
        "Ciso_coupling": "Ciso_coupling bias_tp5 0 50p",
        # Sweep two assumed effective values for the nominal 10 uF MLCC.
        "Cpin_high_bulk": f"Cpin_high_bulk high_bulk_c hi_bulk_n {3 if hot else 6}u",
    }
    for name, line in replacements.items():
        source = replace_line(source, name, line)
    return source


def keep_driver_devices_at_25c(model):
    patched, count = re.subn(
        rb"^(d1 1 2 dd|m1 d g s s _mod)[ \t]*(?=\r?$)",
        rb"\g<1> TEMP=25", model, flags=re.M | re.I,
    )
    if count != 3:
        raise ValueError("Review the temperature override for the UCC21520 model revision")
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="calculate the 29-port coupled copper network")
    extract.add_argument("--fasthenry", default="fasthenry")
    extract.add_argument("--mesh", type=int, default=7)
    extract.add_argument("--via-wall-mm", type=float, default=0.02)
    extract.set_defaults(output=EXTRACTION)

    sim = commands.add_parser("replay", help="run the nominal and hot switching and short cases")
    sim.add_argument("--extraction", type=Path, default=EXTRACTION)
    sim.add_argument("--reference", type=Path, default=ROOT / "bench-bootstrap-impedance.json")
    sim.add_argument("--shunt", type=Path, default=ROOT / "bench-shunt-transfer.json")
    sim.add_argument("--filter", type=Path, default=ROOT / "bench-shunt-filter-results.json")
    sim.add_argument("--driver-archive", type=Path, required=True, help="TI SLUM543 ZIP")
    sim.add_argument("--mosfet-archive", type=Path, required=True, help="TI SLPM077C ZIP")
    sim.add_argument("--ngspice", default="ngspice")
    sim.add_argument("--jobs", type=int, default=6)
    sim.add_argument("--driver-reference-25c", action="store_true",
                     help="diagnostic only: hold three internal driver devices at 25 C in the hot corner")

    for command in (extract, sim):
        command.add_argument("--board", type=Path, default=BOARD)
        command.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.command == "extract":
        exe = shutil.which(args.fasthenry)
        if not exe or args.mesh < 1 or not math.isfinite(args.via_wall_mm) or args.via_wall_mm <= 0:
            parser.error("Select a FastHenry executable, positive mesh and positive via wall thickness")
        args.fasthenry = str(Path(exe).resolve())
        layout.extract(args, PATHS, LOOPS)
    else:
        driver_reference = keep_driver_devices_at_25c if args.driver_reference_25c else None
        if args.output is None:
            suffix = "hot-diagnostic" if driver_reference else "replay"
            args.output = ROOT / f"bench-secondary-isolated-clamp-{suffix}.json"
        replay.run(args, nodes=NODES, revise_bias=revise_bias,
                   additional_sources=(Path(__file__),), driver_reference=driver_reference)


if __name__ == "__main__":
    main()
