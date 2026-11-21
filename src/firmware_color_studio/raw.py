"""Native Pentax K-3 Mark III (PEF, DNG) and Q7 (DNG) Bayer RAW input for the firmware color pipeline."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from math import isfinite, log2, prod
from pathlib import Path

import numpy as np
import rawpy


# TIFF Model -> what a native file of that camera looks like (maker note model id: ExifTool PentaxModelID).
_CAMERAS = {
    "PENTAX K-3 Mark III": {"camera_id": "pentax-k3iii", "sensor": (6304, 4224), "bits": 14, "model_id": 0x13254,
                            "software": r"PENTAX K-3 Mark III Ver\. \d+\.\d+"},
    "PENTAX Q7": {"camera_id": "pentax-q7", "sensor": (4064, 3000), "bits": 12, "model_id": 0x12F7A,
                  "software": r"PENTAX Q7 +Ver \d+\.\d+"},
}
_ACTIVE_AREA = (34, 26, 4194, 6250)
# Native DNG #4678 and the lossless conversion of the matching-geometry PEF
# independently record this ActiveArea-relative crop.
# See upstream analysis/lightroom-model-exports.html and lightroom-pef-neutral.html.
# shortcut: use the full-frame PEF crop until capture crop-mode metadata is verified.
_PEF_CROP = (28, 24, 6192, 4128)
# Adobe DNG Converter 18.7 writes -3/10 for this PEF model across metadata controls.
# The firmware estimate remains in metadata for camera-render comparisons.
_PEF_ADOBE_BASELINE_EXPOSURE = -0.3
_PEF_ADOBE_WHITE_LEVEL_CAP = 16315
_IMAGE_TONES = (
    "natural", "bright", "portrait", "landscape", "vibrant", "monochrome",
    "muted", "reversal-film", "bleach-bypass", "radiant", "cross-processing",
    "flat", "satobi", "harubeni", "katen", "kyushu", "fuyuno", "gold",
)
_SETTINGS = ("saturation", "hue", "key", "contrast", "highlight", "shadow")
# Menu steps of the Q7's Saturation, Contrast and Hue tags (ExifTool Pentax.pm, tags 0x001f, 0x0020, 0x0067).
_Q7_STEPS = {0: -2, 1: 0, 2: 2, 3: -1, 4: 1, 5: -3, 6: 3, 7: -4, 8: 4, 65535: 0}
_TIFF_TYPES = {1: "B", 3: "H", 4: "I", 5: "II", 8: "h", 10: "ii", 13: "I"}
_TAG_NAMES = {
    0x007E: "Pentax WhiteLevel", 0x009D: "Pentax exposure gain", 0x0200: "Pentax BlackPoint",
    0x0201: "Pentax as-shot WhitePoint", 50714: "DNG BlackLevel", 50717: "DNG WhiteLevel",
    50719: "DNG DefaultCropOrigin", 50720: "DNG DefaultCropSize", 50728: "DNG AsShotNeutral",
    50730: "DNG BaselineExposure", 50829: "DNG ActiveArea",
}
_TONING_MODES = {"muted", "bleach-bypass", "harubeni"}


@dataclass
class RawImage:
    """Half-resolution, oriented, white-balanced camera RGB and its unapplied preview EV."""

    rgb: np.ndarray
    baseline_exposure: float
    metadata: dict
    warnings: list[str]


@dataclass
class _Field:
    kind: int
    count: int
    value: bytes
    inline_offset: int


class _Tiff:
    """Read selected classic-TIFF fields without reading the image data."""

    def __init__(self, stream, start=0, length=None):
        self.stream = stream
        self.start = start
        self.length = stream.seek(0, 2) if length is None else length
        self.order = "<"

    def read(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.length:
            raise ValueError("TIFF metadata points outside its containing data")
        self.stream.seek(self.start + offset)
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError("Truncated TIFF metadata")
        return data

    def endian(self, value):
        if value not in (b"II", b"MM"):
            raise ValueError("Invalid TIFF byte order")
        self.order = "<" if value == b"II" else ">"

    def root(self):
        header = self.read(0, 8)
        self.endian(header[:2])
        magic, first = struct.unpack(self.order + "HI", header[2:])
        if magic != 42 or first < 8:
            raise ValueError("Expected a classic TIFF PEF or DNG header")
        return first

    def ifd(self, offset):
        count, = struct.unpack(self.order + "H", self.read(offset, 2))
        if not 0 < count <= 512:
            raise ValueError("Invalid TIFF directory entry count")
        data = self.read(offset + 2, count * 12 + 4)
        fields = {}
        for i, (tag, kind, size, value) in enumerate(
            struct.iter_unpack(self.order + "HHI4s", data[:-4])
        ):
            if tag in fields:
                raise ValueError(f"Duplicate TIFF tag 0x{tag:04x}")
            fields[tag] = _Field(kind, size, value, offset + 10 + i * 12)
        return fields, struct.unpack(self.order + "I", data[-4:])[0]

    def offset(self, field, size):
        offset = field.inline_offset
        if size > 4:
            offset, = struct.unpack(self.order + "I", field.value)
        if offset < 8 or offset + size > self.length:
            raise ValueError("TIFF metadata points outside its containing data")
        return offset

    def field(self, fields, tag, kinds, counts, optional):
        field = fields.get(tag)
        if field is None and optional:
            return None
        label = _TAG_NAMES.get(tag, f"TIFF tag 0x{tag:04x}")
        if field is None:
            raise ValueError(f"Missing {label}")
        if field.kind not in kinds or field.count not in counts:
            raise ValueError(f"Invalid type or count for {label}")
        return field

    def blob(self, fields, tag, kinds, counts, optional=False):
        field = self.field(fields, tag, kinds, counts, optional)
        if field is None:
            return None
        return self.read(self.offset(field, field.count), field.count)

    def numbers(self, fields, tag, kinds, counts=(1,), optional=False):
        field = self.field(fields, tag, kinds, counts, optional)
        if field is None:
            return None
        fmt = self.order + _TIFF_TYPES[field.kind]
        size = field.count * struct.calcsize(fmt)
        data = self.read(self.offset(field, size), size)
        values = tuple(struct.iter_unpack(fmt, data))
        if field.kind in (5, 10):
            if any(den == 0 for _, den in values):
                raise ValueError(f"Zero denominator in TIFF tag 0x{tag:04x}")
            return tuple(num / den for num, den in values)
        return tuple(value for value, in values)

    def scalar(self, fields, tag, kinds=(3, 4), optional=False):
        values = self.numbers(fields, tag, kinds, optional=optional)
        return values[0] if values is not None else None

    def string(self, fields, tag):
        value = self.blob(fields, tag, (2,), range(2, 256))
        try:
            return value.split(b"\0", 1)[0].decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ValueError(f"Invalid ASCII in TIFF tag 0x{tag:04x}") from exc


def _directories(reader):
    pending = [reader.root()]
    visited = set()
    while pending:
        offset = pending.pop()
        if offset < 8 or offset in visited or len(visited) >= 16:
            raise ValueError("Invalid or repeated RAW TIFF directory pointer")
        visited.add(offset)
        fields, sibling = reader.ifd(offset)
        yield fields
        children = reader.numbers(fields, 330, (4, 13), range(1, 9), optional=True)
        if sibling:
            pending.append(sibling)
        pending.extend(children or ())


def _identify(reader):
    directories = _directories(reader)
    first = next(directories)
    name = reader.string(first, 272)
    model = next((known for known in _CAMERAS if known.casefold() == name.casefold()), None)
    if model is None:
        raise ValueError(f"Unsupported camera model {name!r}; expected a {' or '.join(_CAMERAS)} color body")
    version = reader.blob(first, 50706, (1,), (4,), optional=True)
    if version is not None:
        if version[0] != 1:
            raise ValueError("Unsupported DNG version")
        if reader.string(first, 50708).casefold() != model.casefold():
            raise ValueError(f"DNG UniqueCameraModel differs from the {model} color body")

    image_dirs = [first, *directories]
    photometrics = [reader.scalar(fields, 262, (3,), optional=True) for fields in image_dirs]
    if 34892 in photometrics:
        raise ValueError("Linear DNG is unsupported; a single Bayer RAW is required")
    mosaics = [fields for fields, photo in zip(image_dirs, photometrics) if photo == 32803]
    if len(mosaics) != 1 or reader.scalar(mosaics[0], 277, (3,)) != 1:
        raise ValueError("Expected a single-sample Bayer RAW directory; multi-frame RAW is unsupported")
    return first, mosaics[0], version is not None, model


def _pentax_note(reader, first, is_dng, model_id):
    tag = 50740 if is_dng else 37500
    source = first
    if tag not in source:
        exif = reader.scalar(first, 34665, (4, 13), optional=True)
        if exif is None or exif < 8:
            raise ValueError("Missing Pentax maker note")
        source, _ = reader.ifd(exif)
        tag = 37500
    field = reader.field(source, tag, (1, 7), range(12, 4 * 1024 * 1024), optional=False)
    offset = reader.offset(field, field.count)
    note = _Tiff(reader.stream, reader.start + offset, field.count)
    header = note.read(0, 10)
    if header[:8] != b"PENTAX \0":
        raise ValueError("Unsupported Pentax maker note header")
    note.endian(header[8:])
    fields, _ = note.ifd(10)
    if note.scalar(fields, 0x0005, (4,)) != model_id:
        raise ValueError("Pentax maker note belongs to a different camera")
    return note, fields


def _q7_settings(note, fields, mode, warnings):
    """Q7 maker note: one tag per setting; the first of a tag's values is the still image's."""
    def first(tag, kind, counts):
        values = note.numbers(fields, tag, (kind,), counts, optional=True)
        return None if values is None else values[0]

    steps = {key: _Q7_STEPS.get(first(tag, 3, (1, 2))) for key, tag in (("saturation", 0x1F), ("hue", 0x67), ("contrast", 0x20))}
    steps["key"] = first(0x6C, 8, (2,))
    settings = None
    if any(value is None for value in steps.values()):
        warnings.append("Custom Image settings are missing")
    elif not -4 <= steps["key"] <= 4:
        warnings.append("Custom Image settings are outside the supported range")
    else:
        settings = {key: steps.get(key, 0) for key in _SETTINGS}        # the Q7 has no highlight and shadow settings
    # Tag 0x007f holds the toning colour of Bleach Bypass and Muted (0 = off); other Custom Images have 65535.
    toning = first(0x7F, 3, (1,)) if mode in _TONING_MODES else None
    return settings, toning if toning is not None and 0 <= toning <= 8 else None


def _check_capture(note, fields):
    """Reject RAW captures this reader does not unpack: Pixel Shift, HDR, anything but a plain RAW."""
    # ExifTool Pentax tags 0x0008, 0x0085, 0x0243. HDR and Pixel Shift flags
    # are at byte 0. The remaining bytes can be nonzero in a normal capture.
    quality = note.scalar(fields, 0x0008, (3,))
    hdr = note.blob(fields, 0x0085, (1,), (4,), optional=True)
    shift = note.blob(fields, 0x0243, (7,), range(1, 257), optional=True)
    if quality in (7, 8) or (shift and shift[0]):
        raise ValueError("Pixel Shift RAW is unsupported")
    if hdr and hdr[0]:
        raise ValueError("HDR RAW is unsupported")
    if quality != 4:
        raise ValueError("Unsupported Pentax RAW capture quality")


def _capture_info(note, fields, camera_id="pentax-k3iii"):
    """The Custom Image and its settings as the maker note of a RAW or a camera JPEG records them."""
    warnings = []
    mode = note.scalar(fields, 0x004F, (3,), optional=True)
    space = note.scalar(fields, 0x0037, (3,), optional=True)
    record = note.blob(fields, 0x0247, (7,), range(12, 257, 2), optional=True)
    if mode is None or mode >= len(_IMAGE_TONES):
        mode = None
        warnings.append("Custom Image mode is missing or unrecognized")
    else:
        mode = _IMAGE_TONES[mode]
    if space not in (0, 1):
        warnings.append("Capture color space is missing or unrecognized; sRGB is used as the recipe default")

    settings = toning = None
    if camera_id == "pentax-q7":
        settings, toning = _q7_settings(note, fields, mode, warnings)
    elif record is None:
        warnings.append("Custom Image settings are missing")
    else:
        # The record is little-endian independently of the maker note byte order
        # (firmware 0x52f835dc). -32768 marks a control inapplicable to this mode.
        values = struct.unpack_from("<6h", record)
        if all(value == -32768 or -4 <= value <= 4 for value in values):
            settings = {key: 0 if value == -32768 else value for key, value in zip(_SETTINGS, values)}
        else:
            warnings.append("Custom Image settings are outside the supported range")
        if mode in _TONING_MODES and len(record) >= 26:
            value, = struct.unpack_from("<h", record, 24)
            if 0 <= value <= 8:
                toning = value
    if mode in _TONING_MODES and toning is None:
        warnings.append("Custom Image toning is missing or unrecognized")

    metadata = {
        "mode": mode, "settings": settings, "color_space": "adobergb" if space == 1 else "srgb",
        "toning": toning,
    }
    return metadata, warnings


def _pef_baseline(gain_tag, white, black):
    """Standard single-frame firmware branch at 0x53127888, with G=4*tag."""
    if gain_tag <= 0:
        raise ValueError("PEF maker-note exposure gain must be positive")
    return log2(1448.0 / 2048.0 * ((white - max(black)) / 16383.0) * (2048.0 / gain_tag))


def _normalize_whitebalance(values):
    balance = np.asarray(values, dtype=np.float64)
    if balance.shape != (4,) or not np.all(np.isfinite(balance) & (balance > 0)):
        raise ValueError("As-shot white balance requires four positive, finite gains")
    return balance / balance[1]


def _check_levels(black, white):
    if not all(0 <= value < white <= 16383 for value in black):
        raise ValueError("Invalid 14-bit RAW black or white level")


def _dng_fields(reader, first, raw):
    # Adobe DNG: CFA and BlackLevel repeat starting at ActiveArea. WhiteLevel
    # has one value here because the CFA stores one sample per pixel.
    if any(tag in raw for tag in (50712, 50715, 50716, 51008, 51009, 51022)):
        raise ValueError("DNG linearization tables, black-level deltas, and opcodes are unsupported")
    active = reader.numbers(raw, 50829, (3, 4), (4,))
    repeat = reader.numbers(raw, 50713, (3,), (2,), optional=True) or (1, 1)
    if repeat not in ((1, 1), (2, 2)):
        raise ValueError("Unsupported DNG BlackLevelRepeatDim")
    black = reader.numbers(raw, 50714, (3, 4, 5), (prod(repeat),))
    black = black * 4 if len(black) == 1 else black
    white = reader.scalar(raw, 50717)
    _check_levels(black, white)
    origin = reader.numbers(raw, 50719, (3, 4, 5), (2,))
    size = reader.numbers(raw, 50720, (3, 4, 5), (2,))
    if any(int(value) != value for value in (*origin, *size)):
        raise ValueError("Fractional DNG DefaultCropOrigin or DefaultCropSize is unsupported")
    crop = tuple(map(int, (*origin, *size)))
    as_shot = reader.numbers(first, 50728, (3, 5), (3,))
    if any(value <= 0 for value in as_shot):
        raise ValueError("DNG AsShotNeutral must be positive")
    red, green, blue = as_shot
    wb = _normalize_whitebalance((1 / red, 1 / green, 1 / blue, 1 / green))
    baseline = reader.scalar(first, 50730, (10,))
    if not isfinite(baseline) or abs(baseline) > 16:
        raise ValueError("DNG BaselineExposure is outside the supported range")
    return active, crop, black, white, wb, baseline


def _pef_fields(note, fields):
    if note.scalar(fields, 0x0080, (1,), optional=True) not in (None, 1):
        raise ValueError("This PEF capture aspect ratio is unsupported")
    # PEF BlackPoint and WhitePoint store R, G1, G2, B; LibRaw CFA indices
    # are R, G1, B, G2. See upstream analysis/lightroom-pef-neutral.html.
    red, green1, green2, blue = note.numbers(fields, 0x0200, (3,), (4,))
    black = (red, green1, blue, green2)
    white = note.scalar(fields, 0x007E)
    _check_levels(black, white)
    red, green1, green2, blue = note.numbers(fields, 0x0201, (3,), (4,))
    wb = _normalize_whitebalance((red, green1, blue, green2))
    baseline = _pef_baseline(note.scalar(fields, 0x009D), white, black)
    return _ACTIVE_AREA, _PEF_CROP, black, white, wb, baseline


def _orient(rgb, orientation):
    if orientation >= 5:
        rgb = rgb.transpose(1, 0, 2)
    if orientation in (3, 4, 7, 8):
        rgb = rgb[::-1, :, :]
    if orientation in (2, 3, 6, 7):
        rgb = rgb[:, ::-1, :]
    return np.ascontiguousarray(rgb)


def _bayer_rgb(raw, active, crop, black, white, wb, black_by_phase):
    sizes = raw.sizes
    pattern = raw.raw_pattern
    if raw.color_desc != b"RGBG" or pattern is None or pattern.shape != (2, 2):
        raise ValueError("Unsupported sensor pattern; expected a color Bayer array")
    top, left, bottom, right = active
    x, y, width, height = crop
    visible = raw.raw_image_visible
    if (
        visible.shape != (bottom - top, right - left)
        or (top, left) != (sizes.top_margin, sizes.left_margin)
        or not (0 <= top < bottom <= sizes.raw_height and 0 <= left < right <= sizes.raw_width)
    ):
        raise ValueError("RAW active area disagrees with the unpacked mosaic")
    if not (0 <= x and 0 <= y and 2 <= width and 2 <= height
            and x + width <= visible.shape[1] and y + height <= visible.shape[0]):
        raise ValueError("RAW crop is outside the active area")
    # Each output pixel consumes one complete 2×2 tile starting at the crop.
    # shortcut: discard one trailing row or column for odd crops, until a full-resolution demosaic is supported.
    height -= height % 2
    width -= width % 2
    rgb = np.zeros((height // 2, width // 2, 3), dtype=np.float32)
    colors = {
        (dy, dx): raw.raw_color(top + y + dy, left + x + dx)
        for dy in range(2) for dx in range(2)
    }
    if set(colors.values()) != {0, 1, 2, 3}:
        raise ValueError("RAW Bayer tile must have red, blue and two green samples")
    for (dy, dx), color in colors.items():
        # DNG level indices follow ActiveArea phase even when the crop begins
        # at an odd offset. PEF levels follow the LibRaw color index.
        phase = 2 * ((y + dy) % 2) + (x + dx) % 2
        level = black[phase if black_by_phase else color]
        plane = visible[y + dy:y + height:2, x + dx:x + width:2].astype(np.float32)
        plane -= level
        np.maximum(plane, 0, out=plane)
        is_green = color in (1, 3)
        plane *= wb[color] / (white - level) * (0.5 if is_green else 1.0)
        rgb[..., 1 if is_green else color] += plane
    # Match the clipped white-balanced camera RGB domain expected by render_dcp.
    return np.minimum(rgb, 1, out=rgb)


def load_raw(path: str | Path) -> RawImage:
    """Unpack a native PEF/DNG without applying input color, exposure or a display transfer."""
    path = Path(path)
    try:
        with path.open("rb") as stream:
            reader = _Tiff(stream)
            first, sensor, is_dng, model = _identify(reader)
            camera = _CAMERAS[model]
            if is_dng and not re.fullmatch(camera["software"], reader.string(first, 305)):
                raise ValueError(f"DNG preview requires a native {model} capture")
            if not is_dng and camera["camera_id"] != "pentax-k3iii":
                raise ValueError(f"{model} preview requires a DNG")
            size = tuple(reader.scalar(sensor, tag) for tag in (256, 257))
            if size != camera["sensor"] or reader.scalar(sensor, 258, (3,)) != camera["bits"]:
                raise ValueError("Unsupported RAW storage geometry or bit depth")
            orientation = reader.scalar(first, 274, (3,), optional=True)
            if orientation is None:
                orientation = 1  # TIFF's default Orientation.
            if not 1 <= orientation <= 8:
                raise ValueError("Invalid RAW Orientation")
            note, fields = _pentax_note(reader, first, is_dng, camera["model_id"])
            _check_capture(note, fields)
            metadata, warnings = _capture_info(note, fields, camera["camera_id"])
            raw_values = _dng_fields(reader, first, sensor) if is_dng else _pef_fields(note, fields)
            active, crop, black, white, wb, baseline = raw_values
            baseline_source = "DNG BaselineExposure"
            white_source = "DNG WhiteLevel"
            if not is_dng:
                metadata.update(
                    firmware_baseline_exposure=baseline,
                    firmware_baseline_source="PEF MakerNote exposure gain and firmware formula",
                    maker_note_white_level=white,
                )
                baseline = _PEF_ADOBE_BASELINE_EXPOSURE
                baseline_source = "Adobe DNG Converter 18.7 PEF model BaselineExposure"
                white = min(white, _PEF_ADOBE_WHITE_LEVEL_CAP)
                white_source = "PEF MakerNote WhiteLevel with Adobe DNG Converter 18.7 model cap"
                _check_levels(black, white)
            with rawpy.imread(str(path)) as unpacked:
                if unpacked.raw_type != rawpy.RawType.Flat:
                    raise ValueError("Expected a single unpacked Bayer mosaic")
                if (unpacked.sizes.raw_width, unpacked.sizes.raw_height) != size:
                    raise ValueError("RAW dimensions disagree with the unpacked mosaic")
                rgb = _orient(_bayer_rgb(unpacked, active, crop, black, white, wb, is_dng), orientation)
    except (OSError, rawpy.LibRawError, NotImplementedError) as exc:
        raise ValueError(f"Unable to read RAW {path.name}: {exc}") from exc
    metadata.update(
        model=model, camera_id=camera["camera_id"], path=str(path), format="DNG" if is_dng else "PEF",
        width=rgb.shape[1], height=rgb.shape[0], orientation=orientation,
        active_area=list(active), crop_origin=list(crop[:2]), crop_size=list(crop[2:]),
        crop_source="DNG DefaultCrop" if is_dng else "K-3 Mark III full-frame RAW crop",
        baseline_exposure=baseline, baseline_source=baseline_source,
        white_balance=wb.tolist(), black_level=list(black), white_level=white, white_level_source=white_source,
    )
    return RawImage(rgb, baseline, metadata, warnings)


def _reduce_axis(rgb, size, axis):
    src = np.moveaxis(rgb, axis, 0)
    if size == len(src):
        return rgb
    edges = np.linspace(0, len(src), size + 1)
    bounds = edges.astype(np.intp)
    fractions = edges[:-1] - bounds[:-1]
    sums = np.add.reduceat(src, bounds[:-1], axis=0)
    corrections = src[bounds[:-1]] * fractions[:, None, None].astype(np.float32)
    sums -= corrections
    sums[:-1] += corrections[1:]
    sums /= len(src) / size
    return np.moveaxis(sums, 0, axis)


def resize_rgb(rgb: np.ndarray, max_edge: int) -> np.ndarray:
    """Area-average linear RGB to fit max_edge, without enlarging the input."""
    rgb = np.asarray(rgb, dtype=np.float32)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 1:
        raise ValueError("Expected non-empty H×W×3 RGB")
    if isinstance(max_edge, bool) or not isinstance(max_edge, (int, np.integer)) or max_edge < 1:
        raise ValueError("max_edge must be a positive integer")
    height, width = rgb.shape[:2]
    if max(height, width) <= max_edge:
        return rgb
    scale = max_edge / max(height, width)
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    return np.ascontiguousarray(_reduce_axis(_reduce_axis(rgb, new_width, 1), new_height, 0))


def read_calibration(path: str | Path, camera_id: str = "pentax-k3iii") -> list[list[list[float]]]:
    """Read explicitly selected same-camera DNG ColorMatrices in A, D65 order."""
    path = Path(path)
    try:
        with path.open("rb") as stream:
            reader = _Tiff(stream)
            first, _, is_dng, model = _identify(reader)
            if not is_dng or _CAMERAS[model]["camera_id"] != camera_id:
                raise ValueError("Calibration import requires a same-camera DNG")
            checks = ((50778, 50721), (50779, 50722))
            matrices = {}
            for illuminant_tag, matrix_tag in checks:
                illuminant = reader.scalar(first, illuminant_tag, (3,))
                matrix = np.asarray(reader.numbers(first, matrix_tag, (10,), (9,))).reshape(3, 3)
                if (not np.all(np.isfinite(matrix)) or np.max(np.abs(matrix)) > 16
                        or abs(np.linalg.det(matrix)) < 1e-8):
                    raise ValueError("Invalid DNG calibration matrix")
                matrices[illuminant] = matrix.tolist()
            if matrices.keys() != {17, 21}:
                raise ValueError("DNG calibration must contain both illuminant A and D65")
            return [matrices[17], matrices[21]]
    except OSError as exc:
        raise ValueError(f"Unable to read DNG calibration {path.name}: {exc}") from exc
