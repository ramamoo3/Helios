# Full-bridge bootstrap startup

The modeled sequence starts with the 12 V and 24 V rails and local bias supplies already available. After the regular ARM and RUN handshake, hold both diagonal commands low on each bridge. Assert a dedicated precharge request for 7 µs to turn on both low-side FETs per bridge. Both winding terminals on each side are clamped to their local return so the low-side conduction can charge all four bootstrap capacitors without an applied winding voltage. End precharge, leave all gates off for at least 1 µs, then begin the compiled phase ramp at its first frame.

The model gates the four driver enables through the existing current trip and bias-permission logic. The secondary precharge request traverses a modeled 24 ns isolated path. A precharge request combined with either diagonal command drives both logic inputs low on both half-bridges on that side. An implementation still needs to handle propagation skew. The proposed logic is reproduced below, where P and N are the positive and negative diagonal requests.

| P | N | Precharge | Bridge commands with permit present |
| --- | --- | --- | --- |
| 0 | 0 | 0 | All gates off |
| 0 | 0 | 1 | Both low-side gates on |
| 1 | 0 | 0 | Positive diagonal |
| 0 | 1 | 0 | Negative diagonal |
| Any other combination | — | — | All gates off |

The KiCad decoder now routes PRE_REQ from J5.11 directly to the primary bridge and across an ISO7721FD to the secondary bridge. Each side acknowledges its own two-low-side decode only while its driver permit is present. The primary readback goes to J5.12. The secondary readback returns over the reverse isolator channel to J5.13. Separate inputs let the STM32 require both readbacks to rise and both to fall. [Schematic](battery-port-precharge.kicad_sch) · [Schematic preview](battery-port-precharge.svg) · [ISO7721 pinout and default output states](https://www.ti.com/lit/ds/symlink/iso7721.pdf)

The firmware checks for both readbacks low before asserting PRE_REQ. It allows up to 20 µs for both to assert, holds precharge for at least 7 µs after that, removes PRE_REQ and allows up to 20 µs for both to clear. It then waits an additional 1 µs with both clear before starting the first PWM frame. A missing or stuck readback or loss of permit inhibits the run and requires a fresh operator request. If a readback asserts during active PWM, firmware stops the run. These readbacks confirm digital commands and permission. The SPICE fixture separately measures capacitor voltage. [Firmware wiring and verification](BENCH-HRTIM.md) · [Four-leg circuit model](vendor-dab-startup.cir) · [Test runner](vendor_startup_test.py)

## Results from ngspice 47

| Case | Minimum of four bootstrap supplies at end of precharge | Lowest first commanded high-side gate | First-cycle winding peak |
| --- | ---: | ---: | ---: |
| 12 V / 24 V discharge, 100 nF | 9.698 V | 9.437 V | 1.473 A |
| 12 V / 24 V discharge, alternate solver tolerance | 9.698 V | 9.437 V | 1.476 A |
| 12 V / 24 V charge, 100 nF | 9.698 V | 9.437 V | 1.412 A |
| 11.4 V / 25.2 V discharge, 9.3 V bias and 120 nF | 9.017 V | 8.814 V | 2.471 A |
| 12.6 V / 22.8 V charge, 9.3 V bias and 60 nF | 9.167 V | 8.768 V | 2.526 A |

Both modeled bias-loss cases cleared permission during the precharge pulse. All eight gates remained off after bias returned, even though the test retained RUN and later supplied the scheduled PWM inputs. These cases assume the existing fault latch and independent driver enables. The regression checks all four bootstrap capacitors begin below 50 mV and pass the 8.5 V precharge target before PWM. In the normal cases, it also checks both the all-off gap and that winding current remains below 0.25 A during precharge and 3.5 A in the first cycle.

The minimum of the two gates in one half-bridge briefly reached 1.39 V and 2.61 V in the two nominal discharge solver runs. The largest equivalent bump across the tested cases was 3.57 V. It is sensitive to the solver settings and needs a separate switching-transient check. Establish drain-channel overlap and peak current with verified loop and common-source inductances before choosing gate resistors or releasing the layout.

The fixture has prebiased rails, stable bias reservoirs, a discharged bootstrap starting condition, zero initial winding current and a linear transformer. The vendor driver models use the simulator ground for both local returns. Insulation, actual driver tolerance, dead-rail startup and restart with residual transformer current need separate verification. The four gate drivers and eight MOSFETs use TI's unencrypted PSpice models. [UCC27282 datasheet](https://www.ti.com/lit/ds/symlink/ucc27282.pdf) · [Driver model](https://www.ti.com/lit/zip/slum720) · [MOSFET model](https://www.ti.com/lit/zip/slpm046b)

Use the same two TI libraries as the single-leg fixture. The compiler generates the first two frames of each direction's controller trace.

~~~sh
python vendor_startup_test.py --ngspice ngspice --cc cc --driver /path/to/driver.lib --mosfet /path/to/CSD18534KCS.lib
~~~
