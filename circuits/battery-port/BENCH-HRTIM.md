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
| 11 | PRE_REQ output | PB1, CN10.24 |
| 12 | Primary precharge acknowledgement | PB2, CN10.22 |
| 13 | Secondary precharge acknowledgement | PB12, CN10.16 |

The firmware moved ARM from the earlier PB4 assignment to PB5. PB4 has a reset-time debug pull-up. The hold-to-run input is separate from J5. Use a momentary switch from the Nucleo 3.3 V rail to PA6 (CN10.13) and leave the internal pull-down enabled. LD2 indicates a processor fault. The RUN signal is on J5.5. [STM32G474 datasheet, GPIO reset states](https://www.st.com/resource/en/datasheet/stm32g474re.pdf)

## Timer configuration

Use a 160 MHz HRTIM source, ×8 prescaler and 25,600 counts per 20 µs frame. Use the same period and phase for both counters, with shadow compares transferring together at the frame boundary. Assign positive rise/fall to CMP1/CMP2 and negative rise/fall to CMP3/CMP4. Let the compare events set and reset the active-high outputs. Use inactive output states at reset, idle and fault. Route active-low FLT1 from PA12 to both timers without blanking or filtering, and bias PA12 low if the cable is unplugged. The resulting FLT1 path can turn the timer pins off without waiting for a frame callback or interrupt service. [HRTIM programming and fault states, RM0440](https://www.st.com/resource/en/reference_manual/rm0440-stm32g4-series-advanced-armbased-32bit-mcus-stmicroelectronics.pdf)

The compare adapter converts the scheduler's 10 ns ticks to the timer counts and carries the delayed negative pulse's original falling edge into the next frame. Loading the next phase offset at rollover does not shift that edge. Restrict this bench adapter to absolute targets of 60–120 ticks so the early compare always sits at least 0.50 µs after rollover. The portable scheduler retains its smaller targets for other backends. Host checks cover rollover, both directions, 256-count minimum compare spacing and reset after fault. [Compare adapter](bench-hrtim.h) · [Host test](bench-startup-trace.c)

## Build and load

Run the build program with Python 3 and Zig 0.17.1. Use the `Include` directory from ST CMSIS Device G4 v1.2.6 (`25664ddc3a7624ae9627ae8c4c672073dc5b2539`) and `CMSIS/Core/Include` from Arm CMSIS 5.9.0 (`2b7495b8535bdcb306dac29b9ded4cfb679d7e5c`). CI uses those revisions. The build cross-compiles both directions, validates the Cortex-M4 reset address and writes the ELF and raw flash image into the ignored `firmware/out` directory. Both images also passed with Zig 0.13.0. [Zig release](https://ziglang.org/download/) · [ST CMSIS Device G4](https://github.com/STMicroelectronics/cmsis-device-g4/tree/25664ddc3a7624ae9627ae8c4c672073dc5b2539) · [Arm CMSIS](https://github.com/ARM-software/CMSIS_5/tree/2b7495b8535bdcb306dac29b9ded4cfb679d7e5c)

```sh
python firmware/build.py --device-include /path/to/cmsis-device-g4/Include --core-include /path/to/CMSIS_5/CMSIS/Core/Include
```

Load one image with the Nucleo's ST-LINK over SWD. For a raw BIN, use flash address `0x08000000`. Hold-to-run begins only after a release, a new press, an ARM pulse with RUN low and a subsequent high permit. Both precharge readbacks must assert, stay asserted for 7 µs and clear before the 1 µs blanking interval. The firmware stops on release, a failed permit or acknowledgement, or a missed compare preload deadline. A separate watchdog resets the MCU if the control loop stalls. [Firmware source](firmware/stm32g474.c) · [ST STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html)

An unexpected exception or fatal clock setup failure enters the fault handler. It disables enabled HRTIM outputs, drops RUN, ARM and PRE_REQ when GPIOB is active, and lights LD2 while halted until reset. Reset uses explicit stores to initialize RAM. The freestanding image supplies the Arm `__aeabi_memclr4` routine used to clear compiler-generated structures. [Startup code](firmware/startup.S) · [Arm run-time ABI](https://github.com/ARM-software/abi-aa/blob/main/rtabi32/rtabi32.rst)

## Emulate the compiled image

Run the register-model tests against the two ELF/BIN pairs from the build directory. The script executes the Thumb instructions from each reset vector, with BSS initially set to nonzero bytes. It supplies simulated clocks, independent precharge acknowledgements and HRTIM status events. It checks precharge timing, missing and stuck acknowledgement, permit loss, the ramp, missed preload events, latched faults and output disable with LD2 indication on entry to the HardFault handler.

```sh
python -m pip install unicorn==2.1.4 pyelftools==0.32
python firmware/emulate.py
```

The register model does not emulate PWM pin timing, the live HRTIM fault circuit, watchdog reset timing or interrupt latency. [Emulator test](firmware/emulate.py) · [Unicorn Engine](https://github.com/unicorn-engine/unicorn)

## First bench capture

1. Begin with timer outputs disabled and RUN, ARM and PRE_REQ low. Keep RUN low through the ARM edge. PERMIT_P should rise after RUN rises. Verify each precharge acknowledgement asserts on request and deasserts before the first timer frame. [Startup sequence](BENCH-BOOTSTRAP.md)
2. Disconnect J5 from the power board for the later logic-only check. With the bridge rails off, feed RUN from PB10 through a 1 kΩ series resistor and a switch to PA12 to emulate the latch. Use separate 1 kΩ resistors between PB1 and each of PB2 and PB12 to emulate the two readbacks. Capture PRE_REQ, both readbacks and the four timer pins. Check the 50 kHz period and at least 200 ns between opposing commands through rollover. Open the permit switch during a pulse and confirm all four pins stop. Close the switch and verify the commands stay off with the request held. Release the request and make a fresh press to restart.
3. With the prebiased, current-limited bench fixture, record both rail voltages, primary current, trip signal, enables and actual gate-to-source voltage. Measure the first-cycle current, bias and gate dead time in both directions and measure fault-clearing time from the current threshold through gate turn-off. Record drain overshoot and verify the high-side bootstrap rail before increasing load.

The two images cross-compile and the reset vectors were checked. Flashing and the scope captures require a connected NUCLEO-G474RE and instruments.
