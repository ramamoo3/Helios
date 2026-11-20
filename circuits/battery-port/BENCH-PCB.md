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

### Return-plane trial and design rules

The routed parent board carries `/P0` and `/S0` on traces. Its only zone is the primary-to-secondary keepout. The trial adds `/P0` on `In1.Cu` and `/S0` on `In2.Cu`, within separate geometries that stop short of the existing keepout. Existing through connections join the fills to routed copper. The trial widens 20 inner winding segments from 1.20–1.25 mm to 1.60 mm and shifts the `/SEC_B` diagonal to clear an adjacent unnumbered transformer land. After refill, KiCad reported zero ERC and DRC violations, zero open connections and zero schematic parity issues. The solder-land check also passed all 256 vias after native save. [Trial generator](bench_return_plane_trial.py)

The KiCad project assigns the secondary domain and power nets explicitly. The 1.2 mm power-class width is the router's starting width. The custom DRC checks a 0.20 mm routing floor and 0.60 mm of same-layer clearance between named nets in different domains, including pad-to-track and pad-to-pad clearance. The bench passed both rules with zero schematic parity errors. Raising the interdomain threshold to 4 mm in a scratch check produced violations, with a minimum reported gap of 3.00 mm on the routed baseline. Unnumbered transformer holes lack net assignments and need a separate mechanical and insulation review. The 0.60 mm value is a bench design target. [KiCad project](battery-port-bench.kicad_pro) · [Custom design rules](battery-port-bench.kicad_dru) · [KiCad design rules documentation](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#custom-design-rules)

Centreline tracing found 1.35–1.60 mm copper in the R30-to-primary-drain feeds. The main Q3-to-T1 and both secondary switch-to-T1 paths use 1.20 mm on `In2.Cu`. The 0.24–0.28 mm sections on those switch nets route to the gate-driver or bootstrap connections. Each local commutation loop still has 0.90 mm feed and return branches on the front copper. A 20 °C copper-only screen put the inner winding runs at 13.9–20.1 mΩ on the baseline and 10.8–15.4 mΩ in the trial, a 22–25% reduction per run. That estimate covers the selected traces. [Power path extraction](extract_layout.py)

The filled trial has four 2.8 mm non-plated holes for M2.5 hardware with 6.4 mm all-layer copper keepouts, and three 1 mm top copper fiducials with 2 mm mask openings. Hole coordinates in KiCad millimetres are (52, 47), (147, 62), (52, 132) and (152, 140). Each mounting keepout has at least 1.8 mm clearance to the outline, and each fiducial mask opening has at least 0.5 mm. Actual head, standoff, connector and enclosure fit still require a fixture review. [Mounting footprint](Helios_Bench.pretty/Bench_mount_M2_5.kicad_mod) · [Fiducial footprint](Helios_Bench.pretty/Bench_fiducial_1mm.kicad_mod)

Generate a candidate in a scratch copy of the KiCad project directory, with the local symbol and footprint libraries available. Copy the parent `.kicad_pro` and `.kicad_dru` to the trial board's stem before running KiCad.

```sh
python bench_return_plane_trial.py path/to/scratch/return-trial.kicad_pcb
kicad-cli pcb drc --refill-zones --save-board --exit-code-violations path/to/scratch/return-trial.kicad_pcb
```

### Electrical extraction of the filled trial

The DC solver reads the filled polygons, keeps their cutouts, unions same-layer traces and lands, and connects each plane through the actual plated holes. The comparison covers 20 and 25 µm barrel plating and meshes down to 0.10 mm. Each test injects a specified current between two terminals. The reported losses use the modeled winding-current scale and prescribed copper temperature. The 1 µs adiabatic screen applies to traces and barrels. Steady-state temperature rise needs the assembled fixture's heat sources and cooling conditions. [DC model](bench_plane_dc.py) · [DC results](bench-return-plane-dc.json)

At 20 µm plating, the worst baseline secondary return, C25.2 to Q8.3, dropped from 59.08 mΩ to 3.98 mΩ at 20 °C. Its modeled copper loss fell from 0.554 W to 0.037 W at 2.67 A and 100 °C copper. The worst baseline primary return, C24.2 to Q4.3, dropped from 32.28 mΩ to 2.13 mΩ. The two finest meshes agreed within 3.6% on the selected return paths. Local capacitor-to-switch returns stayed at 3.38–3.67 mΩ. Four widened winding paths dropped 19–21% in the full path model. Inspect its per-path trace and barrel current distribution when selecting plating and planning thermal measurements. [DC results](bench-return-plane-dc.json)

The filled-copper FastHenry model approximates the secondary-A feed, switch and return with filaments. At 10 MHz the trace baseline returned 7.99 nH. The 2, 1.5 and 1 mm filled meshes returned 7.64, 7.61 and 7.60 nH respectively. The 1 mm three-port repeat completed within its iteration limit. A separate 1 mm run joined the paths in series at ideal switch terminals and reproduced the three-port sum. The runs have filament geometry warnings. This measures numerical consistency for one loop in the filament model. Capacitive coupling, enclosure effects and the other three bridge loops remain open. [AC model](bench_plane_ac.py) · [AC results and solver options](bench-return-plane-ac.json) · [FastHenry user guide](https://www.fastfieldsolvers.com/Download/FastHenry_User_Guide.pdf)

The BOM update adds hidden purchasing fields to the trace-only parent. The stored 12-port trace extraction reproduced with the same matrices after that update. Replays can use the original extraction only when removing those hidden fields reproduces its exact PCB hash. [Trace extraction](bench-bootstrap-impedance.json) · [Replay input check](layout_switching_test.py)

```sh
python -m pip install -r requirements-copper.txt
python bench_plane_dc.py path/to/filled-trial.kicad_pcb --pitch-mm .4 .2 .1 --output bench-return-plane-dc.json
python bench_plane_ac.py path/to/filled-trial.kicad_pcb --series-10mhz --pitch-mm 1.5 1 --timeout 260 --output series-repeat.json
```

| L1 pad and net | Old via centre (mm) | New via centre (mm) | Nominal gap from hole edge to land (mm) |
| --- | --- | --- | ---: |
| 1, PRI_A | (65.300, 93.500) | (64.300, 93.500) | 0.518 |
| 1, PRI_A | (66.650, 93.500) | (66.650, 92.800) | 0.500 |
| 2, CT_OUTBOUND | (74.100, 93.775) | (74.650, 94.650) | 0.435 |

### Stack-up for electrical extraction

KiCad models the nominal 1.6 mm JLC04161H-7628 four-layer construction. The stack uses 35 µm finished outer copper and 15.2 µm inner copper. From top to bottom, the copper layers are separated by 0.2104 mm prepreg, 1.065 mm core and 0.2104 mm prepreg. Use relative permittivities 4.4 for the prepreg and 4.6 for the core. The board models a uniform 15.24 µm solder mask on each side, based on the published over-trace value, with relative permittivity 3.8. The copper and dielectric thicknesses sum to 1.5862 mm beneath the mask. [Fabricator stack-up and dielectric data](https://jlcpcb.com/impedance)

Use the actual traces and filled zones on each layer to model return paths. Model the via barrel separately and sweep plating thickness until the selected process supplies an assured value. Verify the final stack, finished drills, via covering and stencil against the assembler's process at the fabrication review.

### Component drawing review

| Assembly | Drawing and board check | Remaining fit check |
| --- | --- | --- |
| T1 ETD29 transformer | The 13-hole footprint matches the drawing's 5.08 mm pitch, 25.4 mm row spacing, unoccupied middle position on the six-pin row and nominal 1.6 mm holes. Its 35.5 mm square fabrication outline encloses the 35.3 × 35.2 mm maximum former envelope. | Check the complete wound assembly with its two B66359S2000X000 yokes. Confirm the finished hole tolerance and map the winding dots on the drawing. [TDK former drawing, page 4](https://www.tdk-electronics.tdk.com/inf/80/db/fer/etd_29_16_10.pdf#page=4) |
| Q1–Q8 TO-220 | The 2.54 mm lead pitch matches the KCS outline. The generic footprints use 1.10 mm holes. TI's example uses 1.20 mm. | Check worst-case finished-hole fit with the chosen process and confirm heatsink, live drain-tab clearance and hardware before release. [TI KCS drawing and land pattern](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf#page=12) |
| C25 secondary bulk capacitor | The footprint matches the 18 mm body and 7.5 mm lead pitch. The nominal body edge sits 1.7 mm inside the board outline. The listed height is 35.5 mm. | Allow for body tolerance, soldered height and clearance to fixture hardware. [Panasonic EEUFC1H222 dimensions](https://industrial.panasonic.com/ww/products/pt/aluminum-cap-lead/models/EEUFC1H222) |

FastHenry extracted the commutation and driver paths for all four legs. The per-leg commutation loops are about 8 nH at 10 MHz. The layout-aware switching screen captured local rail current, drain stress and negative driver HS excursions in both directions. The vendor models still stop before usable switching results, and the precharge gate waveform needs follow-up. Fabrication remains subject to the project software verification gate. [Extraction and switching results](BENCH-LAYOUT-SIMULATION.md) · [Project software verification](../../HELIOS-VERIFICATION.md)
