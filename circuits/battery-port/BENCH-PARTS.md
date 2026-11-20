# Battery port bench component selection

The fixture operates from prebiased 12 V and 24 V rails at 50 kHz. These selections apply to the two bench bridges. The household converter has a different voltage and power envelope.

| Reference | Selected part or assembly | Design basis |
| --- | --- | --- |
| Q1–Q8 | TI CSD18534KCS, TO-220 | 60 V rating, gate/drain/source on pins 1/2/3, drain on tab. The model uses the 9.5 mΩ maximum at 10 V and 25 °C. Check switching overshoot on both rails and losses at actual gate voltage and temperature. [TI datasheet](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf) |
| L1 | Coilcraft XAL1010-103MED | 10 µH ±20%, 14.8 mΩ maximum DCR and 17.5 A typical saturation current under the manufacturer's test conditions. Transformer leakage adds in series. Measure the assembled effective inductance and verify the land pattern against the drawing. [Coilcraft data](https://www.coilcraft.com/en-us/products/power/high-voltage-inductors/xal/xal1010/xal1010-103/) |
| T1 | Custom ETD29, two TDK B66358G0000X187 ungapped N87 halves and B66359W1013T001 former | 22 primary turns and 44 secondary turns. The custom footprint uses the two end pads in the seven-pin row for the primary and the two end pads in the six-pin row for the secondary. Pads 1 and 3 mark dot ends. The remaining nine plated holes are unconnected. Verify physical fit and winding polarity before the PCB release. [TDK core and former drawings](https://www.tdk-electronics.tdk.com/inf/80/db/fer/etd_29_16_10.pdf) · [Editable footprint](Helios_Bench.pretty/Transformer_TDK_B66359W1013T001_Helios.kicad_mod) |
| C24 | Panasonic EEUFR1E471 | 470 µF / 25 V, 10 mm diameter, 5 mm lead pitch. Ripple rating is 1.29 Arms at 100 kHz. Check ripple at the actual spectrum and enclosure temperature. Positive is pad 1. [Manufacturer specifications](https://industrial.panasonic.com/ww/products/pt/aluminum-cap-lead/models/EEUFR1E471) |
| C25 | Panasonic EEUFC1H222 | 2,200 µF / 50 V, 18 mm diameter, 7.5 mm lead pitch and 35.5 mm body height. Ripple rating is 3.10 Arms at 100 kHz. Positive is pad 1. [Manufacturer specifications](https://industrial.panasonic.com/ww/products/pt/aluminum-cap-lead/models/EEUFC1H222) |
| C1, C3 | TDK C2012C0G1H103J060AA | 10 nF, 50 V, ±5%, C0G in 0805. Use for the bench RC filters. [TDK specifications](https://product.tdk.com/en/search/capacitor/ceramic/mlcc/info?part_no=C2012C0G1H103J060AA) |
| Unrated 100 nF positions on the parent PCB, including C6, C106, C206 and C306 | TDK CGA4J2X8R1H104K125AA | 100 nF, 50 V, ±10%, X8R in 0805. TDK lists the part in production. Its typical DC bias curve stays near 100 nF at 10 V. Confirm the capacitor stays within the tested 60–150 nF effective range over bias, temperature and lot variation. [TDK specifications](https://product.tdk.com/en/search/capacitor/ceramic/mlcc/info?part_no=CGA4J2X8R1H104K125AA) · [TDK characterization](https://product.tdk.com/en/system/files?file=dam%2Fdoc%2Fproduct%2Fcapacitor%2Fceramic%2Fmlcc%2Fcharasheet%2Fcga4j2x8r1h104k125aa.pdf) |
| C4, C104, C204, C304 | TDK C3216X7R1H225K160AB | 2.2 µF, 50 V, ±10%, X7R in 1206. TDK's typical curve shows about 8% loss by 10 V. Use a separate low-capacitance corner for the gate supply model. [TDK DC-bias characterization](https://product.tdk.com/en/system/files/dam/doc/product/capacitor/ceramic/mlcc/charasheet/c3216x7r1h225k160ab.pdf) |
| J1, J2 | Samtec TSW-104-07-G-S or mating-compatible 1 × 4 header | Vertical 2.54 mm through-hole header for local sense and ADC signals. Pin 1 is marked on the board. [Manufacturer drawing and footprint](https://www.samtec.com/products/tsw-104-07-g-s) |
| J3, J4 | Phoenix Contact MKDS 1,5/2-5,08, 1715721 | 5.08 mm horizontal through-hole terminal. Pin 1 is positive and pin 2 the local return on both ports. [Manufacturer drawing and drilling plan](https://www.phoenixcontact.com/en-pc/products/pcb-terminal-block-mkds-15-2-508-1715721) |
| R30 | Bourns CSS4J-4026R-L500F | 0.5 mΩ ±1%, four separate PCB lands. Force pads 1 and 4 carry the rail current. Sense pads 2 and 3 pair with 1 and 4, respectively. Route sense separately to the INA240. [Bourns land pattern](https://www.bourns.com/docs/Product-Datasheets/css4j-4026.pdf) |
| U9, U109 | TI TPS7A1601DGN | DGN0008C land pattern, with exposed pad 9 on the local return. The footprint uses the mask and paste geometry for the 0.125 mm stencil example. Review thermal copper and optional vias with the final stack. [TI datasheet and land pattern](https://www.ti.com/lit/ds/symlink/tps7a16.pdf) |
| U5 | TI SN74LVC1G74DCU | DCU0008A land pattern. Its 0.30 mm pads on 0.50 mm pitch leave 0.20 mm nominal copper clearance between adjacent pins. [TI datasheet and land pattern](https://www.ti.com/lit/ds/symlink/sn74lvc1g74.pdf) |

## Gate drive and magnetics

The KiCad schematic and PCB both carry the manufacturer, MPN and voltage rating for the 29 audited capacitor positions. KiCad's BOM export reports two 10 nF, 23 100 nF and four 2.2 µF capacitors with those fields. The bench switch BOM still uses the 60 V device while the routed 100 V stress study is open.

At 24 nC maximum specified gate charge, four gates at 50 kHz draw about 4.8 mA per bridge from the drive supply before driver, logic and isolator current. One gate charge removes 0.24 V from an effective 100 nF bootstrap capacitor. Add the driver consumption, leakage, capacitor DC-bias derating and recharge-path drop, then measure the minimum high-side supply during the first pulse and steady operation. The nominal drive rail is 9.93 V. [TI gate-charge conditions](https://www.ti.com/lit/ds/symlink/csd18534kcs.pdf)

### 100 V TO-220 candidate

The CSD19535KCS uses the same TO-220 gate, drain and source lead order as the parent device. Its 100 V rating comes with 78 nC typical gate charge at the data-sheet test point, so it needs its own gate-drive and bootstrap checks. An unencrypted TI SPICE comparison at 9.3 V bias exercised both converter directions and 60, 100 and 150 nF effective bootstrap capacitance. All twelve cases met the startup fixture's limits. The nominal solver stalled in the 100 V device's 60 nF charge case, and the alternate profile completed it. [TI device and model](https://www.ti.com/product/CSD19535KCS) · [Comparison measurements](bench-mosfet-margin-results.json)

| Effective bootstrap capacitance | 60 V part minimum first high gate | 100 V part minimum first high gate |
| --- | ---: | ---: |
| 60 nF | 8.77 V | 8.20 V |
| 100 nF | 8.83 V | 8.47 V |
| 150 nF | 8.77 V | 8.55 V |

The measured simulated drain peaks were below 26 V in this startup fixture. The 100 V device remains a candidate for the parent until the routed switching and hot-fault measurements establish transient voltage, current and safe operating area. The isolated switching leg uses the separate 100 V CSD19531Q5A in SON. [Parent startup replay](bench_mosfet_margin.py) · [Routed SON leg results](BENCH-SECONDARY-PROTECTED.md)

The routed stress repeat uses the trace-only secondary-A extraction, the candidate local current-sense and input-mask circuit, and a continuous gate-driver approximation. It compares both TI TO-220 device models at 25 °C and 100 °C, with two maximum time steps and three solver profiles. Four of sixteen CSD19535KCS cells completed, all with the low-side device shorted. Across those cells the surviving device reached up to 34.29 V across drain and source, local peak current reached 74.34 A and the hot bootstrap minimum was 6.77 V. At the end of the modeled short window, the input mask was low and current was below 1 A while the raw PWM request stayed asserted. The high-side-short and forced-current switching cells remained inconclusive. The model uses fixture source impedance and omits filled-plane high-frequency effects and an independent DC disconnect. These results leave switch selection and safe operating area open. [Routed stress runner](bench_mosfet_fault.py) · [Measurements and solver failures](bench-mosfet-fault-results.json)

```sh
python bench_mosfet_margin.py --driver SLUM720.ZIP --baseline SLPM046B.ZIP \
  --candidate SLPM100A.ZIP --output bench-mosfet-margin-results.json
python extract_layout.py --bootstrap --mesh 11 --output trace-ports.json
python bench_mosfet_fault.py --board battery-port-bench.kicad_pcb \
  --extraction trace-ports.json --baseline SLPM046B.ZIP --candidate SLPM100A.ZIP \
  --output routed-stress-repeat.json
```

The recorded routed run uses the trace-only parent from the previously pushed audit revision. Re-extracting the parent after the BOM field update reproduced the same matrices. [Exact reference revision](https://github.com/ramamoo3/Helios/commit/32094e5)

### Transformer and winding limits

With a nominal core factor of 2,200 nH/turn², the primary magnetizing inductance target is 1.065 mH, or approximately 0.852–1.384 mH with the published core tolerance. At 12.6 V across the primary, 50 kHz, equal positive and negative volt-seconds and 76 mm² effective area, peak flux density is about 38 mT. Flux offset on startup or unequal pulse widths requires separate measurement. The winding targets at room temperature are at most 120 mΩ primary DCR and 320 mΩ secondary DCR. Choose conductor bundle, layer insulation and terminal mapping against the actual window, current and temperature rise. Measure turns ratio and polarity, open-secondary inductance, and primary leakage with the secondary shorted before fitting T1. The nominal transfer simulation assumes 1 µH leakage. [TDK core data](https://www.tdk-electronics.tdk.com/inf/80/db/fer/etd_29_16_10.pdf)

## Startup current

| Simulated condition | DC power into 24 V port | Peak primary current after settling | Peak during startup |
| --- | ---: | ---: | ---: |
| 12 V / 24 V, +0.16 shift | +17.20 W | 1.92 A | 3.07 A |
| 12 V / 24 V, −0.16 shift | −17.82 W | 1.92 A | 3.27 A |
| 11.4 V / 25.2 V, +0.12 shift | +18.64 W | 2.56 A | 4.26 A |
| 12.6 V / 22.8 V, −0.12 shift | −18.87 W | 2.57 A | 4.30 A |

Shift is a signed fraction of half a switching period. The nominal model uses 11 µH total transfer inductance and 214.8 mΩ primary-referred series resistance. The two mismatched-rail cases use 8 µH, 0.852 mH magnetizing inductance and an assumed 60 mΩ series resistance to examine a lower-damping case. The model applies an immediate phase command with 200 ns dead time and measures current with shutdown disabled to expose a potential trip.

Both mismatched-rail starts crossed the nominal 4.04 A trip threshold on the first cycle. Repeating those two starts at a fixed shift magnitude of 0.06 gave 2.58 A and 2.59 A respectively. This establishes two lower-current simulated starting points. The controlled-startup tests below extend these results through the transition to operating power.

At 12.6 V plus 25.2 V referred through the 1:2 transformer, 8 µH gives an illustrative 3.15 A/µs current slope. Each 100 ns between detection and current commutation could add about 0.32 A. Capture primary current, trip, enables, gate voltage and drain overshoot together to determine the physical shutdown margin. The model omits nonlinear core and semiconductor dynamics, body-diode recovery and layout inductance. [Regression deck](bench-parts-test.cir)

## Controlled startup

The portable C scheduler produces four timer compare windows per 20 µs switching period. A signed target of ±120 counts corresponds to ±1.20 µs phase shift. At that target, the first ten frames use 0.60 µs. Each subsequent frame adds 10 ns until frame 70 reaches 1.20 µs, 1.38 ms after the first frame starts. Requests below 60 counts start at their requested magnitude. The scheduler checks the run request and external hardware permission and requires a permitted low run request before a fresh start. Changing the target during a run inhibits output. [C implementation](bench-startup.h)

| Prebiased rails | Direction | Largest primary current across three initial conditions | Settled power into secondary rail |
| --- | --- | ---: | ---: |
| 11.4 V / 25.2 V | Discharge | 2.666 A | +18.65 W |
| 11.4 V / 25.2 V | Charge | 2.451 A | −19.23 W |
| 12.6 V / 22.8 V | Discharge | 2.452 A | +19.01 W |
| 12.6 V / 22.8 V | Charge | 2.659 A | −18.87 W |

The host fixture compiles the scheduler and supplies its compare values to the same switched power-stage equations as the fixed-phase tests. Each 2.4 ms run starts with zero transfer current and initial linear magnetizing current of −0.10, 0 or +0.10 A. Peak current covers the whole run. Power is averaged over the final 20 frames. The largest peak leaves 1.37 A to the nominal trip threshold in this model. The regression ceiling is 3.5 A. Initial current in a linear inductor does not model remanence or saturation. [Trace fixture](bench-startup-trace.c) · [Simulation tests](startup_test.py)

The intended timer resolution is 10 ns. Map PP, PN, SP and SN to the four timing signals at J5. Preserve the last edge of a delayed negative pulse when it crosses a timer rollover. The host test checks 200 ns minimum spacing between compare edges, including frame boundaries. The MCU implementation must cancel queued edges on stop, apply the independent hardware shutdown asynchronously, and restart at the first frame only after a fresh permitted run. Verify these behaviors at the driver and record the first-cycle primary current and gate-to-source waveforms before raising bench power.
