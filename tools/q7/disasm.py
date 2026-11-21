"""Disassemble a function of the uncompressed kernel (or of an unpacked image) by name or address.

usage: disasm.py firmware.bin NAME|0xADDR [bytes]     (optional env Q7_IMAGE=unpacked.bin:0xBASE)
"""
import os, sys, struct
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import symbols as S

data = open(sys.argv[1], "rb").read()
syms = S.load(data)
by_addr = {}
for a, n in syms:
    by_addr.setdefault(a, n)
size = S.sizes(syms)
target = sys.argv[2]
addr = int(target, 16) if target.startswith("0x") else next(a for a, n in syms if n == target)
length = int(sys.argv[3], 0) if len(sys.argv) > 3 else size.get(addr, 256)

def read(address, n):
    image = os.environ.get("Q7_IMAGE")
    if image:
        path, base = image.rsplit(":", 1)
        base = int(base, 16)
        blob = open(path, "rb").read()
        if base <= address < base + len(blob):
            return blob[address - base: address - base + n]
    for label, off, vaddr, filesz, memsz in S.SEGMENTS:
        if vaddr <= address < vaddr + filesz and not label.startswith("packed"):
            return data[off + address - vaddr: off + address - vaddr + n]
    raise SystemExit(f"{address:#x} is not in a readable segment")

md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
code = read(addr, length)
print(f"; {by_addr.get(addr, '?')} @ {addr:#x}, {length} bytes")
for ins in md.disasm(code, addr):
    note = ""
    if ins.mnemonic in ("jal", "j", "b", "bal") or ins.mnemonic.startswith("b"):
        try:
            t = int(ins.op_str.split(",")[-1].strip(), 16)
            if t in by_addr: note = f"  ; {by_addr[t]}"
        except ValueError:
            pass
    print(f"{ins.address:08x}  {ins.mnemonic:8s} {ins.op_str}{note}")
