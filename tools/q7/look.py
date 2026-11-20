import sys, math, collections, re
data = open(sys.argv[1], "rb").read()
print("size", len(data), hex(len(data)))
def hexdump(off, n=96):
    for i in range(off, off + n, 16):
        chunk = data[i:i+16]
        print(f"{i:08x}  {chunk.hex(' ')}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)}")
hexdump(0, 160)
print("..."); hexdump(len(data) - 64, 64)
def entropy(b):
    c = collections.Counter(b); n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())
step = len(data) // 24
print("entropy per 1/24:", " ".join(f"{entropy(data[i:i+step]):.2f}" for i in range(0, len(data), step)))
strings = re.findall(rb"[\x20-\x7e]{6,}", data)
print("printable strings >=6:", len(strings)); print([s.decode() for s in strings[:40]])
print("byte histogram top:", collections.Counter(data).most_common(6))
