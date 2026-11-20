"""The firmware's sorted symbol table (address, name): 122,154 records with full names.

Three files of the embedded FAT16 resource volume hold it (as found by the
pentax-q7-firmware-analysis project): MAINSO~3.ADR, u32 addresses at 0xafa6c0;
MAINSO~5.OFT, u32 name offsets at 0xb71ec0; MAINSO~7.STR, NUL-terminated names at 0xbe96c0.
`segment_of` names the ELF segment an address is in.

usage: symbols.py firmware.bin [regex ...]
"""
import sys, re, struct, collections, bisect

COUNT, ADDRESSES, OFFSETS, NAMES = 122154, 0xafa6c0, 0xb71ec0, 0xbe96c0
# (label, file offset of the segment data, vaddr, file size, memory size)
SEGMENTS = [
    ("boot", 0x1026c0 + 0x254, 0x80000600, 0x154, 0x154),
    ("kernel", 0x1026c0 + 0x3a8, 0x80000780, 0x12d0b8, 0x12d0b8),
    ("packedA", 0x2402c0 + 0x54, 0x8012da80, 0x20bef0, 0x3f2300),
    ("packedB", 0x44c204 + 0x54, 0x8051fe00, 0x182408, 0x2d2e00),
    ("packedC", 0x5ce660 + 0x74, 0x807f2c80, 0x1800cc, 0x36ff80),
    ("packedC.data", 0x5ce660 + 0x180140, 0x80b62c00, 0x2d82c, 0x89780),
]

def load(data):
    addresses = struct.unpack_from(f"<{COUNT}I", data, ADDRESSES)
    offsets = struct.unpack_from(f"<{COUNT}I", data, OFFSETS)
    out = []
    for address, offset in zip(addresses, offsets):
        end = data.index(b"\0", NAMES + offset)
        out.append((address, data[NAMES + offset:end].decode("latin-1")))
    return out

def segment_of(address):
    for label, _, vaddr, _, memsz in SEGMENTS:
        if vaddr <= address < vaddr + memsz:
            return label
    return "ram/other"

def sizes(symbols):
    """Distance to the next different address: an upper bound of each symbol's size."""
    addresses = sorted({a for a, _ in symbols})
    nxt = {a: b for a, b in zip(addresses, addresses[1:])}
    return {a: nxt.get(a, a) - a for a in addresses}

if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    symbols = load(data)
    size = sizes(symbols)
    print("symbols:", len(symbols), "sorted:", all(a <= b for (a, _), (b, _) in zip(symbols, symbols[1:])))
    print("by segment:", dict(collections.Counter(segment_of(a) for a, _ in symbols)))
    for rx in sys.argv[2:]:
        hits = [(a, n) for a, n in symbols if re.search(rx, n)]
        print(f"--- /{rx}/ {len(hits)}")
        for a, n in hits[:80]:
            print(f"  {a:#010x} +{size[a]:<7d} {segment_of(a):12s} {n}")
