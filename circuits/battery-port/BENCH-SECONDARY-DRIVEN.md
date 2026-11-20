# Compact secondary leg with local gate drive

The 33 × 27 mm four-layer board adds a UCC27282DRC to the CSD19531Q5A power cell for one 24 V secondary leg of the 12 V ↔ 24 V bench battery port. It includes the 100 nF bootstrap capacitor and bias bypass, a 22 µF bias reservoir, separate 4.7 Ω gate resistors and 10 kΩ gate and enable pull-downs. The low-side gate return connects to the MOSFET source before the 5 mΩ shunt. The isolated receiver and current-trip circuit connect at the interface pads. [KiCad board](battery-port-secondary-driven.kicad_pcb) · [TI half-bridge reference](https://www.ti.com/tool/TIDA-050022) · [Driver data sheet](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)

| Pad | Connection |
| --- | --- |
| TP1, TP2, TP3 | Positive rail, rail return and switch node |
| TP4, TP5 | Isolated gate-driver bias and source reference |
| TP6, TP7, TP10 | LI, HI and EN, referenced to TP5 |
| TP8, TP9 | Positive and negative Kelvin sense |

KiCad 10.99.0 reported zero violations and zero unconnected items. All 20 via holes clear the SMD solder lands. The DRC applies to the layout study. Schematic parity and integration into the complete bench PCB remain open.

## Coupled copper extraction

The 21-port FastHenry matrix includes both MOSFET source fingers, the shunt force path on the PCB, the driver pin-9 reference, the bootstrap tee, the 100 nF bypass and both legs of the rear TVS connection. Each shared segment enters the matrix once. Separate extractions estimate the two snubber loops. The model uses a nominal 1.617 mm stack and 20 µm via plating. It approximates copper spreading in the package lands. [Extraction data](bench-secondary-driven-impedance.json)

| Loop at 10 MHz | Coupled board estimate |
| --- | ---: |
| Main commutation | 8.85 nH |
| High-side gate | 12.35 nH |
| Low-side gate | 21.00 nH |
| Bootstrap | 2.18 nH |
| Driver 100 nF bypass | 3.44 nH |
| Low-side clamp | 4.36 nH |
| High-side / low-side snubber | 12.05 / 10.88 nH |

Moving the low-side gate resistor closer to Q6 and pairing the long gate and return traces on the first inner layer cut the estimated low-side loop from 32.03 nH to 21.00 nH. The shorter high-side gate and bootstrap loops measure 12.35 and 2.18 nH, versus 15.54 and 2.86 nH on the earlier TO-220 driver coupon. The new power-path model reaches the low-side MOSFET source finger and includes the short segment between that finger and the source star. The earlier compact power-only estimate started at the star. With three filaments across each track, the revised commutation, bootstrap and clamp estimates were 9.01, 2.19 and 4.43 nH respectively. [TO-220 driver reference](BENCH-SECONDARY-LAYOUT.md) · [Prior compact power cell](BENCH-SECONDARY-COMPACT.md)

## Clamp placement comparison

| Rear footprint and stack | Clamp copper at 10 MHz |
| --- | ---: |
| Selected 5.0SMDJ30A SMC, 1.617 mm | 4.36 nH |
| Same SMC geometry, 0.827 mm stack sensitivity | 3.66 nH |
| 1.5SMB36A geometry, 1.617 mm | 3.53 nH |
| 1.5SMB36A geometry, 0.827 mm stack sensitivity | 2.55 nH |

The smaller footprint moves the diode lands between and directly in line with the existing vias. Its geometry passed DRC and via clearance on the baseline stack. The thinner stack is an extraction variation. All four results exceed the 2.5 nH total budget before adding package inductance. The integrated board retains the 5.0SMDJ30A, rated for 103 A on the published 10/1000 µs waveform. The 1.5SMB36A has a 30.8 V standoff and a 30.5 A rating on the same waveform. Its clamping voltage, short-pulse response and package inductance need qualification against the actual fault waveform. [5.0SMDJ data sheet](https://www.littelfuse.com/assetdocs/littelfuse_tvs_diode_5_0smdj_datasheet.pdf?assetguid=2b2f4a8c-2e81-4894-8d41-3d748bb79e68) · [1.5SMB data sheet](https://www.littelfuse.com/assetdocs/tvs-diode-1?assetguid=7ef1e879-b132-484e-b0bd-507f52b5dbb5)

## Replay with the routed driver

Ngspice 47 ran TI’s CSD19531Q5A model in both fixtures. One used the existing reduced-order switching driver, and the other used TI’s UCC27282 model. A separate resistive half-bridge control with both TI models reported 9.92 V and 9.53 V on the commanded low- and high-side gates, 48 ns from EN falling to high-side turn-off, and 24.86 V peak drain stress. The routed fixture includes the shunt transfer model, the receiver and shutdown models, both snubbers, and the reduced-order TVS. The runs assume 1–2 nH of TVS package inductance and retain the bulk bias reservoir as a lumped element at the driver. [Full replay results](bench-secondary-driven-replay.json)

| Cases | Reduced-order driver | TI driver |
| --- | --- | --- |
| Precharge only, 25 and 100 °C | Both completed with high-side gate peaks of 0.072–0.073 V, within the 0.10 V screen | Both stopped with a timestep error near 1 µs |
| Normal switching, four current-load cases per driver | One completed, with 101.1 V peak MOSFET drain voltage and HB–HS outside the driver range. Three stopped with timestep errors. | All four stopped during precharge. Two additional resistive-load checks stopped before the load ramp. |
| Four short cases per driver | All interrupted with 74.8–89.0 V peak drain stress | All interrupted with 58.5–95.9 V peak drain stress |

All eight shorts left less than 31 mA at the observation window while the raw gate request remained high. TI-driver current clearance took 73–324 ns from the 1 A crossing. Peak terminal current in the selected rear clamp was 62.4 A across the two model sets. This current includes displacement current and is specific to the modeled fixture. The TI-driver high-side-switch-short cases reached approximately −1.50 V across HB–HS, below the driver's −0.3 V absolute minimum. The completed normal run also exceeded the 100 V MOSFET absolute maximum. The independent TI control establishes that the two models run together in a simple circuit. It leaves precharge, switching edge stress and short-circuit waveform validation open on the coupled layout. [Driver absolute maximum ratings](https://www.ti.com/lit/ds/symlink/ucc27282.pdf) · [MOSFET absolute maximum ratings](https://www.ti.com/lit/ds/symlink/csd19531q5a.pdf)

### High-side clamp sensitivity

Adding an unrouted `BENCH_TVS` across the high-side MOSFET terminals reduced its peak during a low-side short from 95.9 to 38.3 V at 25 °C and from 79.6 to 47.9 V at 100 °C, with a 2.5 nH assumed total loop. Two fault polarities, two temperature corners and two assumed loop inductances of 2.5 and 4.0 nH completed. When the high-side switch failed short, the low-side peak was still 57.5–60.1 V and HB–HS still reached about −1.50 V. The screen supports routing a dedicated clamp at Q5 and addressing the bootstrap differential and Q6 loop separately. [Sensitivity data](bench-secondary-driven-clamp-screen.json)

The sensitivity adds `Xtvs_high drainh sourceh p_tvs_high BENCH_TVS` to each TI-driver short deck and uses the same temperature-dependent TVS parameters as the low side. Its `LLOOP` includes the assumed copper and package contributions. The added diode energy is the integral of `v(p_tvs_high)` over the 4 µs run.

**Fabrication remains on hold.** Route and qualify suppression for both switch positions and the bootstrap differential. Repeat precharge and commutation with the extracted layout and TI device models. Complete the matching schematic and check parity before carrying the cell into the full bench board.

The follow-on board now routes both TVS devices and the bootstrap Schottky and has a parity-checked schematic. [Protected secondary bench leg](BENCH-SECONDARY-PROTECTED.md)

## Reproduce the selected board

Run from the battery-port directory with FastHenry and ngspice on PATH. Use TI’s unencrypted SLUM720 driver library and SLPM077C MOSFET archive. The replay writes the measurements and reports an unsuccessful status while waveform or copper limits remain open. [UCC27282 models](https://www.ti.com/product/UCC27282#design-development) · [CSD19531Q5A models](https://www.ti.com/product/CSD19531Q5A#design-development)

```sh
python driven_layout_extract.py --output bench-secondary-driven-impedance.json
python driven_layout_extract.py --core-mm 0.275 --output driven-thin-sensitivity.json
python driven_layout_replay.py --vendor-archive SLPM077C.ZIP \
  --driver-model UCC27282_Unencypted_PSpice_Model.lib \
  --output bench-secondary-driven-replay.json
```
