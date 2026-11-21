"""Exercise the exported rail interlock wiring with discrete logic states.

Comparator outputs are stimuli. Each propagation step is abstract and the
monostable has a finite test window. This model makes no timing or SOA claim.
"""

from collections import defaultdict
from itertools import product
from math import log1p


def check_voltage_corners(components):
    def divider(top, bottom):
        for a, b in product((0.999, 1.001), repeat=2):
            yield (bottom * b) / (top * a + bottom * b)

    def resistance(ref):
        part = components[f"R{ref}"]
        if part.findtext("./fields/field[@name='Tolerance']") != "0.1%":
            raise ValueError(f"R{ref}: voltage window calculation requires 0.1% tolerance")
        return 1000 * float(part.findtext("value").removesuffix("k"))

    minimum, maximum, worst_charge = 100.0, 0.0, 0.0
    comparator_error = (-0.010, 0.010)
    for offset, endpoints in ((0, (10.8, 12.6)), (100, (21.6, 25.2))):
        bridge, lower, upper, reference = (
            tuple(divider(resistance(ref + offset), resistance(ref + offset + 1)))
            for ref in (881, 883, 885, 887)
        )
        for rail, ref, supply, error in product(upper, reference, (3.135, 3.465), comparator_error):
            trip = (supply * ref + error) / rail
            minimum = min(minimum, trip)
            maximum = max(maximum, trip)
            if not 8.5 < trip < endpoints[0]:
                raise ValueError(f"Bulk-presence threshold {trip:.3f} V is outside the bench screen")
        for volts, sense, low, high, lo_error, hi_error in product(
            endpoints, bridge, lower, upper, comparator_error, comparator_error
        ):
            low_trip = (volts * low + lo_error) / sense
            high_trip = (volts * high + hi_error) / sense
            if not 0.8 * volts < low_trip < volts < high_trip < 1.2 * volts:
                raise ValueError(f"Voltage window fails equal-rail or 20% mismatch screen at {volts} V")
            # Worst case for the unloaded RC model: 210 ohms and 2.2 uF.
            charge_at_match = -210 * 2.2e-6 * log1p(-low_trip / volts)
            worst_charge = max(worst_charge, charge_at_match)
    print(f"Bulk presence screen {minimum:.2f} to {maximum:.2f} V, unloaded RC match by {worst_charge*1e3:.2f} ms")


class Interlocks:
    def __init__(self, components, pins, gate_feedback):
        self.levels = defaultdict(bool)
        self.previous = defaultdict(bool)
        self.inputs = {}
        self.blocked = set()
        self.missing_gates = set()
        self.gate_channels = []
        self.remaining = {"U807": 0, "U907": 0}
        rail_logic = (804, 805, 806, 807, 808, 809, 812, 813, 814, 815, 816,
                      818, 819, 820, 821, 822, 823, 824, 826, 827, 828)
        refs = [f"U{number}" for number in range(701, 710)]
        for offset in (0, 100):
            refs.extend(f"U{number + offset}" for number in rail_logic)
            if gate_feedback:
                refs.extend((f"U{830 + offset}", f"U{831 + offset}"))
                for pin in ("1", "7"):
                    self.gate_channels.append(((f"U{829 + offset}", pin), pins[f"U{801 + offset}", "2"],
                                               pins[f"U{829 + offset}", "8"]))
        self.devices = [(ref, components[ref].findtext("value")) for ref in refs]
        self.pins = pins

    def drive(self, ref, pin, value):
        self.inputs[self.pins[ref, pin]] = value

    def levels_at(self, *locations):
        return [self.levels[self.pins[ref, pin]] for ref, pin in locations]

    def step(self):
        now = self.levels
        updates = {}
        # Physical gate-voltage comparisons are stimuli with per-gate availability.
        for output, command, power in self.gate_channels:
            updates[self.pins[output]] = now[command] and now[power] and output not in self.missing_gates
        for ref, kind in self.devices:
            def net(pin):
                return self.pins[ref, str(pin)]

            def pin_level(pin):
                return now[net(pin)]

            def rose(pin):
                return pin_level(pin) and not self.previous[net(pin)]

            if kind == "SN74LVC1G08":
                updates[net(4)] = pin_level(5) and pin_level(1) and pin_level(2)
            elif kind == "SN74LVC1G32":
                updates[net(4)] = pin_level(5) and (pin_level(1) or pin_level(2))
            elif kind == "SN74LVC1G04":
                updates[net(4)] = pin_level(5) and not pin_level(2)
            elif kind == "SN74LVC1G74DCU":
                if not pin_level(8) or not pin_level(6):
                    updates[net(5)] = False
                elif rose(1) and self.previous[net(6)]:
                    updates[net(5)] = pin_level(2)
            elif kind == "CD74HC221M":
                if not pin_level(16) or not pin_level(3):
                    self.remaining[ref] = 0
                elif self.remaining[ref]:
                    self.remaining[ref] -= 1
                elif not pin_level(1) and pin_level(2) and (rose(2) or rose(3)):
                    self.remaining[ref] = 64
                updates[net(13)] = self.remaining[ref] > 0
            elif kind in ("ISO7721FD", "ISO7720FD"):
                routes = ((7, 2), (3, 6)) if kind == "ISO7721FD" else ((2, 7), (3, 6))
                for upstream, downstream in routes:
                    powered = pin_level(1) and pin_level(8)
                    updates[net(downstream)] = powered and (ref, downstream) not in self.blocked and pin_level(upstream)
            else:
                raise ValueError(f"{ref}: no discrete model for {kind}")

        self.previous = now.copy()
        now.update(updates)
        now.update(self.inputs)

    def settle(self, cycles=20):
        for _ in range(cycles):
            self.step()


def check_transitions(components, pins, gate_feedback=False):
    power = (("U701", "8"), ("U701", "1"))
    bias = (("U813", "2"), ("U913", "2"))
    bulk = (("U825", "1"), ("U925", "1"))
    compare_rail = ((("U817", "1"), ("U817", "7")), (("U917", "1"), ("U917", "7")))
    current = (("U811", "1"), ("U811", "7"), ("U911", "1"), ("U911", "7"))
    legacy = (("U4", "11"), ("U13", "4"))
    arm, run, enable, request = ("J5", "6"), ("J5", "5"), ("J701", "2"), ("J701", "3")
    ready = (("J701", "4"),)
    command = "2" if gate_feedback else "4"
    cutoffs = (("U801", command), ("U901", command))
    pwm = (("U2", "6"), ("U102", "6"), ("U202", "6"), ("U302", "6"), ("J5", "10"))
    precharge = ((("U802", command), ("U803", command)), (("U902", command), ("U903", command)))

    def new_board():
        return Interlocks(components, pins, gate_feedback)

    def drive(board, locations, value):
        for location in locations:
            board.drive(*location, value)

    def expect(board, locations, expected, reason):
        actual = board.levels_at(*locations)
        if any(value != expected for value in actual):
            raise ValueError(f"{reason}: expected {expected} on {locations}, got {actual}")

    def expect_precharge(board, expected, reason):
        actual = [all(board.levels_at(*pair)) for pair in precharge]
        if actual != [expected, expected]:
            raise ValueError(f"{reason}: expected both precharge paths {expected}, got {actual}")

    def ready_inputs(board):
        drive(board, power + bias + bulk + current + (enable,), True)
        board.settle()

    def armed_board():
        board = new_board()
        ready_inputs(board)
        drive(board, (request,), True)
        board.settle()
        expect_precharge(board, True, "fresh precharge request")
        expect(board, cutoffs + pwm + ready, False, "precharge precedes cutoff and PWM")
        drive(board, (arm,), True)
        drive(board, compare_rail[0] + compare_rail[1], True)
        board.settle()
        expect(board, cutoffs, False, "ARM while precharge is requested")
        board.settle(90)
        expect_precharge(board, False, "timed window even with request held")
        drive(board, (request, arm), False)
        board.settle()
        drive(board, (arm,), True)
        board.settle()
        expect(board, cutoffs + ready, True, "both cutoffs armed with rails matched")
        expect(board, pwm, False, "legacy permit still required")
        drive(board, (run,) + legacy, True)
        drive(board, (arm,), False)
        board.settle()
        expect(board, cutoffs + pwm + ready, True, "normal RUN")
        return board

    board = new_board()
    drive(board, (arm, request, enable), True)
    board.settle()
    ready_inputs(board)
    expect_precharge(board, False, "held power-up request")
    expect(board, cutoffs + pwm + ready, False, "held ARM through power-up")
    drive(board, (request, arm), False)
    board.settle()
    drive(board, (arm,), True)
    board.settle()
    expect(board, cutoffs + pwm + ready, False, "both bridge rails discharged")

    for side in (0, 1):
        board = new_board()
        ready_inputs(board)
        drive(board, compare_rail[side], True)
        drive(board, (arm,), True)
        board.settle()
        expect(board, pwm + ready + (cutoffs[1],), False, "one bridge rail outside voltage window")
        drive(board, (run,) + legacy, True)
        board.settle()
        expect(board, cutoffs + pwm + ready, False, "RUN before both cutoffs ready")

    # Fault inputs act independently. Restore them with RUN and ARM still high.
    for fault in current + bias + bulk + power + (enable,):
        board = armed_board()
        drive(board, (arm,), True)
        board.settle()
        drive(board, (fault,), False)
        board.settle()
        expect(board, cutoffs + pwm + ready, False, f"fault at {fault}")
        drive(board, (fault,), True)
        board.settle()
        expect(board, cutoffs + pwm + ready, False, f"held command after restoring {fault}")
        drive(board, (run, arm, enable) + legacy, False)
        board.settle()
        drive(board, (enable,), True)
        board.settle()
        expect(board, cutoffs + pwm + ready, False, "enabling an idle board without ARM")
        drive(board, (arm,), True)
        board.settle()
        expect(board, cutoffs + ready, True, "fresh ARM after fault with voltage still matched")
        expect(board, pwm, False, "re-arm still requires the legacy permit")

    for channel in (("U701", 2), ("U701", 6), ("U702", 6)):
        board = armed_board()
        board.blocked.add(channel)
        board.settle()
        expect(board, cutoffs + pwm + ready, False, f"lost isolated signal {channel}")
        board.blocked.clear()
        board.settle()
        expect(board, cutoffs + pwm + ready, False, f"isolated signal {channel} restored during RUN")

    for off in bias + power:
        board = new_board()
        ready_inputs(board)
        drive(board, (request,), True)
        board.settle()
        expect_precharge(board, True, "precharge active before interruption")
        drive(board, (off,), False)
        board.settle()
        expect_precharge(board, False, "precharge interrupted by loss of power or bias")
        drive(board, (off,), True)
        board.settle()
        expect_precharge(board, False, "no automatic precharge after power or bias recovery")
        drive(board, (request,), False)
        board.settle(90)
        drive(board, (request,), True)
        board.settle()
        expect_precharge(board, True, "fresh request after recovery")

    print("Passed discrete startup, invalid rail voltage, both current trips, link loss and held-request recovery tests")

    if gate_feedback:
        for comparator in ("U829", "U929"):
            for pin in ("1", "7"):
                missing = (comparator, pin)
                board = new_board()
                ready_inputs(board)
                board.missing_gates.add(missing)
                drive(board, compare_rail[0] + compare_rail[1], True)
                board.settle()
                drive(board, (arm,), True)
                board.settle()
                expect(board, cutoffs, True, "matched rails and cutoff commands")
                expect(board, pwm + ready, False, f"prebiased false readiness with missing gate {missing}")

                board = armed_board()
                board.missing_gates.add(missing)
                board.settle()
                expect(board, cutoffs + pwm + ready, False, f"gate feedback lost in RUN at {missing}")
                board.missing_gates.clear()
                board.settle()
                expect(board, cutoffs + pwm + ready, False, f"restored gate feedback with RUN held at {missing}")
        print("Physical readiness rejects each missing gate and latches off after feedback loss during RUN")
