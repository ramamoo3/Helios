# Compact secondary power cell

The 29 × 26 mm four-layer KiCad board clusters the rail ceramic, shunt and two 100 V CSD19531Q5A MOSFETs for one 24 V bench leg. It retains the WSK2512 5 mΩ shunt, both RC snubbers and the 5.0SMDJ30A TVS, mounted on the back. The clamp anode returns to the low-side source before the shunt. The rail ceramic returns on the supply side, and two separate Kelvin connections leave the shunt sense lands. The gates, source references and sense pair have test pads. The driver and receiver are external to this layout study. [KiCad board](battery-port-secondary-compact.kicad_pcb) · [TI power-stage reference](https://www.ti.com/tool/TIDA-050022)

KiCad 10.99.0 DRC reported zero violations and zero unconnected items. The independent drill check cleared all eight vias against SMD solder lands on both faces. The DQJ footprint groups the physical source leads 1–3 as KiCad pad 1, gate lead 4 as pad 2, and drain leads 5–8 and the exposed drain land as pad 3. Use that numbering convention when creating the matching schematic symbol. [CSD19531Q5A pinout and land pattern](https://www.ti.com/lit/ds/symlink/csd19531q5a.pdf)

## Copper impedance

| Loop at 10 MHz | TO-220 reference | Compact surface-mount |
| --- | ---: | ---: |
| Main commutation copper | 28.78 nH | 8.21 nH |
| Full low-side TVS copper | 4.33 nH | 3.93 nH |
| High-side snubber copper | 17.72 nH | 12.05 nH |
| Low-side snubber copper | 10.69 nH | 9.23 nH |

The seven-port FastHenry solve includes the shared drain path between the low-side MOSFET and the clamp branch, and uses 20 µm assumed via plating. Going from three to seven filaments across each track changed the commutation estimate from 8.36 to 8.21 nH and the full TVS path from 4.00 to 3.93 nH. The TVS-only branch estimate of 2.16 nH excludes the shared drain copper. Use 3.93 nH for comparison against the 2.5 nH budget, which also has to cover the TVS package. Separate three-port solves estimate the two snubber loops. The model uses routed copper and via geometry and approximates current spreading in the lands. [Compact matrices and stack](bench-secondary-compact-impedance.json) · [TO-220 extraction](BENCH-SECONDARY-LAYOUT.md)

Reducing the modeled central dielectric from 1.065 mm to 0.275 mm cuts the overall thickness from 1.617 mm to about 0.827 mm. The estimated full clamp copper drops to 3.26 nH and the commutation loop stays at 8.21 nH. The result is a stack sensitivity study. A thinner board alone leaves the clamp above budget before package inductance.

## Vendor-model replay

Ngspice 47 used the TI CSD19531Q5A PSpice model. The independent 24 V, 10 Ω load check measured 24 V with the gate off and a 12.98 mV drop with the gate on. The transient fixture combines the compact power copper with the earlier TO-220 board’s nine gate and bootstrap impedances and the reduced-order driver, receiver and TVS models. The package sensitivity assumes 1 nH of TVS package inductance at 25 °C and 2 nH at 100 °C. The hot short fixture also changes the clamp, snubber, comparator and sense-filter parameters. The changed MOSFET model and fixture limit direct waveform comparisons with the TO-220 run. [Replay data](bench-secondary-compact-replay.json) · [TI model SLPM077C](https://www.ti.com/product/CSD19531Q5A#design-development)

- **Four short cases** cleared within 201–247 ns of the 1 A crossing and reached less than 32 mA in the observation window with the raw gate request still asserted. Peak MOSFET drain stress was 67.6 V. All four stayed below the provisional 80 V screen for this 100 V MOSFET and exceeded the earlier 54 V comparison target.
- **Driver stress** remains open. Two cases reached about −9.7 V at HS relative to VSS against the −8 V design screen. The hot high-side-short case reached −8.15 V across HB–HS in the combined fixture. Compare that with the driver’s −0.3 V absolute minimum for the bootstrap differential when qualifying the actual driver and copper. [UCC27282 limits, sections 6.1 and 6.3](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)
- **Both precharge-only cases** converged through 2.5 µs. The commanded low-side gate reached 11.91–12.21 V. The uncommanded high-side gate reached 0.68–0.69 V against the 0.10 V screen. The vendor model exposes the drain terminal current, which includes displacement current and cannot establish channel overlap on its own.
- **Four normal-switching cases** stopped at the first switching transition near 3.38 µs. Gear at 250 ps and 125 ps and trapezoidal integration at 500 ps all hit the timestep limit. Normal switching and its stress limits remain unverified.

## Next revision

1. Place and route the UCC27282 with short gate and source-reference loops and a local bootstrap capacitor. Keep the receiver and Kelvin sense returns out of the commutation path.
2. Compare a closer pulse-rated clamp placement and both fault polarities. Include package inductance, clamp current and energy, MOSFET safe operating area, and gate-driver pin limits in the comparison.
3. Extract the actual gate and power paths together. Repeat precharge, bidirectional normal switching and short-circuit runs with a validated driver model. Resolve solver failures and verify thermal limits and independent DC interruption before fabrication review.

Fabrication remains on hold. This study covers one secondary leg of the 12 V ↔ 24 V bench battery port.

The follow-on layout now routes the driver, bootstrap and local bypass and replays the coupled extraction with the TI driver and MOSFET models. [Compact secondary leg with local gate drive](BENCH-SECONDARY-DRIVEN.md)

## Reproduce

Run from the battery-port directory with FastHenry and ngspice on PATH. Download the unencrypted SLPM077C model from the TI product page. The replay normalizes whitespace-only PSpice parameter assignments for ngspice while preserving their values.

```sh
python compact_layout_extract.py --mesh 7 --output bench-secondary-compact-impedance.json
python compact_layout_extract.py --mesh 7 --core-mm 0.275 --output compact-thin-sensitivity.json
python compact_layout_replay.py --vendor-archive SLPM077C.ZIP --output bench-secondary-compact-replay.json
```

The replay saves the case data and exits with a failure status while the layout or waveform criteria remain open.
