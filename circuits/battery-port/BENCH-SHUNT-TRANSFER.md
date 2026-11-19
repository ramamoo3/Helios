# Kelvin shunt and comparator filter

The next bench PCB design uses a separate four-terminal shunt in each low-side source return. The candidate is the Vishay WSK2512 5 mΩ, 1% version. Its small sense lands are on opposite corners. The new KiCad footprint uses the manufacturer's dimensions for 5 mΩ and above. Pad 1 is I1, pad 2 is E1, pad 3 is E2 and pad 4 is I2. Keep the E1/E2 traces on separate Kelvin returns and prevent any gate-driver or decoupling ground connection from bypassing the force path. [Editable footprint](Helios_Bench.pretty/Shunt_Vishay_WSK2512_5mR.kicad_mod) · [Vishay land and terminal drawings](https://www.vishay.com/docs/30108/wsk2512.pdf)

## Extraction method

The manufacturer's STEP model supplies the notched 0.635 mm copper terminal geometry and the 0.245 mm central element thickness. FastHenry uses a sheet approximation of those shapes plus the 35 µm lands, solder contacts and short fan-out from the candidate footprint. The calibrated alloy conductivity gives about 5 mΩ open-circuit Kelvin transfer resistance at 100 kHz. Short, inboard, outboard and extended fan-out cases vary hypothetical contact and trace locations. These are fixture geometry assumptions pending placement and package verification. [Vishay STEP download](https://www.vishay.com/en/product/30108/tab/designtools-ppg/) · [FastHenry solver](https://www.fastfieldsolvers.com/fasthenry2.htm)

The force port is I1 to I2. The open-circuit transfer port is E1 to E2. With the sense-port current set to zero, the force drop is Z11 times force current and the Kelvin signal is Z21 times force current. Simulation uses the low-frequency real terms and the 10 MHz inductance terms separately, so a comparator filter responds to the Kelvin path while the bridge sees the force-path impedance. Approximate solder current distribution, crossbars within the plates and nearby PCB copper are accuracy limits. The final installed board needs its own extraction.

| Coupon geometry | Force resistance at 100 kHz | Force inductance at 10 MHz | Kelvin inductance at 10 MHz | Matched filter calculation |
| --- | ---: | ---: | ---: | ---: |
| Nominal short fan-out | 6.76 mΩ | 4.63 nH | 3.26 nH | 7.18 nF |
| Inboard contact | 6.83 mΩ | 4.63 nH | 3.26 nH | 7.18 nF |
| Outboard contact | 6.69 mΩ | 4.63 nH | 3.27 nH | 7.19 nF |
| Extended fan-out | 7.58 mΩ | 6.27 nH | 3.97 nH | 8.74 nF |

The nominal Kelvin inductance changed by 0.011 nH when the conductor discretization increased from three to five filaments in each cross-section direction. Changing the fan-out moved it by 0.71 nH. The coupon uses 0.5 mm force and 0.25 mm sense extensions on both ends in the short layout and 1.5 mm and 0.75 mm in the extended layout. Keep the sense loop short in the KiCad integration and rerun the transfer extraction with the routed returns. [Impedance matrices and geometry inputs](bench-shunt-transfer.json)

## Filter and fast shutdown results

Use **6.8 nF provisionally** with the 100 Ω input and 1 kΩ bias resistors. It was the passing standard value closest to the nominal 7.18 nF match. The early-trip tests used −10% capacitance, +1% Kelvin resistance and +5 mV comparator offset. The late-trip tests used +10% capacitance, −1% Kelvin resistance, −5 mV offset, 7 ns comparator delay and 12 ns permit logic delay. Each capacitor saw both directions of 2.5 A two-pulse switching and both failed-switch shorts on secondary leg A across all four coupon geometries.

| Nominal capacitor | Switching cases passed | Fault cases passed |
| --- | ---: | ---: |
| 1.1 nF historical control | 0/8 | 8/8 |
| 5.6 nF | 8/8 | 8/8 |
| **6.8 nF** | **8/8** | **8/8** |
| 8.2 nF | 8/8 | 8/8 |

At 6.8 nF, all eight nominal two-pulse tests and all eight nominal fault tests also passed across the four legs. The 16 passing nominal and corner faults reached a final current below 1 A in **291–415 ns** measured from the initial 1 A crossing. The external PWM request remained high throughout the observation window and EN stayed asserted relative to VSS. Both bridge permits latched low in the model with a zero winding-current signal. The secondary-leg-A bypass control sustained approximately 298 A at the end of the window, compared with 0.15 A with the mask active. These simulated currents depend on the assumed rail impedance and failed-switch resistance. [Per-case simulation data](bench-shunt-filter-results.json)

The UCC27282 EN disable time is 1.5 µs typical. The fast path uses HI and LI, whose falling propagation is specified at up to 30 ns in TI's no-load test. The behavioral screen approximates that delay and models the HI/LI mask output relative to driver VSS. The rail-referenced comparison drove the active input to −2.28 V relative to VSS, outside the recommended input range. The VSS-referenced model kept the input at about 0 to 3.3 V. It uses ideal reference translation and an assumed logic delay. Driver and receiver timing, bias behavior, common-mode transients and default output states need to be verified with the actual implementation. [TI driver operating limits and timing](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)

The slow fault corners reach about **58.9 V** on the 60 V MOSFET in a screening model that includes avalanche. Peak current in those corners is 78.6–91.8 A and the highest device energy proxy is 263 µJ. Those results leave clamp margin and allowable repetitive fault energy open. The next bench revision needs the component-level VSS-referenced interface, revised shunt routing, installed-board extraction, and a switching and fault rerun with the clamp and independent DC interruption modeled. [MOSFET datasheet](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf)

## Reproduce

Run from the battery-port directory with FastHenry and ngspice on PATH.

```sh
python shunt_transfer.py --output bench-shunt-transfer.json
python shunt_filter_test.py --output bench-shunt-filter-results.json
```
