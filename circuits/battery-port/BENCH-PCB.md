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

KiCad 10.99 reported zero schematic electrical-rule violations, zero board design-rule violations, zero open connections and zero schematic-to-board mismatches. The board has 1,850 trace segments and 256 vias. A geometry comparison verified the preserved power copper and checked that every trace and via stays clear of the center keepout. The new through drills clear the SMD copper lands. The local SPICE regression passed with the existing circuit models.

Establish the copper thickness, dielectric stack and cooling provisions before freezing the layout. Confirm the mechanical fits at T1, the TO-220 bodies and the 35.5 mm-tall secondary bulk capacitor.

For the next transient model, extract feed, return and shared source impedance from the selected stack-up and the routed copper, including the via and MOSFET pad geometry at each source takeoff. Include local capacitor effective capacitance, ESR and ESL and the TI package parasitics already in the device model. Use the extracted paths to check local rail current, MOSFET Vds, negative switch-node excursions and channel overlap in both power directions. Fabrication requires completion of the routing and the [software verification](../../HELIOS-VERIFICATION.md). [Prior switching simulations](BENCH-BOOTSTRAP.md#channel-overlap-during-startup)
