"""Execute the real Cortex-M4 binary with a minimal, deterministic register model."""
from argparse import ArgumentParser
from pathlib import Path
from struct import pack, unpack

from elftools.elf.elffile import ELFFile
from unicorn import UC_ARCH_ARM, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_CPU_ARM_CORTEX_M4


FLASH = 0x08000000
RAM = 0x20000000
RCC = 0x40021000
GPIO_A = 0x48000000
GPIO_B = 0x48000400
HRTIM = 0x40016800
COMMON = HRTIM + 0x380
DWT_COUNTER = 0xE0001004
COUNTER_ENABLE = 0x70000
ARM = 1 << 5
RUN = 1 << 10
PRE = 1 << 1
LED = 1 << 5
ACK_PRIMARY = 1 << 2
ACK_SECONDARY = 1 << 12
CUT_ENABLE = 1 << 13
DC_PRE = 1 << 14
DC_READY = 1 << 15
REQUEST_OUTPUTS = RUN | ARM | PRE | CUT_ENABLE | DC_PRE
CYCLES_PER_MS = 160_000
DC_READY_DELAY = CYCLES_PER_MS // 2
DC_READY_SETTLE = CYCLES_PER_MS // 4
COMPARE_OFFSETS = (0x1C, 0x24, 0x28, 0x2C)
TIMERS = (HRTIM + 0x80, HRTIM + 0x100)
BRIDGE_OUTPUTS = 0xF
# STM32G474 timer events: compare 1/3 set the outputs and compare 2/4 reset them.
# The reset writes at startup also request a software reset of each output.
OUTPUT_EVENT_REGISTERS = ((0x3C, 1 << 3), (0x40, (1 << 4) | 1),
                          (0x44, 1 << 5), (0x48, (1 << 6) | 1))


def require(valid, message):
    if not valid:
        raise ValueError(message)


class BenchRegisters:
    def __init__(self, binary, protected=False):
        image = binary.read_bytes()
        stack, reset = unpack("<II", image[:8])
        self.hard_fault, = unpack("<I", image[12:16])
        with binary.with_suffix(".elf").open("rb") as source:
            elf = ELFFile(source)
            symbols = elf.get_section_by_name(".symtab")
            self.millis = symbols.get_symbol_by_name("millis")[0]["st_value"]
            bss = elf.get_section_by_name(".bss")
            bss_start, bss_size = bss["sh_addr"], bss["sh_size"]

        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
        for address, size in [(FLASH, 0x10000), (RAM, 0x8000)]:
            self.cpu.mem_map(address, size)
        for address, size in [(0x40000000, 0x30000), (GPIO_A, 0x1000),
                              (0xE0001000, 0x1000), (0xE000E000, 0x1000)]:
            self.cpu.mmio_map(address, size, self.on_read, address, self.on_write, address)
        self.cpu.mem_write(FLASH, image)
        self.cpu.mem_write(bss_start, b"\xa5" * bss_size)
        self.cpu.reg_write(UC_ARM_REG_SP, stack)
        self.cpu.reg_write(UC_ARM_REG_PC, reset & ~1)

        self.registers = {}
        self.protected = protected
        self.request = True
        self.allow_permit = True
        self.allow_precharge_ack = True
        self.hold_precharge_ack = False
        self.trip_during_precharge = False
        self.drop_dc_ready_during_bootstrap = False
        self.block_midpoint = False
        self.cycles = 0
        self.until = 0
        self.started = None
        self.midpoint = False
        self.latched_fault = False
        self.gpio_b = 0
        self.precharge_rise = None
        self.precharge_fall = None
        self.precharge_ack_at = None
        self.dc_healthy = True
        self.allow_dc_ready = True
        self.force_dc_ready = False
        self.dc_ready_duration = None
        self.cut_enable_at = None
        self.dc_pre_at = None
        self.dc_pre_end = None
        self.dc_charge_valid = False
        self.dc_arm_at = None
        self.dc_requests = 0
        self.arming_edges = 0
        self.disable_writes = 0
        self.enabled_outputs = 0
        self.initial_compares = []
        self.preload_writes = 0

    def read(self, address):
        return self.registers.get(address, 0)

    def dc_ready(self):
        if not self.dc_healthy:
            self.dc_arm_at = None
            self.dc_charge_valid = False
        if self.force_dc_ready:
            return True
        if not self.allow_dc_ready or not self.gpio_b & CUT_ENABLE or self.dc_arm_at is None:
            return False
        elapsed = self.cycles - self.dc_arm_at - DC_READY_DELAY
        return elapsed >= 0 and (self.dc_ready_duration is None or elapsed < self.dc_ready_duration)

    def advance(self, amount):
        previous = self.cycles
        self.cycles += amount
        if self.cycles // CYCLES_PER_MS != previous // CYCLES_PER_MS:
            # Advance the firmware's millisecond clock without simulating NVIC latency.
            self.cpu.mem_write(self.millis, pack("<I", self.cycles // CYCLES_PER_MS))
        if self.started is not None:
            period = self.read(HRTIM + 0x14) // 8
            compare = self.read(HRTIM + 0x1C) // 8
            before = (previous - self.started - compare) // period
            after = (self.cycles - self.started - compare) // period
            self.midpoint |= not self.block_midpoint and after > before
        if self.cycles >= self.until:
            self.cpu.emu_stop()

    def on_read(self, _cpu, offset, _size, base):
        address = base + offset
        if address == GPIO_A + 0x10:
            self.advance(32 if self.gpio_b & RUN else 1024)
            if self.gpio_b & PRE and self.cycles - self.precharge_rise > 400:
                if self.trip_during_precharge:
                    self.allow_permit = False
                if self.drop_dc_ready_during_bootstrap:
                    self.allow_dc_ready = False
            permit = self.allow_permit and bool(self.gpio_b & RUN)
            self.latched_fault |= self.started is not None and not permit
            return (int(self.request) << 6) | (int(permit) << 12)
        elif address == GPIO_B + 0x10:
            local = (self.allow_permit and bool(self.gpio_b & RUN) and bool(self.gpio_b & PRE))
            remote = local and self.allow_precharge_ack and self.cycles - self.precharge_rise >= 96
            if remote and self.precharge_ack_at is None:
                self.precharge_ack_at = self.cycles
            stuck = self.hold_precharge_ack and self.precharge_ack_at is not None
            ready = self.protected and self.dc_ready()
            return ((ACK_PRIMARY if local else 0) | (ACK_SECONDARY if remote or stuck else 0) |
                    (DC_READY if ready else 0))
        elif address == DWT_COUNTER:
            self.advance(32)
            return self.cycles
        elif address == RCC:
            return self.read(address) | (1 << 10) | (1 << 25)
        elif address == RCC + 8:
            config = self.read(address)
            return (config & ~12) | ((config & 3) << 2)
        elif address == COMMON + 8:
            return (1 << 16) | int(self.latched_fault)
        elif address == HRTIM + 4:
            return int(self.midpoint)
        elif address == HRTIM + 0x10 and self.started is not None:
            return ((self.cycles - self.started) * 8) % self.read(HRTIM + 0x14)
        return self.read(address)

    def on_write(self, _cpu, offset, _size, value, base):
        address = base + offset
        self.registers[address] = value
        if address == GPIO_B + 0x18:
            state = (self.gpio_b | (value & 0xFFFF)) & ~(value >> 16)
            rising = state & ~self.gpio_b
            if self.protected:
                if rising & CUT_ENABLE:
                    require(not state & (RUN | ARM | PRE | DC_PRE) and self.started is None,
                            "Cutoff enabled outside the idle state")
                    self.cut_enable_at = self.cycles
                    self.dc_pre_at = self.dc_pre_end = None
                if rising & DC_PRE:
                    require(state & CUT_ENABLE and not state & (RUN | ARM | PRE) and self.started is None,
                            "DC precharge was requested with PWM active or cutoff disabled")
                    require(self.cycles - self.cut_enable_at >= 2 * CYCLES_PER_MS,
                            "DC precharge began before cutoff enable settled")
                    self.dc_pre_at = self.cycles
                    self.dc_charge_valid = self.dc_healthy
                    self.dc_requests += 1
                if not state & DC_PRE and self.gpio_b & DC_PRE:
                    self.dc_pre_end = self.cycles
                if not state & CUT_ENABLE:
                    self.dc_arm_at = None
                if rising & ARM:
                    require(state & CUT_ENABLE and not state & (DC_PRE | PRE) and self.dc_pre_end is not None,
                            "ARM before the DC precharge request ended")
                    request_us = (self.dc_pre_end - self.dc_pre_at) * 1000 / CYCLES_PER_MS
                    coast_us = (self.cycles - self.dc_pre_end) * 1000 / CYCLES_PER_MS
                    require(3000 <= request_us <= 3100 and 50 <= coast_us <= 100,
                            "DC request or release interval was outside the verified command timing")
                    if self.dc_healthy and self.dc_charge_valid:
                        self.dc_arm_at = self.cycles
                if rising & RUN:
                    require(not state & (DC_PRE | ARM) and self.dc_ready() and self.dc_arm_at is not None and
                            self.cycles - self.dc_arm_at >= DC_READY_DELAY + DC_READY_SETTLE,
                            "RUN rose before both rail cutoffs reported stable readiness")
            if state & ARM and not self.gpio_b & ARM:
                require(not state & RUN, "ARM edge while RUN was high")
                self.arming_edges += 1
            if state & PRE and not self.gpio_b & PRE:
                require(state & RUN and self.started is None, "Precharge with RUN low or PWM active")
                self.precharge_rise = self.cycles
                self.precharge_ack_at = None
            elif not state & PRE and self.gpio_b & PRE:
                self.precharge_fall = self.cycles
            self.gpio_b = state
        elif address == COMMON + 0x0C and value & 1:
            self.latched_fault = False
        elif address == COMMON + 0x14 and value & BRIDGE_OUTPUTS:
            require(self.allow_permit and self.gpio_b & RUN, "Timer enabled without permit")
            require(not self.protected or self.dc_ready(), "Timer enabled without DC readiness")
            require(not self.gpio_b & PRE and self.precharge_ack_at is not None and
                    self.precharge_fall - self.precharge_ack_at >= 7 * 160 and
                    self.cycles - self.precharge_fall >= 160, "Timer enabled before precharge and blanking completed")
            require(value == BRIDGE_OUTPUTS, "Expected all four timer outputs enabled together")
            require(self.read(COMMON + 0x50) == 1, "FLT1 must use a raw, active-low GPIO input")
            require(self.read(COMMON + 4) & 6 == 6, "Both initial preload values need a software update")
            for timer in TIMERS:
                require(self.read(timer + 0x68) & 1, "Bridge timer must listen to FLT1")
                require(self.read(timer + 0x64) & 0x00300030 == 0x00200020,
                        "Both bridge outputs must be inactive on FLT1")
                for offset, events in OUTPUT_EVENT_REGISTERS:
                    require(self.read(timer + offset) == events, "A bridge output uses the wrong compare event")
            self.initial_compares.append(tuple(self.read(t + off) for t in TIMERS for off in COMPARE_OFFSETS))
            self.enabled_outputs |= value
        elif address == COMMON + 0x18:
            self.enabled_outputs &= ~value
            if value & BRIDGE_OUTPUTS == BRIDGE_OUTPUTS:
                self.disable_writes += 1
        elif address == HRTIM:
            if not value & COUNTER_ENABLE:
                self.started = None
            elif self.started is None:
                self.started = self.cycles
        elif address == HRTIM + 8 and value & 1:
            self.midpoint = False
        elif self.started is not None and any(address - t in COMPARE_OFFSETS for t in TIMERS):
            require(self.read(COMMON) & 6 == 6, "Compare preload writes were not protected")
            self.preload_writes += 1

    def run(self, milliseconds):
        self.until = self.cycles + milliseconds * CYCLES_PER_MS
        self.cpu.emu_start(self.cpu.reg_read(UC_ARM_REG_PC) | 1, 0, count=2_000_000)
        require(self.cycles >= self.until, "Firmware stalled before the modeled time limit")


def check(binary, charging, protected=False):
    board = BenchRegisters(binary, protected)
    start_time = 40 if protected else 21
    board.run(30)
    require(not board.initial_compares and not board.arming_edges and not board.dc_requests and
            not board.gpio_b & REQUEST_OUTPUTS, "Held request started after reset")
    if protected:
        mode, pulls = board.read(GPIO_B), board.read(GPIO_B + 0x0C)
        require(mode >> 26 & 0x3F == 0x05 and pulls >> 26 & 0x3F == 0x2A,
                "J701 GPIO direction or pull-down configuration is wrong")

    board.request = False
    board.run(25)
    board.request = True
    board.run(start_time + 1)
    require(len(board.initial_compares) == 1 and board.arming_edges == 1, "Fresh request did not start")
    require(board.started is not None and board.enabled_outputs == BRIDGE_OUTPUTS and board.preload_writes > 70 * 8,
            "Ramp was not serviced")
    first = board.initial_compares[0]
    expected_delay = -768 if charging else 768
    require(first[4] - first[0] == expected_delay, "Wrong startup phase or direction")
    primary, secondary = (board.read(t + COMPARE_OFFSETS[0]) for t in TIMERS)
    require(secondary - primary == 2 * expected_delay, "Ramp did not reach its target")

    board.allow_permit = False
    previous_disables = board.disable_writes
    board.run(1)
    require(board.started is None and board.enabled_outputs == 0 and not board.gpio_b & REQUEST_OUTPUTS and
            board.disable_writes == previous_disables + 1, "Permit loss did not disable the controller")
    board.allow_permit = True
    board.run(25)
    require(len(board.initial_compares) == 1, "Restored permit restarted a held request")
    board.request = False
    board.run(25)
    board.request = True
    board.run(start_time)
    require(board.initial_compares == [first, first] and board.arming_edges == 2,
            "Fresh restart did not reset the ramp")

    board.block_midpoint = True
    board.run(1)
    require(board.started is None and not board.gpio_b & REQUEST_OUTPUTS,
            "Missing preload timing event did not stop the controller")
    board.block_midpoint = False
    board.run(25)
    require(len(board.initial_compares) == 2, "Missed deadline restarted a held request")

    board.request = False
    board.run(25)
    board.request = True
    board.run(start_time)
    require(board.initial_compares == [first, first, first], "Third start reused stale compare state")
    board.latched_fault = True
    board.run(1)
    require(board.started is None and not board.gpio_b & REQUEST_OUTPUTS,
            "Latched flag was ignored after permit recovery")

    board.request = False
    board.run(25)
    board.request = True
    board.run(start_time)
    require(board.started is not None and board.gpio_b & RUN, "Fault fixture failed to start")
    require(not board.read(GPIO_A + 0x18) & LED, "Fault LED was on during normal operation")
    prior_disables = board.disable_writes
    board.cpu.emu_start(board.hard_fault, 0, count=128)
    require(board.disable_writes == prior_disables + 1 and board.enabled_outputs == 0 and
            not board.gpio_b & REQUEST_OUTPUTS,
            "Fault handler did not disable PWM and requests")
    require(board.read(GPIO_A + 0x18) == LED, "Fault handler did not indicate the fault on LD2")

    for condition in ("missing ack", "stuck ack", "permit lost during precharge"):
        faulty = BenchRegisters(binary, protected)
        faulty.request = False
        faulty.run(25)
        faulty.allow_precharge_ack = condition != "missing ack"
        faulty.hold_precharge_ack = condition == "stuck ack"
        faulty.trip_during_precharge = condition == "permit lost during precharge"
        faulty.request = True
        faulty.run(max(25, start_time))
        require(faulty.precharge_rise is not None and faulty.precharge_fall is not None,
                f"Fixture failed to reach precharge for {condition}")
        require(not faulty.initial_compares and not faulty.gpio_b & REQUEST_OUTPUTS,
                f"Precharge failure did not inhibit PWM for {condition}")
        faulty.allow_permit = True
        faulty.allow_precharge_ack = True
        faulty.hold_precharge_ack = False
        faulty.run(25)
        require(not faulty.initial_compares, f"Held request restarted after {condition}")
    print(f"{binary.name}: precharge timing, missing/stuck ACK, permit loss, "
          "ramp, re-arm, latched faults and fault handler passed")


def check_dc_rails(binary):
    def released_board():
        board = BenchRegisters(binary, protected=True)
        board.request = False
        board.run(25)
        return board

    def expect_off(board, condition):
        require(not board.initial_compares and not board.gpio_b & REQUEST_OUTPUTS and
                not board.enabled_outputs, condition)

    for ready_duration in (None, DC_READY_SETTLE // 4):
        board = released_board()
        board.allow_dc_ready = ready_duration is not None
        board.dc_ready_duration = ready_duration
        board.request = True
        board.run(42)
        require(board.dc_requests == 1 and board.arming_edges == 1, "Fixture failed to reach rail readiness")
        expect_off(board, "Missing or unstable DC readiness did not abort")
        board.allow_dc_ready = True
        board.dc_ready_duration = None
        board.run(45)
        expect_off(board, "Held request retried after a readiness failure")
        require(board.dc_requests == 1, "DC precharge pulsed again after a readiness failure")

    board = BenchRegisters(binary, protected=True)
    board.force_dc_ready = True
    board.request = False
    board.run(25)
    board.request = True
    board.run(45)
    expect_off(board, "A stuck-high DC_READY allowed startup")
    require(board.dc_requests == 0 and board.arming_edges == 0, "Stuck readiness allowed a command")
    board.force_dc_ready = False
    board.run(45)
    expect_off(board, "Clearing stale readiness started a held request")

    for fail_during_bootstrap in (False, True):
        board = released_board()
        board.allow_permit = fail_during_bootstrap
        board.drop_dc_ready_during_bootstrap = fail_during_bootstrap
        board.request = True
        board.run(45)
        require(board.arming_edges == 1 and (board.precharge_rise is not None) == fail_during_bootstrap,
                "Fixture did not exercise the expected final permit or bootstrap failure")
        expect_off(board, "Missing final permit or readiness loss during bootstrap did not abort")
        board.allow_permit = board.allow_dc_ready = True
        board.drop_dc_ready_during_bootstrap = False
        board.run(45)
        expect_off(board, "Restoring final permit or readiness restarted a held request")

    for condition in ("released request", "premature readiness", "bias loss"):
        board = released_board()
        board.request = True
        board.run(23)
        require(board.gpio_b & DC_PRE and not board.gpio_b & (RUN | ARM | PRE),
                f"Fixture did not interrupt DC precharge for {condition}")
        if condition == "released request":
            board.request = False
        elif condition == "premature readiness":
            board.force_dc_ready = True
        else:
            board.dc_healthy = False
        board.run(1)
        if condition != "bias loss":
            expect_off(board, f"DC precharge stayed enabled after {condition}")
        board.dc_healthy = True
        board.force_dc_ready = False
        board.request = True
        board.run(45)
        expect_off(board, f"Restoring inputs resumed startup after {condition}")
        require(board.dc_requests == 1, f"Re-issued DC precharge after {condition}")
        board.request = False
        board.run(25)
        board.request = True
        board.run(40)
        require(len(board.initial_compares) == 1 and board.dc_requests == 2 and board.started is not None,
                f"Fresh request could not start after {condition}")

    board = released_board()
    board.request = True
    board.run(40)
    require(board.started is not None and board.dc_requests == 1, "Readiness loss test never entered RUN")
    board.allow_dc_ready = False
    board.run(1)
    require(board.allow_permit and not board.gpio_b & REQUEST_OUTPUTS and
            board.enabled_outputs == 0 and board.started is None,
            "Lost DC_READY with PERMIT high did not disable both cutoffs and PWM")
    board.allow_dc_ready = True
    board.run(45)
    require(board.dc_requests == 1 and len(board.initial_compares) == 1, "Held RUN request retried after DC loss")
    print(f"{binary.name}: protected sequence, stuck or lost DC_READY, interrupted precharge and recovery passed")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=Path(__file__).resolve().parent / "out")
    args = parser.parse_args()
    check(args.images / "helios-g474-discharge.bin", charging=False)
    check(args.images / "helios-g474-charge.bin", charging=True)
    for direction in ("discharge", "charge"):
        image = args.images / f"helios-g474-protected-{direction}.bin"
        check(image, charging=direction == "charge", protected=True)
        check_dc_rails(image)
