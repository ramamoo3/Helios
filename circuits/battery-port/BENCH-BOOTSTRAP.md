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

The fixture has prebiased rails, stable bias reservoirs, a discharged bootstrap starting condition, zero initial winding current and a linear transformer. The vendor driver models use the simulator ground for both local returns. Insulation, actual driver tolerance, dead-rail startup and restart with residual transformer current need separate verification. The four gate drivers and eight MOSFETs use TI's unencrypted PSpice models. [UCC27282 datasheet](https://www.ti.com/lit/ds/symlink/ucc27282.pdf) · [Driver model](https://www.ti.com/lit/zip/slum720) · [MOSFET model](https://www.ti.com/lit/zip/slpm046b)

Use the same two TI libraries as the single-leg fixture. The compiler generates the first two frames of each direction's controller trace.

~~~sh
python vendor_startup_test.py --ngspice ngspice --cc cc --driver /path/to/driver.lib --mosfet /path/to/CSD18534KCS.lib
~~~

## Channel overlap during startup

The gate bump is the largest simultaneous value of the lower gate-to-source voltage in any one leg. To check conduction directly, the diagnostic saves the intrinsic drain current and drain-source voltage of each TI MOSFET model's BSIM3 channel, without adding devices to the solver's circuit. It takes the smaller channel current in each leg when both intrinsic drain-source voltages are positive and integrates that common forward current from 17 to 39 µs. The explicit body-diode and capacitance branches are outside this measurement. A positive control forced both channels on through an ideal current-limited source. Both readbacks agreed with the 0.982 A supply current. [ngspice vector recording](https://nmg.gitlab.io/ngspice-manual/analysesandoutputcontrol_batchmode/batchoutput/save_namevector_s_tobesavedinrawfile.html) · [CSD18534KCS model and datasheet](https://www.ti.com/product/CSD18534KCS)

| Full converter, packaged-device model with no PCB inductance | Gate bump | Peak simultaneous forward channel current | Largest positive package Vds |
| --- | ---: | ---: | ---: |
| Nominal discharge | 2.610 V | 0.000055 µA | 24.715 V |
| Nominal discharge, alternate tolerance | 1.391 V | 0.000039 µA | 24.715 V |
| Nominal charge | 2.527 V | 0.00095 µA | 24.748 V |
| 11.4 V / 25.2 V discharge, 9.3 V bias, 120 nF | 3.571 V | 0.172 µA | 25.928 V |
| 12.6 V / 22.8 V charge, 9.3 V bias, 60 nF | 2.868 V | 0.019 µA | 23.554 V |
| Same charge case, 0.5 ns maximum step | 2.909 V | 0.072 µA | 23.556 V |
| Same charge case, alternate tolerance | 2.820 V | 0.015 µA | 23.556 V |

The baseline models put the simulated common forward channel current below 0.2 µA even in the 3.571 V case. Treat the small currents as numerical estimates. The metric does not cover total local rail current, diode reverse recovery or all switching losses. The winding current transformer senses transformer current and cannot qualify shoot-through confined to a half-bridge. [TI note on dV/dt-induced turn-on](https://www.ti.com/document-viewer/lit/html/SLYA091/GUID-2DA39407-8B48-4337-A3C3-C28780CB1745)

The four pre-layout runs add either 2 nH in the capacitor feed and 1 nH in each common-source path at nominal voltages, or 10 nH in the feed and 3 nH in each source path at the low-bias rail and capacitor corners. The sweep covers both power directions. These are assumed values in addition to the TI model's package inductance. All four stopped with a timestep error during precharge or early switching. A retry with 8 mΩ feed resistance, 5 mΩ source resistance, alternate Gear tolerances and a 0.5 ns maximum step also stopped in all four cases. The runner exits with a failure status when a case is inconclusive. Before setting the gate resistance or releasing the PCB, qualify positive Vds, negative switch-node excursions and peak local rail current with layout-derived impedance and a converged commutation model. Include the final driver reference takeoff, source lead and local capacitor return.

~~~sh
python vendor_overlap_test.py --ngspice ngspice --cc cc --driver /path/to/driver.lib --mosfet /path/to/CSD18534KCS.lib
python vendor_overlap_test.py --ngspice ngspice --cc cc --driver /path/to/driver.lib --mosfet /path/to/CSD18534KCS.lib --damped-layout
~~~
