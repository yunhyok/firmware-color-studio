"""Export the colour tables of the Q7 firmware, by symbol name, to JSON (numbers only).

usage: export_tables.py firmware.bin image.bin output.json
Values are as stored.  Matrices are nine signed 16-bit values; tone tables are 256 unsigned
16-bit values; the DNG matrices are nine signed (numerator, denominator) pairs.
"""
import hashlib, json, re, struct, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from peek import Image, BASE

GROUPS = [
    ("matrices_s16", "h", 9, r"^(cnsCameraBasicMatrix(Inverse)?|cnsFlatMatrix|cnsMakeUpMatrix[A-Za-z]+|cnarsSatCtlMatrix\d\d|"
                              r"cnsHueShiftMatrix\d\d|cnsHueShiftDisableMatrix|cnarsFilterEffectMatrix\d\d|arsActualMatrix3DDefault|"
                              r"arcnsSRGBAdobeRGB)$"),
    ("matrix_sets_6_s16", "h", 54, r"^cnsMakeUpMatrix[A-Za-z]+6$"),
    ("tone_u16", "H", 256, r"^(cnarwBasicTone\d+(Low|Middle|High)|cnarwReversalTone\d+)$"),
    ("dng_color_matrix_s32_pairs", "i", 18, r"^arcnlDNGColorMatrix[12]$"),
    ("ycbcr_s16", "h", 9, r"^arcnwYCbCrConversionMatrixDefault$"),
    ("chroma_offsets_s16", "h", 9, r"^(cnars(Cb|Cr)(Offset|Addition)(AdobeRGB)?|cnarsCbCrOAdditionNon)$"),
    ("tone_constants_u16", "H", 1, r"^cnwBasicTone(SaturationPointMin|SaturationPointOutput|BaseNumber)$"),
    ("composition_rate_u16", "H", 97, r"^cnwHighlightShadowCompositionRate2048$"),
    ("custom_image_records_u8", "B", 28, r"^cntCustomImageUnit[A-Za-z0-9]+$"),
    ("chroma_suppression_u16", "H", 2048, r"^arwCChromaSuppressionRatioLut$"),
]
# Statics that have no symbol of their own: (label, preceding symbol, offset from it, format, count).
ANONYMOUS = [
    ("key_table_u32", "arcwXvdEvtoRatio256", 0x124, "I", 9),
    ("reversal_bounds_u32", "arcwXvdEvtoRatio256", 0x148, "I", 7),
    ("cm_base_matrix_s16", "arcnwYCbCrConversionMatrixDefault", 0x80, "h", 9),
    ("lut_node_levels_u16", "arcnwYCbCrConversionMatrixDefault", 0x94, "H", 9),
]

def main():
    image = Image(sys.argv[1], sys.argv[2])
    out = {
        "scope": "Colour tables read from PENTAX Q7 firmware by symbol name. Values as stored; how the firmware combines them is described in the research notes that accompany this file.",
        "firmware": {"file": "fwdc603p.bin", "sha256": hashlib.sha256(image.data).hexdigest()},
    }
    for group, fmt, count, pattern in GROUPS:
        table = {}
        for name, address in sorted(image.address.items(), key=lambda item: item[1]):
            if re.search(pattern, name):
                table[name] = {"address": f"{address:#010x}", "values": list(image.read(address, fmt, count))}
        out[group] = table
    out["anonymous"] = {}
    for label, symbol, offset, fmt, count in ANONYMOUS:
        address = image.address[symbol] + offset
        out["anonymous"][label] = {"after": symbol, "offset": offset, "address": f"{address:#010x}",
                                   "values": list(image.read(address, fmt, count))}
    with open(sys.argv[3], "x", encoding="utf-8", newline="\n") as output:   # the same bytes on every platform
        json.dump(out, output, indent=1, sort_keys=True)
        output.write("\n")
    print({group: len(out[group]) for group, *_ in GROUPS})

if __name__ == "__main__":
    main()
