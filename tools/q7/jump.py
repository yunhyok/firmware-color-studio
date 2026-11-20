"""Resolve the 'lui/addiu v0' result of each case of a small jump-table getter.

usage: jump.py firmware.bin image.bin FUNCTION TABLE_ADDR COUNT
"""
import struct, sys
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from peek import Image, BASE

image = Image(sys.argv[1], sys.argv[2])
table, count = int(sys.argv[4], 16), int(sys.argv[5])
md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
for case, target in enumerate(image.read(table, "I", count)):
    code = image.memory[target - BASE: target - BASE + 16]
    hi = lo = None
    text = []
    for ins in md.disasm(code, target):
        text.append(f"{ins.mnemonic} {ins.op_str}")
        ops = [o.strip() for o in ins.op_str.split(",")]
        if ins.mnemonic == "lui":
            hi = int(ops[1], 16) << 16
        elif ins.mnemonic == "addiu" and hi is not None and lo is None and ops[1] != "$zero":
            lo = int(ops[2], 16)
        elif ins.mnemonic == "addiu" and ops[1] == "$zero":
            print(case, hex(target), "constant", ops[2]); break
        if hi is not None and lo is not None:
            address = (hi + lo) & 0xffffffff
            print(case, hex(target), hex(address), image.names.get(address, "?")); break
    else:
        print(case, hex(target), "; ".join(text))
