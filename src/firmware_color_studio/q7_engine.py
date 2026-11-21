"""The PENTAX Q7 colour parameter calculations, without the firmware.

The Q7 turns a Custom Image and its settings into a colour matrix, a gamma
table and a YC conversion matrix, as the K-3 Mark III does, with an older
form of the same tables.  This module repeats the integer calculations of
three firmware routines from the tables in data/q7/q7-color-tables.json:

    ColorMatchingService_MakeColorMatrix                      -> color_matrix, yc, chroma_offset
    GammaCorrectionService_CalcGammaCorrectionTable           -> gamma (regular)
    GammaCorrectionService_CalcGammaCorrectionTableReversal   -> gamma (Reversal Film)

    GammaCorrectionService_CalcBasicGammaCorrectionTable      -> basic_gamma
    ColorMatchingService_MakeColorReproductionLutParam        -> reproduction_table

tools/q7/check_port.py runs those routines in a CPU emulator and compares
every output value with this module.

What the camera does with the results differs from the K-3 Mark III: it does
not apply matrix and gamma as separate stages.  The image processor passes
white-balanced RGB through the basic gamma table and looks the result up in
a 9 x 9 x 9 table whose points hold
"gamma(dark chroma suppression(matrix x RGB))".  camera() hands both tables
to color_model, which interpolates between the points as the camera does.
See docs/research/q7-port.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .engine import SLIDERS

PACK_DIRECTORY = Path(__file__).resolve().parent / "data" / "q7"
TABLES = PACK_DIRECTORY / "q7-color-tables.json"
U32 = 0xFFFFFFFF

# Recipe key -> name of the Custom Image in the firmware's symbols.  The id in
# the first byte of its cntCustomImageUnit record selects the matrices.
MODES = {
    "natural": "Natural", "bright": "Vivid", "portrait": "Portrait", "landscape": "Landscape",
    "vibrant": "Miyabi", "radiant": "PopTune", "muted": "Honoka", "bleach-bypass": "BleachBypass",
    "reversal-film": "Reversal", "monochrome": "Monotone",
}
HUELESS_IDS = (5, 7)        # Muted and Bleach Bypass: toning colour in place of hue
REVERSAL_ID = 6
MONOCHROME_ID = 10
TONE_COLUMNS = (128, 256, 512, 1024, 2048)
# Settings word +0x174 in normal shooting; the firmware itself writes this value at 0x80428de4.
# It gives 0x400000 / 0x2000 = 512, the constant the K-3 Mark III has in the same place, and a
# Q7 photograph confirms it (docs/q7.md).  The routine's fallback for a zero word is 256.
NOMINAL_RATIO = 0x2000
TONING_NAMES = ["off", "green", "yellow", "orange", "red", "magenta", "purple", "blue", "cyan"]


def _s16(x):
    return ((x & 0xFFFF) ^ 0x8000) - 0x8000


def _s32(x):
    return ((x & U32) ^ 0x80000000) - 0x80000000


def _trunc_shift(x, bits):
    """Arithmetic shift that rounds towards zero."""
    x = _s32(x)
    return _s32(x + (1 << bits) - 1 if x < 0 else x) >> bits


def _product(left, right, shift=13):
    """3x3 product; logical shift after adding half, low 16 bits (0x8041bc90, 0x8041be94)."""
    half = 1 << (shift - 1)
    return [_s16(((sum(left[3 * row + k] * right[3 * k + col] for k in range(3)) + half) & U32) >> shift)
            for row in range(3) for col in range(3)]


def _blend(a, b, weight):
    return ((weight * a + (512 - weight) * b + 256) & U32) >> 9


class Q7Engine:
    def __init__(self, tables: dict):
        self.tables = {**tables, "toning": {"names": TONING_NAMES}}
        self._matrices = {name: record["values"] for name, record in tables["matrices_s16"].items()}
        self._tone = {name: record["values"] for name, record in tables["tone_u16"].items()}
        self._chroma = {name: record["values"] for name, record in tables["chroma_offsets_s16"].items()}
        constants = {name: record["values"][0] for name, record in tables["tone_constants_u16"].items()}
        self._saturation_point = constants["cnwBasicToneSaturationPointMin"]
        self._output_max = constants["cnwBasicToneSaturationPointOutput"]
        self._base_number = constants["cnwBasicToneBaseNumber"]
        self._key_table = tables["anonymous"]["key_table_u32"]["values"]
        self._reversal_bounds = tables["anonymous"]["reversal_bounds_u32"]["values"]
        self.modes = {}
        for mode, name in MODES.items():
            record = tables["custom_image_records_u8"][f"cntCustomImageUnit{name}"]["values"]
            mode_id = record[0]
            toning = mode_id in HUELESS_IDS
            adjustable = mode_id != REVERSAL_ID
            sliders = {
                "saturation": "slider" if adjustable and mode_id != MONOCHROME_ID else 0,
                "hue": "slider" if adjustable and not toning and mode_id != MONOCHROME_ID else 0,
                "key": "slider" if adjustable else 0,
                "contrast": "slider" if adjustable else 0,
                "highlight": 0,                 # the Q7 has no highlight and shadow settings
                "shadow": 0,
            }
            stored = {"saturation": record[1] - 4, "contrast": record[2] - 4, "key": record[4] - 4, "hue": record[5] - 4}
            self.modes[mode] = {
                "id": mode_id, "name": name, "sliders": sliders, "toning": toning,
                "gamma": "reversal" if mode_id == REVERSAL_ID else "regular",
                "filter_effect": record[6],
                "factory_settings": {
                    **{key: stored.get(key, 0) if sliders[key] == "slider" else None for key in SLIDERS},
                    "sharpness": record[3] - 4, "toning": record[8] if toning else None,
                },
            }

    @classmethod
    def load(cls, path: Path = TABLES) -> "Q7Engine":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- settings -----------------------------------------------------------------

    def settings(self, mode: str, **sliders) -> dict:
        """Menu settings (-4..+4) as the tuning code sees them in this Custom Image."""
        unknown = set(sliders) - set(SLIDERS)
        if unknown:
            raise ValueError(f"unknown settings: {sorted(unknown)}")
        effective = {}
        for name in SLIDERS:
            value = sliders.get(name, 0)
            if type(value) is not int or not -4 <= value <= 4:
                raise ValueError("settings must be integers within -4..+4")
            rule = self.modes[mode]["sliders"][name]
            effective[name] = value if rule == "slider" else rule
        return effective

    def factory_settings(self, mode: str) -> dict:
        """The settings as the camera ships them for this Custom Image (0 where it has no such setting)."""
        record = self.modes[mode]["factory_settings"]
        return {name: record[name] or 0 for name in SLIDERS}

    def factory_toning(self, mode: str) -> int:
        """Factory toning colour (0 = off) of Muted and Bleach Bypass; 0 for every other Custom Image."""
        return self.modes[mode]["factory_settings"]["toning"] or 0

    def chroma_offset(self, mode: str, toning: int = 0, color_space: str = "srgb") -> tuple:
        """Constant added to Cb and Cr for a toning colour 0..8 (1024 = full chroma range).

        The firmware stores these on a 12-bit scale (4096 = full range).
        """
        if type(toning) is not int or not 0 <= toning <= 8:
            raise ValueError("toning must be an integer within 0..8")
        if not self.modes[mode]["toning"]:
            return (0, 0)
        suffix = "AdobeRGB" if color_space == "adobergb" else ""
        return (self._chroma["cnarsCbAddition" + suffix][toning] / 4, self._chroma["cnarsCrAddition" + suffix][toning] / 4)

    # -- colour matrix (routine 0x8041c180) --------------------------------------------

    def color_matrix(self, mode: str, saturation: int = 0) -> list:
        """The colour matrix (signed, 1.0 = 256) that the three-dimensional table is built from.

        The firmware computes six, one per hue sector; in firmware 1.01 the six
        make-up matrices of every Custom Image are equal, so this is all of them.
        """
        entry = self.modes[mode]
        if entry["id"] == MONOCHROME_ID:
            selected = self._matrices[f'cnarsFilterEffectMatrix{entry["filter_effect"]:02d}']
        else:
            index = self.settings(mode, saturation=saturation)["saturation"] + 4
            selected = self._matrices[f"cnarsSatCtlMatrix{index:02d}"]
        look = self.tables["matrix_sets_6_s16"][f'cnsMakeUpMatrix{entry["name"]}6']["values"][:9]
        stage = _product(selected, look)
        values = [_s16(_trunc_shift(value, 5)) for value in _product(stage, self._matrices["cnsCameraBasicMatrix"])]
        for row in range(3):                     # each row sums to 256
            values[4 * row] = _s16(0x100 - sum(values[3 * row + col] for col in range(3) if col != row))
        return values

    # -- YC conversion (same routine) -----------------------------------------------------

    def yc(self, mode: str, hue: int = 0, adobe_rgb: bool = False) -> list:
        """YC conversion (signed, 1.0 = 256).  The register holds these values shifted left by 3."""
        index = self.settings(mode, hue=hue)["hue"] + 4
        ycbcr = self.tables["ycbcr_s16"]["arcnwYCbCrConversionMatrixDefault"]["values"]
        values = _product(self._matrices[f"cnsHueShiftMatrix{index:02d}"], ycbcr, 8)
        if adobe_rgb:
            values = _product(values, self._matrices["arcnsSRGBAdobeRGB"])
        return values

    # -- gamma table (routines 0x8041d058 and 0x8041cd28) -----------------------------------

    def gamma(self, mode: str, key: int = 0, contrast: int = 0, exposure_gain: int = 0x2000,
              ratio: int = NOMINAL_RATIO, step: int = 1) -> list:
        """The 4096-entry gamma table (maximum 4095) for a Custom Image and its tone settings.

        `exposure_gain` (0x2000 = 1.0) and `ratio` are run-time values of the
        camera; `step` is 4 for the firmware's coarse variant.
        """
        s = self.settings(mode, key=key, contrast=contrast)
        v = self._gain(s["key"], exposure_gain, ratio)
        if self.modes[mode]["gamma"] != "reversal":
            return self._register_table(self._tone_points(v, 2 * s["contrast"]), step)
        bounds = self._reversal_bounds
        v = max(bounds[0], min(bounds[-1], v))
        first = max(index for index, bound in enumerate(bounds) if v >= bound)
        second = min(first + 1, len(bounds) - 1)
        return self._register_table(
            self._meet(v, *(self._tone[f"cnarwReversalTone{bounds[index]}"] for index in (first, second))), step)

    def _gain(self, key, exposure_gain, ratio):
        """Tone gain `v` (256 = 1.0 of the tone columns); the reference grey goes to input 16 x (v // 16) of 4096."""
        scale = _trunc_shift(self._key_table[4 + key] * (0x400000 // ratio if ratio else 0x100), 8)
        return ((scale * exposure_gain) & U32) >> 13

    def _meet(self, v, left, right):
        """Mix two neighbouring tone curves so that point v // 16 is the reference grey (64 x 118)."""
        target = self._base_number * 118
        a, b = left[v // 16], right[v // 16]
        weight = 512 if a <= b else 0 if b >= target else ((target - b) << 9) // (a - b)
        return [_blend(p, q, weight) for p, q in zip(left, right)]

    def _tone_points(self, v, amount):
        """The 256 tone points for gain v and contrast amount -12..+12 (twice the menu step)."""
        v = max(TONE_COLUMNS[0], min(TONE_COLUMNS[-1], v))
        column = max(index for index, bound in enumerate(TONE_COLUMNS[:-1]) if v >= bound)
        amount = max(-12, min(12, amount))
        families = ("High", "Middle") if amount > 0 else ("Middle", "Low")
        weight = ((amount if amount > 0 else amount + 12) << 9) // 12
        return self._meet(v, *([_blend(a, b, weight) for a, b in zip(*(self._tone[f"cnarwBasicTone{TONE_COLUMNS[index]}{family}"]
                                                                       for family in families))]
                               for index in (column, column + 1)))

    def _register_table(self, points, step):
        """Tone points 0..128 scaled and interpolated into entries 0..2047; a straight line to 4095 above."""
        out = [0] * 4096
        previous = index = 0
        while index < 129:
            following = index + step
            value = points[min(following, 128)]
            delta = (value - previous) & U32
            for i in range(16 * step):
                position = 16 * index + i
                if position < 4096:
                    level = (((i * delta) & U32) // (16 * step) + previous) & U32
                    out[position] = self._code(level)
            previous, index = value, following
        start = out[2048]
        for i in range(2048):
            out[2048 + i] = (i * (0xFFF - start)) // 0x7FF + start
        return out

    def _code(self, level):
        return min(((self._output_max * level) & U32) // self._saturation_point, self._output_max)

    # -- basic gamma table (routine 0x8041d7e8) and the three-dimensional table (0x8041c7dc) --------

    def basic_gamma(self) -> list:
        """The 4096-entry table of the hardware gamma block; its output addresses the three-dimensional table.

        It does not depend on the Custom Image or its settings.  The routine is the K-3 Mark III's
        highlight and shadow contrast calculation with fixed amounts: contrast -2, highlight -3 above
        the reference grey and shadow -2 below it, joined with the same composition rates.  All 256
        tone points are used.  shortcut: ported for the nominal run-time gains only (v = 512);
        other gains need the rest of the routine.
        """
        v = self._gain(0, 0x2000, NOMINAL_RATIO)
        high, middle, low = (self._tone_points(v, amount) for amount in (-7, -4, -6))
        rate = self.tables["composition_rate_u16"]["cnwHighlightShadowCompositionRate2048"]["values"]
        points = []
        for k in range(256):
            x, y = 16 * k, middle[k]
            if x != v:
                other = high[k] if x > v else low[k]
                far = x >= 4 * v or x <= v // 4
                share = 2048 if far else rate[max(0, min(96, ((32 * x) // v if x > v else (32 * v) // x) - 32))]
                y = ((other * share + y * (2048 - share) + 1024) & U32) >> 11
            points.append(y)
        return [self._code(a + (i * (b - a)) // 16) for a, b in zip(points, points[1:] + points[-1:]) for i in range(16)]

    def table_inputs(self) -> list:
        """The nine 12-bit input levels of the table's points: where the basic gamma first reaches each level."""
        basic, levels = self.basic_gamma(), self.tables["anonymous"]["lut_node_levels_u16"]["values"]
        inputs, index = [], 0
        while len(inputs) < 9:                   # one table entry gives at most one point
            if index > 0xFFF or basic[index] >= levels[len(inputs)]:
                inputs.append(min(index, 0xFFF))
            index += 1
        return inputs[:8] + [0xFFF]

    def reproduction_table(self, mode: str, saturation: int = 0, key: int = 0, contrast: int = 0) -> np.ndarray:
        """The 9 x 9 x 9 table the camera interpolates: point [R][G][B] -> RGB codes 0..4095.

        Each point holds gamma(dark chroma suppression(colour matrix x RGB)).  Divisions round
        towards zero, as the firmware's do.
        """
        def shift(x, bits):
            return np.where(x < 0, -(-x >> bits), x >> bits)

        m = self.color_matrix(mode, saturation)
        rgb = np.stack(np.meshgrid(*[np.array(self.table_inputs(), dtype=np.int64)] * 3, indexing="ij"))
        r, g, b = (shift(sum(m[3 * row + col] * rgb[col] for col in range(3)), 8) for row in range(3))
        y = shift(306 * r + 601 * g + 117 * b, 10)
        cb, cr = shift(-173 * r - 339 * g + 512 * b, 10), shift(512 * r - 429 * g - 83 * b, 10)
        ratio = np.array(self.tables["chroma_suppression_u16"]["arwCChromaSuppressionRatioLut"]["values"],
                         dtype=np.int64)[np.clip(2 * (256 - g), 0, 2047)]
        cb, cr = (np.where(g <= 256, shift(c * ratio, 13), c) for c in (cb, cr))     # 1.0 down to 0.875 at black
        out = np.stack([shift(1024 * y + 1436 * cr, 10), shift(1024 * y - 352 * cb - 731 * cr, 10),
                        shift(1024 * y + 1815 * cb, 10)], axis=-1)
        return np.array(self.gamma(mode, key, contrast), dtype=np.int64)[np.clip(out, 0, 0xFFF)]

    # -- everything together --------------------------------------------------------------

    def camera(self, mode: str, color_space: str = "srgb", toning: int = 0, **sliders):
        """Colour parameters as a color_model.CameraColour."""
        from . import color_model as model

        if color_space not in model.RGB_SPACES:
            raise ValueError("color space must be srgb or adobergb")
        s = self.settings(mode, **sliders)
        curve = np.array(self.gamma(mode, s["key"], s["contrast"]), dtype=np.float64)
        return model.CameraColour(
            cc0=np.array(self.color_matrix(mode, s["saturation"]), dtype=np.float64).reshape(3, 3), cc0_unit=256.0,
            curves=np.stack([curve] * 3), curve_max=float(self._output_max),
            yc=np.array(self.yc(mode, s["hue"], color_space == "adobergb"), dtype=np.float64).reshape(3, 3),
            csp_enable=False, chroma_offset=self.chroma_offset(mode, toning, color_space),
            table=(np.array(self.basic_gamma(), dtype=np.float64),
                   self.reproduction_table(mode, s["saturation"], s["key"], s["contrast"]).astype(np.float64)),
            name=mode, space=color_space)

    def common_matrix(self) -> np.ndarray:
        """Sensor matrix shared by every Custom Image: white-balanced sensor RGB -> linear sRGB."""
        return np.array(self._matrices["cnsCameraBasicMatrix"], dtype=np.float64).reshape(3, 3) / 8192.0

    def dng_color_matrices(self) -> list:
        """ColorMatrix1 (illuminant A) and ColorMatrix2 (D65) as stored in the firmware for its DNG files."""
        out = []
        for name in ("arcnlDNGColorMatrix1", "arcnlDNGColorMatrix2"):
            pairs = self.tables["dng_color_matrix_s32_pairs"][name]["values"]
            out.append(np.array([pairs[2 * i] / pairs[2 * i + 1] for i in range(9)]).reshape(3, 3))
        return out
