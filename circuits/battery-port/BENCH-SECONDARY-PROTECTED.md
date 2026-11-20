# Secondary bench leg with routed clamps

The 33 × 27 mm four-layer layout adds a 5.0SMDJ30A across each 100 V CSD19531Q5A and a PMEG3020ER across the UCC27282 bootstrap supply. D2 has its cathode on BUS and its anode on SW. D1 has its cathode on SW and its anode on the low-side source ahead of the shunt. D3 has its cathode on HB and its anode on HS. The existing receiver and current-trip circuit connect at the test pads. The parent bench board uses the 60 V CSD18534KCS in TO-220. The isolated-leg studies use the 100 V SON device and retain the local 54 V screening limit. Integrating the SON part into the parent requires a footprint, drive and thermal review. [KiCad schematic](battery-port-secondary-protected.kicad_sch) · [KiCad PCB](battery-port-secondary-protected.kicad_pcb) · [TI CSD19531Q5A data sheet](https://www.ti.com/lit/ds/symlink/csd19531q5a.pdf) · [Parent parts](BENCH-PARTS.md)

KiCad 10.99.0 reported zero schematic ERC violations, zero PCB DRC violations, zero unconnected items, and zero schematic-to-PCB parity issues. The independent SMD drill check passed for all 24 vias. The power cell uses a 0.827 mm candidate stack with a 0.275 mm central dielectric. Board stiffness, stack availability, copper thickness tolerance and assembly fit still need review before release.

## Extracted copper

The 26-port FastHenry solve includes the driver and shunt paths and all three clamp branches. It splits the shared high-side rail run at D2’s takeoff and includes shared MOSFET source copper once. The model uses an assumed 20 µm via wall. The two TVS loop values include their routed vias and exclude package inductance. [FastHenry matrix](bench-secondary-protected-impedance.json)

| Loop at 10 MHz | Previous driver layout | Protected layout |
| --- | ---: | ---: |
| Main commutation | 8.85 nH | 8.83 nH |
| Low-side TVS copper | 4.36 nH | 3.65 nH |
| High-side TVS copper | — | 4.96 nH |
| Bootstrap capacitor copper | 2.18 nH | 2.17 nH |
| Bootstrap Schottky copper | — | 5.94 nH |

The shorter via barrels reduced the low-side loop by 16%. Both TVS paths still exceed the 2.5 nH total allowance before package inductance. A three-filament mesh gave 3.72 nH for the low-side TVS and 5.05 nH for the high side, within 0.09 nH of the seven-filament estimates.

## Electrical replay

Ngspice 47 replayed the extracted network with TI’s CSD19531Q5A model. The two driver variants use the TI UCC27282 model and the project’s reduced-order switching model. The replay includes the receiver, shunt transfer, RC snubbers, and two lumped TVS junction models with assumed 1–2 nH package inductance each. D3 uses a fit to the 25 °C data sheet curves and 0.65 nH assumed package inductance. The independent model controls passed. The Schottky fit gave 235 mV at 0.1 A, 325 mV at 1 A, and 370 mV at 2 A. [Ngspice replay](bench-secondary-protected-replay.json) · [Schottky data sheet](https://assets.nexperia.com/documents/data-sheet/PMEG3020ER.pdf) · [TVS data sheet](https://www.littelfuse.com/assetdocs/littelfuse_tvs_diode_5_0smdj_datasheet.pdf?assetguid=2b2f4a8c-2e81-4894-8d41-3d748bb79e68)

- All eight short cases interrupted current with the external gate request still asserted. With the TI driver, the largest peak was 58.8 V. For the two Q6-short cases, peak Q5 voltage fell from 95.9 to 40.5 V at 25 °C and from 79.6 to 47.7 V at 100 °C compared with the previous board. The reduced-order driver gave a worst peak of 81.6 V.
- When Q5 was shorted, the TI driver model still reached −1.47 V across HB–HS, below the −0.3 V absolute minimum. D3 carried up to 0.95 A in those modeled shorts. The split between diode voltage and voltage at the driver pins makes the clamp connection geometry part of the protection design. [Driver limits, section 6.1](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)
- The two reduced-order precharge runs passed with off-gate peaks of 0.072–0.075 V against the 0.10 V limit. Both TI precharge runs and seven of the eight normal-switching runs stopped with solver failures. The nominal reduced-order low-side run completed with Gear at a 125 ps maximum step and exceeded the MOSFET rating at 101.1 V. It also exceeded the bootstrap and driver pin limits.

### Driver-pin protection screen

A follow-on model placed the Schottky directly across HB and HS with 0.85 nH assumed total series inductance, first on its own and then with 2 Ω between the HS pin and its PCB takeoff. During a Q5 short, the direct clamp gave −1.01 V at 25 °C and −0.82 V at 100 °C. With 2 Ω added, the results improved to −0.73 V and −0.48 V. Both still exceeded the negative rating. One of the eight cases, the hot Q6 short with 2 Ω, stopped with a timestep error. These results give the next protection layout a comparison point and leave the clamp and driver selection open. [Driver-pin sensitivity data](bench-secondary-protected-hs-screen.json)

Fabrication stays on hold. Develop a driver-pin clamp with enough forward-voltage margin at the modeled pulse current, or evaluate a driver architecture with the required transient tolerance. Verify both fault polarities and converged normal switching with the extracted candidate before integrating it into the full bench bridge.

## Isolated-driver alternative

The next schematic replaces the bootstrap with a UCC21520DW and two independently referenced 12 V bias rails. The high channel uses a floating TMR 1-2412 tied to Q5’s Kelvin source. The low channel and input circuit reuse the receiver-side 12 V and 3.3 V rails referenced to Q6’s source. A 10 kΩ timing resistor sets nominal driver dead time to 100 ns. The 0.1 µF and 2.2 µF capacitors for each drive rail belong at their corresponding driver pins on the next layout. [Isolated-driver schematic](battery-port-leg-isolated-driver.kicad_sch) · [TI driver data sheet](https://www.ti.com/lit/ds/symlink/ucc21520.pdf) · [Traco module data sheet](https://www.tracopower.com/products/tmr1.pdf)

The two TPS3808 monitors use 100 kΩ and 4.32 kΩ sense dividers for a nominal falling threshold of 9.78 V. The high-side monitor returns its signal through a default-low ISO7710FD. `RAILS_OK` gates the local driver enable and must reach the parent run latch through the receiver’s isolated bias-good return. An open-drain inverter pulls DIS low only when both rails and the run permit are high. ERC reported zero issues and 116 connected pins matched the expected nets in the exported netlist. The feedback route to the parent latch and the SOIC driver routing remain to be built. [TPS3808 supervisor data sheet](https://www.ti.com/lit/ds/symlink/tps3808.pdf) · [ISO7710 data sheet](https://www.ti.com/lit/ds/symlink/iso7710.pdf)

The latch fixture passed all eight checks under a simulated supervisor output loss. DIS measured about 3.23 V at power-up, during either fault and after restoration until fresh arm. It measured about 18 mV during each enabled interval. The test models the supervisor outputs as digital inputs and leaves the threshold, transient response and parent wiring for verification. [Latch fixture](isolated-bias-interlock.cir) · [Latch measurements](bench-isolated-bias-interlock-results.json)

With TI’s SLUM543 driver model, a capacitive gate load reached 12.0 V on the first high-side pulse without a low-side preparation pulse. Measured output dead time was 81.9 ns in the control, using the 2 V gate crossings. The bias-loss control commanded DIS before the rail sag and held it through recovery. A separate model check exercised the CSD19531Q5A. The 16 power-stage cases used both TI models, with the previous driver’s copper reused as a comparison fixture. The UCC21520 macro represents the 8 V UVLO version and lacks vendor temperature characterization. Ngspice also reported unsupported parameters in the macro’s internal MOS models. The 100 °C cases bracketed the MOSFET and clamp model and remained inconclusive. [Isolated-driver replay](bench-isolated-driver-results.json) · [TI model download](https://www.ti.com/product/UCC21520#design-development)

Both nominal shorts interrupted current, but the Q5-short case reached 101.2 V at Q6 and the Q6-short case pulled the high-side drive rail to 5.28 V. One of the two nominal resistive switching cases passed the electrical screens. The other completed with the high-side rail below its minimum. The current-load and inductive switching cases stopped with solver errors. The next extracted layout needs to address local bias impedance, remaining TVS overshoot and convergence before fabrication.

### Local bypass sensitivity

A nominal comparison placed 2.2 µF and 100 nF directly across each modeled driver supply, with 0.55 and 0.35 nH of series inductance and 30 mΩ ESR per capacitor. It removed the previous board’s capacitor trace branches from the coupled model and compared symmetric 4.7 Ω and 8.2 Ω gate resistors. Both resistive-load polarities passed with either resistor. In the 4.7 Ω high-side switching case, the minimum high-side drive rail improved from 5.22 V to 9.70 V. The Q5-short case still reached 101.2 V at Q6. The two high-side inductive runs completed at 2.48–2.51 A of inductor current at commutation and reached 100.9–101.1 V at Q6. Only the 8.2 Ω run kept both bias rails within their screening limits. The capacitor improvement supports placing the bypass at the pins and leaves drain-clamp placement and switching convergence open. [Pin bypass sensitivity](bench-isolated-driver-pin-bypass-results.json)

The alternative model is reproducible with `python isolated_driver_test.py --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP --output bench-isolated-driver-results.json`. The runner saves the case data before reporting open criteria.

## Routed isolated-driver coupon

The 43.5 × 29.0 mm, 0.827 mm thick, four-layer coupon now carries the UCC21520DW, both MOSFETs, both clamps and all four output-side bypass capacitors. Channel B drives Q5 and channel A drives Q6 so each output faces its MOSFET. Both gate resistors are 8.2 Ω for comparison with the earlier bypass sensitivity. The floating 12 V supply, the low-side receiver supply and the rail monitor remain external to this coupon. The 2.2 kΩ DIS pull-up keeps the driver disabled when the external open-drain enable is released. [KiCad schematic](battery-port-secondary-isolated-routed.kicad_sch) · [KiCad PCB](battery-port-secondary-isolated-routed.kicad_pcb) · [TI evaluation board](https://www.ti.com/lit/ug/sluubg8c/sluubg8c.pdf)

| Test pads | Interface |
| --- | --- |
| TP1, TP2, TP3 | Bench DC rail, rail return and switch node |
| TP4, TP5 | Floating 12 V input and Q5 source reference |
| TP6, TP7 | Low-side 12 V input and Q6 source reference |
| TP8, TP9 | Positive and negative shunt Kelvin sense |
| TP10, TP11, TP12, TP13 | High PWM, low PWM, 3.3 V receiver supply and open-drain DIS |

KiCad reported zero ERC, DRC and schematic-to-PCB parity issues, with zero unconnected items. All 32 via holes cleared the SMD solder lands. The thin stack is a candidate for electrical comparison and still requires mechanical and process review.

| Extracted loop at 10 MHz | Prior routed board | Isolated-driver coupon |
| --- | ---: | ---: |
| Main commutation | 8.83 nH | 8.85 nH |
| Low-side TVS | 3.65 nH | 2.25 nH |
| High-side TVS | 4.96 nH | 4.96 nH |
| High-side gate | 12.33 nH | 10.02 nH |
| Low-side gate | 20.92 nH | 17.33 nH |
| High-side / low-side 100 nF bypass | — | 2.65 / 2.65 nH |
| High-side / low-side 2.2 µF bypass | — | 2.88 / 2.88 nH |

The 27-port extraction includes the copper on both sides of the shunt, shared source junctions, both TVS paths, gate paths and all four bypass branches. The new low-side clamp picks up the exposed Q6 drain directly into the rear SMB land. The 100 nF capacitors are on the driver face. Moving the 2.2 µF capacitors directly behind the IC reduced their loop estimates from 10.52 and 8.13 nH to about 2.88 nH each. The main estimates assume a 20 µm via wall and seven filaments across each trace. A three-filament solve gave 2.30 nH for the new low-side TVS loop. With 1 nH assumed for each diode package, the nominal loop totals are 3.25 nH and 5.96 nH against the 2.5 nH comparison budget. [Extracted matrices](bench-secondary-isolated-routed-impedance.json)

D1 is a 1.5SMB36A and D2 retains the 5.0SMDJ30A. The D1 data sheet specifies a 30.8 V standoff and a 49.9 V maximum clamp at 30.5 A for the 10/1000 µs waveform. Its 8/20 µs rating is 167.8 A at 64.5 V. These curves bound different pulses from those in the switch fixture. The replay fits the former voltage and current point, uses nominal junction capacitance and assumed package inductance, and leaves short-pulse correlation and thermal margin open. [D1 manufacturer data sheet](https://www.littelfuse.com/assetdocs/tvs-diode-1?assetguid=7ef1e879-b132-484e-b0bd-507f52b5dbb5)

### Replay of the routed coupon

The SPICE fixture uses the extracted power and driver paths and the TI models for both the driver and MOSFET. It includes 0.35 nH and 0.55 nH of assumed capacitor package inductance for the 100 nF and 2.2 µF parts, 30 mΩ capacitor ESR and 1–2 nH per TVS package. The external bias sources use lumped source impedance and isolation capacitance. Harness impedance and the physical receiver and rail monitor remain outside this extraction. [Replay data](bench-secondary-isolated-routed-replay.json)

The first isolated routed replay and sensitivity JSON preserve their original script fingerprints. The replay helpers have changed since those files were generated. Use these records to trace that iteration and the latest rear-bypass replay for current evidence. [Latest revision](#routed-rear-driver-bypass)

The local audit repeat ran the original coupon through the current replay helpers. It completed four of twelve nominal and hot cases. The nominal short peaks reproduced at 74.58 V and 94.54 V. In the nominal short sensitivity repeat, four Gear runs completed and both trapezoidal runs stopped. All four completed short-profile runs exceeded the 54 V screen. The low-side-short high-side bias minimum varied from 4.91 to 8.34 V across the two Gear time steps. [Repeat report with fingerprints](bench-secondary-isolated-routed-audit.json)

- Both 25 °C short cases interrupted current about 209 ns after crossing 1 A with the external PWM request held high. Q6 reached 74.6 V when Q5 was shorted, compared with 101.2 V in the earlier isolated-driver proxy. The new TVS, gate resistors and extracted copper changed together. Q5 reached 94.5 V when Q6 was shorted. Both exceed the 54 V design screen. Peak terminal current in D1 was 51.4 A, including displacement current.
- Both nominal resistive switching cases completed. Only low-side switching passed. The high-side resistive case reached a 6.65 V bias minimum against the 9.2 V screen. Both nominal inductive cases stopped with timestep errors. All six 100 °C cases with the original vendor libraries stopped before transient analysis.
- Gear retries at 125 ps and 500 ps kept the peak Q5 and Q6 fault voltages within 0.5 V and 0.6 V of the 250 ps runs. The high-side bias extrema during the Q6 short varied substantially with step size. Both trapezoidal retries failed. The narrow spread in drain peaks describes the completed Gear runs. The driver bias waveform and inductive cases still need convergence. [Solver sensitivity](bench-secondary-isolated-routed-sensitivity.json)
- A diagnostic kept the two internal MOSFET models and the diode in the UCC21520 library at 25 °C using instance temperature overrides, while the external 100 °C corner stayed in effect. Both short simulations and one resistive run completed. The short cases peaked at 71.1–84.7 V and the high-side rail fell to 6.52 V in the Q6 short. This variation checks sensitivity to the vendor macro’s treatment of temperature. Hot switching and fault qualification remain open. [Temperature diagnostic](bench-secondary-isolated-routed-sensitivity.json)

This revision left the high-side clamp connection, high-side bias and inductive and temperature verification open.

Reproduce from the battery-port directory with KiCad, FastHenry and ngspice available. Use the same TI vendor archives as the isolated-driver screen.

```sh
kicad-cli sch erc --exit-code-violations battery-port-secondary-isolated-routed.kicad_sch
kicad-cli pcb drc --schematic-parity --exit-code-violations battery-port-secondary-isolated-routed.kicad_pcb
python isolated_layout_extract.py --output bench-secondary-isolated-routed-impedance.json
python isolated_layout_replay.py --driver-archive SLUM543.ZIP \
  --mosfet-archive SLPM077C.ZIP --output bench-secondary-isolated-routed-replay.json
python isolated_layout_replay.py --driver-archive SLUM543.ZIP \
  --mosfet-archive SLPM077C.ZIP --short-profiles --output routed-short-profile-repeat.json
```

## Local high-side clamp revision

The next isolated-driver coupon moves D2 behind Q5 and connects its cathode directly to the Q5 drain land. Its anode returns at the Q5 source takeoff. TP3 now branches from the switch copper beside the bus bypass. D2 remains a 5.0SMDJ30A. C202 moves closer to the bias vias and changes to a nominal 10 µF, 25 V ceramic. The 100 nF capacitor stays on the driver side. The high-side bias still comes from an external supply at TP4 and TP5. [KiCad schematic](battery-port-secondary-isolated-clamp.kicad_sch) · [KiCad PCB](battery-port-secondary-isolated-clamp.kicad_pcb) · [Littelfuse TVS data sheet](https://www.littelfuse.com/assetdocs/littelfuse_tvs_diode_5_0smdj_datasheet.pdf?assetguid=2b2f4a8c-2e81-4894-8d41-3d748bb79e68) · [TI driver bypass guidance](https://www.ti.com/lit/ds/symlink/ucc21520.pdf)

KiCad reported zero ERC and DRC violations, zero unconnected items and zero schematic parity issues. An independent geometry check found all 33 via holes clear of SMD lands. The 29-port extraction adds both high-side supply test-pad routes to the coupled network. These values use the provisional 0.827 mm four-layer stack and an assumed 20 µm via wall. [Coupled copper model](bench-secondary-isolated-clamp-impedance.json)

| Extracted copper loop at 10 MHz | Previous revision | Local clamp revision |
| --- | ---: | ---: |
| Low-side TVS | 2.25 nH | 2.25 nH |
| High-side TVS | 4.96 nH | 3.24 nH |
| High-side gate | 10.02 nH | 9.24 nH |
| High-side bulk bypass | 2.88 nH | 2.32 nH |
| High-side bias test-pad pair | — | 11.40 nH |

The three-filament rerun estimated 3.30 nH for the high-side TVS and 2.35 nH for the high-side bulk bypass, compared with the seven-filament values in the table. The clamp loops total 3.25 nH and 4.24 nH with 1 nH assumed per diode package. Both exceed the 2.5 nH project budget.

The switching replay drives the floating bias at TP4 and TP5 through the extracted paths. It assumes 0.25 Ω and 1 nH in the external supply and 50 pF of isolation capacitance. The 10 µF MLCC is modeled with 6 µF effective capacitance at the nominal corner and 3 µF at the hot corner. Those values are trial assumptions. Verify the chosen capacitor’s DC-bias curve and the actual supply and harness impedance before relying on the margin.

| 25 °C replay with the vendor models | Peak drain voltage | Minimum high-side driver bias | Result |
| --- | ---: | ---: | --- |
| Q5 shorted, Q6 commanded | 71.5 V at Q6 | 11.83 V | Current interrupted in 210 ns |
| Q6 shorted, Q5 commanded | 85.8 V at Q5 | 4.95 V | Current interrupted in 214 ns |
| Q5 resistive switching | 32.6 V | 4.89 V | Driver bias below the 9.2 V screen |
| Q6 resistive switching | 32.1 V | 11.89 V | Passed the project screens |

The previous coupon reached 74.6 V at Q6 and 94.5 V at Q5 for the corresponding short cases. Both peaks improved, and both still exceed the 54 V design screen. The Q5 resistive bias minimum fell from 6.65 V to 4.89 V. Both inductive runs exhausted the timestep retries. All six hot runs with the unmodified vendor driver model failed to reach a transient solution. [Switching and fault results](bench-secondary-isolated-clamp-replay.json)

- Nominal Gear runs at 125, 250 and 500 ps kept Q6 fault peaks between 71.2 and 71.7 V and Q5 peaks between 85.8 and 86.4 V. During the Q6 short, the simulated high-side bias minimum varied between 3.39 and 6.71 V. Both trapezoidal runs stopped with timestep errors.
- Probing the Q5 resistive run with the 6 µF effective bulk model gave a 10.46 V minimum across the bulk pads and 10.97 V across the 100 nF pads, while the IC pin pair reached 4.89 V. Reducing the assumed bulk capacitance to 2.2 µF changed the pin minimum by only 0.03 V. The same comparison during the Q6 short gave about 10.48 V across the bulk pads and 4.96 V at the driver pins for both capacitances. Prioritize the copper from the capacitor to the driver pin pair and the source-reference route. Recheck the excursions in a second solver because the bias waveform varies with the timestep. [Solver and bias sensitivity](bench-secondary-isolated-clamp-sensitivity.json)
- Holding three internal driver devices at 25 °C let both shorts and both resistive cases complete with the rest of the circuit at the 100 °C corner. The short cases peaked at 69.5 and 70.9 V, and the high-side resistive run reached 4.82 V at the driver pins. Both inductive cases were inconclusive. The edited model provides a temperature diagnostic. Hot qualification requires temperature-valid models. [Driver temperature diagnostic](bench-secondary-isolated-clamp-hot-diagnostic.json)

Fabrication remains on hold. Close the clamp voltage and loop budgets and reduce the pin-level bias excursion. Repeat nominal and hot inductive switching with an independent solver or a validated model before carrying this leg into the four-leg bench converter.

Reproduce from the battery-port directory using KiCad, FastHenry, ngspice and the TI vendor archives.

```sh
kicad-cli sch erc --exit-code-violations battery-port-secondary-isolated-clamp.kicad_sch
kicad-cli pcb drc --schematic-parity --exit-code-violations battery-port-secondary-isolated-clamp.kicad_pcb
python isolated_clamp_test.py extract
python isolated_clamp_test.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP
python isolated_clamp_test.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP --driver-reference-25c
```

## High-side pin bypass revision

C201 moves toward the UCC21520 pins and uses the stock 0402 footprint. Its feed and return use wider front-copper traces. The driver source reference has a separate branch from U201.9 to the Q5 source takeoff. The reference and switch current share the MOSFET source and its package connection. [KiCad schematic](battery-port-secondary-isolated-bypass.kicad_sch) · [KiCad PCB](battery-port-secondary-isolated-bypass.kicad_pcb) · [TI layout guidance](https://www.ti.com/document-viewer/lit/html/SLUAAM3)

ERC, DRC and schematic parity reported zero issues and there were zero unconnected items. The independent via check cleared all 33 vias. The coupled extraction retains the same 29 ports and splits the high-side bypass return from the dedicated branch to Q5. [Extracted copper](bench-secondary-isolated-bypass-impedance.json)

| Extracted loop at 10 MHz | Local clamp revision | Pin bypass revision |
| --- | ---: | ---: |
| High-side 100 nF bypass | 2.65 nH | 1.92 nH |
| High-side bulk bypass | 2.32 nH | 2.32 nH |
| High-side gate | 9.24 nH | 8.85 nH |
| Low-side / high-side TVS | 2.25 / 3.24 nH | 2.25 / 3.24 nH |

The three-filament solve estimated 1.94 nH for the fast bypass versus 1.92 nH at seven filaments. The main replay keeps the previous electrical assumptions to isolate the copper change. The 0402 part still needs a selected manufacturer part number and DC-bias data to establish its actual effective capacitance.

With the routed 8.2 Ω gate resistors, the nominal high-side resistive run reached 5.29 V at the driver pins, versus 4.89 V previously and a 9.2 V minimum requirement. The fast bypass pads stayed above 10.80 V. The low-side resistive case passed. The short cases interrupted current in 210–214 ns and peaked at 71.5 V on Q6 and 84.1 V on Q5. Both exceed the 54 V screen. Both nominal inductive runs remained inconclusive, including the added Gear order and error tolerance trials. All six hot runs with the unmodified driver model stopped before transient analysis. [Switching and fault replay](bench-secondary-isolated-bypass-replay.json)

The temperature diagnostic held three internal driver devices at 25 °C while applying the 100 °C corner to the rest of the circuit. It completed both resistive and both short cases. The short peaks remained above 70 V and the high-side resistive run reached only 5.13 V at the driver pins. Both inductive runs remained inconclusive. This diagnostic leaves high-temperature qualification open. [Temperature results](bench-secondary-isolated-bypass-hot-diagnostic.json)

The protection sensitivity sweep changed component values in the simulator at 25 °C. It uses the extracted routing of this PCB for each comparison. The TVS fits use the manufacturers' maximum breakdown and stated 10/1000 µs clamp points. The previous junction capacitance assumptions were retained for the replacement devices. Package parasitics, short-pulse curves, thermal behavior and candidate pad routing still require verification. [Screen results](bench-secondary-isolated-bypass-sensitivity.json) · [Vishay 3KDFN data](https://www.vishay.com/docs/98814/3kdfn12athru3kdfn100a.pdf) · [Littelfuse 5.0SMDJ data](https://www.littelfuse.com/assetdocs/littelfuse_tvs_diode_5_0smdj_datasheet.pdf?assetguid=2b2f4a8c-2e81-4894-8d41-3d748bb79e68) · [TI gate-resistor selection guide](https://www.ti.com/lit/ab/slla385a/slla385a.pdf)

| Nominal fault case | Existing layout model | 15 Ω Q5, 22 Ω Q6 with 3KDFN33A D1 and 5.0SMDJ28A D2 |
| --- | ---: | ---: |
| Q5 shorted, peak Q6 drain voltage | 71.5 V | 50.5 V |
| Q6 shorted, peak Q5 drain voltage | 84.1 V | 47.5 V |
| Q5 shorted, peak shunt current / clearing time | 127.2 A / 210 ns | 139.3 A / 235 ns |
| Q6 shorted, peak shunt current / clearing time | 128.9 A / 214 ns | 138.2 A / 244 ns |
| Q5 shorted, Q6 terminal-energy estimate | 85.5 µJ | 137.6 µJ |
| Q6 shorted, Q5 terminal-energy estimate | 93.6 µJ | 123.8 µJ |
| Q6 shorted, high-side bias range | 5.34–16.25 V | 5.30–23.90 V |

With the fitted TVS values, both simulated drain peaks fell below 54 V. The estimated energy entering the commanded MOSFET increased by 32–61%. The estimate integrates the positive terminal voltage-current product and includes displacement current. MOSFET safe operating area still needs verification with the time-correlated current and voltage and temperature-valid models. The driver rail still exceeds its allowed 9.2–16 V window. Prioritize pin-level bias and source-reference behavior, then re-extract the clamp candidate with its actual footprint and confirm the combined result at nominal and hot conditions. Fabrication remains on hold.

The legacy bench firmware startup and SPICE regression suite passed after rerunning it with the host compiler.

Reproduce from the battery-port directory with KiCad, FastHenry, ngspice and the TI vendor archives.

```sh
kicad-cli sch erc --exit-code-violations battery-port-secondary-isolated-bypass.kicad_sch
kicad-cli pcb drc --schematic-parity --exit-code-violations battery-port-secondary-isolated-bypass.kicad_pcb
python isolated_bypass_test.py extract
python isolated_bypass_test.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP
python isolated_bypass_test.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP --driver-reference-25c
```

## Routed DFN clamp and pin-bias screen

The combined clamp candidate is now a schematic and routed PCB. R206 and R207 are 15 Ω and 22 Ω. D2 is a 5.0SMDJ28A. D1 uses a Vishay 3KDFN33A and a footprint drawn from the manufacturer's DFN6546A land pattern. The two small cathode lands each connect to the switch node. The 4.70 × 3.88 mm exposed anode land connects to the Q6 source net. The footprint represents both cathode lands as pad 1, with a separate paste aperture for each land. The initial stencil sizes are engineering selections for assembly review. [DFN footprint](Helios_Bench.pretty/Diode_TVS_Vishay_DFN6546A.kicad_mod) · [Vishay polarity and electrical data](https://www.vishay.com/docs/98814/3kdfn12athru3kdfn100a.pdf) · [Vishay land and stencil drawing](https://www.vishay.com/docs/98535/solderingrecommendations_powerdfn_packages.pdf)

Both DFN layouts passed KiCad ERC, DRC and schematic parity with zero unconnected items. The independent checks cleared all 33 vias on each layout. The 31-port extraction separates the two rear cathode routes and ties them at the modeled package terminal. The loop estimates use a 10 MHz copper model and equal current division for reporting. The transient replay solves the split through both coupled branches and assumes 1 nH package inductance per TVS nominally and 2 nH hot. [First PCB](battery-port-secondary-isolated-dfn.kicad_pcb) · [First schematic](battery-port-secondary-isolated-dfn.kicad_sch) · [Shorter clamp PCB](battery-port-secondary-isolated-dfn-local.kicad_pcb) · [Shorter clamp schematic](battery-port-secondary-isolated-dfn-local.kicad_sch)

| Extracted copper loop | SMB bypass PCB | First DFN layout | Shorter DFN layout |
| --- | ---: | ---: | ---: |
| Low-side TVS | 2.25 nH | 2.85 nH | 2.42 nH |
| High-side TVS | 3.24 nH | 3.24 nH | 3.24 nH |
| High-side bias bypass | 1.92 nH | 1.92 nH | 1.92 nH |

The shorter layout places the switch-node via between the two cathode lands. It moves the low-side source-reference and gate vias clear of the anode pad. The first DFN layout's copper estimate changes from 2.85 to 2.92 nH when using three filaments instead of seven. [First 31-port extraction](bench-secondary-isolated-dfn-impedance.json) · [Shorter 31-port extraction](bench-secondary-isolated-dfn-local-impedance.json)

With the 1 nH nominal package estimate, the shorter PCB has 3.42 nH in the low-side clamp loop and 4.24 nH in the high-side loop. Both exceed the 2.5 nH comparison budget.

The as-routed Q5-short peak fell from 62.04 V on the first DFN board to 54.33 V on the shorter board. The shorter board's Q6-short peak was 47.45 V. Its high-side resistive test reached a 3.68 V driver bias minimum. Both boards completed the nominal low-side resistive run. Both nominal inductive cases and all six hot cases remained inconclusive for each board with the unmodified driver model. [First routed replay](bench-secondary-isolated-dfn-routed.json) · [Shorter routed replay](bench-secondary-isolated-dfn-local-routed.json)

The simulated extra pin bypass uses 100 nF, 0.10 Ω and a total series inductance of 0.2, 0.3, 0.4 or 0.6 nH. Its electrical connection is directly across U201's high-side bias pins in the deck. It is a design target for comparison. Both PCBs use the routed C201 and C202 network.

On the previous bypass PCB, the 0.2 nH trial raised the high-side resistive minimum from 5.29 V to 9.86 V. A 0.6 nH trial reached 8.09 V, and series resistance added to the source reference left the minimum near 5.3 V. On the first DFN layout, the 0.2 nH trial passed the Q6-short and high-side resistive bias checks. Q6 still reached 62.0 V with Q5 shorted. [Initial bias sweep and terminal stress](bench-secondary-isolated-dfn-supplemental.json) · [DFN pin screen](bench-secondary-isolated-dfn-pin-screen.json)

The first DFN's synchronized short waveforms show about 51.3 V and 100.5 A at the Q6 peak terminal-power point. Q5 reached about 39.7 V and 115.8 A at its corresponding point. TI's shortest plotted single-pulse safe-operating-area curve is 10 µs. These sub-microsecond fault trajectories need a device and temperature-specific margin review. The positive terminal-energy proxy includes displacement current. [MOSFET data sheet, Figure 10](https://www.ti.com/lit/ds/symlink/csd19531q5a.pdf)

The hot diagnostic on the first DFN layout held three internal driver devices at 25 °C and applied the 100 °C corner to the rest of the circuit. Both short and both resistive runs completed. The Q6 short produced a simulated 35.36 V high-side bias maximum. Both inductive cases remained inconclusive. Hot qualification is open. [Hot diagnostic](bench-secondary-isolated-dfn-hot-diagnostic.json)

The shorter layout's 0.2 nH pin trial gave 9.88 V in high-side resistive switching and 9.91 V during the Q6 short. The same trial left the Q5-short drain peak at 54.33 V, above the 54 V limit. The 0.3 nH trial completed the high-side resistive case, but the Q6 short failed to converge. This sweep sets a target for a physical bias layout. [Shorter-layout pin screen](bench-secondary-isolated-dfn-local-pin-screen.json)

With 27 Ω simulated for the Q6 gate resistor and the 0.2 nH supply branch, both nominal shorts passed the electrical screens at 250 ps and 500 ps Gear settings. At 250 ps they peaked at 52.66 V at Q6 and 47.62 V at Q5 and cleared in 241 and 243 ns. At 125 ps, the Q5-short case reproduced the drain peak, the Q6-short case hit a timestep error, and the high-side resistive bias fell to 8.51 V. The native PCB uses 22 Ω and the routed C201 and C202 paths. [Solver and component sensitivity](bench-secondary-isolated-dfn-supplemental.json)

Run from the battery-port directory with KiCad, FastHenry and ngspice available. The two extraction calls select the measured cathode via location on each native PCB.

```sh
python isolated_dfn_test.py extract
python -c 'import isolated_dfn_test as f; f.DFN_JUNCTION = (32.655, 35.53, "B.Cu"); f.main()' extract \
  --board battery-port-secondary-isolated-dfn-local.kicad_pcb \
  --output bench-secondary-isolated-dfn-local-impedance.json
python isolated_dfn_test.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP
python isolated_dfn_test.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP \
  --board battery-port-secondary-isolated-dfn-local.kicad_pcb \
  --extraction bench-secondary-isolated-dfn-local-impedance.json \
  --output bench-secondary-isolated-dfn-local-routed.json
```

Use `--mode pin-screen` with a separate output name for the additional 100 nF branch or `--mode hot-diagnostic` for the temperature-limited driver experiment. Both layouts remain on fabrication hold.

## Routed rear driver bypass

C207 is a second 100 nF, 50 V 0402 bypass on the rear copper. The existing A12 and switch-reference vias go first to C207, then to the relocated C202 bulk capacitor. The front C201 bypass and the dedicated Q5 reference branch remain part of the extracted circuit. R207 is now 27 Ω in both the schematic and layout. Both clamps use the shorter DFN revision's copper. KiCad reported zero ERC, DRC, connectivity and schematic parity issues. All 33 via holes cleared the solder lands. [Schematic](battery-port-secondary-isolated-dfn-rear-bypass.kicad_sch) · [PCB](battery-port-secondary-isolated-dfn-rear-bypass.kicad_pcb)

| High-side bypass at 10 MHz | Shorter DFN PCB | Rear-bypass PCB |
| --- | ---: | ---: |
| Front bypass, copper | 1.92 nH | 1.92 nH |
| Rear fast bypass, copper | — | 2.60 nH |
| Bulk bypass, copper | 2.32 nH | 4.07 nH |
| Fast branches in parallel, including estimated part ESL | 2.27 nH | 1.20 nH |

The 33-port extraction models front and rear coupling and splits the shared route to C207 from the onward bulk branches. The parallel estimate includes an assumed 0.35 nH per fast capacitor. It was 1.21 nH in the three-filament run. The transient includes the capacitors on the extracted routes. The C207 model uses 30 mΩ ESR and assumed effective capacitances of 75 nF at nominal and 55 nF at hot. Confirm the selected part's DC-bias and frequency curves before treating those values as component limits. [Copper model](bench-secondary-isolated-dfn-rear-bypass-impedance.json) · [Example 100 nF 50 V 0402 part data](https://product.tdk.com/en/search/capacitor/ceramic/mlcc/info?part_no=C1005X7R1H104K050BE)

The separately written driver model sources and sinks current through the physical supply and reference. It uses data sheet timing and output-current targets with simplified rail clamps and output undervoltage behavior. Both driver models run in ngspice with the same extracted layout, MOSFET models and protection circuit. The reduced model has no internal isolation or common-mode transient dynamics, no UVLO hysteresis or recovery delay, and only approximate dead time. In its standalone control it enabled both outputs, turned them off on disable or undervoltage, and gave 56.9 ns of non-overlap in the test fixture. The vendor model previously gave 81.9 ns in that fixture. [Reduced driver model](isolated-bench-driver.lib) · [TI driver specifications](https://www.ti.com/lit/ds/symlink/ucc21520.pdf)

| Nominal result | Vendor at 125 ps | Vendor at 250 ps | Vendor at 500 ps | Reduced at 250 ps |
| --- | ---: | ---: | ---: | ---: |
| Q5 shorted, peak Q6 VDS | 52.68 V | 52.66 V | 52.68 V | 52.74 V |
| Q6 shorted, peak Q5 VDS | 47.44 V | 47.42 V | 47.38 V | 47.57 V |
| Q6 shorted, high-side bias range | 3.64–36.08 V | 5.27–23.64 V | 7.02–14.52 V | 11.43–12.67 V |
| High-side resistive, minimum bias | Timed out | 5.22 V | 6.97 V | 11.40 V |

Both nominal shorts interrupted the modeled current with PWM still requested. The vendor cases stayed below 54 V across the three Gear step settings. The large spread in bias extrema and the reduced model's different waveform leave the 9.2–16 V rail test open. At 500 ps, populating C207 improved the vendor model's minima by 0.52–0.55 V compared with the same copper and an open C207. The simulated dips were about 0.10 ns at the 9.2 V threshold, with the rear pads near 11.4 V at the pin minimum. Duration and amplitude need independent confirmation. [Vendor replay](bench-secondary-isolated-dfn-rear-bypass-vendor-250ps.json) · [125 ps retry](bench-secondary-isolated-dfn-rear-bypass-vendor-125ps-nominal-quick.json) · [500 ps retry](bench-secondary-isolated-dfn-rear-bypass-vendor-500ps-nominal-quick.json) · [Population and time-domain checks](bench-secondary-isolated-dfn-rear-bypass-supplemental.json)

The 500 ps trapezoidal runs put the nominal fault peaks within 0.07 V of the corresponding model's 500 ps Gear peaks where both runs were available. The vendor model reached 8.24 V minimum bias during the Q6 short and failed to complete the high-side resistive run. The reduced model reached 11.43 V during the Q6 short and passed the high-side resistive run. [Alternate integration results](bench-secondary-isolated-dfn-rear-bypass-supplemental.json)

All six 100 °C vendor cases failed before transient analysis. The reduced driver completed both hot resistive and both hot short cases. The Q5-short case reached 54.22 V at Q6 and required 263 ns to interrupt. Both nominal inductive cases and both hot inductive cases remained inconclusive with the reduced model. [Reduced-model results](bench-secondary-isolated-dfn-rear-bypass-compare-250ps.json)

### Gate resistance and pin-bypass trial

The model keeps the rear-bypass copper and screens a 39 Ω low-side gate resistor. All eight nominal and hot resistive and short cases passed in the reduced driver at both 250 and 500 ps. With hot Q5 shorted, Q6 peaked at 51.35 V and cleared in about 283 ns at 500 ps. The opposite hot short reached about 53.08 V at the finer step. The candidate trades lower overshoot for a longer current-clearing interval. Verify paired device voltage and current against the safe operating area. [Trial results](bench-secondary-isolated-dfn-rear-drive-trial.json)

In the vendor-driver variant, the nominal Q6 short reached 7.02 V at the high-side bias pins. Larger effective rear capacitance left a similar dip. Adding a separate 100 nF branch directly across the driver pins with 0.6 nH assumed total loop inductance passed at 500 ps, dropped to 6.41 V at 125 ps and stalled at 250 ps. With 0.2 nH assumed, the 125 ps minimum was still 8.57 V. The 9.2 V minimum and the inductive cases remain open. The gate resistor and direct pin bypass are still simulation candidates. [Vendor and reduced-driver results](bench-secondary-isolated-dfn-rear-drive-trial.json)

The inductive diagnostic smoothed the reduced driver's current-limit transitions. The nominal high-side case completed at 2.52 A at commutation and reached 101.04 V across Q6. A gate-source clamp trial kept gate stress within ±16 V in the completed hot case, while Q6 still reached 101.10 V. Adding a modeled direct drain clamp in the nominal case reduced the peak to 80.07 V, above the 54 V screen. The corresponding hot run stalled. All six symmetrized resistance and inductance matrices were positive definite at their extraction frequencies. That check covers the extracted matrices. It gives no time-domain convergence or stress credit. [Inductive diagnostics](bench-secondary-isolated-dfn-rear-drive-trial.json)

### Inductive commutation stress

Saving the nominal direct-clamp waveform moved the reported Q6 peak from 80.07 V to 100.60 V at 4.711 µs. At that sample, the switch node reached 66.13 V and the source fell to −34.47 V with 2.53 A still flowing in the load. The modeled clamp junction was 0.67 V below the source and carried no reverse avalanche at that sample. Linear interpolation gives 6.64 ps total above 54 V across the saved run. The peak depends on how ngspice records the transient, so its magnitude and duration remain uncorrelated. The node voltages are consistent with a transient across the modeled clamp path inductance. [Waveforms and measurements](bench-inductive-waveform-results.json) · [TI ringing guidance](https://www.ti.com/lit/an/slpa010/slpa010.pdf)

The combined diagnostic candidate keeps the original clamps and 39 Ω low-side gate resistor, increases the high-side gate resistor from 15 Ω to 27 Ω, and adds a 1 Ω / 2.2 nF RC branch across Q6 with 0.50 nH assumed loop inductance. A generic diode steers source-to-drain current with a 0.45 nH series loop. The diode parameters and loop inductances are screening assumptions. Four nominal alternatives without the steering diode hit the simulation time limit.

| Reduced-driver case, generic steering diodes on Q5 and Q6 | Peak VDS at 125 ps | At 250 ps | At 500 ps |
| --- | ---: | ---: | ---: |
| 25 °C high-side switching | 32.07 V | 32.07 V | 32.07 V |
| 25 °C low-side switching | 31.98 V | 31.85 V | 31.84 V |
| 100 °C high-side switching | 32.26 V | 32.26 V | 32.26 V |
| 100 °C low-side switching | 33.44 V | 33.07 V | 33.05 V |

All 12 runs passed the 54 V drain limit, ±16 V gate limit and 9.2–16 V driver-rail limits. Commutation current stayed between 2.64 and 2.72 A. The nominal Q6-only variant reached 32.07 V at 2.64 A with the 250 ps step. Its saved waveform agreed and had no samples over 54 V. Its 125 and 500 ps repeats timed out, as did its 100 °C high-side runs at 250 and 500 ps. [Results and source hashes](bench-inductive-waveform-results.json)

The manufacturer’s STPST10H100SF PSpice model passed the 100 °C high-side case at 250 ps with a 33.20 V peak and 2.65 A at commutation. The test assumed a 0.45 nH external loop per diode. Both hot directions timed out at 1.0 nH, so the acceptable layout inductance range remains open. Use the published model in the next layout trial and extract the actual loops. Recheck fault interruption, repetitive switching losses and device safe operating area. The vendor-driver rail verification remains open. [ST part and PSpice model archive](https://www.st.com/en/diodes-and-rectifiers/stpst10h100.html) · [Results](bench-inductive-waveform-results.json)

From this directory, reproduce the nominal saved waveform and candidate measurement with ngspice and the two TI archives. Use `--capture trace` on the candidate to save and inspect its key waveform extrema. Run the hot high-side case with `--case hot_high --steering both` to exercise both modeled diodes.

```sh
python bench_inductive_waveform.py --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP \
  --output original-waveform.json
python bench_inductive_waveform.py --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP \
  --high-gate-ohm 27 --snubber-nf 2.2 --steering q6 --capture measurements --output candidate.json
python bench_inductive_waveform.py --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP \
  --high-gate-ohm 27 --snubber-nf 2.2 --steering both --capture measurements --case hot_high \
  --schottky-archive st-schottky-models.zip --output st-hot-trial.json
```

Reproduce the extracted cases with the two TI model archives and ngspice. Use the PCB and schematic with the same stem for native ERC and DRC.

```sh
python isolated_rear_bypass.py extract
python isolated_rear_bypass.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP
python isolated_rear_bypass.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP --mode compare
python isolated_rear_bypass.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP \
  --low-gate-ohm 39 --pin-bypass-nh 0.6 --step-ps 125 --nominal --case nominal_low_short \
  --output pin-bypass-repeat.json
python isolated_rear_bypass.py replay --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP \
  --nominal --quick --step-ps 500
```

## Independent Xyce verification

Xyce 7.10 ran the original TI UCC21520 PSpice macro in the standalone fixture. With normal local truncation error control, its Gear run stalled at the enable edge. Gear and trapezoidal runs completed with Newton-iteration timestep control (`ERROPTION=1`, 2 ns maximum step). Xyce warned that it ignored the macro's internal MOS parameters `N` and `RG`. The CSD19531Q5A translation uses the same vendor coefficients with Xyce's BSIM3 model level, table syntax and explicit constants for the geometry and temperature parameters. Its default transient stalled at turn-off. Gear with the alternate timestep control completed, and both engines measured 12.98 mV on-state drop and 24.00 V off-state voltage in the resistive fixture. These two operating points check the translation's DC behavior. [Xyce reference guide](https://xyce.sandia.gov/documentation-tutorials/) · [TI driver models](https://www.ti.com/product/UCC21520#design-development) · [TI MOSFET model](https://www.ti.com/product/CSD19531Q5A#design-development)

| Driver control input gap and direction | ngspice | Xyce Gear | Xyce trapezoidal |
| --- | ---: | ---: | ---: |
| 20 ns, high to low | +81.9 ns | −3.6 ns | −3.5 ns |
| 200 ns, high to low | +177.5 ns | +176.6 ns | +176.7 ns |
| 200 ns, low to high | +177.5 ns | +176.6 ns | +176.8 ns |

The measurements use the 2 V gate crossings. Positive values are separation, and negative values are simultaneous gate voltage above 2 V. The 200 ns command gap comes from `BENCH_BLANK` in the existing scheduler. The prototype can retain that command gap for the next verification stage. The test uses capacitive gate loads, so actual channel overlap, receiver skew and switching stress still need the routed power stage. [Firmware command spacing](bench-startup.h) · [TI dead-time definition and selection guidance](https://www.ti.com/lit/ds/symlink/ucc21520.pdf#page=33)

The replay captures DIS and both PWM voltages relative to VSS from the 500 ps ngspice protection simulation. Both engines receive those same three traces as piecewise-linear sources that reproduce the accepted samples within 5 mV. The 33-port impedance, driver, bias rails, transistor models and load are retained. The ideal sources also change the impedance driving the input pins. The local comparator, receiver and latch are exercised in the original ngspice capture.

Ngspice completed the prescribed-input high-side resistive run and Q6-short run. Their minimum high-side pin biases shifted from 6.97 V and 7.02 V in the original runs to 6.18 V and 6.22 V. The Q6-short peak at Q5 was 47.38 V. The Q5-short replay stalled at 0.85 µs in both runs. In an intervening attempt, a closed-loop Q6-short capture also stalled at 1.58 µs. Running the captures before starting the replay jobs recovered all three original input traces. At a 60-second wall-clock limit per deck, Xyce reached 41–50 ns of simulated time in the six routed runs, before any switching event. [Replay measurements and input hashes](bench-secondary-isolated-dfn-rear-bypass-xyce.json) · [Replay script](isolated_xyce_replay.py)

```sh
python isolated_xyce_replay.py --driver-archive SLUM543.ZIP --mosfet-archive SLPM077C.ZIP --timeout 60 --jobs 8
```

Fabrication remains on hold. Correlate the pin rail waveform using the vendor-supported simulator or a converged independent replay. Review the paired drain-voltage and current stresses and close the hot and inductive cases before duplicating the leg. [PSpice for TI](https://www.ti.com/tool/PSPICE-FOR-TI)

## Reproduce

Run from the battery-port directory with KiCad, FastHenry and ngspice available. Use `SLPM077C.ZIP` and the unzipped `SLUM720` library from the prior driver study. The replay saves measurements before reporting the open limits.

```sh
kicad-cli sch erc --exit-code-violations battery-port-secondary-protected.kicad_sch
kicad-cli pcb drc --schematic-parity --exit-code-violations battery-port-secondary-protected.kicad_pcb
python protected_layout_extract.py --output bench-secondary-protected-impedance.json
python protected_layout_replay.py --vendor-archive SLPM077C.ZIP \
  --driver-model UCC27282_Unencypted_PSpice_Model.lib \
  --output bench-secondary-protected-replay.json
```
