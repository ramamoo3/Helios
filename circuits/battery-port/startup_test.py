"""Drive the switched converter with edges from the compiled bench scheduler."""
from pathlib import Path
import os
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
FRAMES = 120
PERIOD = 2000  # 10 ns timer ticks


def command_sources(program, target, *, start_ns=0, frames=FRAMES):
    trace = subprocess.check_output([program, str(target), str(frames)], text=True)
    rows = [list(map(int, line.split())) for line in trace.splitlines()]
    if len(rows) != frames:
        raise ValueError("Missing timer frames")
    signals = [[] for _ in range(4)]
    last_fall = [-20, -20]
    for index, row in enumerate(rows):
        shift = min(120, 60 + max(0, index - 9))
        if row[4] - row[0] != (shift if target > 0 else -shift):
            raise ValueError(f"Incorrect signed phase in frame {index}")
        for leg, pin in enumerate((0, 4)):
            pa, pb, na, nb = (t + index * PERIOD for t in row[pin:pin + 4])
            if (pb - pa != 980 or nb - na != 980 or
                    na - pb != 20 or pa - last_fall[leg] < 20):
                raise ValueError(f"Invalid pulse width or blank interval in frame {index}")
            last_fall[leg] = nb
        for signal, points in enumerate(signals):
            rise, fall = (start_ns + (t + index * PERIOD) * 10
                          for t in row[2*signal:2*signal+2])
            points.append(f"+ {rise}n 0 {rise+25}n 5 {fall}n 5 {fall+25}n 0")
    sources = []
    for node, points in zip(("pa", "pb", "sa", "sb"), signals):
        sources.extend([f"V{node} {node} 0 PWL(0 0", *points, "+ )"])
    return sources


def check_protected_converter(program, spice, run_spice, scratch):
    start = 100  # us
    for target in (120, -120):
        # A secondary-rail step in either half-cycle exercises the bipolar CT.
        # The bias case drops secondary power-good with the rails unchanged.
        for fault, at, threshold, bias in [("negative winding current", 502, 1.246, None),
                                           ("positive winding current", 512, 2.054, None),
                                           ("lost primary bias", 502, None, "pok"),
                                           ("lost secondary bias", 502, None, "sok")]:
            rail = ("24" if bias else
                    f"PWL(0 24 {at}u 24 {at+0.05}u 42 {at+30}u 42 {at+31}u 24)")
            dropout = f"PWL(0 3.3 {at}u 3.3 {at+0.01}u 0 {at+30}u 0 {at+30.01}u 3.3)"
            deck = ["Helios winding-current and bias paths through the complete bench port",
                    ".options method=gear reltol=0.0005 abstol=1n",
                    f'.include "{(ROOT / "protection.lib").as_posix()}"',
                    f'.include "{(ROOT / "protected-dab.lib").as_posix()}"',
                    "Vp p 0 12", f"Vs h 0 {rail}",
                    f"Vpri pok 0 {dropout if bias == 'pok' else '3.3'}",
                    f"Vsec sok 0 {dropout if bias == 'sok' else '3.3'}",
                    "Varm arm 0 PWL(0 0 80u 0 80.01u 3.3 660u 3.3 660.01u 0 690u 0 690.01u 3.3)",
                    "Vrun run 0 PWL(0 0 99u 0 99.01u 3.3 670u 3.3 670.01u 0 699u 0 699.01u 3.3)",
                    *command_sources(program, target, start_ns=start*1000, frames=45),
                    "Xport p 0 h 0 pa pb sa sb pok sok arm run enp ens ct ip p_cmd s_cmd PROTECTED_DAB",
                    ".tran 80n 980u 0 80n",
                    ".meas tran start_en MAX v(enp) from=0 to=98u",
                    ".meas tran normal_en MIN v(ens) from=110u to=490u",
                    ".meas tran normal_p AVG i(Vs) from=440u to=480u",
                    ".meas tran normal_hi MAX v(ip) from=120u to=490u",
                    ".meas tran normal_lo MIN v(ip) from=120u to=490u",
                    f".meas tran trip_p WHEN v(enp)=1.65 FALL=1 TD={at}u",
                    f".meas tran trip_s WHEN v(ens)=1.65 FALL=1 TD={at}u",
                    f".meas tran off_p WHEN v(p_cmd)=0.10 FALL=1 TD={at}u",
                    f".meas tran off_s WHEN v(s_cmd)=0.10 FALL=1 TD={at}u",
                    f".meas tran all_off_p MAX v(p_cmd) from={at+18}u to=669u",
                    f".meas tran all_off_s MAX v(s_cmd) from={at+18}u to=669u",
                    ".meas tran rearm MIN v(ens) from=705u to=975u",
                    ".meas tran restart_p AVG i(Vs) from=900u to=960u"]
            if bias:
                deck.append(f".meas tran fault_at WHEN v({bias})=1.65 FALL=1 TD={at}u")
            else:
                edge = "RISE" if threshold > 1.65 else "FALL"
                deck.extend([f".meas tran fault_at WHEN v(ct)={threshold} {edge}=1 TD={at}u",
                             f".meas tran i_hi MAX v(ip) from={at}u to={at+18}u",
                             f".meas tran i_lo MIN v(ip) from={at}u to={at+18}u"])
            path = scratch / "protected-startup.cir"
            path.write_text("\n".join([*deck, ".end", ""]), encoding="ascii")
            measures = run_spice(spice, str(path))
            label = f"{target:+d} shift, {fault}"
            swing = max(measures["normal_hi"], -measures["normal_lo"])
            worst_delay = max(measures["trip_p"], measures["trip_s"]) - measures["fault_at"]
            turnoff = max(measures["off_p"], measures["off_s"]) - measures["fault_at"]
            peak = max(measures.get("i_hi", 0), -measures.get("i_lo", 0))
            if not (measures["start_en"] < 0.01 and measures["normal_en"] > 3.2 and
                    swing < 3.5 and 0 < worst_delay < 300e-9 and
                    0 < turnoff < 400e-9 and (bias or 4 < peak < 4.75) and
                    measures["all_off_p"] < 0.01 and measures["all_off_s"] < 0.01 and
                    measures["rearm"] > 3.2 and
                    target * measures["normal_p"] > 30 and target * measures["restart_p"] > 30):
                raise ValueError(f"Integrated protection {label}: {measures}")
            print(f"Protected port {label}: {worst_delay*1e9:.0f} ns to both enables low"
                  + f", {turnoff*1e9:.0f} ns to both command envelopes low"
                  + (f", {peak:.2f} A winding peak" if not bias else "")
                  + ", fresh re-arm passed", flush=True)


def check_startup(cc, spice, run_spice):
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        program = scratch / ("trace.exe" if os.name == "nt" else "trace")
        compiler = [cc, "cc"] if Path(cc).stem == "zig" else [cc]
        subprocess.run([*compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "bench-startup-trace.c"), "-o", str(program)], check=True)
        for target in (120, -120):
            deck = ["Bench startup ramp from timer compare edges",
                    ".options method=gear reltol=0.0005 abstol=1n",
                    ".subckt port P N H L cpa cpb csa csb params: IMAG0=0",
                    ".param LK=8u LM=851.84u NSEC=2 RP=0.06 RLO=9.5m RHI=9.5m",
                    f'.include "{(ROOT / "dab-power.inc").as_posix()}"', ".ends port",
                    *command_sources(program, target)]
            cases = []
            for p, v in [(11.4, 25.2), (12.6, 22.8)]:
                for initial in (-0.10, 0, 0.10):
                    n = f"c{len(cases)}"
                    cases.append((n, p, v, initial))
                    deck.extend([f"Vp{n} p{n} 0 {p}", f"Vs{n} s{n} 0 {v}",
                                 f"X{n} p{n} 0 s{n} 0 pa pb sa sb port IMAG0={initial}",
                                 f".meas tran {n}hi MAX i(l.x{n}.ltransfer)",
                                 f".meas tran {n}lo MIN i(l.x{n}.ltransfer)",
                                 f".meas tran {n}bus AVG i(Vs{n}) from=2m to=2.4m"])
            deck.extend([".tran 100n 2.4m 0 100n uic", ".end"])
            path = scratch / "startup.cir"
            path.write_text("\n".join(deck) + "\n", encoding="ascii")
            results = run_spice(spice, str(path))
            for n, p, v, initial in cases:
                peak = max(results[n+"hi"], -results[n+"lo"])
                watts = v * results[n+"bus"]
                if not (0 < peak < 3.5 and 15 < watts * (1 if target > 0 else -1) < 24):
                    raise ValueError(f"Startup outside test limits: {p}/{v} V, {initial} A, "
                                     f"target {target}, peak {peak:.3f} A, {watts:.2f} W")
                print(f"Ramp {target:+d}, {p}/{v} V, initial Im {initial:+.2f} A: "
                      f"peak {peak:.3f} A, {watts:+.2f} W", flush=True)
        check_protected_converter(program, spice, run_spice, scratch)
