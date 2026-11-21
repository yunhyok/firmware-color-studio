import sys, re, struct, collections
data = open(sys.argv[1], "rb").read()
def hexdump(off, n=64):
    for i in range(off, off + n, 16):
        chunk = data[i:i+16]
        print(f"  {i:08x}  {chunk.hex(' ')}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)}")
for sig, name in ((b"\x7fELF", "ELF"), (b"\x1f\x8b\x08", "gzip"), (b"\x5d\x00\x00", "lzma?"), (b"PK\x03\x04", "zip"),
                  (b"\xff\xd8\xff", "jpeg"), (b"FAT16", "FAT16"), (b"FAT12", "FAT12"), (b"FAT32", "FAT32"),
                  (b"MSDOS", "MSDOS"), (b"\x55\xaa", "55aa"), (b"\x78\x9c", "zlib9c"), (b"\x78\xda", "zlibda"), (b"LZO", "LZO"),
                  (b"hsqs", "squashfs"), (b"UBI#", "ubi")):
    offs = [m.start() for m in re.finditer(re.escape(sig), data)]
    print(f"{name}: {len(offs)}", [hex(o) for o in offs[:10]])
# header region
print("header:"); hexdump(0, 0x40)
# look at boundaries
for off in (0x1f0, 0x200, 0x240000 - 0x40, 0x240000, 0x780000 - 0x40, 0x780000, 0xbc0000 - 0x20, 0xbc0000):
    print(f"@{off:#x}"); hexdump(off & ~15, 64)
# find the first offset where the name table begins: scan backwards from 0xc00000 for non-text
import string
text = set(string.printable.encode()) | {0}
i = 0xc00000
while i > 0 and data[i] in text: i -= 1
print("name table text run starts near", hex(i))
hexdump((i & ~15) - 32, 160)
