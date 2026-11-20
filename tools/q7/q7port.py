"""Python port of the Q7 colour parameter routines, checked against the emulated firmware by check_port.py."""
U32 = 0xFFFFFFFF
MODES = ("Natural", "Vivid", "Portrait", "Landscape", "Miyabi", "Honoka", "Reversal", "BleachBypass", "PopTune",
         "Vivid", "Monotone")
KEY_TABLE = (512, 431, 362, 304, 256, 215, 181, 152, 128)
SENSITIVITY = (0x80, 0xB5, 0x100, 0x16A, 0x200)


def s16(x):
    return ((x & 0xFFFF) ^ 0x8000) - 0x8000


def s32(x):
    return ((x & U32) ^ 0x80000000) - 0x80000000


def trunc_shift(x, bits):
    """Arithmetic shift that rounds towards zero, as 'addiu; slti; movn; sra' does."""
    x = s32(x)
    return s32(x + (1 << bits) - 1 if x < 0 else x) >> bits


def product(left, right, shift=13):
    half = 1 << (shift - 1)
    return [s16(((sum(left[3 * i + k] * right[3 * k + j] for k in range(3)) + half) & U32) >> shift)
            for i in range(3) for j in range(3)]


def color_matrices(t, mode, saturation=4, filter_effect=4):
    """Six register matrices (1.0 = 256) and the returned saturation x make-up product."""
    name = MODES[mode]
    look6 = t["matrix_sets_6_s16"][f"cnsMakeUpMatrix{name}6"]["values"]
    m = t["matrices_s16"]
    selected = (m[f"cnarsFilterEffectMatrix{filter_effect:02d}"] if mode == 10 else m[f"cnarsSatCtlMatrix{saturation:02d}"])["values"]
    camera = m["cnsCameraBasicMatrix"]["values"]
    out = []
    for index in range(6):
        stage = product(selected, look6[9 * index: 9 * index + 9])
        values = [s16(trunc_shift(v, 5)) for v in product(stage, camera)]
        for row in range(3):
            values[4 * row] = s16(0x100 - sum(values[3 * row + col] for col in range(3) if col != row))
        out.append(values)
    return out, product(selected, m[f"cnsMakeUpMatrix{name}"]["values"])


def yc_matrix(t, mode, hue=4, adobe=False):
    """FC1 register matrix (1.0 = 2048)."""
    m = t["matrices_s16"]
    index = 4 if mode in (5, 7) else hue
    values = product(m[f"cnsHueShiftMatrix{index:02d}"]["values"], t["ycbcr_s16"]["arcnwYCbCrConversionMatrixDefault"]["values"], 8)
    if adobe:
        values = product(values, t["extra"]["arcnsSRGBAdobeRGB"])
    return [s16(v << 3) for v in values]


def chroma_offsets(t, mode, toning=0, mono_toning=4, adobe=False):
    e = t["extra"]
    suffix = "AdobeRGB" if adobe else ""
    if mode == 10:
        return e["cnarsCbOffset" + suffix][mono_toning], e["cnarsCrOffset" + suffix][mono_toning]
    if mode in (5, 7):
        return e["cnarsCbAddition" + suffix][toning], e["cnarsCrAddition" + suffix][toning]
    return 0, 0


def cm_matrix(gain=0x2000, sensitivity=2):
    """CM register matrix before white balance (1.0 = 256): the identity scaled by the development gain."""
    g = trunc_shift(gain * SENSITIVITY[sensitivity], 8)
    return [max(-0x7FF, min(0x7FF, s16(trunc_shift(v * g, 13)))) for v in (256, 0, 0, 0, 256, 0, 0, 0, 256)]


def gamma(t, key=4, contrast=4, exposure=0x2000, ratio=0, step=1):
    """The 4096-entry gamma table (maximum 4095) of GammaCorrectionService_CalcGammaCorrectionTable."""
    tone = t["tone_u16"]
    families = [[tone[f"cnarwBasicTone{c}{f}"]["values"] for c in (128, 256, 512, 1024, 2048)] for f in ("High", "Middle", "Low")]
    saturation, maximum, base = 16130, 4095, 64
    scale = trunc_shift(KEY_TABLE[key] * (0x400000 // ratio if ratio else 0x100), 8)
    v = max(0x80, min(0x800, ((scale * exposure) & U32) >> 13))
    column = 3 if v >= 1024 else 2 if v >= 512 else 1 if v >= 256 else 0
    j = v // 16
    target = base * 118
    c = max(-12, min(12, 2 * (contrast - 4)))
    if c > 0:
        first, second, weight = 0, 1, (c << 9) // 12
    else:
        first, second, weight = 1, 2, ((c + 12) << 9) // 12

    def blend(a, b, w):
        return ((w * a + (512 - w) * b + 256) & U32) >> 9

    left = [blend(a, b, weight) for a, b in zip(families[first][column], families[second][column])]
    right = [blend(a, b, weight) for a, b in zip(families[first][column + 1], families[second][column + 1])]
    a, b = left[j], right[j]
    w = 512 if a <= b else 0 if b >= target else ((target - b) << 9) // (a - b)
    points = [blend(p, q, w) for p, q in zip(left, right)]
    out = [0] * 4096
    previous = 0
    index = 0
    while index < 129:
        nxt = index + step
        y = points[min(nxt, 128)]
        delta = (y - previous) & U32
        for i in range(16 * step):
            value = (((i * delta) & U32) // (16 * step) + previous) & U32
            position = 16 * index + i
            if position < 4096:
                out[position] = min(((maximum * value) & U32) // saturation, maximum)
        previous = y
        index = nxt
    start = out[2048]
    for i in range(2048):
        out[2048 + i] = (i * (0xFFF - start)) // 0x7FF + start
    return out
