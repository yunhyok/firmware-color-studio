"""Walk the block chain of the packed ELF segments.

Each block: 16-byte header {u32 kind, u32 output bytes, u32 data bytes, u16 table1 bytes,
u16 table2 bytes}, table 1, table 2, data.  (From InflatingStreamSetupInputJob, 0x800fae80.)
"""
import sys, struct, collections
PACKED = [("A", 0x2402c0 + 0x54, 0x20bef0, 0x3f2300), ("B", 0x44c204 + 0x54, 0x182408, 0x2d2e00),
          ("C", 0x5ce660 + 0x74, 0x1800cc, 0x36ff80), ("C.data", 0x5ce660 + 0x180140, 0x2d82c, 0x89780)]

def blocks(data, start, filesz):
    pos, end = start, start + filesz
    while pos + 16 <= end:
        kind, out, size, t1, t2 = struct.unpack_from("<IIIHH", data, pos)
        if kind == 0 and out == 0 and size == 0:
            break
        yield pos, kind, out, size, t1, t2
        pos += 16 + t1 + t2 + size

if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    for label, start, filesz, memsz in PACKED:
        rows = list(blocks(data, start, filesz))
        total = sum(r[2] for r in rows)
        last = rows[-1]
        print(f"{label}: {len(rows)} blocks, output {total:#x} (memsz {memsz:#x}), kinds {dict(collections.Counter(r[1] for r in rows))}, "
              f"t1 sizes {sorted(set(r[4] for r in rows))[:6]}.., t2 sizes {sorted(set(r[5] for r in rows))[:6]}, "
              f"out sizes {sorted(set(r[2] for r in rows))[-3:]}, chain ends at +{last[0] + 16 + last[4] + last[5] + last[3] - start:#x} of {filesz:#x}")
        for r in rows[:3]:
            print("   block @%#x kind %d out %#x data %#x t1 %#x t2 %#x" % r)
