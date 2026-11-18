"""Build both flash images for the NUCLEO-G474RE with Zig and Arm/ST CMSIS."""
import argparse
from pathlib import Path
import struct
import subprocess


ROOT = Path(__file__).resolve().parent


def build(zig, device, core, output):
    for direction, shift in [("discharge", 120), ("charge", -120)]:
        elf = output / ("helios-g474-" + direction + ".elf")
        binary = elf.with_suffix(".bin")
        command = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m4",
                   "-std=c11", "-Os", "-g", "-Wall", "-Wextra", "-Werror", "-ffreestanding",
                   "-ffunction-sections", "-fdata-sections", "-fno-builtin", "-fno-stack-protector",
                   "-nostdlib", "-Wl,--gc-sections,-e,Reset_Handler", "-T", str(ROOT / "stm32g474.ld"),
                   "-isystem", str(device), "-isystem", str(core), f"-DHELIOS_SHIFT={shift}",
                   str(ROOT / "stm32g474.c"), str(ROOT / "startup.S"), "-o", str(elf)]
        subprocess.run(command, check=True)
        subprocess.run([zig, "objcopy", "-O", "binary", str(elf), str(binary)], check=True)
        image = binary.read_bytes()
        stack, reset = struct.unpack_from("<II", image)
        elf_header = elf.read_bytes()[:52]
        entry, = struct.unpack_from("<I", elf_header, 24)
        if (elf_header[:6] != b"\x7fELF\x01\x01" or stack != 0x20008000 or
                entry != reset or not reset & 1 or not 0x08000000 < reset < 0x08000000 + len(image)):
            raise ValueError(f"Invalid vector table in {binary.name}")
        print(f"{binary.name}, {len(image)} bytes, reset vector 0x{reset:08X}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--device-include", type=Path, required=True)
    parser.add_argument("--core-include", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "out")
    args = parser.parse_args()
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=True)
    build(args.zig, args.device_include.resolve(), args.core_include.resolve(), target)
