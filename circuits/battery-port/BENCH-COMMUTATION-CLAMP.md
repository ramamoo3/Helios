# Bench commutation clamp and return layout

The candidate adds a 2.2 Ω, 4.7 nF series snubber across each MOSFET, a 30 V unidirectional TVS across the low-side MOSFET, and a 100 nF bootstrap capacitor directly at the UCC27282 HB and HS pins. The KiCad sheet passed ERC in a test parent with all five ports connected. The bench converter still requires placement, routing and extraction for the revised geometry. [KiCad candidate](battery-port-leg-clamp.kicad_sch)

## Placement and extraction targets

| Connection | Existing secondary leg A | Candidate |
| --- | --- | --- |
| Driver VSS to low-side source | 11.3 mm routed, 7.38 nH at 10 MHz | Place the driver beside the MOSFET pair. Route its VSS straight to the low-side source land on a Kelvin branch, on the MOSFET side of the four-terminal shunt. The nominal model uses 1.99 nH. |
| Driver HS to high-side source | 4.1 mm to the bootstrap return tee, then 14.9 mm to the source. The two extracted self terms are 3.29 and 12.78 nH. | Shorten the source branch and take it at the high-side source land. The modeled self terms are 0.43 and 2.30 nH. Keep the high-current switch-node branch separate at the land. |
| Bootstrap capacitor | 8.4 mm from HB to the capacitor and another 1.2 mm to the HS return tee | Place the capacitor directly on the driver side of the Kelvin junction. The modeled capacitor loop uses 0.35 nH nominal and 0.70 nH in the longer-return corner. Move the existing capacitor connection when integrating the sheet. |
| Snubber loops | Existing power paths | Connect R1/C1 across the high-side package pads and R2/C2 across the low-side package pads. The model assumes 0.8 nH in each loop at nominal, and 1.4 nH at the longer layout corner. Use pulse-rated resistors and 100 V C0G capacitors. |
| Low-side TVS loop | New branch | Locate D1 at the low-side drain and source lands, with cathode to drain. Use wide, short copper and keep the package and board path at or below **2.5 nH total**. The anode connects to the FET-side source land so clamp current stays in the intended commutation path. |

The old dimensions come from the routed board via `extract_layout.py`. The candidate is a sensitivity model. It reduces the five selected self terms and scales their mutual terms to preserve a passive matrix, while leaving the power-path and gate-feed self terms intact. A separate sweep removes mutual coupling to those returns and crosses the stress targets. Extract the signed mutual terms, package connections, capacitor ESL and TVS loop from the new layout before transferring these results to hardware. [Board extraction](BENCH-LAYOUT-SIMULATION.md) · [TI driver layout guidance](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)

## Simulated switching and faults

The ngspice model preserves the isolated receiver timing and the 5 mΩ shunt and 6.8 nF filter. The fault fixture holds EN and the raw PWM request high through the observation window. The TVS model uses 36.8 V breakdown and a slope fitted to the manufacturer's 48.4 V clamping point at 103 A. The hot corner uses a 39 V knee, 0.14 Ω slope, reduced capacitance and increased interconnect inductance as sensitivity assumptions. The datasheet rates clamping on a 10/1000 µs pulse. The approximation does not establish nanosecond overshoot, pulse endurance or repetitive fault ratings. [Littelfuse 5.0SMDJ30A datasheet](https://www.littelfuse.com/~/media/electronics/datasheets/tvs_diodes/littelfuse_tvs_diode_5_0smdj_datasheet.pdf.pdf)

| Configuration | Outcome |
| --- | --- |
| Original secondary A | HS reached −35.1 V relative to VSS and HB–HS reached 40.5 V. One short retained more than 1 A at its observation point. |
| Shorter returns, snubbers and pin-local bootstrap capacitor | Secondary A cleared both modeled faults. Peak VDS was still 59.6 V before adding the low-side TVS. |
| Nominal candidate, 2 nH TVS loop | All eight short cases met the current and stress criteria. Worst VDS was 46.3 V. The lowest HS was −6.7 V, and peak HB–HS was 12.7 V. |
| Hot corner, 2.5 nH TVS loop | All eight short cases met the current and stress criteria. Secondary A also passed at 125 ps and 500 ps maximum timesteps. Across those runs, worst VDS was 51.5 V, peak HB–HS was about 14.0 V and the largest TVS energy proxy was about 108 µJ. The longest time between the first and final 1 A crossings was 230.1 ns. |
| Hot corner, 4 nH TVS loop | The secondary high-side shorts rose to 55.1 V, above the 54 V design target. |
| Optional ST catch diode | The published model reduced the negative HS excursion on the nominal secondary leg. It did not restore the 54 V margin at the 4 nH hot corner. The base candidate uses the single low-side TVS. [ST Schottky model and datasheet](https://www.st.com/en/diodes-and-rectifiers/stps20m60s.html) |

The normal runs drove both commanded pulses. The high-side gate still peaked at 0.35–0.65 V during precharge across the nominal and 2.5 nH corner cases, above the existing 0.1 V screening target. The separate high-side channel probe measured less than 1 µA of forward current during precharge in the compact MOSFET model and about 2.5 A in the commanded positive control. Confirm the waveform with a converged vendor model and temperature corners before accepting the precharge behavior. [Case-level results](bench-commutation-clamp-results.json)

For component sizing, a first-order estimate for one 4.7 nF snubber on a 24 V full-swing node at 50 kHz is about 0.135 W. Check continuous and individual pulse limits from the actual resistor voltage waveform, plus capacitor temperature and assembled clamp-loop inductance. [Pulse-resistor data](https://www.vishay.com/docs/20115/crcwhp.pdf)

## Reproduce and integrate

Run from the battery-port directory. The optional ST archive adds the catch-diode comparisons.

```sh
python commutation_clamp_test.py --output bench-commutation-clamp-results.json
python commutation_clamp_test.py --catch-archive /path/to/st_power_schottky_diodes_pspice_models_v6.zip --output bench-commutation-clamp-results.json
```

The runner saves the results and returns failure while the precharge criterion remains open. The subsequent routed secondary-leg study found 4.33 nH in the clamp copper and excessive stress in the replay. Further placement work is required before repeating the layout across all four legs. [Routed secondary-leg results](BENCH-SECONDARY-LAYOUT.md)
