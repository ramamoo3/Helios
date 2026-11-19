# STM32G474 bench timer integration

The bench controller target is the NUCLEO-G474RE. It uses timer A for the primary bridge, timer B for the secondary bridge and FLT1 to disable all four PWM commands on loss of the existing hardware permit. The schematic exposes that permit on J5 pin 10. The comparator and hardware latch also continue to disable both bridge drivers directly. [Bench I/O schematic](battery-port-bench-io.kicad_sch) · [STM32G474 datasheet](https://www.st.com/resource/en/datasheet/stm32g474re.pdf) · [Nucleo connector assignments](https://www.st.com/resource/en/user_manual/um2505-stm32g4-nucleo64-boards-mb1367-stmicroelectronics.pdf)

| J5 pin | Purpose | Nucleo connection |
| --- | --- | --- |
| 1 | Primary positive diagonal | PA8, HRTIM CHA1, CN10.23 |
| 2 | Primary negative diagonal | PA9, HRTIM CHA2, CN10.21 |
| 3 | Secondary positive diagonal command | PA10, HRTIM CHB1, CN10.33 |
| 4 | Secondary negative diagonal command | PA11, HRTIM CHB2, CN10.14 |
| 5 | RUN output | PB10, CN10.25 |
| 6 | ARM output | PB5, CN10.29 |
| 7–8 | Current and voltage telemetry | Available for later ADC integration |
| 9 | Primary reference P0 | CN10.20 GND |
| 10 | PERMIT_P input | PA12, HRTIM FLT1, CN10.12 |

The firmware moved ARM from the earlier PB4 assignment to PB5. PB4 has a reset-time debug pull-up. The hold-to-run input is separate from J5. Use a momentary switch from the Nucleo 3.3 V rail to PA6 (CN10.13) and leave the internal pull-down enabled. LD2 is on while the firmware runs the timer. [STM32G474 datasheet, GPIO reset states](https://www.st.com/resource/en/datasheet/stm32g474re.pdf)

## Timer configuration

Use a 160 MHz HRTIM source, ×8 prescaler and 25,600 counts per 20 µs frame. Use the same period and phase for both counters, with shadow compares transferring together at the frame boundary. Assign positive rise/fall to CMP1/CMP2 and negative rise/fall to CMP3/CMP4. Let the compare events set and reset the active-high outputs. Use inactive output states at reset, idle and fault. Route active-low FLT1 from PA12 to both timers without blanking or filtering, and bias PA12 low if the cable is unplugged. The resulting FLT1 path can turn the timer pins off without waiting for a frame callback or interrupt service. [HRTIM programming and fault states, RM0440](https://www.st.com/resource/en/reference_manual/rm0440-stm32g4-series-advanced-armbased-32bit-mcus-stmicroelectronics.pdf)

The compare adapter converts the scheduler's 10 ns ticks to the timer counts and carries the delayed negative pulse's original falling edge into the next frame. Loading the next phase offset at rollover does not shift that edge. Restrict this bench adapter to absolute targets of 60–120 ticks so the early compare always sits at least 0.50 µs after rollover. The portable scheduler retains its smaller targets for other backends. Host checks cover rollover, both directions, 256-count minimum compare spacing and reset after fault. [Compare adapter](bench-hrtim.h) · [Host test](bench-startup-trace.c)

## Build and load

Run the build program with Python 3, Zig 0.13 and the pinned ST and Arm CMSIS include directories. It cross-compiles both directions, validates the Cortex-M4 reset address and writes the ELF and raw flash image into the ignored `firmware/out` directory.

```sh
python firmware/build.py --device-include /path/to/cmsis-device-g4/Include --core-include /path/to/CMSIS_5/CMSIS/Core/Include
```

Load one image with the Nucleo's ST-LINK over SWD. For a raw BIN, use flash address `0x08000000`. Hold-to-run begins only after a release, a new press, an ARM pulse with RUN low and a subsequent high permit. The firmware stops on release, failed permit or a missed compare preload deadline. A separate watchdog resets the MCU if the control loop stalls. [Firmware source](firmware/stm32g474.c) · [ST STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html)

## Emulate the compiled image

Run the register-model tests against the two ELF/BIN pairs from the build directory. The script executes the actual Thumb instructions starting at each binary's reset vector. It supplies simulated clocks, GPIO levels and HRTIM status events, then checks that firmware writes the expected compare and enable registers. It verifies startup inhibition, the ramp in both directions, lost permit, recovery with RUN held, a fresh re-arm, a missing preload event and a latched fault after permission returns.

```sh
python -m pip install unicorn==2.1.4 pyelftools==0.32
python firmware/emulate.py
```

The register model does not emulate PWM pin timing, the live HRTIM fault circuit, watchdog reset timing or interrupt latency. [Emulator test](firmware/emulate.py) · [Unicorn Engine](https://github.com/unicorn-engine/unicorn)

## First bench capture

1. Begin with timer outputs disabled and both RUN and ARM low. Observe a low permit. Keep RUN low for a deliberate ARM edge. Assert RUN and wait for PERMIT_P to go high. Stage the first frame, reset the output state low and enable outputs from a known frame boundary. The controller request stays distinct from physical RUN so the firmware can wait for permit without deadlocking the hardware latch.
2. Disconnect J5 from the power board for the logic-only check. With the bridge rails off, feed RUN from PB10 through a 1 kΩ series resistor and a switch to PA12 to emulate the latch's permit response. Start with the permit switch closed. Capture all four timer pins and check the 50 kHz period, both current directions and at least 200 ns between opposing commands through rollover. Open the permit switch during a pulse and confirm that all four pins stop. Close the switch again while holding the request and confirm the commands stay off. Release the hold-to-run switch and then make a fresh press to restart.
3. With the prebiased, current-limited bench fixture, record both rail voltages, primary current, trip signal, enables and actual gate-to-source voltage. Measure the first-cycle current, bias and gate dead time in both directions and measure fault-clearing time from the current threshold through gate turn-off. Record drain overshoot and verify the high-side bootstrap rail before increasing load.

The two images cross-compile and the reset vectors were checked. Flashing and the scope captures require a connected NUCLEO-G474RE and instruments.
