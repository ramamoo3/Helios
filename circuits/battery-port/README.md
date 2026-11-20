# Helios battery port · Rev A

One base-unit channel connects one protected 16S LFP cabinet to the shared DC link. Each cabinet gets its own converter and sensing electronics. The low-voltage bench PCB is fully routed and passes KiCad’s geometry and schematic parity checks. A reproducible return-plane trial adds board mounting features and has its own KiCad and filled-copper extraction results. Routed switching qualification and assembly fit remain open. The independent SPICE netlists use ideal supplies for the single-channel operating points and a finite capacitor for the two-channel link. [Bench PCB routing and verification](BENCH-PCB.md)

## Secondary-leg experiments

The rear-bypass DFN board is the current candidate for isolated-leg replay. Earlier experiments retain their original filenames so the recorded input hashes and reproduction commands remain usable. [Rear-bypass candidate](BENCH-SECONDARY-PROTECTED.md#routed-rear-driver-bypass)

| Archived layout studies | Evidence |
| --- | --- |
| TO-220, compact SON and integrated-driver coupons | [TO-220](BENCH-SECONDARY-LAYOUT.md) · [Compact SON](BENCH-SECONDARY-COMPACT.md) · [Driver coupon](BENCH-SECONDARY-DRIVEN.md) |
| Protected and isolated-driver coupons | [Protected layout](BENCH-SECONDARY-PROTECTED.md) · [Isolated-driver layout](BENCH-SECONDARY-PROTECTED.md#routed-isolated-driver-coupon) |
| Clamp, pin bypass and two DFN clamp layouts | [Local clamp](BENCH-SECONDARY-PROTECTED.md#local-high-side-clamp-revision) · [Pin bypass](BENCH-SECONDARY-PROTECTED.md#high-side-pin-bypass-revision) · [DFN layouts](BENCH-SECONDARY-PROTECTED.md#routed-dfn-clamp-and-pin-bias-screen) |

Open the [12 V / 24 V bench project](battery-port-bench.kicad_pro) and its [top-level schematic](battery-port-bench.kicad_sch) to inspect the wired assembly. The bench power sheet uses a 1:2 transformer and the series current detector. The separate 700 V power study remains outside this assembly. [Bench component selection, updated model and startup limits](BENCH-PARTS.md)

| Circuit | Editable source | Preview | Simulation |
| --- | --- | --- | --- |
| Isolated bidirectional power path | [Power schematic](battery-port-power.kicad_sch) | [View power sheet](battery-port-power.svg) | [Converter model](dab.lib), [operating points](dab-test.cir), [low-pack stress case](dab-low-pack.cir) |
| Battery voltage and signed current measurement | [Sensing schematic](battery-port-sense.kicad_sch) | [View sensing sheet](battery-port-sense.svg) | [Sensing model](sense.lib), [calibration test](sense-test.cir) |
| One bench half-bridge driver | [Driver schematic](battery-port-driver.kicad_sch) | [View driver](battery-port-driver.svg) | [Gate-load test](driver-test.cir) |
| Bench winding-current detector | [Detector schematic](battery-port-detector.kicad_sch) | [View detector](battery-port-detector.svg) | [Protection model](protection.lib) |
| Reset-dominant arm latch and logic | [Latch schematic](battery-port-triplogic.kicad_sch) | [View latch](battery-port-triplogic.svg) | [Fault sequences](protection-test.cir) |
| Cross-barrier enable and bias feedback | [Isolation schematic](battery-port-trip-isolation.kicad_sch) | [View isolation](battery-port-trip-isolation.svg) | [Two-domain permission test](protection-test.cir) |
| Local drive, logic and supervision (two instances) | [Bias sheet](battery-port-bias.kicad_sch) | [View bias](battery-port-bias.svg) | [Staggered startup and rail faults](bench-bias-test.cir) |
| Complementary PWM and secondary enable | [PWM sheet](battery-port-pwm.kicad_sch) | [View PWM](battery-port-pwm.svg) | [Dead time and local veto](bench-pwm-test.cir) |
| Bootstrap precharge and gate decode | [Precharge sheet](battery-port-precharge.kicad_sch) | [View decoder](battery-port-precharge.svg) | [Full converter precharge and bias-loss cases](vendor_startup_test.py) |
| Scaled power stage and external connections | [Power](battery-port-bench-power.kicad_sch) · [Terminals](battery-port-bench-io.kicad_sch) | [Power](battery-port-bench-power.svg) · [Terminals](battery-port-bench-io.svg) | [Scaled power model](dab-test.cir) |

## Measured in simulation

Positive link power means the battery supplies the base. Negative link power means the base supplies the charger side of the port. The nominal full-scale model uses a 51.2 V pack, a **provisional** 700 V link, a 1:14 transformer, 1.5 µH effective primary-referred transfer inductance, 180 µH magnetizing inductance and 50 kHz switching. D is the signed phase shift as a fraction of half a switching period. The 40–60 V sweep is a converter study range. The battery manufacturer and BMS set actual operating limits.

| Battery / link | D | Mean power into DC link | Observation |
| --- | ---: | ---: | --- |
| 12 V / 24 V scaled model | +0.20 / −0.20 | +23.0 / −23.1 W | Reversal at low voltage with 1:2 turns ratio and 10 µH transfer inductance |
| 51.2 V / 700 V | +0.20 / −0.20 | +2.730 / −2.730 kW | Battery supplies 53.8 A average on discharge and receives 52.9 A average on charge |
| 40 V / 700 V | +0.20 | +2.120 kW | Transfer-inductor current 58.9 A RMS |
| 60 V / 700 V | +0.20 | +3.211 kW | Transfer-inductor current 71.0 A RMS |
| 40 V / 700 V | +0.285 | +2.695 kW | Pack supplies 68.2 A average. Transfer inductor carries 79.0 A RMS and reaches 110.7 A peak |
| 50 V / 700 V matched winding voltages | 0 | −11.7 W | Residual draw at the link with both bridges switching. Disabled-port standby requires a separate test |

The standby deck measures both rails. With both bridges still switching at zero shift, the model draws 11.66 W from the DC link, returns 7.88 W to the pack and dissipates 3.78 W net. Disabling both bridges removes that circulation at the matched voltages and at the two voltage corners. The modeled off-state draw of 4–6 mW comes from assumed switch conductance. Actual standby depends on devices, the BMS, bias and housekeeping supplies, controls and inverter no-load consumption. [Standby simulation](dab-standby-test.cir)

The open-loop tests average 20 switching cycles. The ideal single-phase-shift comparison is `P = Vpack × (Vlink / turns_ratio) × D × (1 − |D|) / (2 × fs × Ltransfer)`. The tests check sign and magnitude against this expression. Device capacitance, diodes, winding resistance and switching transitions are simplified. Device losses, saturation, insulation performance, cooling and delivered household AC power require further work. [Phase-shift control reference](https://imperix.com/doc/implementation/dab-converter-control)

## Two cabinets on the same link

The scaled two-port test connects a 12 V pack and an 11 V pack through separate converters to one 24 V link with 2,200 µF capacitance. A constant 1.45 A load remains connected. Before the inhibit, the two channels supplied 0.957 A and 0.659 A into the link. At 2 ms the second port stopped receiving gate commands. In the final 0.4 ms the first port still supplied 0.957 A and the second contributed less than 1 µA in magnitude. The bus averaged 24.13 V before the inhibit and 23.74 V in the final window.

This demonstrates independent PWM inhibit in the scaled model. The disabled bridge retains diode paths. Fault isolation needs a separate disconnect. The observed voltage sag quantifies the need for a bus-voltage controller that redistributes load within the surviving pack's current limit. [Two-port SPICE deck](two-port-test.cir)

## Sensing circuit

The parent bench board uses a Kelvin-connected 0.5 mΩ primary rail shunt, R30, for INA240A1PW telemetry. Positive battery discharge raises the ADC signal above 1.65 V. The predicted transfer is 10 mV/A. The model produced 0.900, 1.650 and 2.400 V at −75, 0 and +75 A respectively. A 75 A continuous current alone dissipates 2.81 W in the shunt. Select the part using its temperature and pulse ratings. The isolated-leg test boards have a separate four-terminal 5 mΩ shunt for fast local shutdown at the low-side source. The standalone leg also labels that part R30. [INA240 datasheet](https://www.ti.com/lit/ds/symlink/ina240.pdf) · [5 mΩ shunt study](BENCH-SHUNT-TRANSFER.md)

The voltage divider uses three 56 kΩ resistors over 8.2 kΩ with 10 nF at its output. It produced 1.862, 2.383 and 2.792 V at 40, 51.2 and 60 V. Its nominal pole is 2.04 kHz. The shunt-amplifier model checks ideal DC gain and the external output filter. Input faults, amplifier dynamics, PWM rejection, ADC acquisition time, resistor tolerances and supply sequencing need characterization. The ADC and 3.3 V supply are local to each cabinet port. The controller interface requires isolated power and data where it crosses that boundary.

## Gate-driver bench circuit

Use one UCC27282DRC per leg, two legs per bridge. Each side of the transformer needs its own local bias supply and logic reference. The DRC package provides the enable input. Local pull-downs hold enable and gates low when undriven. Supply PWM with explicit dead time. [TI datasheet, pin table and application circuit](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)

The 10 V bias, 4.7 Ω gate resistors and 100 nF nominal bootstrap capacitor are bench starting values. The vendor startup study also tested 60 nF and 120 nF at reduced bias. Select an exact capacitor MPN and use its minimum effective capacitance over DC bias, tolerance and temperature for the bootstrap refill and maximum on-time checks. The schematic shows the interface for local gate permission. The bench protection sheets provide the detector, latch and cross-barrier permission. The local bias and PWM sheets supply those interfaces in the bench hierarchy. [Bootstrap startup cases](BENCH-BOOTSTRAP.md)

The behavioral test checks high- and low-side gate-to-source voltage under valid commands, overlapping commands, overcurrent and loss of bias. It uses an imposed switch-node voltage, a 2 nF load and an illustrative 4 A fault threshold. Actual propagation, fault-current overshoot, bootstrap operation and physical gate turn-off time require bench measurement.

## Bench overcurrent shutdown

T2 senses the alternating primary winding current. On the bench variant, split the L1-to-T1 connection and insert T2 pins 4 and 3 in series. Wire its 1:100 secondary across the permanent 10 Ω burden, giving an ideal 100 mV/A about 1.65 V. U3, a TLV3202D, compares this signal with 1.246 V and 2.054 V. The **nominal ±4.04 A** threshold is a fixture design choice. Actual trip current depends on supply tolerance, CT droop, winding resistance, pulse shape, resistor tolerance, comparator offset and hysteresis. Check both polarities at 50 kHz. Sustained DC and same-leg shoot-through require independent rail current limiting and branch protection. [Coilcraft CT data and pin diagram](https://www.coilcraft.com/getmedia/12ba6199-a24d-486f-ba70-4b6bec000ed3/cst7030datasheet.pdf) · [TI TLV3202 comparator data and SOIC pin table](https://www.ti.com/lit/ds/symlink/tlv3202.pdf)

The comparator outputs feed an AND gate. Leaving the current window or losing either logic-domain power-good signal asserts the flip-flop's asynchronous clear. Arming samples the inverse of RUN on a rising ARM edge. A held ARM cannot restart the port after a trip. Two primary driver enables share PERMIT_P. Two secondary enables share PERMIT_S via the default-low ISO7710F. A second isolator returns SEC_OK to the primary latch. Each driver retains its own enable pull-down. [TI flip-flop](https://www.ti.com/lit/ds/symlink/sn74lvc1g74.pdf) · [TI quad AND](https://www.ti.com/lit/ds/symlink/sn74lvc08a.pdf) · [TI inverter](https://www.ti.com/lit/ds/symlink/sn74lvc1g04.pdf) · [TI isolator](https://www.ti.com/lit/ds/symlink/iso7710.pdf)

The test injects ±2.4 A ordinary excursions and separate +5.4 A and −5.4 A fault pulses. It checks both enable outputs, a held arm request across fault recovery, an arm attempt while running, deliberate re-arming and loss of secondary power-good. Both modeled comparator-input threshold crossings reached the remote enable midpoint in approximately 62 ns. This measures a behavioral delay assumption. The input current is injected, the digital rails stay powered and the model omits gate discharge, supply-collapse timing, core saturation and semiconductor fault current. For the physical fixture record current, comparator output, both enables and gate-to-source voltages together. Also test loss and restoration of each actual bias rail.

### Bench supplies, supervision and timing

Each bridge derives its rails from its own externally supplied DC port. P0 and S0 are separate. J3 is the 12 V primary port and J4 is the prebiased 24 V secondary port. This setup assumes that both rails are available before arming and that the receiving supply or an external load can absorb returned power. The 470 µF and 2,200 µF bulk capacitors each support a bridge with two dedicated 1 µF local ceramic bypass capacitors. Check bulk ripple, inrush and available voltage margin before assembly. [Bench part selections](BENCH-PARTS.md)

U9 uses a 73.2 kΩ / 10 kΩ divider and a 1.193 V nominal reference for a 9.926 V drive rail. U10 derives 3.3 V logic from that rail. U9 power-good pulls U11 manual reset low when the drive rail is low. U11 also monitors the logic rail, nominally at 3.07 V, and delays release by a nominal 20 ms with CT open. The 10 kΩ pull-up and 100 kΩ downstream pull-down give a nominal 3.00 V healthy signal. Budget dissipation separately at 24 V. For example, at an assumed 20 mA total regulator output, the first stage dissipates about 0.28 W on the secondary side. The selected MOSFETs add up to 4.8 mA of gate-charge demand per side at 50 kHz. Check regulator temperature and all voltage thresholds with component tolerances. [Drive regulator](https://www.ti.com/lit/ds/symlink/tps7a16.pdf) · [Logic regulator](https://www.ti.com/lit/ds/symlink/tps7a24.pdf) · [Supervisor](https://www.ti.com/lit/ds/symlink/tps3808.pdf)

The external timing controller uses J5 pins 1–4 for primary positive, primary negative, secondary positive and secondary negative commands. Pins 5–6 carry RUN and ARM. Pins 7–8 return current and voltage telemetry, pin 9 is P0 and pin 10 returns the hardware latch's PERMIT_P for the controller's active-low fault input. Pins 11–13 carry the precharge request and the two independent local acknowledgements. The controller supplies non-overlapping positive and negative commands for each bridge. Each pair drives opposite diagonals. The ISO7720F transfers the secondary commands and a secondary-side AND gate requires both isolated permission and local power-good. The upstream latch also receives the isolated return of secondary power-good. [Timer setup and bench capture](BENCH-HRTIM.md) · [Timing isolator](https://www.ti.com/lit/ds/symlink/iso7720.pdf)

The behavioral startup test delays the 24 V source, lowers primary bias while 3.3 V logic survives, then lowers secondary logic while gate bias survives. Both enables dropped for each fault and recovered only after a fresh arm sequence. The timing test applies 200 ns nominal command spacing and unequal channel-delay assumptions. The two modeled gaps were approximately 211 ns and 190 ns with zero modeled overlap. The supervisor release timing, isolator propagation and regulator headroom are functional approximations. These results do not establish gate-to-source dead time, brownout behavior outside specified supply ranges, regulator thermal margin, or operation of a discharged secondary bus.

## Reproducing the checks

Open the bench project with the adjacent Helios symbol library and standard KiCad footprints. Its electrical connection grid is 25 mil. J3 and J4 represent independent external sources and the BOOT flag on each driver represents the supply fed through its internal bootstrap diode. Use independently isolated bench ports and account for any ground connections through instruments or controller cables when evaluating the isolation barrier.

Run the following from this directory with Python 3, a C99 host compiler and an XSPICE-enabled build of ngspice. The Python check compares each sheet's pin connections with the expected nets, follows the parent wires and child ports, checks instance annotations and tests numerical results from ten simulation decks. It also compiles the portable C startup controller and drives the converter from its actual timer compare values across 12 startup conditions. The final command runs KiCad's native electrical-rules check on the same hierarchy.

```sh
python verify.py
python verify.py --ngspice /path/to/ngspice --cc /path/to/cc
python verify.py --schematics-only
kicad-cli sch erc --exit-code-violations -o bench-erc.rpt battery-port-bench.kicad_sch
```

The existing circuit decks and the 12-case startup sweep passed with ngspice 47 locally. The circuit CI job uses ngspice 42 from Ubuntu. The sweep includes both power directions at both mismatched rail pairs, with three initial magnetizing currents. The compiled host fixture checks STM32 compare mapping and re-arm. Eleven sheet pin maps passed, and the hierarchy check covered 14 sheet instances, 143 sheet pins and 149 components. The precharge logic passed all 128 input combinations. KiCad CLI 10.99 nightly reported zero ERC violations, and the exported netlist confirmed the two independent acknowledgement returns, the original permits and all eight gate decoder outputs. Separate CI jobs cover the compiled firmware and the parent and rear-bypass KiCad projects. TI model replays and board-level electrical qualification have separate procedures. [CI workflow](../../.github/workflows/verify.yml) · [Startup results](BENCH-PARTS.md#controlled-startup) · [Timer setup](BENCH-HRTIM.md)

## Integrated protection regression

The switched winding current now feeds the CT burden, comparator and trip latch in the same transient run. Compiled scheduler traces supply the four PWM inputs. A simulated 24 V to 42 V secondary rail step during either active half-cycle creates both overcurrent polarities. Separate cases drop primary or secondary power-good. Test both operating directions. After a fault clears, the simulated controller holds ARM and RUN high and both bridges stay off. Lowering RUN and making a fresh ARM edge restores transfer.

| Injected fault | Cases | Both enables below 1.65 V | Both switching command envelopes below 0.10 V | Largest winding peak |
| --- | ---: | ---: | ---: | ---: |
| Positive or negative winding overcurrent | 4 | 61–73 ns from the modeled threshold crossing | 113–124 ns | 4.35 A |
| Primary or secondary power-good loss | 4 | 22–34 ns from the power-good midpoint | 73 ns | — |

These are ngspice behavioral timings. The command envelope tracks switch conductance in the model. The model uses ideal rail sources, linear magnetics and assumed comparator, isolator and switch-transition delays. This sweep does not quantify actual device turn-off, common-mode transients, insulation, shoot-through, a shorted MOSFET or a disconnected CT. [Protected converter model](protected-dab.lib) · [Integrated test](startup_test.py)

## Vendor model half bridge

The 24 V fixture uses TI's UCC27282 driver, two CSD18534KCS MOSFETs, 4.7 Ω gate resistors, a 100 nF bootstrap capacitor, and a 10 Ω load to a stiff 12 V midpoint. With a 7 µs low-side precharge pulse, the high-side gate held at least 9.617 V over the measured on-time. Deasserting enable took 36.3–37.2 ns to bring the modeled high-side gate below 1.5 V. Peak drain-source voltage was approximately 24.85 V. During a held overlap of both logic commands the two gates stayed low. These results use ngspice 47 in PSpice compatibility mode with two Gear solver tolerances. They cover this 24 V fixture and its assumed source and load. [Driver model SLUM720](https://www.ti.com/lit/zip/slum720) · [MOSFET model SLPM046B](https://www.ti.com/lit/zip/slpm046b)

With the low-side precharge pulse omitted, the first high-side gate reached only 2.95 mV in this single-leg model. The full-converter model tests charging all four bootstrap capacitors with a simultaneous low-side pulse. The KiCad decoder and STM32 firmware now use a dedicated request, independent acknowledgement inputs and a blanking interval before PWM. Both rebuilt firmware images pass emulation for missing or stuck acknowledgement and permit loss during precharge. [Full-bridge startup results](BENCH-BOOTSTRAP.md) · [Single-leg test fixture](vendor-halfbridge.cir) · [Vendor model test](vendor_test.py)

Extract the two TI libraries and run the command below. The runner translates six PSpice parameter declarations in a temporary copy of the MOSFET file for ngspice.

```sh
python vendor_test.py --driver /path/to/driver.lib --mosfet /path/to/CSD18534KCS.lib
```

## Next circuit revision

The [PWM interlock model](trip.lib) and [fault-injection test](trip-test.cir) define the intended hardware behavior. At startup both bridges must stay inhibited. A valid arm edge with the run request low permits a subsequent start. Either current polarity crossing the test threshold or loss of gate bias revokes permission. Recovery needs a fresh arm edge once the fault clears, with the run request low.

The test injects a 110.7 A normal peak and ±135 A fault pulses, using 125 A as an illustrative trip threshold. It checks the permission signal independently of the power-stage model. Comparator delay, sensing bandwidth, isolation delay, driver turn-off time and current rise during shutdown must be established against component ratings before selecting an actual threshold. The bench protection sheets implement a separate scaled current window for the 12 V / 24 V fixture.

The 2.5 kW per-cabinet AC-equivalent target depends on the downstream inverter, the pack's allowable current and thermal performance. Design the full-power detector separately and establish its trip threshold from the selected magnetics and switches, with margin over the verified normal waveform. Model the link capacitor, pack impedance, startup/precharge, loss of a cabinet and load rejection before validating closed-loop operation. Pack and link fusing, isolation coordination, DC disconnects, and safe stored-energy discharge remain open design items. Fabrication and connection to a battery, house or mains require completion of those circuits and hardware qualification.

[Comparison circuits and reuse decisions](../REFERENCE-DESIGNS.md) · [System architecture](../../HELIOS-ARCHITECTURE.md)
