"""Compare firmware_color_studio.q7_engine with the firmware routines run in a CPU emulator.

usage: check_port.py firmware.bin image.bin        (image.bin: the memory image written by unpack.py)

Every output value of the three routines is compared for every Custom Image and setting that
the engine offers, and for run-time gains outside the nominal ones.  Needs unicorn.
"""
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from emu import Emulator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from firmware_color_studio.q7_engine import Q7Engine

emulator = Emulator(sys.argv[1], sys.argv[2])
engine = Q7Engine.load()
settings = emulator.alloc(0x400)
out_a, out_b, out6, table = emulator.alloc(0x40), emulator.alloc(0x40), emulator.alloc(108), emulator.alloc(0x2100)
LAYOUT = {"mode": (0x34, "B"), "saturation": (0x35, "B"), "contrast": (0x36, "B"), "key": (0x38, "B"), "hue": (0x39, "B"),
          "filter": (0x3A, "B"), "mono_toning": (0x3B, "B"), "toning": (0x3C, "B"), "exposure": (0x164, "I"),
          "ratio": (0x174, "I"), "gain": (0x178, "I"), "coarse": (0x1A0, "B"), "space": (0x1FC, "I"), "sensitivity": (0x200, "I")}


def setup(**fields):
    emulator.write(settings, "1024x")
    values = dict(mode=0, saturation=4, contrast=4, key=4, hue=4, filter=0, mono_toning=4, toning=0, exposure=0x2000, ratio=0,
                  gain=0x2000, coarse=0, space=0, sensitivity=2)
    values.update(fields)
    for name, value in values.items():
        offset, fmt = LAYOUT[name]
        emulator.write(settings + offset, fmt, value)


def report(label, bad, total):
    print(f"{label}: {total - bad}/{total} settings identical")
    return bad


failures = 0
bad = total = 0
for mode, entry in engine.modes.items():
    rule = entry["sliders"]
    for saturation in (range(-4, 5) if rule["saturation"] == "slider" else (0,)):
        for hue in (range(-4, 5) if rule["hue"] == "slider" and saturation == 0 else (0,)):
            for space in ("srgb", "adobergb"):
                for toning in (range(9) if entry["toning"] and saturation == 0 else (0,)):
                    setup(mode=entry["id"], saturation=saturation + 4, hue=hue + 4, space=space == "adobergb", toning=toning,
                          filter=entry["filter_effect"])
                    emulator.call("ColorMatchingService_MakeColorMatrix", settings, 0, out_a, out_b, out6)
                    six = [list(emulator.read(out6 + 18 * i, "9h")) for i in range(6)]
                    cm = list(emulator.read(out_a + 0x18, "9h"))
                    fc1 = list(emulator.read(out_b + 0x18, "9h"))
                    offsets = tuple((value - 0x800) / 4 for value in emulator.read(out_b + 0x2A, "2H"))
                    want = engine.color_matrix(mode, saturation)
                    total += 1
                    if (six != [want] * 6 or cm != [256, 0, 0, 0, 256, 0, 0, 0, 256]
                            or fc1 != [value << 3 for value in engine.yc(mode, hue, space == "adobergb")]
                            or offsets != engine.chroma_offset(mode, toning, space)):
                        bad += 1
                        print("MISMATCH colour", mode, saturation, hue, space, toning)
failures += report("MakeColorMatrix (six colour matrices, CM, FC1, chroma offsets)", bad, total)

bad = total = 0
for mode, entry in engine.modes.items():
    rule = entry["sliders"]
    cases = [(key, contrast, 0x2000, 0, 1) for key in (range(-4, 5) if rule["key"] == "slider" else (0,))
             for contrast in (range(-4, 5) if rule["contrast"] == "slider" else (0,))]
    if mode in ("natural", "reversal-film"):
        cases += [(0, 0, exposure, ratio, step) for exposure in (0x400, 0x800, 0x1000, 0x16A0, 0x1800, 0x2ABC, 0x2D41, 0x4000,
                                                                0x5A82, 0x8000, 0x10000)
                  for ratio in (0, 0x2000, 0x4000, 0x5555) for step in (1, 4)]
    routine = "GammaCorrectionService_CalcGammaCorrectionTable" + ("Reversal" if entry["gamma"] == "reversal" else "")
    for key, contrast, exposure, ratio, step in cases:
        setup(mode=entry["id"], key=key + 4, contrast=contrast + 4, exposure=exposure, ratio=ratio, coarse=step == 4)
        emulator.write(table, f"{0x2100}x")
        emulator.call(routine, settings, 0, table)
        total += 1
        if list(emulator.read(table, "4096H")) != engine.gamma(mode, key, contrast, exposure, ratio, step) \
                or any(emulator.read(table + 0x2000, "32H")):
            bad += 1
            print("MISMATCH gamma", mode, key, contrast, hex(exposure), hex(ratio), step)
failures += report("CalcGammaCorrectionTable and ...Reversal (4096 entries each)", bad, total)
sys.exit(1 if failures else 0)
