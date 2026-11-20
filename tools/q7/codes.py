"""Symbol -> code bit strings implied by a block's lookup table.

Table entries are u32.  Bits 0-1: 3 = leaf, 0 = pointer to a direct table of 2^B slots starting
at `index`, 1 = pointer to a run-class table of B + A entries starting at `index` + 1.
Pointer: index = bits 2-10, B = bits 11-14, A = bits 15-18.  Entry 0 is the root pointer.
Run-class table: the first B entries are selected by the length of a leading run of one bit
value, the next A entries by the run of the other value; the longest run has no terminator.
Leaf: value = bits 2-11, k = bits 12-14 extra bits, bits 15 and up = code bits beyond the
table's shortest code + k (direct tables only).
"""
import sys, struct
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from blocks import blocks, PACKED

def bitstr(v, n):
    return format(v, f"0{n}b") if n else ""

def run_classes(b, a, first="0", zero_long_first=False, one_long_first=False):
    """Prefixes of the B + A classes, in table order."""
    other = "1" if first == "0" else "0"
    def group(n, bit, stop, long_first):
        prefixes = [bit * i + stop for i in range(1, n)] + [bit * n] if n else []
        return prefixes[::-1] if long_first else prefixes
    return group(b, first, other, zero_long_first) + group(a, other, first, one_long_first)

def enumerate_codes(table, **order):
    """Yield (leaf entry, code string, extra bits k)."""
    def walk(entry, prefix):
        if entry & 3 == 3:
            yield entry, prefix, (entry >> 12) & 7
            return
        b, a, index = (entry >> 11) & 0xf, (entry >> 15) & 0xf, (entry >> 2) & 0x1ff
        if entry & 1:
            for i, tail in enumerate(run_classes(b, a, **order)):
                if index + 1 + i < len(table):
                    yield from walk(table[index + 1 + i], prefix + tail)
        else:
            seen = set()
            for v in range(1 << b):
                leaf = table[index + v]
                if leaf & 3 != 3:
                    yield from walk(leaf, prefix + bitstr(v, b)); continue
                k = (leaf >> 12) & 7
                code = bitstr(v, b)[:a + (leaf >> 15) - k]
                if (leaf, code) not in seen:
                    seen.add((leaf, code)); yield leaf, prefix + code, k
    yield from walk(table[0], "")

if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    label, start, filesz, memsz = PACKED[0]
    pos, kind, out, size, t1, t2 = next(blocks(data, start, filesz))
    for name, off, n in (("literal/length", pos + 16, t1 // 4), ("distance", pos + 16 + t1, t2 // 4)):
        table = struct.unpack_from(f"<{n}I", data, off)
        codes = list(enumerate_codes(table))
        print(name, "codes", len(codes), "kraft", sum(2.0 ** -len(c) for _, c, _ in codes),
              "lengths", min(len(c) for _, c, _ in codes), "..", max(len(c) for _, c, _ in codes))
