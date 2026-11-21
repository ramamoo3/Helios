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

A second run used 2.00 µF downstream of each cutoff, the nominal total for the two local 1 µF ceramics per rail on the bench PCB. All ten cases reproduced their expected behavior at both timesteps. Across the four protected shorts, the largest calculated fault energy increased from 0.245 mJ with 0.70 µF to 0.625 mJ with 2.00 µF. From 20 µs after the fault, the maximum modeled source current was 1.87 mA, below the fixture's 20 mA limit. The capacitors are lumped and ideal in this model. Use installed capacitance, ESR, ESL, tolerance and actual routing for device and clamp qualification. [Board capacitor placement](BENCH-PCB.md#copper-already-routed) · [2.00 µF sensitivity results](bench-linked-cutoff-ceramic-results.json)

```sh
python bench_linked_cutoff_test.py --ngspice ngspice --output bench-linked-cutoff-results.json
python bench_linked_cutoff_test.py --ngspice ngspice --bridge-cap-nf 2000 --output ceramic-repeat.json
```

## Rail protection schematic

Open the [12 V ↔ 24 V protection project](battery-port-bench-protected.kicad_pro) and its [top-level schematic](battery-port-bench-protected.kicad_sch). One [protection sheet](battery-port-rail-protection.kicad_sch) serves each rail. C24 (470 µF) and C25 (2,200 µF) stay upstream with the bias supplies. C26–C29 stay on the bridge side, with two nominal 1 µF ceramics per rail. The shunts sit between the bulk capacitors and the split to the main and precharge paths. The existing filled-plane PCB is the layout baseline for this schematic revision. [Bench parts and rail capacitors](BENCH-PARTS.md) · [Baseline PCB](BENCH-PCB.md)

| Circuit | Schematic implementation |
| --- | --- |
| Main cutoff | A common-source pair of 100 V CSD19531Q5A MOSFETs interrupts current in either direction. An LTC7001IMSE drives the pair and an SMBJ28CA clamps the voltage across it. On the KiCad footprint, pad group 1 maps to physical source pins 1–3, group 2 to gate pin 4, and group 3 to drain pins 5–8 and the exposed pad. [MOSFET package drawing](https://www.ti.com/lit/ds/symlink/csd19531q5a.pdf) · [Static high-side driver](https://www.analog.com/media/en/technical-documentation/data-sheets/ltc7001.pdf) |
| Signed current trip | Each 5 mΩ Kelvin shunt feeds an INA241A2 at 20 V/V. At nominal 3.3 V, the 1.05–2.25 V window around 1.65 V gives a ±6 A starting threshold. Either comparator can clear the latch through the hardware logic. Loss of bias, bulk voltage, peer health or the cutoff command also clears it. Closing the main path requires a fresh ARM edge with RUN low, DC precharge released and the local rail voltages matched. The current threshold and maximum clearing time need qualification with gain and offset errors, switching transients and hot-device limits. [Current amplifier](https://www.ti.com/lit/ds/symlink/ina241a.pdf) · [Comparators](https://www.ti.com/lit/ds/symlink/tlv3202.pdf) · [Latch](https://www.ti.com/lit/ds/symlink/sn74lvc1g74.pdf) |
| DC precharge | Two separately driven bidirectional switches and two 100 Ω, 3 W candidate resistors sit in series. A fresh request clocks the acceptance latch. The accepted request drives the first switch and starts the non-retriggerable CD74HC221 pulse for the second switch. Loss of health or raising RUN clears the latch and timer. At 25.2 V, an ideal short sees 126 mA with nominal resistors. With 2 µF and zero load, the nominal time constant is 0.4 ms. The 33.2 kΩ and 220 nF timer network has an RC product of 7.3 ms. Qualify the actual pulse width at 3.3 V and confirm the loaded bridge reaches the cutoff window. [Timer](https://www.ti.com/lit/ds/symlink/cd74hc221.pdf) · [Resistor family](https://www.vishay.com/doc?28729=) |
| Rail voltage | A TLV3201 detects bulk voltage above about 9.45 V at nominal 3.3 V. A TLV3202 and 0.1% dividers require nominal bridge voltage between 93.1% and 107.2% of bulk before a cutoff can arm. The same window qualifies that rail's readiness during RUN. The corner calculation uses ±10 mV effective comparator error, ±5% logic supply, and the KiCad resistor values and tolerances. At 10.8–12.6 V primary and 21.6–25.2 V secondary, equal rails pass and a ±20% mismatch fails. The calculated bulk threshold spans 8.57–10.33 V. The unloaded 210 Ω and 2.2 µF model reaches the worst screened lower threshold in 1.64 ms. [Comparator limits](https://www.ti.com/lit/ds/symlink/tlv3202.pdf) |

### Isolated rail shutdown and PWM permission

The [rail interlock sheet](battery-port-rail-interlocks.kicad_sch) uses default-low ISO7720F and ISO7721F channels with separately powered sides. Each rail sends health during idle and requires its cutoff and voltage match to keep that health asserted during RUN. A local current trip clears its cutoff latch and withdraws peer permission. Loss of secondary readiness at the primary also clears the cutoffs during RUN. The primary's final permit goes to both primary driver enables, the gate decoder, the existing secondary enable chain and the controller's hardware fault input at J5.10. The secondary also masks both of its driver enables and its gate decoder with local readiness. [Isolator pinout and fallback behavior](https://www.ti.com/lit/ds/symlink/iso7721.pdf)

| J701 pin | Controller signal |
| --- | --- |
| 1 | Primary logic return P0 |
| 2 | CUT_ENABLE. Low clears the primary latch and withdraws secondary permission. |
| 3 | DC_PRE_REQ. A fresh rising edge requests bulk-to-bridge precharge while RUN is low. The secondary receives only the primary's timed request. |
| 4 | DC_READY. High reports both rail latches armed and both bridge voltages within their local windows. |

On a fresh start, the protected firmware keeps RUN low, asserts CUT_ENABLE, requests DC precharge, then releases the request before pulsing ARM. The primary cutoff latch starts the isolated secondary arm sequence. The controller requires stable DC_READY before raising RUN. J5.11 and J5.12–13 retain the bootstrap request and acknowledgements after RUN and final permit. A failed start or fault returns the controller to RUN low and CUT_ENABLE low before a fresh request. The compiled charge and discharge images passed the register-model tests. [J701 wiring and controller timing](BENCH-HRTIM.md#protected-bench-rail-sequence)

### Verification and remaining qualification

KiCad ERC reported zero errors and warnings. The exported netlist check covers the isolation direction and supplies, final permit fan-out, switched capacitors, sense polarity, latch clear pins, separate precharge controls and grouped MOSFET footprint. The discrete model reads those nets from KiCad and exercised early ARM and RUN, positive and negative current trips on both rails, loss of bias or logic power, loss and restoration of isolated peer or readiness signals, held precharge through recovery and fresh re-arm. The checks rejected eight deliberate wiring changes and two logic-gate substitutions, including bypasses of the secondary PWM gate and readiness latch. Comparator results are test inputs and the model uses abstract propagation steps.

```sh
kicad-cli sch erc --severity-all --exit-code-violations battery-port-bench-protected.kicad_sch
kicad-cli sch export netlist --format kicadxml --output rail-protection.xml battery-port-bench-protected.kicad_sch
python verify_bench_rail_protection.py rail-protection.xml
```

### Loaded precharge and analog fault screen

Ngspice 47 ran 146 cases at two maximum timesteps. The model uses actual resistor, divider and capacitor values where specified. Timer pulse width, off-state loading, pump current, bias detection delay, sink retention and source limits are sensitivity inputs. Six additional DC cases used TI's CSD19531Q5A PSpice macro. [Runner](bench_rail_analog_test.py) · [Measurements and input hashes](bench-rail-analog-results.json) · [TI MOSFET model](https://www.ti.com/product/CSD19531Q5A#design-development)

| Case | Result |
| --- | --- |
| Loaded precharge with warm drivers | At 10.8 V, a 100 µA added bridge load prevented ARM under the original 10 ms request and 2 ms delay in all six primary capacitance and timer combinations. The new 3 ms request and 50 µs delay passed both rails at 0–1 mA added load with 1–2.2 µF, 210 Ω total and 3.2–6.8 ms modeled guard windows. The smallest primary margin at 1 mA was 1.06 mV at the comparator input after the divider corners and 10 mV sensing allowance. The 2 mA primary cases, a 1 ms guard and the shorted-bus controls missed the voltage window. At a 25.2 V short and 190 Ω total, each resistor saw 1.67 W peak and 4.94 mJ for the 3 ms command. The actual timer width at 3.3 V, installed leakage, driver delays and resistor thermal margins still need qualification. [CD74HC221 pulse characteristics](https://www.ti.com/lit/ds/symlink/cd74hc221.pdf) · [PR03 resistor family](https://www.vishay.com/doc?28729=) |
| Cold cutoff bias | With the 1 µF floating capacitor and 15–30 µA pump-current inputs, the modeled BST–TS was 0.63–1.26 V at the 42 ms startup request. The modeled 3.1 V UVLO threshold was reached around 103–207 ms. With bridge voltage already matched, the latch and voltage checks reported DC_READY even though the driver still blocked its gate. The model uses a constant pump-current screen, and ADI specifies the 15 µA minimum under a particular TS and BST bias condition. The schematic needs cutoff-driver readiness or a conduction check that independently verifies the commanded power path. [LTC7001 startup and UVLO](https://www.analog.com/media/en/technical-documentation/data-sheets/ltc7001.pdf) |
| Warm brownout | PWM permission dropped 0.5–40 µs after the start of the modeled dips. Both gates stayed off after bias recovered with no fresh ARM when the active sink remained available. The control that removed the sink during a fast drive-supply collapse left about 4.1 V on the affected gates 500 µs later. A static vendor-model check at 4 V gate bias passed about 23.94 V through the cutoff pair into 10 Ω at either 25 or 100 °C. The sink-loss case is a sensitivity condition and needs a driver-model or hardware test before turn-off can be signed off. [LTC7001 pull-down limits](https://www.analog.com/media/en/technical-documentation/data-sheets/ltc7001.pdf) · [TPS3808 timing](https://www.ti.com/lit/ds/symlink/tps3808.pdf) |

The nominal C24 and C25 reservoirs store 37 mJ at 12.6 V and 699 mJ at 25.2 V. A failed-short cutoff connects that stored energy to the fault independently of the source limit. In the modeled 24 V rail with a 10 A source limit, the initial fault current reached 389 A. Taking the source current to zero at 100 µs still put 0.237 J into the modeled 20 mΩ fault resistor. With the same reference fuse resistance moved after C25, its modeled path saw 9.78 A²s over 2 ms. Littelfuse quotes 37 A²s typical pre-arcing I²t for the 5 A reference fuse. No simulated pulse establishes a guaranteed fuse opening time. The placement comparison uses cold fuse resistance and leaves the fuse intact throughout the waveform. [Littelfuse 297 series](https://www.littelfuse.com/assetdocs/littelfuse-datasheet-297-mini32v?assetguid=42c9dd21-a88e-4328-8e67-2f832444faf1)

The 3 A and 5.5 A current-limited cases kept feeding a failed cutoff. At 5.5 A, the 5 A reference fuse datasheet gives a 100-hour minimum opening time under its test conditions. Its opening range is 0.15–5 s at 10 A and 30–100 ms at 30 A. A foldback model that reached 3 A after 100 µs also kept feeding the fault. Establish the actual source's fault current and foldback or latch-off curve, then coordinate a separate branch interrupter with the capacitor location, fuse holder, connector, PCB copper and component energy limits. Fabrication remains on hold for cutoff feedback, brownout turn-off, fuse coordination and verification on the revised layout. [Littelfuse opening times and derating](https://www.littelfuse.com/assetdocs/littelfuse-datasheet-297-mini32v?assetguid=42c9dd21-a88e-4328-8e67-2f832444faf1)

```sh
python bench_rail_analog_test.py --ngspice ngspice --output bench-rail-analog-results.json
```

Add `--mosfet-model /path/to/CSD19531Q5A.lib` to include the optional vendor checks from TI's SLPM077C archive. [TI model download](https://www.ti.com/product/CSD19531Q5A#design-development)

### Gate feedback and passive turn-off

The [gate-feedback KiCad project](battery-port-bench-gate-feedback.kicad_pro) is the next 12 V ↔ 24 V bench schematic. Both rails use the same [gate-feedback sheet](battery-port-rail-gate-feedback.kicad_sch). The earlier LTC7001 project remains the source for the preceding cold-start and brownout report.

| Change | Implementation and result |
| --- | --- |
| Separate driver bias | Each main cutoff, precharge and guard pair has a UCC5350SBD split-output driver and an R2M-2412S isolated 12 V supply. The supply return connects to that pair's common MOSFET source. The six module input fuses sit upstream of the power cutoff and protect their bias feeds. Check converter inrush, input-fuse coordination, output derating, ripple and heat with the bench sources. [TI driver and UVLO behavior](https://www.ti.com/lit/ds/symlink/ucc5350.pdf) · [RECOM supply and package drawing](https://recom-power.com/pdf/Econoline/R2M.pdf) · [Module fuse family](https://www.littelfuse.com/assetdocs/fuse-452-and-454-datasheet?assetguid=8c87aa93-80a7-4ea8-8749-a19ba03901c2) |
| Main cutoff feedback | The TLV3202 compares each actual gate terminal with a divided common-source voltage plus an offset. The two comparisons, the cutoff latch and the bus-voltage window all qualify local readiness. Losing either gate indication during RUN withdraws peer health and latches both cutoffs off in the netlist model. With 0.1% dividers, ±5% logic supply and ±10 mV effective comparator error, the calculated threshold spans 6.71–8.86 V over the screened common-source range of −4 to 60 V. A matched external bridge voltage and a missing gate now keep DC_READY low in the model. An open MOSFET channel still needs a continuity check if a separate source can hold up the bridge rail. [Comparator input characteristics](https://www.ti.com/lit/ds/symlink/tlv3202.pdf) |
| Passive turn-off | A 2.2 kΩ, 1% resistor sits directly across every gate and source, including the precharge and guard switches. The screen used 4.8–6.0 nF per gate and 2.222 kΩ. With the pull-up disabled, the slowest gate fell below 1.8 V in 24.2 µs with the active sink removed. The independent resistor path still needs verification against nonlinear gate charge, Miller injection, bias supply collapse and the extracted board. A driver output that fails high calls for a separate interrupting path. [CSD19531Q5A gate charge and threshold](https://www.ti.com/lit/ds/symlink/csd19531q5a.pdf) |

KiCad reported zero errors or warnings. The exported electrical checks rejected five altered connections and a logic substitution that bypassed gate feedback. The logic model exercised startup and RUN with each of the four main gate indications missing individually. Ngspice repeated 42 gate sensing, discharge and backup-placement cases at two maximum steps. [Netlist verifier](verify_bench_rail_protection.py) · [Simulation runner](bench_gate_feedback_test.py) · [Results and input hashes](bench-gate-feedback-results.json)

### Independent interrupter placement

The 25.2 V fixture retained C25, a 3 A source limit and a permanently shorted main cutoff. An independently commanded switch opened on each side of the capacitor in separate cases. Both placements stopped sustained fault current. The post-capacitor location can cut capacitor discharge when it opens early, at the cost of switching the live capacitor pulse. The table uses the assumed 33 V clamp knee, 0.23 Ω clamp slope and 0.2 µH feeder. The switch model leaves opening detection, arc behavior, device safe operating area and actual turn-off timing to the component selection.

| Time after fault | Fault energy with upstream opening | Fault energy with downstream opening | Current just before downstream opening | Downstream opening peak |
| --- | ---: | ---: | ---: | ---: |
| 20 µs | 230 mJ | 40 mJ | 325 A | 87.6 V |
| 200 µs | 233 mJ | 185 mJ | 103 A | 49.2 V |
| 2 ms | 234 mJ | 202 mJ | 3.0 A | 15.0 V |

Physical interrupter selection is pending. Size it using the source's prospective current, actual bulk capacitor impedance and the allowed fault energy. A source-side opening leaves the initial bulk-capacitor discharge on the board. The early downstream case requires its own verified margin for peak turn-off current and clamp stress. Placement, routing and fabrication remain pending.

```sh
kicad-cli sch erc --severity-all --exit-code-violations battery-port-bench-gate-feedback.kicad_sch
kicad-cli sch export netlist --format kicadxml --output gate-feedback.xml battery-port-bench-gate-feedback.kicad_sch
python verify_bench_rail_protection.py gate-feedback.xml --gate-feedback
python bench_gate_feedback_test.py --ngspice ngspice --output bench-gate-feedback-results.json
```
