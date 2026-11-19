# Bridge-local shutdown candidate

The routed 12 V ↔ 24 V bench bridge can draw rail current through a failed MOSFET and its complementary device while the primary winding-current sensor reads zero. The new SPICE circuit senses each leg's low-side source current, turns off the local bridge and sends its latched state to the opposite bridge. The winding-current circuit remains in the enable chain. [Previous local short screen](BENCH-LAYOUT-SIMULATION.md#bootstrap-extraction-and-independent-half-bridge-screen)

## Circuit connections for the schematic

Each bridge gets two shunt channels and one latch. One four-channel isolator carries ARM, RUN and primary READY forward and secondary READY in reverse. Both READY outputs are derived from local health and the local latch. The isolated peer input masks permission and clears the latch if it drops during RUN. With RUN low, the two domains can arm and establish both READY signals before RUN resumes.

| Function | Connection and component candidates |
| --- | --- |
| Local current | Place a Kelvin 5 mΩ shunt in each low-side source return. Route C26–C29 negative and the corresponding bulk return on the supply side of the shunt. Keep the gate driver's source reference at the MOSFET source. Remove parallel power returns around the shunt, including any shared inner-layer return. Use the shunt force and sense terminals separately. The WSK2512 is one footprint candidate. [Vishay shunt datasheet](https://www.vishay.com/docs/30108/wsk2512.pdf) |
| Current comparator | On a TLV3601DBV, pin 4 receives the shunt voltage through 100 Ω, with 1 kΩ to 3.3 V and the compensation capacitor to the negative Kelvin reference. Pin 3 sees 3.3 V divided by 6.98 kΩ and 1 kΩ with 100 pF in parallel with the lower resistor. Pin 1 supplies the active-high current-OK signal. Pins 2 and 5 are return and 3.3 V. The static threshold is about +25 A. A ±5 mV input offset alone shifts it by about ±1.1 A. [TI comparator pinout and timing](https://www.ti.com/lit/ds/symlink/tlv3601.pdf) |
| Latch and local permit | Form HEALTHY from both current-OK signals and supervised 3.3 V and driver bias. On an SN74LVC1G74, clock ARM, connect D to inverted RUN, tie preset inactive and drive active-low clear with `HEALTHY & (!RUN OR PEER_READY)`. READY is HEALTHY AND latch Q. Qualify the existing driver permit with local READY and isolated PEER_READY. Use LVC AND, OR and inverter gates with the existing driver enable pull-downs. The combinational HEALTHY term turns off the drivers independently of the latch. [TI flip-flop](https://www.ti.com/lit/ds/symlink/sn74lvc1g74.pdf) · [TI three-input AND gate](https://www.ti.com/lit/ds/symlink/sn74lvc1g11.pdf) |
| Peer shutdown | Use default-low isolation, for example ISO7741F, with local pull-downs and existing bias supervision. Both driver enables must fall when either local latch trips. Require a fresh ARM with RUN low after a local trip, peer loss while running or recovery from lost bias. [TI isolator channel directions and defaults](https://www.ti.com/product/ISO7741) |

The nominal input time constant is 100 ns from 100 Ω in parallel with 1 kΩ and a 1.1 nF capacitor. In the model it compensates the shunt's L/R ratio at 0.5 nH and 5 mΩ. The effective inductance is the four-terminal **transfer** inductance including the chosen pads and Kelvin traces. Obtain or extract that value before selecting the compensation capacitor. The package-series inductance quoted by a resistor supplier is insufficient to set this filter.

## Simulation results

The runner places the shunt in the existing extracted return and uses the prior fit for MOSFET charge and diode recovery. It starts with bias available and excludes the earlier test fixture's forced bootstrap clamp, which would otherwise inject DC through a failed switch. The 20 mΩ failed switch, shunt parasitics, switching driver and logic delays are model inputs. The matched case uses 4 ns comparator and 6 ns logic delay. The delay corner uses 7 ns and 12 ns. Peer isolation is an RC delay near the nominal propagation time.

| Test | Result |
| --- | --- |
| All four legs, high-side and low-side failed closed | All eight nominal cases shut off both permits with winding current fixed at zero. Current returned below 1 A while the switching command was still asserted. Rise-to-final-fall time across the 1 A threshold was approximately 142–227 ns. |
| Secondary A with Q6 failed, matched shunt | Peak local current fell from 130.91 A with the same shunt and local enable bypassed to 61.09 A under local shutdown. The Q5 energy proxy fell from 443 µJ to 74 µJ. Comparator threshold output to local permit took 6.1 ns and to counterpart permit 18.6 ns. |
| Normal two-pulse switching at 2.5 A imposed winding current | Nominal primary and secondary cases stayed enabled in both switch directions. A 2 nH transfer-inductance case nuisance-tripped with 1.1 nF in both directions. Retuning to 4.4 nF kept both normal cases enabled and retained short-current shutdown in the tested fault case. |
| Re-arm | Nine sampled states passed. Start-up, a held RUN, ARM while RUN was high, cycling RUN alone, and recovery after local bias or peer loss kept the driver disabled. Fresh ARM with RUN low restored permission under healthy inputs. |

The guarded cases still reach about 58 V at the MOSFET, close to its 60 V rating in the approximate breakdown model. Gate shutdown interrupts the complementary switch when it remains controllable. Stored DC-rail energy with both devices failed closed requires an independently coordinated disconnect. Allowable fault energy, comparator input transients, enable voltage relative to each driver's moving source and post-route recovery must be checked on the updated board. [MOSFET ratings](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf)

## Reproduce

From the battery-port directory with ngspice installed, run the following. The published JSON records the board, extraction and protection model hashes and includes the bypass and transfer-inductance controls.

```sh
python local_shutdown_test.py --output bench-local-shutdown-results.json
```

The model passed the nominal shutdown and interlock checks. The schematic wiring above is the candidate for integration after selecting the shunt and compensation. **Fabrication stays on hold** for layout integration, re-extraction, device stress verification and independent DC fault interruption. [SPICE circuit](local_shutdown.lib) · [Result data](bench-local-shutdown-results.json)
