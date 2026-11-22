"""Which white balance the Q7 uses for each Custom Image, and its preset table.

usage: white_balance.py firmware.bin image.bin        (image.bin: the memory image written by unpack.py)

Prints the white balance record of every Custom Image, the table that turns an effective
white balance mode into a calculation, and the preset entries, and checks them against the
preset list a Q7 DNG carries in its maker note.  Exits with an error if a check fails.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peek import Image

image = Image(sys.argv[1], sys.argv[2])
CUSTOM_IMAGES = ("Natural", "Vivid", "Portrait", "Landscape", "Miyabi", "Honoka", "Reversal", "BleachBypass", "PopTune",
                 "CrossProcess", "Monotone")
FIELDS = ("mode limitation", "mode", "inner mode limitation", "inner mode", "semi auto", "fine tune")

# Record of each Custom Image: m_arpcPictureArrangeParameter[id] -> picture mode -> record at +4.
# The fields are those the ImageTuningRelay_GetDefaultWhiteBalance... getters read (one byte every four).
records = {}
for mode_id, name in enumerate(CUSTOM_IMAGES):
    picture_mode, = image.read(image.address["m_arpcPictureArrangeParameter"] + 4 * mode_id, "I", 1)
    record, = image.read(picture_mode + 4, "I", 1)
    records[name] = image.names[record]
    values = image.read(record, "B", 24)[::4]
    print(f"{mode_id:2d} {name:13s} {image.names[record]:26s} " + ", ".join(f"{f} {v}" for f, v in zip(FIELDS, values)))
assert {name for name, record in records.items() if record != "cntWhiteBalanceRegular"} == {"Reversal"}
assert image.read(image.address["cntWhiteBalanceReversal"], "B", 16)[8::4] == (0, 1)       # inner mode 1, not limited to Auto

# CWhiteBalanceService_vCalclation: with Auto selected and "inner mode limitation" 0 the inner mode
# replaces Auto; the effective mode then indexes this jump table.
CASES = {0x80410480: "the automatic result", 0x804104ec: "manual", 0x80410544: "preset (bGainCalclationPreset)",
         0x80410584: "the CTE result", 0x804105a4: "stored gains"}
jumps = image.read(0x804a35f4, "I", 18)
for mode, target in enumerate(jumps):
    print(f"effective mode {mode:2d}: {CASES[target]}")
assert CASES[jumps[1]].startswith("preset") and CASES[jumps[0]] == "the automatic result"

# bGainCalclationPreset: jump table (mode -> preset entry and light categories; cases read from the code)
# and the entries (red, green, green, blue; the reference entry is Daylight).
ENTRY = {0x80376924: 0x803a1bd8, 0x80376914: 0x803a1c18, 0x80376904: 0x803a1c10, 0x803768f4: 0x803a1c08,
         0x803768e0: 0x803a1c00, 0x803768d0: 0x803a1bf8, 0x803766f8: 0x803a1be8, 0x803768ac: 0x803a1be0, 0x80376898: 0x803a1bf0}
cases = image.read(0x803a2588, "I", 16)
reference = image.read(0x803a1c28, "H", 4)
# Preset list of a Q7 DNG (maker note WB_RGGBLevels..., red and blue for green 8192), by internal mode.
DNG = {1: ("Daylight", 14363, 15300), 2: ("Shade", 17646, 11947), 3: ("Cloudy", 16552, 13624),
       4: ("Fluorescent D", 19117, 15091), 5: ("Fluorescent N", 16415, 17082), 6: ("Fluorescent W", 15321, 21169),
       7: ("Tungsten", 8755, 26829), 8: ("Flash", 17099, 12785), 15: ("Fluorescent L", 12858, 24628)}
for mode, (name, red, blue) in DNG.items():
    entry = image.read(ENTRY[cases[mode]], "H", 4)
    ratio = (entry[0] / reference[0], entry[3] / reference[3])
    want = (red / DNG[1][1], blue / DNG[1][2])
    print(f"preset mode {mode:2d} {name:13s} entry {entry}: red, blue over Daylight {ratio[0]:.4f} {ratio[1]:.4f}; DNG {want[0]:.4f} {want[1]:.4f}")
    assert abs(ratio[0] - want[0]) < 2e-4 and abs(ratio[1] - want[1]) < 2e-4, name
print("checks passed: only Reversal Film replaces Auto, by mode 1, and mode 1 is the Daylight preset")
