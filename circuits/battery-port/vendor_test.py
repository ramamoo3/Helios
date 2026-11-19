"""Run TI's UCC27282 and CSD18534KCS PSpice models in an ngspice bench fixture."""
import argparse
from pathlib import Path
import re
import shutil
import tempfile

from verify import run_spice


def check(ngspice, driver, mosfet):
    fixture = Path(__file__).with_name("vendor-halfbridge.cir").read_text(encoding="ascii")
    # PSpice accepts whitespace between a parameter name and its value. Keep
    # the vendor originals intact and translate only those six declarations.
    pattern = rb"(?im)^([ \t]*\.param[ \t]+\w+)[ \t]+([^=\s].*)$"
    definitions, count = re.subn(pattern, rb"\1=\2", mosfet.read_bytes())
    if count != 6 or b".SUBCKT CSD18534KCS" not in definitions:
        raise ValueError("Expected TI SLPM046B, with six parameter declarations to translate")
    options = ("-n", "-D", "ngbehavior=psa")
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        shutil.copyfile(driver, scratch / "ti-driver.lib")
        (scratch / "ti-mosfet.lib").write_bytes(definitions)
        deck = scratch / "halfbridge.cir"
        for reltol in (0.005, 0.02):
            deck.write_text(fixture.replace("reltol=0.005", f"reltol={reltol}"), encoding="ascii")
            m = run_spice(ngspice, deck, cwd=scratch, options=options)
            delay = m["high_off"] - m["en_off"]
            peak = max(m["high_vds"], m["low_vds"])
            if not (9 < m["high_on"] < 10.1 and 9 < m["boot_min"] < 10.1 and
                    9 < m["low_on"] < 10.1 and 9 < m["low_after"] < 10.1 and
                    0 < delay < 100e-9 and 24 < peak < 30 and
                    m["simultaneous"] < 1.2 and
                    max(m["disable_hold"], m["overlap_hi"], m["overlap_lo"]) < 0.10):
                raise ValueError(f"Vendor half bridge outside limits with reltol={reltol}: {m}")
            print(f"TI models, reltol={reltol}: {m['high_on']:.3f} V high-side gate, "
                  f"{delay*1e9:.1f} ns disable, {peak:.2f} V peak Vds", flush=True)

        # Request the first high-side pulse without the low-side charge pulse.
        cold = re.sub(r"^Vlo .*", "Vlo li 0 0", fixture, flags=re.M)
        cold = re.sub(r"^\.meas .*\n", "", cold, flags=re.M)
        cold = cold.replace(".end", ".meas tran cold_gate MAX v(high) from=8.2u to=12u\n.end")
        deck.write_text(cold, encoding="ascii")
        m = run_spice(ngspice, deck, cwd=scratch, options=options)
        if m["cold_gate"] >= 1.2:
            raise ValueError(f"Unexpected cold-start gate voltage: {m['cold_gate']}")
        print(f"First high-side pulse without precharge: gate stayed below 1.2 V ({m['cold_gate']:.3g} V peak)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--driver", required=True, type=Path, help="TI SLUM720 LIB file")
    parser.add_argument("--mosfet", required=True, type=Path, help="TI SLPM046B LIB file")
    args = parser.parse_args()
    check(args.ngspice, args.driver, args.mosfet)
