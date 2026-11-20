# VSS-referenced bench gate-driver interface

The reusable KiCad sheet connects the bridge control domain to one low-side MOSFET source reference. The 12 V ↔ 24 V bench converter needs four instances. The candidate sheet passed KiCad ERC with zero errors and warnings in a temporary parent that connected all 13 ports. All 87 component pins in its exported netlist matched the expected connections. The power-stage simulations still fail the stress and cutoff criteria below. [KiCad sheet](battery-port-leg-receiver.kicad_sch) · [Module footprint](Helios_Bench.pretty/Converter_Traco_TMR1_SIP6_Single.kicad_mod)

## Circuit

| Function | Candidate implementation |
| --- | --- |
| Fast mask | U1 is a dual SN74LVC2G08DCU. Each raw input includes the existing precharge decoder path. FAST_PERMIT independently gates HI and LI. Both input paths have pull-downs. TI specifies up to 4.7 ns gate propagation at 3.3 V. [TI AND gate](https://www.ti.com/lit/ds/symlink/sn74lvc2g08.pdf) |
| Reference translation | U2 is an ISO7741FDW. A/B/C forward masked HI, masked LI and ENABLE_REQ. D returns bias-good. EN1 is held high on bridge logic power. RX_GOOD drives EN2 and IND. HI, LI, EN and returned bias-good each have 10 kΩ pull-downs to their receiving reference. The F variant defaults low on lost input power. TI specifies up to 18.5 ns data propagation at 3.3 V and up to 31 ns from output enable low to a high output becoming high-impedance. [TI isolator](https://www.ti.com/lit/ds/symlink/iso7741.pdf) |
| VSS and driver bias | PS1 is a regulated 12 V, 83 mA Traco module. Use TMR 1-1212 on the 12 V rail and TMR 1-2412 on the 24 V rail. Feed each leg from the protected rail ahead of its shunt. Connect output return to the corresponding driver VSS and MOSFET source reference. The module specifies up to 50 pF input-to-output capacitance. Its insulation is functional within this low-voltage bench design. [Traco module datasheet](https://www.tracopower.com/products/tmr1.pdf) |
| Receiver bias and qualification | U3 is TPS7A2433DBV. U4 supervises VDD_DRV at 10.00 V nominal from 237 kΩ and 10 kΩ. U5 supervises RX_3V3. Their open-drain reset outputs share a 10 kΩ pull-up. The CT pins are open for a 12–28 ms specified reset-release interval. Supervisor assertion delay is separate from this interval and the fast overcurrent path. [TI LDO](https://www.ti.com/lit/ds/symlink/tps7a24.pdf) · [TI supervisors](https://www.ti.com/lit/ds/symlink/tps3808.pdf) |

Use each leg's returned BIAS_GOOD as an asynchronous input to the bridge permit and re-arm latch. Confirm all supplies are ready and qualify the driver's EN turn-on before issuing precharge. TI gives 18 µs as a typical EN turn-on time. The existing decoder acknowledgement observes the command chain. Verify coverage and sequencing at the actual driver and bootstrap before allowing normal PWM. Keep the existing hardware dead time and include isolator part-to-part skew in the timing review. [TI gate driver](https://www.ti.com/lit/ds/symlink/ucc27282.pdf) · [Existing precharge interface](BENCH-HRTIM.md)

## Simulation results

The ngspice application model uses the selected part timing limits, a 15 pF load and a passive output pull-down. An imposed ±7 V reference excursion tests logic levels and sequencing. It does not exercise the isolator's internal common-mode transient immunity. Bias-good and bias dropout are supplied as fixture inputs. The model omits regulator and supervisor startup dynamics, supply fault propagation before bias-good falls and hardware measurements.

| Check | Result |
| --- | --- |
| Command and fail-low behavior | The active driver input stayed between 0 and 3.28 V relative to VSS. It fell below 0.9 V 24.5 ns after the raw command fell. After the simulated supervisor output fell, HI passed 0.9 V in 226 ns and EN passed 0.7 V in 264 ns. Restored bias kept PWM off until a fresh ARM with RUN low. |
| 2.5 A switching | All eight nominal two-pulse cases retained permission and drove both requested pulses with VSS-referenced bias. |
| Failed-switch cutoff | Seven of eight nominal faults and four of eight secondary tolerance corners met the current criterion with EN held high. Five secondary failed-high cases still carried more than 1 A at the 500 ns observation point. Secondary A still missed that point at 125 ps and 500 ps maximum timesteps and with the bias reduced to 9.926 V. The external command remained high and both bridge permits dropped. |
| Device stress | The worst modeled VDS reached 60.21 V, above the 60 V MOSFET rating. Eight faults crossed the driver's −14 V absolute HS limit for short pulses, reaching −35.1 V relative to VSS. These are screening-model values using the earlier extracted board and approximated devices. [TI MOSFET limits](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf) · [TI driver limits](https://www.ti.com/lit/ds/symlink/ucc27282.pdf) |

The power runs replace the ideal masks in the shunt study, use 12 V nominal driver bias relative to VSS and include the supply module's 50 pF coupling estimate. The late-trip cases use the 6.8 nF filter tolerances and 12.3 V bias for sensitivity. Peak current, negative HS voltage and time below 1 A depend on the board return model, the synthetic short and the approximation of the gate-driver output and device breakdown. The result file records the passes and failures individually. [Simulation data](bench-leg-receiver-results.json)

## Reproduce

From the battery-port directory with ngspice installed:

```sh
python leg_receiver_test.py --output bench-leg-receiver-results.json
```

The runner writes the case data before it returns a failure for the unresolved bridge faults. The follow-on study models a shorter Kelvin source and HS return and adds a clamp and damping network. The new geometry needs board extraction, and the precharge gate excursion still needs verification. Include the bias module's input-voltage stress and driver supply behavior during rail transients before closing the integrated converter fault matrix. [Commutation clamp and return layout](BENCH-COMMUTATION-CLAMP.md)
