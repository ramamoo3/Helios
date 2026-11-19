# Bench PCB placement and commutation routing

Open the editable [KiCad board](battery-port-bench.kicad_pcb) in the [bench project](battery-port-bench.kicad_pro). The 122 × 103 mm outline and four copper layers are provisional. All 149 schematic parts are placed. The primary occupies the left side and the secondary the right. A 2.6 mm copper and via keepout through the board center preserves room for the isolation boundary. T1 and the four digital isolators straddle it. The keepout is a placement constraint for this 12 V ↔ 24 V prototype. The household converter requires its own isolation design.

## Copper already routed

Each leg has a local ceramic across its rail. The front-copper commutation path runs from the capacitor positive pad to the high-side drain, through the high-side source and low-side drain connection, then from the low-side source back to the capacitor negative pad. The positive and return branches are 0.9 mm wide. The switched-node trace is 1.2 mm wide. The driver HS and VSS traces land directly at the respective high-side and low-side source pads. HS uses In2.Cu after its front-layer fan-out and VSS uses In1.Cu. Each has one through via.

| Leg | MOSFETs | Driver | Local capacitor | Top copper in commutation loop | HS / VSS reference traces |
| --- | --- | --- | --- | ---: | ---: |
| Primary A | Q1, Q2 | U2 | C26 | 21.70 mm | 18.67 / 10.87 mm |
| Primary B | Q3, Q4 | U102 | C28 | 21.70 mm | 18.67 / 10.87 mm |
| Secondary A | Q5, Q6 | U202 | C27 | 20.65 mm | 18.67 / 10.87 mm |
| Secondary B | Q7, Q8 | U302 | C29 | 20.65 mm | 18.67 / 10.87 mm |

The lengths are copper centerlines measured in the board plane. Device leads, via barrels and pad current spreading still need to be included in the model. C26 and C28 are 1 µF / 25 V in 0805. C27 and C29 are 1 µF / 50 V in 1206. Select the ceramic by effective capacitance at the rail voltage, ESR and ESL.

## Verification and remaining routing

KiCad 10.99 reported zero schematic electrical-rule violations, zero schematic-to-PCB mismatches and zero violations in the placed and routed geometry. It reported 403 unrouted connections. The board still needs gate-drive and bootstrap wiring, driver exposed-pad returns, the bulk capacitor and rail feeds, shunt Kelvin sense routing, magnetics and control wiring. Establish the copper thickness, dielectric stack and cooling provisions before freezing the layout. Confirm the mechanical fits at T1, the TO-220 bodies and the 35.5 mm-tall secondary bulk capacitor.

For the next transient model, extract feed, return and shared source impedance from the selected stack-up and the routed copper, including the via and MOSFET pad geometry at each source takeoff. Include local capacitor effective capacitance, ESR and ESL and the TI package parasitics already in the device model. Use the extracted paths to check local rail current, MOSFET Vds, negative switch-node excursions and channel overlap in both power directions. Fabrication requires completion of the routing and the [software verification](../../HELIOS-VERIFICATION.md). [Prior switching simulations](BENCH-BOOTSTRAP.md#channel-overlap-during-startup)
