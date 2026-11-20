"""Extract and replay the short high-side bias and return routing on the bench leg."""

import argparse
import math
from pathlib import Path
import shutil

import isolated_clamp_test as clamp
import isolated_layout_extract as layout
import isolated_layout_replay as replay
from verify import ROOT


BOARD = ROOT / "battery-port-secondary-isolated-bypass.kicad_pcb"
REPORT = "bench-secondary-isolated-bypass"
EXTRACTION = ROOT / f"{REPORT}-impedance.json"
PATHS = {
    **clamp.PATHS,
    "hs_source": (("U201", "high_return_tee"), ("Q5", "hs_takeoff")),
}
LOOPS = {
    **clamp.LOOPS,
    "high_gate": {"ho": 1, "gh": 1, "high_source": 1, "hs": -1, "hs_source": -1},
}
NODES = {**clamp.NODES, "hs_source": ("hs_junction", "hs_takeoff")}


def revise_bias(source, voltage, hot):
    # Use the same electrical bypass and external source assumptions as the
    # clamp revision so that routing is the variable in this comparison.
    source = clamp.revise_bias(source, voltage, hot)
    return source.removesuffix(".end\n") + """Bbias_bulk bias_bulk 0 V=v(hi_bulk_p,hi_bulk_n)
Bbias_fast bias_fast 0 V=v(hb_cap,hs_cap)
Bbias_return bias_return 0 V=v(hs,hs_takeoff)
.meas tran high_bulk_min MIN v(bias_bulk)
.meas tran high_bulk_max MAX v(bias_bulk)
.meas tran high_fast_min MIN v(bias_fast)
.meas tran high_fast_max MAX v(bias_fast)
.meas tran high_return_min MIN v(bias_return)
.meas tran high_return_max MAX v(bias_return)
.end
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="calculate the 29-port coupled copper network")
    extract.add_argument("--fasthenry", default="fasthenry")
    extract.add_argument("--mesh", type=int, default=7)
    extract.add_argument("--via-wall-mm", type=float, default=0.02)
    extract.set_defaults(output=EXTRACTION)

    sim = commands.add_parser("replay", help="run the nominal and hot switching and short cases")
    sim.add_argument("--driver-archive", type=Path, required=True, help="TI SLUM543 ZIP")
    sim.add_argument("--mosfet-archive", type=Path, required=True, help="TI SLPM077C ZIP")
    sim.add_argument("--ngspice", default="ngspice")
    sim.add_argument("--jobs", type=int, default=6)
    sim.add_argument("--driver-reference-25c", action="store_true",
                     help="diagnostic only: hold three internal driver devices at 25 C in the hot corner")
    sim.set_defaults(extraction=EXTRACTION, reference=ROOT / "bench-bootstrap-impedance.json",
                     shunt=ROOT / "bench-shunt-transfer.json", filter=ROOT / "bench-shunt-filter-results.json")

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
        if args.jobs < 1:
            parser.error("Select at least one simulation worker")
        driver_reference = clamp.keep_driver_devices_at_25c if args.driver_reference_25c else None
        if args.output is None:
            suffix = "hot-diagnostic" if driver_reference else "replay"
            args.output = ROOT / f"{REPORT}-{suffix}.json"
        replay.run(args, nodes=NODES, revise_bias=revise_bias,
                   additional_sources=(Path(__file__), Path(clamp.__file__)),
                   driver_reference=driver_reference)


if __name__ == "__main__":
    main()
