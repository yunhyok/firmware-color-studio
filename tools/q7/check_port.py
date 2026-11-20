"""Compare q7port.py with the firmware routines run in the emulator.

usage: check_port.py firmware.bin image.bin tables.json
"""
import json, struct, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from emu import Emulator
import q7port as port

e = Emulator(sys.argv[1], sys.argv[2])
t = json.load(open(sys.argv[3]))
im = e.image
t["extra"] = {name: list(im.values(name, "h", 9)) for name in
              ("cnarsCbOffset", "cnarsCrOffset", "cnarsCbOffsetAdobeRGB", "cnarsCrOffsetAdobeRGB",
               "cnarsCbAddition", "cnarsCrAddition", "cnarsCbAdditionAdobeRGB", "cnarsCrAdditionAdobeRGB", "arcnsSRGBAdobeRGB")}

settings = e.alloc(0x400)
out_a, out_b, out6 = e.alloc(0x40), e.alloc(0x40), e.alloc(108)
table = e.alloc(0x2100)


def setup(**fields):
    e.uc.mem_write(settings & 0x1FFFFFFF, bytes(0x400))
    layout = {"mode": (0x34, "B"), "saturation": (0x35, "B"), "contrast": (0x36, "B"), "key": (0x38, "B"), "hue": (0x39, "B"),
              "filter": (0x3A, "B"), "mono_toning": (0x3B, "B"), "toning": (0x3C, "B"), "exposure": (0x164, "I"),
              "ratio": (0x174, "I"), "gain": (0x178, "I"), "flag": (0x1A0, "B"), "space": (0x1FC, "I"), "sensitivity": (0x200, "I")}
    base = dict(mode=0, saturation=4, contrast=4, key=4, hue=4, filter=4, mono_toning=4, toning=0, exposure=0x2000, ratio=0,
                gain=0x2000, flag=0, space=0, sensitivity=2)
    base.update(fields)
    for name, value in base.items():
        offset, fmt = layout[name]
        e.write(settings + offset, fmt, value)


bad = total = 0
for mode in range(11):
    for saturation in range(9):
        for hue in (range(9) if saturation == 4 else (4,)):
            for space in (0, 1):
                for extra in ((0, 4), (3, 1), (8, 8)) if mode in (5, 7, 10) else ((0, 4),):
                    toning, mono = extra
                    setup(mode=mode, saturation=saturation, hue=hue, space=space, toning=toning, mono_toning=mono, filter=saturation)
                    work = e.call("ColorMatchingService_MakeColorMatrix", settings, 0, out_a, out_b, out6)
                    got6 = [list(e.read(out6 + 18 * i, "9h")) for i in range(6)]
                    got_cm = list(e.read(out_a + 0x18, "9h")); got_yc = list(e.read(out_b + 0x18, "9h"))
                    got_off = tuple(v - 0x800 for v in e.read(out_b + 0x2A, "2H")); got_work = list(e.read(work, "9h"))
                    want6, want_work = port.color_matrices(t, mode, saturation, saturation)
                    want = (want6, port.cm_matrix(), port.yc_matrix(t, mode, hue, space == 1),
                            port.chroma_offsets(t, mode, toning, mono, space == 1), want_work)
                    total += 1
                    if (got6, got_cm, got_yc, got_off, got_work) != want:
                        bad += 1
                        if bad <= 5:
                            print("MISMATCH", mode, saturation, hue, space, toning, mono)
                            for g, w in zip((got6, got_cm, got_yc, got_off, got_work), want):
                                if g != w: print("   got ", g, "\n   want", w)
print(f"MakeColorMatrix: {total - bad}/{total} settings identical")

for gain, sensitivity in ((0x2000, 0), (0x2000, 1), (0x2000, 3), (0x2000, 4), (0x1800, 2), (0x3000, 3), (0x1234, 1)):
    setup(gain=gain, sensitivity=sensitivity)
    e.call("ColorMatchingService_MakeColorMatrix", settings, 0, out_a, out_b, out6)
    got = list(e.read(out_a + 0x18, "9h"))
    print("CM gain", hex(gain), sensitivity, "OK" if got == port.cm_matrix(gain, sensitivity) else f"MISMATCH {got} {port.cm_matrix(gain, sensitivity)}")

bad = total = 0
cases = [(key, contrast, 0x2000, 0, 0) for key in range(9) for contrast in range(9)]
cases += [(4, 4, exposure, 0, 0) for exposure in (0x800, 0x1000, 0x1555, 0x1800, 0x2abc, 0x3000, 0x4000, 0x8000, 0x10000, 0x20000)]
cases += [(key, contrast, exposure, ratio, flag) for key in (0, 3, 8) for contrast in (0, 5, 8) for exposure in (0x1700, 0x2000, 0x5000)
          for ratio in (0, 0x2000, 0x4000, 0x6000) for flag in (0, 1)]
cases += [(0xFF, 0xFF, 0x2000, 0, 0)]
for key, contrast, exposure, ratio, flag in cases:
    setup(key=key, contrast=contrast, exposure=exposure, ratio=ratio, flag=flag)
    e.uc.mem_write(table & 0x1FFFFFFF, bytes(0x2100))
    e.call("GammaCorrectionService_CalcGammaCorrectionTable", settings, 0, table)
    got = list(e.read(table, "4096H"))
    after = e.read(table + 0x2000, "32H")
    want = port.gamma(t, 4 if key == 0xFF else key, 4 if contrast == 0xFF else contrast, exposure, ratio, 4 if flag else 1)
    total += 1
    if got != want or any(after):
        bad += 1
        if bad <= 5:
            diff = [i for i in range(4096) if got[i] != want[i]]
            print("GAMMA MISMATCH", key, contrast, hex(exposure), hex(ratio), flag, len(diff), diff[:8], [(got[i], want[i]) for i in diff[:8]], any(after))
print(f"CalcGammaCorrectionTable: {total - bad}/{total} settings identical")
