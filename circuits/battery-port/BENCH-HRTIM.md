# STM32G474 bench timer integration

The bench controller target is the NUCLEO-G474RE. It uses timer A for the primary bridge, timer B for the secondary bridge and FLT1 to disable all four PWM commands on loss of the existing hardware permit. The schematic exposes that permit on J5 pin 10. The comparator and hardware latch also continue to disable both bridge drivers directly. [Bench I/O schematic](battery-port-bench-io.kicad_sch) · [STM32G474 datasheet](https://www.st.com/resource/en/datasheet/stm32g474re.pdf) · [Nucleo connector assignments](https://www.st.com/resource/en/user_manual/um2505-stm32g4-nucleo64-boards-mb1367-stmicroelectronics.pdf)

| J5 pin | Purpose | Nucleo connection |
| --- | --- | --- |
| 1 | Primary positive diagonal | PA8, HRTIM CHA1, CN10.23 |
| 2 | Primary negative diagonal | PA9, HRTIM CHA2, CN10.21 |
| 3 | Secondary positive diagonal command | PA10, HRTIM CHB1, CN10.33 |
| 4 | Secondary negative diagonal command | PA11, HRTIM CHB2, CN10.14 |
| 5 | RUN output | PB10, CN10.25 |
| 6 | ARM output | PB4, CN10.27 |
| 7–8 | Current and voltage telemetry | Available for later ADC integration |
| 9 | Primary reference P0 | CN10.20 GND |
| 10 | PERMIT_P input | PA12, HRTIM FLT1, CN10.12 |

## Timer configuration

Use a 160 MHz HRTIM source, ×8 prescaler and 25,600 counts per 20 µs frame. Use the same period and phase for both counters, with shadow compares transferring together at the frame boundary. Assign positive rise/fall to CMP1/CMP2 and negative rise/fall to CMP3/CMP4. Let the compare events set and reset the active-high outputs. Use inactive output states at reset, idle and fault. Route active-low FLT1 from PA12 to both timers without blanking or filtering, and bias PA12 low if the cable is unplugged. The resulting FLT1 path can turn the timer pins off without waiting for a frame callback or interrupt service. [HRTIM programming and fault states, RM0440](https://www.st.com/resource/en/reference_manual/rm0440-stm32g4-series-advanced-armbased-32bit-mcus-stmicroelectronics.pdf)

The compare adapter converts the scheduler's 10 ns ticks to the timer counts and carries the delayed negative pulse's original falling edge into the next frame. Loading the next phase offset at rollover does not shift that edge. Restrict this bench adapter to absolute targets of 60–120 ticks so the early compare always sits at least 0.50 µs after rollover. The portable scheduler retains its smaller targets for other backends. Host checks cover rollover, both directions, 256-count minimum compare spacing and reset after fault. [Compare adapter](bench-hrtim.h) · [Host test](bench-startup-trace.c)

## First bench capture

1. Begin with timer outputs disabled and both RUN and ARM low. Observe a low permit. Keep RUN low for a deliberate ARM edge. Assert RUN and wait for PERMIT_P to go high. Stage the first frame, reset the output state low and enable outputs from a known frame boundary. The controller request stays distinct from physical RUN so the firmware can wait for permit without deadlocking the hardware latch.
2. With the bridge DC ports off, use a 3.3 V test signal for the disconnected FLT1 input and capture all four timer pins. Check the 50 kHz period, both phase directions and the minimum 200 ns compare spacing across rollover. Pull FLT1 low during an active pulse and confirm that all four pins stop, stay off after permission returns, and restart only after the operator releases the request and arms again. The board firmware must disable outputs, clear pending compare updates and reset the adapter on a fault or a missed preload deadline.
3. With the prebiased, current-limited bench fixture, record both rail voltages, primary current, trip signal, enables and actual gate-to-source voltage. Measure the first-cycle current, bias and gate dead time in both directions and measure fault-clearing time from the current threshold through gate turn-off. Record drain overshoot and verify the high-side bootstrap rail before increasing load.

The board-specific clock, GPIO, HRTIM initialization and preload interrupt still need to be built and flashed. The current evidence covers the native schematic and C compare calculations. Actual timer behavior and gate timing require hardware capture.
