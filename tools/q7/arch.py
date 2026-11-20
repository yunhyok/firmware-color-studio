import sys, math, collections, re, struct
data = open(sys.argv[1], "rb").read()
pats = {
    "MIPS LE jr ra (08 00 e0 03)": bytes.fromhex("0800e003"),
    "MIPS BE jr ra (03 e0 00 08)": bytes.fromhex("03e00008"),
    "MIPS LE addiu sp (.. ff bd 27)": None,
    "ARM bx lr (1e ff 2f e1)": bytes.fromhex("1eff2fe1"),
    "ARM BE bx lr": bytes.fromhex("e12fff1e"),
    "Thumb bx lr (70 47)": bytes.fromhex("7047"),
    "ARM push {..lr} (.. .. 2d e9)": None,
}
for name, p in pats.items():
    if p is not None:
        print(f"{name}: {data.count(p)}")
print("MIPS LE addiu sp,sp,-N:", len(re.findall(rb"[\x80-\xff]\xff\xbd\x27", data)))
print("MIPS BE addiu sp,sp,-N:", len(re.findall(rb"\x27\xbd\xff[\x80-\xff]", data)))
print("ARM LE stmfd sp!:", len(re.findall(rb"..\x2d\xe9", data, re.S)))
# where do they cluster (per 1 MiB)
def clusters(rx):
    hist = collections.Counter(m.start() >> 20 for m in re.finditer(rx, data, re.S))
    return " ".join(f"{k}:{v}" for k, v in sorted(hist.items()))
print("jr ra LE per MiB:", clusters(rb"\x08\x00\xe0\x03"))
print("addiu sp LE per MiB:", clusters(rb"[\x80-\xff]\xff\xbd\x27"))
# entropy map per 256 KiB
def entropy(b):
    c = collections.Counter(b); n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())
step = 1 << 18
print("entropy/256KiB:", " ".join(f"{entropy(data[i:i+step]):.1f}" for i in range(0, len(data), step)))
# header words
print("header LE32:", [hex(x) for x in struct.unpack_from("<16I", data, 0)])
# long ASCII strings (likely real text)
strings = [(m.start(), m.group().decode()) for m in re.finditer(rb"[\x20-\x7e]{12,}", data)]
print("strings>=12:", len(strings))
for off, s in strings[:25]: print(f"  {off:08x} {s[:90]}")
import random; random.seed(1)
for off, s in random.sample(strings, 40): print(f"  {off:08x} {s[:90]}")
