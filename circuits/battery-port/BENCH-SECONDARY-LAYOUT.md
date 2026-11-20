# Routed secondary-leg layout study

The 41 × 34 mm four-layer KiCad board routes one 24 V bench leg with Q5 and Q6 in their existing TO-220 packages, the UCC27282 driver, the WSK2512 shunt, the 5.0SMDJ30A TVS, and both snubbers. The reference and shutdown circuits connect at the test pads. KiCad DRC reported zero violations and zero unconnected items with the project and standard footprints loaded. All 28 via holes clear the SMD solder lands. [KiCad board](battery-port-secondary-layout.kicad_pcb)

The shunt is between the low-side source and supply return. The driver reference and TVS anode connect on the MOSFET side. The ceramic rail capacitor returns on the supply side. The two sense pads fan out separately. TP1–TP3 are local rail, supply return and switch-node access. TP4–TP8 carry driver bias, source reference, HI, LI and EN. TP9 and TP10 are the Kelvin pair. [Shunt connections](BENCH-SHUNT-TRANSFER.md) · [Driver layout reference](https://www.ti.com/tool/TIDA-050022)

## Extracted paths

FastHenry used the routed copper centerlines, actual segment widths, the four-layer stack, and an assumed 20 µm plated via wall. The signed 15-port matrix includes both clamp arms, each side of the shunt, both driver returns and the bootstrap branch tee. Separate three-port solves cover each snubber branch. The clamp figure excludes the SMC package. The model approximates pads and plated holes, omits capacitance and current spreading through neighboring copper, and represents each snubber's board impedance separately from the coupled bridge matrix. [Impedance matrices](bench-secondary-layout-impedance.json)

| Loop | Routed estimate at 10 MHz | Earlier model or design target |
| --- | ---: | --- |
| TVS copper | 4.33 nH | 2.5 nH maximum including the TVS package |
| Commutation copper | 28.78 nH | 7.75 nH in the previous bench extraction before the installed shunt |
| Bootstrap copper | 2.86 nH | 0.35 nH nominal assumed at the pins |
| High-side gate loop | 15.54 nH | About 22 nH in the existing bench extraction |
| Low-side gate loop | 14.44 nH | About 21 nH in the existing bench extraction |
| High-side snubber copper | 17.72 nH | 0.8 nH nominal assumed |
| Low-side snubber copper | 10.69 nH | 0.8 nH nominal assumed |

Changing the mesh from three to seven filaments across the copper widths moved the clamp result from 4.43 to 4.33 nH. The 26.55 mm connection from the supply side of the shunt to the rail ceramic contributed a 17.78 nH self term. This placement connects the TVS through two roughly 5.5 mm traces. Moving the TVS alone leaves a distributed commutation return and both snubber branches to resolve.

## Replay with the routed geometry

The ngspice replay replaces the original bridge impedances with the routed matrix, keeps the selected 5 mΩ shunt and 6.8 nF filter, and gives the TVS three assumed package contributions from 0.05 to 2 nH. It uses the reduced-order driver and MOSFET models. The external PWM request and EN stay high through the fault observation window. [Case data](bench-secondary-layout-replay.json)

- All eight short cases fell below 1 A while the external request was still asserted. All eight exceeded the 54 V design target. Worst VDS was 60.4 V. The hottest higher-ESL case reached 18.7 V across HB–HS, above the driver's 16 V recommended limit. [TI MOSFET rating](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf) · [TI driver ratings](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)
- All eight normal two-pulse tests drove both commands. The high-side gate rose to about 0.83 V during precharge. The low-side switching cases also exceeded the 54 V VDS design target.
- Shortening the TVS branch, the commutation loop, or the snubbers individually in the model failed to close both fault polarities. An assumed 2.5 nH high-side TVS plus shorter paths brought the failed-low-side case to 49.0 V. The failed-high-side case still reached 60.2 V. These sensitivity controls are modeled variations of the extracted data.

Fabrication stays on hold. The follow-on compact study clusters the DC-link ceramic, shunt and switches and compares the extracted copper and vendor-model replay with this TO-220 reference. [Compact secondary power cell](BENCH-SECONDARY-COMPACT.md)

## Reproduce

From the battery-port directory with FastHenry and ngspice on PATH:

```sh
python secondary_layout_extract.py --mesh 7 --output bench-secondary-layout-impedance.json
python secondary_layout_replay.py --output bench-secondary-layout-replay.json
```

The replay writes the cases and returns a failure for the open electrical criteria.
