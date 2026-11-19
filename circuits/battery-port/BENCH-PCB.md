# Bench PCB routing and verification

Open the editable [KiCad board](battery-port-bench.kicad_pcb) in the [bench project](battery-port-bench.kicad_pro). The 122 × 103 mm outline and four copper layers are provisional. All 149 schematic parts are placed. The primary occupies the left side and the secondary the right. A 2.6 mm copper and via keepout through the board center preserves room for the isolation boundary. T1 and the four digital isolators straddle it. The keepout is a placement constraint for this 12 V ↔ 24 V prototype. The household converter requires its own isolation design.

## Copper already routed

Each leg has a local ceramic across its rail. The front-copper commutation path runs from the capacitor positive pad to the high-side drain, through the high-side source and low-side drain connection, then from the low-side source back to the capacitor negative pad. The positive and return branches are 0.9 mm wide. The switched-node trace is 1.2 mm wide. The driver HS and VSS traces land directly at the respective high-side and low-side source pads. HS uses In2.Cu after its front-layer fan-out. VSS leaves the driver’s exposed-pad copper through a single via, then follows In1.Cu to the low-side source. This puts the VSS vias clear of the PWM input escapes.

| Leg | MOSFETs | Driver | Local capacitor | Top copper in commutation loop | HS reference trace |
| --- | --- | --- | --- | ---: | ---: |
| Primary A | Q1, Q2 | U2 | C26 | 21.70 mm | 19.02 mm |
| Primary B | Q3, Q4 | U102 | C28 | 21.70 mm | 19.02 mm |
| Secondary A | Q5, Q6 | U202 | C27 | 20.65 mm | 19.02 mm |
| Secondary B | Q7, Q8 | U302 | C29 | 20.65 mm | 19.02 mm |

The lengths are copper centerlines measured in the board plane. Device leads, via barrels and pad current spreading still need to be included in the model. C26 and C28 are 1 µF / 25 V in 0805. C27 and C29 are 1 µF / 50 V in 1206. Select the ceramic by effective capacitance at the rail voltage, ESR and ESL.

All eight gate output paths run through their series resistors. Each leg has its gate and enable pull-downs, bootstrap capacitor and local VDD bypass wired. The high-side and low-side gate traces total 17.14 mm and 18.26 mm per leg, respectively, excluding the series resistors and via barrels. The HB pin-to-capacitor route is 8.36 mm with two through vias. Include those vias and the HS reference path when simulating bootstrap recharge and switching. The VDD feeds run to the respective 10 V regulator output and reservoir. [TI gate-driver layout guidance](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)

The 12 V and 24 V terminals, bulk capacitors and both bridges are wired. The primary positive feed passes through R30. Its Kelvin sense pads have separate inner-layer traces to U1 and J1. The four T1 winding terminals are connected. The primary A path runs through L1 and the current transformer's primary conductor.

The rest of the routing covers both bias regulators, the current transformer’s sense winding and fast trip detector, the PWM and hardware permission paths, the isolated precharge signals, and the telemetry. Freerouting 2.5.0 proposed the signal routes locally. The final board includes the repaired PWM input escapes and 0.20 mm minimum trace width. The commutation, rail and winding copper from the prior revision was preserved. The driver return via fan-outs and two enable pull-down returns were changed to make room for the input traces. [Freerouting](https://github.com/freerouting/freerouting/releases/tag/v2.5.0)

## Verification before fabrication

KiCad 10.99 reported zero schematic electrical-rule violations, zero board design-rule violations, zero open connections and zero schematic-to-board mismatches. The board has 1,850 trace segments and 256 vias. The L1 repair moved three through vias and their six attached segments. The routes retain 1.20 mm top copper, 1.25 mm bottom copper and parallel 0.40 mm drills on each end of L1. The circuit regression checks all 256 via holes against the SMD lands. It reproduced the three failures on the pre-repair board and passed on the revised board.

| L1 pad and net | Old via centre (mm) | New via centre (mm) | Nominal gap from hole edge to land (mm) |
| --- | --- | --- | ---: |
| 1, PRI_A | (65.300, 93.500) | (64.300, 93.500) | 0.518 |
| 1, PRI_A | (66.650, 93.500) | (66.650, 92.800) | 0.500 |
| 2, CT_OUTBOUND | (74.100, 93.775) | (74.650, 94.650) | 0.435 |

### Stack-up for electrical extraction

KiCad models the nominal 1.6 mm JLC04161H-7628 four-layer construction. The stack uses 35 µm finished outer copper and 15.2 µm inner copper. From top to bottom, the copper layers are separated by 0.2104 mm prepreg, 1.065 mm core and 0.2104 mm prepreg. Use relative permittivities 4.4 for the prepreg and 4.6 for the core. The board models a uniform 15.24 µm solder mask on each side, based on the published over-trace value, with relative permittivity 3.8. The copper and dielectric thicknesses sum to 1.5862 mm beneath the mask. [Fabricator stack-up and dielectric data](https://jlcpcb.com/impedance)

Use the actual copper on each layer to model return paths. The inner layers carry traces. Model the via barrel separately and sweep plating thickness until the selected process supplies an assured value. Verify the final stack, finished drills, via covering and stencil against the assembler's process at the fabrication review.

### Component drawing review

| Assembly | Drawing and board check | Remaining fit check |
| --- | --- | --- |
| T1 ETD29 transformer | The 13-hole footprint matches the drawing's 5.08 mm pitch, 25.4 mm row spacing, unoccupied middle position on the six-pin row and nominal 1.6 mm holes. Its 35.5 mm square fabrication outline encloses the 35.3 × 35.2 mm maximum former envelope. | Check the complete wound assembly with its two B66359S2000X000 yokes. Confirm the finished hole tolerance and map the winding dots on the drawing. [TDK former drawing, page 4](https://www.tdk-electronics.tdk.com/inf/80/db/fer/etd_29_16_10.pdf#page=4) |
| Q1–Q8 TO-220 | The 2.54 mm lead pitch matches the KCS outline. The generic footprints use 1.10 mm holes. TI's example uses 1.20 mm. | Check worst-case finished-hole fit with the chosen process and confirm heatsink, live drain-tab clearance and hardware before release. [TI KCS drawing and land pattern](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf#page=12) |
| C25 secondary bulk capacitor | The footprint matches the 18 mm body and 7.5 mm lead pitch. The nominal body edge sits 1.7 mm inside the board outline. The listed height is 35.5 mm. | Allow for body tolerance, soldered height and clearance to fixture hardware. [Panasonic EEUFC1H222 dimensions](https://industrial.panasonic.com/ww/products/pt/aluminum-cap-lead/models/EEUFC1H222) |

FastHenry extracted the commutation and driver paths for all four legs. The per-leg commutation loops are about 8 nH at 10 MHz. The layout-aware switching screen captured local rail current, drain stress and negative driver HS excursions in both directions. The vendor models still stop before usable switching results, and the precharge gate waveform needs follow-up. Fabrication remains subject to the project software verification gate. [Extraction and switching results](BENCH-LAYOUT-SIMULATION.md) · [Project software verification](../../HELIOS-VERIFICATION.md)
