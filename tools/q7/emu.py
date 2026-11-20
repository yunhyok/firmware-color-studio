"""Run a routine of the unpacked Q7 image in a CPU emulator (unicorn, MIPS32 little-endian).

Only self-contained arithmetic routines are meant to be run here: there is no
hardware, no operating system and no heap behind them.

    emulator = Emulator(firmware_path, image_path)
    out = emulator.alloc(18)
    emulator.call("ColorMatchingService_MatrixMultiplication", out, a, b)
"""
import struct, sys
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UcError
from unicorn.mips_const import (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3, UC_MIPS_REG_SP,
                                UC_MIPS_REG_RA, UC_MIPS_REG_V0, UC_MIPS_REG_PC)
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from peek import Image, BASE

# kseg0 addresses (0x80000000..0x9fffffff) are the physical addresses with the top three bits cleared;
# the emulator's memory map is physical, so everything is mapped and accessed through physical().
RAM = 0x02000000                                 # 32 MiB from physical 0
SCRATCH, SCRATCH_SIZE = 0x81000000, 0x200000     # above the image and its work areas
STACK_TOP = SCRATCH + SCRATCH_SIZE - 0x1000
RETURN = SCRATCH + SCRATCH_SIZE - 0x100          # a mapped address that is never executed past


def physical(address):
    return address & 0x1FFFFFFF


class Emulator:
    def __init__(self, firmware, image):
        self.image = Image(firmware, image)
        self.uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        self.uc.mem_map(0, RAM)
        self.uc.mem_write(physical(BASE), self.image.memory)
        self.next = SCRATCH

    def alloc(self, size, data=b""):
        address = self.next
        self.next += (size + 15) & ~15
        self.uc.mem_write(physical(address), bytes(data).ljust(size, b"\0"))
        return address

    def write(self, address, fmt, *values):
        self.uc.mem_write(physical(address), struct.pack("<" + fmt, *values))

    def read(self, address, fmt):
        return struct.unpack("<" + fmt, bytes(self.uc.mem_read(physical(address), struct.calcsize("<" + fmt))))

    def address(self, name):
        return self.image.address[name]

    def call(self, function, *arguments, limit=20_000_000):
        entry = function if isinstance(function, int) else self.image.address[function]
        sp = STACK_TOP - 0x100
        for register, value in zip((UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3), arguments):
            self.uc.reg_write(register, value & 0xFFFFFFFF)
        for index, value in enumerate(arguments[4:], 4):          # o32: further arguments on the stack
            self.write(sp + 4 * index, "I", value & 0xFFFFFFFF)
        self.uc.reg_write(UC_MIPS_REG_SP, sp)
        self.uc.reg_write(UC_MIPS_REG_RA, RETURN)
        self.uc.emu_start(entry, RETURN, count=limit)
        if self.uc.reg_read(UC_MIPS_REG_PC) != RETURN:
            raise RuntimeError(f"{function}: did not return (pc={self.uc.reg_read(UC_MIPS_REG_PC):#x})")
        return self.uc.reg_read(UC_MIPS_REG_V0)


if __name__ == "__main__":
    e = Emulator(sys.argv[1], sys.argv[2])
    a = e.alloc(18, struct.pack("<9h", 9190, -57, -941, -18, 9296, -1086, -394, -647, 9233))
    b = e.alloc(18, struct.pack("<9h", 11243, -3459, 408, -2736, 12937, -2009, -2, -4343, 12537))
    out = e.alloc(18)
    e.call("ColorMatchingService_MatrixMultiplication", out, a, b)
    print(e.read(out, "9h"))
