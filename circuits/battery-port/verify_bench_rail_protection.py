"""Verify the native KiCad netlist of the two-rail protection schematic."""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

from bench_rail_interlocks_test import check_transitions, check_voltage_corners


def verify(path, gate_feedback=False):
    design = ET.parse(path)
    components = {part.get("ref"): part for part in design.findall("./components/comp")}
    pins = {}
    for net in design.findall("./nets/net"):
        for pin in net.findall("node"):
            key = (pin.get("ref"), pin.get("pin"))
            if key in pins:
                raise ValueError(f"{key[0]}.{key[1]} is exported more than once")
            pins[key] = net.get("name")

    def expect(net, *references):
        for reference in references:
            ref, pin = reference.rsplit(".", 1)
            actual = pins.get((ref, pin))
            if actual != net:
                raise ValueError(f"{reference} should connect to {net}, got {actual}")

    def verify_rail(side, offset, bulk, bridge, rtn, supply, logic, good, bulk_cap, ceramics, switches, ports):
        def rail_ref(ref):
            prefix = ref.rstrip("0123456789")
            return f"{prefix}{int(ref[len(prefix):]) + offset}"

        def verify_net(name, *references):
            expanded = []
            for reference in references:
                ref, pin = reference.rsplit(".", 1)
                expanded.append(f"{rail_ref(ref)}.{pin}")
            expect(ports.get(name, f"/{side} rail protection/{name}"), *expanded)

        def part(ref):
            return components[rail_ref(ref)]

        def expect_part(ref, key, value):
            actual = part(ref).findtext(key)
            if actual != value:
                raise ValueError(f"{side} {ref} {key} should be {value}, got {actual}")

        expect(bulk, f"{bulk_cap}.1", f"R{801 + offset}.1")
        expect(rtn, f"{bulk_cap}.2", *(f"{c}.2" for c in ceramics))
        expect(bridge, *(f"{c}.1" for c in ceramics), *(f"{q}.2" for q in switches),
               f"Q{802 + offset}.3", f"R{803 + offset}.2", f"D{801 + offset}.2")
        verify_net("CUT_IN", "R801.4", "Q801.3", "Q803.3", "D801.1")
        verify_net("KS_P", "R801.2", "U810.8")
        verify_net("KS_N", "R801.3", "U810.1")
        verify_net("PRE_MID", "Q804.3", "Q805.3")
        verify_net("GUARD_OUT", "Q806.3", "R802.1")
        verify_net("PRE_RMID", "R802.2", "R803.1")

        for stage, driver, mosfet, resistance, capacitance in (
            ("CUT", 801, 801, 810, 810), ("PRE", 802, 803, 820, 820), ("GUARD", 803, 805, 830, 830)
        ):
            common_source = (f"U{driver}.8", f"C{capacitance}.2", f"Q{mosfet}.1",
                             f"Q{mosfet + 1}.1", f"R{resistance + 2}.2", f"R{resistance + 4}.2")
            if gate_feedback:
                expect_part(f"U{driver}", "value", "UCC5350SBD")
                expect_part(f"PS{driver}", "value", "R2M-2412S")
                expect_part(f"PS{driver}", "footprint", "Helios_Bench:Converter_RECOM_R2M_THT_Single")
                expect_part(f"F{driver}", "footprint", "Helios_Bench:Fuse_Littelfuse_NANO2_452_454")
                expect(logic, f"U{driver + offset}.1", f"C{capacitance + 1 + offset}.1")
                expect(rtn, f"U{driver + offset}.3", f"U{driver + offset}.4", f"PS{driver + offset}.2",
                       f"C{capacitance + 1 + offset}.2", f"C{capacitance + 3 + offset}.2")
                expect(bulk, f"F{driver + offset}.1")
                verify_net(f"{stage}_BIAS_IN", f"F{driver}.2", f"PS{driver}.1", f"C{capacitance + 3}.1")
                verify_net(f"{stage}_VISO", f"U{driver}.5", f"PS{driver}.7", f"C{capacitance}.1",
                           f"C{capacitance + 2}.1")
                common_source += (f"PS{driver}.6", f"C{capacitance + 2}.2")
                for pin in ("4", "5"):
                    net = pins.get((f"PS{driver + offset}", pin))
                    if net and not net.startswith("unconnected-"):
                        raise ValueError(f"{side} {stage} isolated module pin {pin} should be open, got {net}")
                charge_pin, drive_pin, pull = 6, 7, "2.2k"
            else:
                u = driver + offset
                expect(supply, f"U{u}.1", f"C{capacitance + 1 + offset}.1")
                expect(rtn, f"U{u}.3", f"U{u}.5", f"U{u}.11", f"C{capacitance + 1 + offset}.2")
                verify_net(f"{stage}_BST", f"U{driver}.9", f"C{capacitance}.1")
                charge_pin, drive_pin, pull = 7, 6, "4.7M"

            verify_net(f"{stage}_SOURCE", *common_source)
            verify_net(f"{stage}_CHARGE", f"U{driver}.{charge_pin}", f"R{resistance}.1")
            verify_net(f"{stage}_DRIVE", f"U{driver}.{drive_pin}", f"R{resistance}.2", f"R{resistance + 1}.1",
                       f"R{resistance + 3}.1")
            verify_net(f"{stage}_G1", f"Q{mosfet}.2", f"R{resistance + 1}.2", f"R{resistance + 2}.1")
            verify_net(f"{stage}_G2", f"Q{mosfet + 1}.2", f"R{resistance + 3}.2", f"R{resistance + 4}.1")
            for number, value in enumerate(("100", "4.7", pull, "4.7", pull)):
                expect_part(f"R{resistance + number}", "value", value)
                if gate_feedback and number in (2, 4):
                    ref = f"R{resistance + number}"
                    expect_part(ref, "footprint", "Resistor_SMD:R_1206_3216Metric")
                    expect_part(ref, "./fields/field[@name='Tolerance']", "1%")
                    expect_part(ref, "./fields/field[@name='Power Rating']", "0.25 W minimum")
            for q in (mosfet, mosfet + 1):
                expect_part(f"Q{q}", "value", "CSD19531Q5A")
                expect_part(f"Q{q}", "footprint", "Package_SON:VSONP-8-1EP_5x6_P1.27mm")

        verify_net("CUT_CMD", "R804.1", "U816.2")
        command_pin = 2 if gate_feedback else 4
        verify_net("CUT_INP", "U815.5", f"U801.{command_pin}", "U819.1")
        verify_net("DC_PRE_REQ", "R805.1", "U808.1", "U823.1", "U827.2")
        verify_net("RUN", "R806.1", "U804.2")
        verify_net("RUN_LOW", "U804.4", "U806.1", "U821.1", "U828.1")
        verify_net("PRE_IDLE", "U827.4", "U828.2")
        verify_net("ARM_OK", "U828.4", "U805.1")
        verify_net("ARM_DATA", "U805.4", "U815.2")
        verify_net("I_MON", "U810.5", "U811.3", "U811.6")
        verify_net("V_HIGH", "U811.5", "R840.2", "R841.1")
        verify_net("V_LOW", "U811.2", "R841.2", "R842.1")
        verify_net("ABOVE_LOW", "U811.1", "U812.1")
        verify_net("BELOW_HIGH", "U811.7", "U812.2")
        verify_net("WINDOW_OK", "U812.4", "U813.1")
        verify_net("SENSE_OK", "U813.4", "U816.1")
        verify_net("ENABLE_OK", "U816.4", "U826.1")
        verify_net("LOCAL_OK", "U826.4", "U814.1", "U822.2")
        verify_net("PEER_OK", "R844.1", "U814.2")
        verify_net("BOTH_OK", "U814.4", "U815.6", "U806.2", "U820.2")
        verify_net("ARM", "R843.1", "U815.1")
        verify_net("PRE_ALLOWED", "U806.4", "U807.3", "U809.2", "U823.6")
        verify_net("PRE_ACCEPT", "U823.5", "U808.2")
        verify_net("TIMER_Q", "U807.13", "U809.1")
        verify_net("TIMER_RC", "U807.15", "C801.1", "R807.2")
        verify_net("PRE_INP", "U808.4", f"U802.{command_pin}", "U807.2", "U824.1")
        verify_net("GUARD_INP", "U809.4", f"U803.{command_pin}", "U824.2")
        verify_net("PRE_SEND", "U824.4")
        verify_net("V_MATCH", "U818.4", "U805.2", "U819.2")
        if gate_feedback:
            verify_net("VOLTAGE_AND_LATCH", "U819.4", "U831.2")
            verify_net("CUT_READY", "U831.4", "U820.1", "U821.2")
            verify_net("CUT_G1", "R851.1")
            verify_net("CUT_G2", "R853.1")
            verify_net("CUT_SOURCE", "R855.1")
            verify_net("G1_SENSE", "U829.3", "R851.2", "R852.1")
            verify_net("G2_SENSE", "U829.5", "R853.2", "R854.1")
            verify_net("GATE_REFERENCE", "U829.2", "U829.6", "R855.2", "R856.2", "R857.1")
            verify_net("G1_HIGH", "U829.1", "U830.1")
            verify_net("G2_HIGH", "U829.7", "U830.2")
            verify_net("GATES_HIGH", "U830.4", "U831.1")
            expect(logic, f"U{829 + offset}.8", f"U{830 + offset}.5", f"U{831 + offset}.5",
                   f"R{856 + offset}.1", f"R{858 + offset}.1")
            expect(rtn, f"U{829 + offset}.4", f"U{830 + offset}.3", f"U{831 + offset}.3",
                   *(f"R{ref + offset}.2" for ref in (852, 854, 857, 858)))
            for ref, value in enumerate(("402k", "10.0k", "402k", "10.0k", "402k", "165k", "10.6k"), 851):
                expect_part(f"R{ref}", "value", value)
                expect_part(f"R{ref}", "./fields/field[@name='Tolerance']", "0.1%")
        else:
            verify_net("CUT_READY", "U819.4", "U820.1", "U821.2")
        verify_net("PWM_READY", "U820.4")
        verify_net("KEEP_ALLOW", "U821.4", "U822.1")
        verify_net("KEEP", "U822.4")
        verify_net("V_ABOVE", "U817.1", "U818.1")
        verify_net("V_BELOW", "U817.7", "U818.2")
        verify_net("BR_V", "R881.2", "R882.1", "C881.1", "U817.3", "U817.6")
        verify_net("BULK_LO", "R883.2", "R884.1", "C882.1", "U817.2")
        verify_net("BULK_HI", "R885.2", "R886.1", "C883.1", "U817.5", "U825.3")
        verify_net("MIN_V", "R887.2", "R888.1", "U825.4")
        verify_net("BULK_VALID", "U825.1", "U826.2")
        expect(bulk, f"R{883 + offset}.1", f"R{885 + offset}.1")
        expect(bridge, f"R{881 + offset}.1")
        expect(good, f"U{813 + offset}.2")
        expect(logic, f"U{807 + offset}.16", f"R{807 + offset}.1",
               f"U{810 + offset}.6", f"U{810 + offset}.7", f"U{811 + offset}.8",
               f"U{815 + offset}.7", f"U{815 + offset}.8", f"R{840 + offset}.1",
               f"U{817 + offset}.8", f"U{823 + offset}.2", f"U{823 + offset}.7", f"U{823 + offset}.8",
               f"U{825 + offset}.5", f"R{887 + offset}.1")
        expect(rtn, f"U{807 + offset}.1", f"U{807 + offset}.8", f"U{807 + offset}.14", f"C{801 + offset}.2",
               f"R{804 + offset}.2", f"R{805 + offset}.2", f"R{806 + offset}.2",
               f"U{810 + offset}.2", f"U{810 + offset}.3", f"U{811 + offset}.4",
               f"U{815 + offset}.4", f"R{842 + offset}.2", f"R{843 + offset}.2", f"R{844 + offset}.2",
               f"U{817 + offset}.4", f"U{823 + offset}.4", f"U{825 + offset}.2",
               *(f"R{r + offset}.2" for r in (882, 884, 886, 888)), *(f"C{c + offset}.2" for c in (881, 882, 883)))

        for ref, value in (
            ("R801", "5m / Kelvin"), ("R802", "100 / 3W"), ("R803", "100 / 3W"),
            ("R807", "33.2k"), ("C801", "220n / 16V"), ("U810", "INA241A2 20V/V"),
            ("R840", "10.5k"), ("R841", "12.0k"), ("R842", "10.5k"),
            ("R881", "392k"), ("R882", "10.0k"), ("R883", "422k"), ("R884", "10.0k"),
            ("R885", "365k"), ("R886", "10.0k"), ("R887", "12.1k"), ("R888", "1.00k"),
        ):
            expect_part(ref, "value", value)

    verify_rail("Primary", 0, "/PRIMARY12", "/P_SWITCHED", "/P0", "/P10", "/P3V3", "/PRI_OK",
                "C24", ("C26", "C28"), ("Q1", "Q3"),
                {"ARM": "/ARM", "RUN": "/RUN", "CUT_CMD": "/CUT_ENABLE", "CUT_INP": "/P_CUT_INP",
                 "DC_PRE_REQ": "/DC_PRE_P", "PEER_OK": "/P_PEER_OK", "KEEP": "/P_KEEP",
                 "PWM_READY": "/P_PWM_READY", "PRE_SEND": "/P_PRE_SEND"})
    verify_rail("Secondary", 100, "/LINK24", "/S_SWITCHED", "/S0", "/S10", "/S3V3", "/SEC_OK",
                "C25", ("C27", "C29"), ("Q5", "Q7"),
                {"ARM": "/S_ARM", "RUN": "/S_RUN", "CUT_CMD": "/S3V3", "DC_PRE_REQ": "/S_PRE_REQ",
                 "PEER_OK": "/S_PEER_OK", "KEEP": "/S_KEEP", "PWM_READY": "/S_PWM_READY"})
    expect("/PRIMARY12", "R30.4", "C24.1")

    link = "/Rail interlocks/"
    expect("/P3V3", "U701.8", "U702.8", "U703.1", "U704.5", "U705.5", "U707.5", "U708.5", "U709.5")
    expect("/P0", "U701.5", "U702.5", "U703.4", "U704.3", "U705.3", "U707.3", "U708.3", "U709.3",
           "R701.2", "R702.2", "J701.1")
    expect("/S3V3", "U701.1", "U702.1", "U703.8", "U706.5")
    expect("/S0", "U701.4", "U702.4", "U703.5", "U706.3")
    expect("/P_KEEP", "U701.7")
    expect("/S_KEEP", "U701.3")
    expect("/S_PEER_OK", "U701.2")
    expect(link + "P_PEER_RAW", "U701.6", "U709.1", "R702.1")
    expect("/P_PEER_OK", "U709.4")
    expect("/P_CUT_INP", "U703.2")
    expect("/RUN", "U703.3", "U707.2")
    expect("/S_ARM", "U703.7")
    expect("/S_RUN", "U703.6")
    expect("/P_PRE_SEND", "U702.7")
    expect("/S_PRE_REQ", "U702.2")
    expect("/P_PWM_READY", "U704.1")
    expect("/S_PWM_READY", "U702.3", "U706.2")
    expect(link + "S_READY_RX", "U702.6", "U704.2", "U708.2", "R701.1")
    expect(link + "P_RUN_LOW", "U707.4", "U708.1")
    expect(link + "READBACK_OK", "U708.4", "U709.2")
    expect(link + "DC_READY", "U704.4", "U705.2", "J701.4")
    expect("/CUT_ENABLE", "J701.2")
    expect("/DC_PRE_P", "J701.3")
    expect("/LEGACY_PERMIT_P", "U4.11", "U705.1")
    expect("/LEGACY_SEC_EN", "U13.4", "U706.1")
    expect("/PERMIT_P", "U705.4", "J5.10", "U2.6", "U102.6", "U7.2", "U43.13")
    expect("/SEC_EN", "U706.4", "U202.6", "U302.6", "U47.13")
    print("Verified both rail cutoffs, voltage windows, isolated shutdown and final PWM permissions")
    check_voltage_corners(components)
    check_transitions(components, pins, gate_feedback)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path, help="KiCad XML netlist exported from the protection candidate")
    parser.add_argument("--gate-feedback", action="store_true", help="verify the isolated-drive revision")
    args = parser.parse_args()
    verify(args.netlist, args.gate_feedback)
