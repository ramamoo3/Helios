# Battery port bench component selection

The fixture operates from prebiased 12 V and 24 V rails at 50 kHz. These selections apply to the two bench bridges. The household converter has a different voltage and power envelope.

| Reference | Selected part or assembly | Design basis |
| --- | --- | --- |
| Q1–Q8 | TI CSD18534KCS, TO-220 | 60 V rating, gate/drain/source on pins 1/2/3, drain on tab. The model uses the 9.5 mΩ maximum at 10 V and 25 °C. Check switching overshoot on both rails and losses at actual gate voltage and temperature. [TI datasheet](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf) |
| L1 | Coilcraft XAL1010-103MED | 10 µH ±20%, 14.8 mΩ maximum DCR and 17.5 A typical saturation current under the manufacturer's test conditions. Transformer leakage adds in series. Measure the assembled effective inductance and verify the land pattern against the drawing. [Coilcraft data](https://www.coilcraft.com/en-us/products/power/high-voltage-inductors/xal/xal1010/xal1010-103/) |
| T1 | Custom ETD29, two TDK B66358G0000X187 ungapped N87 halves and B66359W1013T001 former | 22 primary turns and 44 secondary turns. The dotted ends connect to schematic pins 1 and 3. These numbers identify winding terminals. The 13-pin former needs a separate pad assignment. [TDK core and former drawings](https://www.tdk-electronics.tdk.com/inf/80/db/fer/etd_29_16_10.pdf) |

## Gate drive and magnetics

At 24 nC maximum specified gate charge, four gates at 50 kHz draw about 4.8 mA per bridge from the drive supply before driver, logic and isolator current. One gate charge removes 0.24 V from an effective 100 nF bootstrap capacitor. Add the driver consumption, leakage, capacitor DC-bias derating and recharge-path drop, then measure the minimum high-side supply during the first pulse and steady operation. The nominal drive rail is 9.93 V. [TI gate-charge conditions](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf)

With a nominal core factor of 2,200 nH/turn², the primary magnetizing inductance target is 1.065 mH, or approximately 0.852–1.384 mH with the published core tolerance. At 12.6 V across the primary, 50 kHz, equal positive and negative volt-seconds and 76 mm² effective area, peak flux density is about 38 mT. Flux offset on startup or unequal pulse widths requires separate measurement. The winding targets at room temperature are at most 120 mΩ primary DCR and 320 mΩ secondary DCR. Choose conductor bundle, layer insulation and terminal mapping against the actual window, current and temperature rise. Measure turns ratio and polarity, open-secondary inductance, and primary leakage with the secondary shorted before fitting T1. The nominal transfer simulation assumes 1 µH leakage. [TDK core data](https://www.tdk-electronics.tdk.com/inf/80/db/fer/etd_29_16_10.pdf)

## Startup current

| Simulated condition | DC power into 24 V port | Peak primary current after settling | Peak during startup |
| --- | ---: | ---: | ---: |
| 12 V / 24 V, +0.16 shift | +17.20 W | 1.92 A | 3.07 A |
| 12 V / 24 V, −0.16 shift | −17.82 W | 1.92 A | 3.27 A |
| 11.4 V / 25.2 V, +0.12 shift | +18.64 W | 2.56 A | 4.26 A |
| 12.6 V / 22.8 V, −0.12 shift | −18.87 W | 2.57 A | 4.30 A |

Shift is a signed fraction of half a switching period. The nominal model uses 11 µH total transfer inductance and 214.8 mΩ primary-referred series resistance. The two mismatched-rail cases use 8 µH, 0.852 mH magnetizing inductance and an assumed 60 mΩ series resistance to examine a lower-damping case. The model applies an immediate phase command with 200 ns dead time and measures current with shutdown disabled to expose a potential trip.

Both mismatched-rail starts crossed the nominal 4.04 A trip threshold on the first cycle. Repeating those two starts at a fixed shift magnitude of 0.06 gave 2.58 A and 2.59 A respectively. This establishes two lower-current simulated starting points. A controller that ramps to operating power still needs validation across initial flux, rail mismatch and both energy directions.

At 12.6 V plus 25.2 V referred through the 1:2 transformer, 8 µH gives an illustrative 3.15 A/µs current slope. Each 100 ns between detection and current commutation could add about 0.32 A. Capture primary current, trip, enables, gate voltage and drain overshoot together to determine the physical shutdown margin. The model omits nonlinear core and semiconductor dynamics, body-diode recovery and layout inductance. [Regression deck](bench-parts-test.cir)
