"""Drive the switched converter with edges from the compiled bench scheduler."""
from pathlib import Path
import os
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
FRAMES = 120
PERIOD = 2000  # 10 ns timer ticks


def command_sources(program, target):
    trace = subprocess.check_output([program, str(target), str(FRAMES)], text=True)
    rows = [list(map(int, line.split())) for line in trace.splitlines()]
    if len(rows) != FRAMES:
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
            rise, fall = ((t + index * PERIOD) * 10 for t in row[2*signal:2*signal+2])
            points.append(f"+ {rise}n 0 {rise+25}n 5 {fall}n 5 {fall+25}n 0")
    sources = []
    for node, points in zip(("pa", "pb", "sa", "sb"), signals):
        sources.extend([f"V{node} {node} 0 PWL(0 0", *points, "+ )"])
    return sources


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
