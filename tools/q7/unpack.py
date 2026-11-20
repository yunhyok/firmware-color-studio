"""Unpack the packed ELF segments of the Q7 firmware into one memory image.

usage: unpack.py firmware.bin output.bin
Writes the image of 0x80000600..0x80bec380 (boot, kernel and the four unpacked segments at
their load addresses; gaps are zero).  The output is derived from the firmware and must not be
committed.  Format notes are in codes.py and blocks.py; the stream is LZ77 with deflate's
length and distance alphabets and per-block prefix codes, read most significant bit first.
"""
import struct, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from blocks import blocks, PACKED
from codes import enumerate_codes
import symbols as S

BASE = 0x80000600

def unpack_segment(data, start, filesz):
    out = bytearray()
    for pos, kind, size_out, size, t1, t2 in blocks(data, start, filesz):
        if kind != 2:
            raise ValueError(f"block kind {kind} at {pos:#x}")
        lit = {c: (leaf, k) for leaf, c, k in enumerate_codes(struct.unpack_from(f"<{t1 // 4}I", data, pos + 16))}
        dist = {c: leaf for leaf, c, k in enumerate_codes(struct.unpack_from(f"<{t2 // 4}I", data, pos + 16 + t1))}
        lit_lengths = sorted({len(c) for c in lit}); dist_lengths = sorted({len(c) for c in dist})
        payload = data[pos + 16 + t1 + t2: pos + 16 + t1 + t2 + size]
        stream = "".join(format(b, "08b") for b in payload)
        p, end = 0, len(out) + size_out
        while len(out) < end:
            for n in lit_lengths:
                hit = lit.get(stream[p:p + n])
                if hit: break
            else:
                raise ValueError(f"no literal/length code at bit {p} of block {pos:#x}")
            p += n
            leaf, k = hit
            value = (leaf >> 2) & 0x3ff
            if value < 0x100:
                out.append(value); continue
            if value == 0x100:
                break
            length = value - 0x200
            if k:
                length += int(stream[p:p + k], 2); p += k
            for n in dist_lengths:
                leaf = dist.get(stream[p:p + n])
                if leaf: break
            else:
                raise ValueError(f"no distance code at bit {p} of block {pos:#x}")
            p += n
            code = (leaf >> 2) & 0x3ff
            if code < 4:
                distance = code + 1
            else:
                extra = code >> 2
                distance = ((2 | (code & 1)) << extra) + int(stream[p:p + extra], 2) + 1; p += extra
            if distance > len(out):
                raise ValueError(f"distance {distance} beyond {len(out)} bytes in block {pos:#x}")
            # The last match of a block may run past the block's output size; the output stops there.
            length = min(length, end - len(out))
            if distance >= length:
                out += out[-distance:len(out) - distance + length]
            else:
                for _ in range(length):
                    out.append(out[-distance])
        if len(out) != end:
            raise ValueError(f"block {pos:#x} gave {len(out) - end + size_out} of {size_out} bytes")
    return bytes(out)

def image(data):
    memory = bytearray(0x80bec380 - BASE)
    for label, off, vaddr, filesz, memsz in S.SEGMENTS:
        if label.startswith("packed"):
            chunk = unpack_segment(data, off, filesz)
            if len(chunk) != memsz:
                raise ValueError(f"{label}: {len(chunk):#x} bytes, expected {memsz:#x}")
        else:
            chunk = data[off:off + filesz]
        memory[vaddr - BASE: vaddr - BASE + len(chunk)] = chunk
        print(f"{label}: {len(chunk):#x} bytes at {vaddr:#x}", file=sys.stderr)
    return bytes(memory)

if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    memory = image(data)
    with open(sys.argv[2], "xb") as output:
        output.write(memory)
    # Functions named in the symbol table should begin with a stack adjustment where they have one.
    symbols = S.load(data)
    checked = hits = 0
    for address, name in symbols:
        if S.segment_of(address).startswith("packed") and name.startswith(("App", "Still", "Path", "Sensor")):
            word = memory[address - BASE: address - BASE + 4]
            checked += 1
            hits += word[1:] == b"\xff\xbd\x27"
    print(f"function symbols checked {checked}, starting with addiu sp,sp,-N: {hits}", file=sys.stderr)
