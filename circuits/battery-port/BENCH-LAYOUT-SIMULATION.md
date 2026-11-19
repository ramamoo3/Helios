# Bench converter layout extraction and switching results

The extraction uses the 12 V ↔ 24 V bench PCB at [revision 28c60eb](https://github.com/ramamoo3/Helios/commit/28c60eb85ac6409f0fd434ee8f7c6d7e2167d908). The four combinations of rail voltage, direction and bootstrap capacitance still fail with the TI PSpice models in ngspice. The reduced-order switching models completed and identified two waveforms to investigate before fabrication.

## Routed copper

FastHenry 3.0.1 extracted nine ports per bridge leg at 100 kHz, 1 MHz and 10 MHz. Each port runs between named component pads on the KiCad board. The model uses the actual segment centreline, width and layer height, with the published copper thickness from the board stack-up. It models via and source-pad barrels as rectangular conductors with the same copper cross-sectional area as a nominal 20 µm circular plating wall. The extraction includes mutual coupling among paths in the same leg. The dataset records the board's SHA-256 and port order. [Full impedance matrices](bench-impedance.json) · [Stack-up and routing](BENCH-PCB.md#stack-up-for-electrical-extraction) · [FastHenry solver](https://www.fastfieldsolvers.com/fasthenry2.htm)

| Leg | Commutation loop L at 10 MHz | Commutation loop R at 100 kHz | High-side gate loop L at 10 MHz | Low-side gate loop L at 10 MHz |
| --- | ---: | ---: | ---: | ---: |
| Primary A | 7.970 nH | 10.767 mΩ | 22.352 nH | 20.985 nH |
| Primary B | 7.970 nH | 10.767 mΩ | 22.352 nH | 20.985 nH |
| Secondary A | 8.028 nH | 10.189 mΩ | 22.345 nH | 21.270 nH |
| Secondary B | 8.028 nH | 10.189 mΩ | 22.345 nH | 20.985 nH |

Commutation-loop current traverses feed, switch and return copper in the port directions. Each gate-loop current runs from the driver output through both gate-resistor lands and returns along the HS or VSS trace in the reverse port direction. The loop values sum the signed self and mutual terms. Raising the width mesh from seven to eleven filaments changed the commutation values by about 0.01 nH. Sweeping via-wall thickness from 15 to 25 µm changed the gate loops by at most 2.33 mΩ and 0.04 nH. The solver returned 4.93269 mΩ for a 10 mm × 1 mm × 35 µm copper bar, matching the low-frequency 4.926 mΩ calculated from length, area and conductivity within 0.14%.

The model omits pad spreading, distributed rail and winding branches, adjacent-leg coupling, fringing capacitance and the HB-to-bootstrap routing. PCB source-pad barrels are included where they connect the driver returns. The MOSFET package inductances remain in the device model. For simulation, the SPICE network uses the diagonal resistance at 100 kHz and the reciprocal inductance terms at 10 MHz. The full frequency-dependent R and L matrices remain available for sensitivity analysis.

## Switching and bias-loss screening

The default simulation uses TI's UCC27282 and CSD18534KCS PSpice models. With the extracted copper, all four cases halted in bootstrap precharge at approximately 9.09–9.10 µs, before the 17 µs PWM start. A continuous-output driver with the TI MOSFETs advanced all six non-fault trials to PWM, then halted near the first transition. These runs provide no defensible voltage or overlap limits. The MOSFET channel probe positive control correctly read 0.982 A through both vendor devices.

The table uses the continuous-output driver and a compact VDMOS approximation fitted to typical on-resistance and capacitance, with package inductance. It uses assumed effective local ceramic capacitances of 0.70 µF for nominal cases and 0.35 µF for rail and bias corners, with 10 mΩ ESR and 0.6 nH ESL. An assumed 15 nH bulk feed is included on each rail. The approximation skips a reverse-recovery fit and cannot establish a channel overlap limit. Driver delays, sourcing and sinking impedance and the four capacitor values need full temperature and tolerance treatment before release. [TI MOSFET characteristics](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf) · [TI driver characteristics](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)

| Case | Largest package Vds | Most negative HS relative to VSS | Largest local feed current | Largest local ceramic current | Largest winding current |
| --- | ---: | ---: | ---: | ---: | ---: |
| Nominal discharge | 25.26 V | −3.36 V | 2.14 A | 1.00 A | 1.49 A |
| Nominal charge | 44.05 V | −3.35 V | 3.49 A | 1.05 A | 1.37 A |
| Discharge corner | 27.02 V | −3.14 V | 3.77 A | 1.76 A | 2.48 A |
| Charge corner | 42.76 V | −3.14 V | 4.32 A | 1.89 A | 2.51 A |

Halving the maximum timestep from 1 ns to 0.5 ns moved the nominal charge peak at Q6 from 44.05 V to 44.34 V. The two corner peak Vds results changed by 0.51 V and 0.09 V. The corner winding peaks changed by less than 0.002 A. The largest high-side Vgs during precharge was 2.14 V, above the existing 0.1 V simulated precharge criterion. Prior vendor-model simulations with ideal wiring did not reproduce that bump. Resolve the spike and the off-gate waveform using a converged device model before selecting snubbers or gate resistance.

Four bias-good fault cases completed with the reduced models. Each primary or secondary power-good input was taken low during precharge or active switching and restored after 2 µs. Both permits stayed low after recovery. The largest positive gate voltage from 0.5 µs after the injected loss through the end of the measured interval was 52.3 mV, below the 0.1 V inhibit criterion. This checks the latch and commands with the extracted network. A local bridge short and the time to interrupt actual current still require separate transient models.

## Reproduce

The extraction ran on FastHenry source revision `363e43e` with a local build for Windows. Its changes accommodate the compiler and the host and memory reporting functions. The field equations are upstream. Python scripts need the local FastHenry executable, ngspice, a C compiler, and the TI SLUM720 and SLPM046B files. The reported simulations used ngspice 47. [FastHenry source revision](https://github.com/ediloren/FastHenry2/tree/363e43ed57ad3b9affa11cba5a86624fad0edaa9)

```sh
python extract_layout.py --fasthenry fasthenry --mesh 11 --output bench-impedance.json
python layout_switching_test.py --extraction bench-impedance.json --output vendor-results.json --driver /path/to/UCC27282.lib --mosfet /path/to/CSD18534KCS.lib
python layout_switching_test.py --extraction bench-impedance.json --output screening-results.json --driver /path/to/UCC27282.lib --mosfet /path/to/CSD18534KCS.lib --screening-driver --screening-devices
```

Run from the battery-port directory. The runners write measured values or solver failures to JSON and return a failing exit status when a run stops early or a fault case fails the inhibit check. Each completed case also reports the precharge off-gate criterion. The screening run preserves the extracted topology and substitutes the driver and MOSFET models.

**Fabrication remains on hold.** Correlate the vendor and compact models against an independent switching model, add pad and bootstrap parasitics, and establish bounds on drain stress, gate turn-on, rail current and fault energy. Complete the thermal and mechanical review on the same board revision.
