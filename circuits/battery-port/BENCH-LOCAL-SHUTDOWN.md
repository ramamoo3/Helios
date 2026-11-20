# Bridge-local shutdown candidate

The routed 12 V ↔ 24 V bench bridge can draw rail current through a failed MOSFET and its complementary device while the primary winding-current sensor reads zero. The SPICE candidate senses each leg's low-side source current, masks both PWM inputs on each local driver and sends its latched state to the opposite bridge. The winding-current circuit remains in the permit chain. [Previous local short screen](BENCH-LAYOUT-SIMULATION.md#bootstrap-extraction-and-independent-half-bridge-screen)

## Circuit connections for the schematic

Each bridge gets two shunt channels and one latch. One four-channel isolator carries ARM, RUN and primary READY forward and secondary READY in reverse. Both READY outputs are derived from local health and the local latch. The isolated peer input masks permission and clears the latch if it drops during RUN. With RUN low, the two domains can arm and establish both READY signals before RUN resumes.

| Function | Connection and component candidates |
| --- | --- |
| Local current | Place a Vishay WSK2512 5 mΩ Kelvin shunt in each low-side source return. Route C26–C29 negative and the corresponding bulk return on the supply side of the shunt. Keep the gate driver's source reference at the MOSFET source. Remove parallel power returns around the shunt, including any shared inner-layer return. Use the shunt force and sense terminals separately. [Footprint and transfer extraction](BENCH-SHUNT-TRANSFER.md) |
| Current comparator | On a TLV3601DBV, pin 4 receives the shunt voltage through 100 Ω, with 1 kΩ to 3.3 V and the compensation capacitor to the negative Kelvin reference. Pin 3 sees 3.3 V divided by 6.98 kΩ and 1 kΩ with 100 pF in parallel with the lower resistor. Pin 1 supplies the active-high current-OK signal. Pins 2 and 5 are return and 3.3 V. The static threshold is about +25 A. A ±5 mV input offset alone shifts it by about ±1.1 A. [TI comparator pinout and timing](https://www.ti.com/lit/ds/symlink/tlv3601.pdf) |
| Latch and local permit | Form HEALTHY from both current-OK signals and supervised 3.3 V and driver bias. On an SN74LVC1G74, clock ARM, connect D to inverted RUN, tie preset inactive and drive active-low clear with `HEALTHY & (!RUN OR PEER_READY)`. READY is HEALTHY AND latch Q. Qualify the existing driver permit with local READY and isolated PEER_READY. The combinational HEALTHY term removes permission independently of the latch. [TI flip-flop](https://www.ti.com/lit/ds/symlink/sn74lvc1g74.pdf) |
| Driver inputs | Mask HI and LI on all four drivers using hardware logic in each driver's VSS reference domain. Transfer the PWM and permit using receivers with defined low outputs on lost input or bias. Qualify receiver delay, power-off behavior, bias return and input thresholds on the routed board. Use EN as a secondary inhibit and account for its start-up delay before issuing precharge or PWM. [TI UCC27282 timing and limits](https://www.ti.com/lit/ds/symlink/ucc27282.pdf) |
| Peer shutdown | Use default-low isolation, for example ISO7741F, with local pull-downs and existing bias supervision. When either local latch trips, both bridges must drop HI/LI permission and request EN low. Require a fresh ARM with RUN low after a local trip, peer loss while running or recovery from lost bias. [TI isolator channel directions and defaults](https://www.ti.com/product/ISO7741) |

The filter depends on the four-terminal **transfer** inductance including the selected pads and Kelvin traces. The earlier assumed 0.5 nH and 1.1 nF filter were replaced in the candidate by the coupon-derived values. [Current filter screen](BENCH-SHUNT-TRANSFER.md)

## Earlier EN-only screening

The table records the original behavioral model. Its EN timing was idealized. TI specifies a typical EN disable delay of 1.5 µs. The sub-microsecond results below show how local sensing can reveal a winding-sensor-blind fault. Use the updated HI/LI study to assess the revised turn-off path. [TI UCC27282 datasheet, sections 6.5 and 6.6](https://www.ti.com/lit/ds/symlink/ucc27282.pdf) · [HI/LI results](BENCH-SHUNT-TRANSFER.md)

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

This command reproduces the historical model and the logic interlock checks. **Fabrication stays on hold** for layout integration, re-extraction, device stress verification and independent DC fault interruption. [SPICE circuit](local_shutdown.lib) · [Historical result data](bench-local-shutdown-results.json)

## Independent DC cutoff fixture

A separate current window and hardware latch control a modeled source-to-source MOSFET pair in the rail feed. The model includes its opposed body diodes and a bidirectional feeder clamp. Triggering the cutoff drops the gate permit even while the bridge request stays high. The two-terminal branch was exercised in both directions, with 12.6 V and 25.2 V source corners, slower sensing and loss of bias. The latch stayed open after the fault cleared with RUN held high. [Cutoff model](bench_disconnect.lib) · [Cases and limits](bench_disconnect_test.py)

At 24 V with the 2,200 µF bulk capacitor on the source side and 0.7 µF on the bridge side, the forward short sent about 0.24 mJ into the fault branch during the test window. Source and fault currents were each below 20 mA at 20 µs. Moving the bulk capacitor downstream raised modeled fault-branch energy to 337 mJ and left about 368 A in the short at the same sample, even after source current had stopped. Bypassing the disconnect kept feeding the fault with its enable low. These controls establish the need to isolate the bulk reservoir, limit the source and provide protection for a failed disconnect. [Simulation results](bench-disconnect-results.json)

Keep the precharge path outside normal operation and account for the energy in every capacitor that remains connected to the bridge after cutoff. The fixture precharges the rail before the test and models a single rail at a time. Both powered domains and the actual magnetics, cutoff switches, current sensor, gate drive, clamp, fuse, precharge and re-arm paths need integrated validation. [Bench layout and copper](BENCH-PCB.md)

```sh
python bench_disconnect_test.py --ngspice ngspice --output bench-disconnect-results.json
```

## Linked cutoff and PWM inhibit

The 12 V and 24 V model now has a separate source cutoff and current latch on each rail. Each latch receives a default-low health signal from the other rail. Either lost permit opens both supply paths and masks both bridges' PWM. The precharge path includes a series guard with a separate time window and a RUN-low condition. The bulk capacitors are on the source side of the cutoff switches. [Linked circuit runner](bench_linked_cutoff_test.py) · [PWM permit model](dab-control.inc)

Ten cases were repeated at 100 ns and 50 ns. In all four short cases, the model first transferred power in the requested direction. With both protections enabled, each source and fault current fell below 20 mA at the start of the 20–150 µs observation window and stayed below that limit. The cutoffs remained disabled after fault removal with RUN held high. Losing the secondary bias or the peer signal also inhibited both rails. With one precharge switch forced on, the guard still opened the precharge branch. [Result data and thresholds](bench-linked-cutoff-results.json)

The controls exposed different failure paths. Bypassing only the PWM inhibit let stored energy reach the fault at up to 5.76 A during the observation window, even after both sources were cut. Bypassing the secondary cutoff let that supply continue to feed the short. Forcing both precharge switches on left about 120 mA through the precharge resistor. These controls check why the three protective functions are needed. The fixture uses idealized power switches and a shared simulation reference. Validate real isolation, device fault energy, fuse coordination, pulse timing and precharge re-arm before connecting a populated board. [Result data](bench-linked-cutoff-results.json)

```sh
python bench_linked_cutoff_test.py --ngspice ngspice --output bench-linked-cutoff-results.json
```
