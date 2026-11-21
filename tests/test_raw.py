import struct
from contextlib import nullcontext
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest

from firmware_color_studio import raw


def _ifd(tags, order="<", offset=8, sibling=0):
    directory = bytearray(struct.pack(order + "H", len(tags)))
    payload = bytearray()
    payload_start = offset + 2 + 12 * len(tags) + 4
    for tag, (kind, count, value) in sorted(tags.items()):
        directory.extend(struct.pack(order + "HHI", tag, kind, count))
        if len(value) > 4:
            directory.extend(struct.pack(order + "I", payload_start + len(payload)))
            payload.extend(value)
        else:
            directory.extend(value.ljust(4, b"\0"))
    return bytes(directory) + struct.pack(order + "I", sibling) + bytes(payload)


def _short(*values, order="<"):
    return 3, len(values), struct.pack(order + "H" * len(values), *values)


def _long(*values, order="<"):
    return 4, len(values), struct.pack(order + "I" * len(values), *values)


def _bytes(value, kind=1):
    return kind, len(value), value


def _rat(values, signed=False):
    flat = [number for pair in values for number in pair]
    return (10 if signed else 5), len(values), struct.pack(
        "<" + ("i" if signed else "I") * len(flat), *flat
    )


def _note(override=None, order=">"):
    record = struct.pack("<24h", -32768, 2, -3, 4, 1, -1, *([0] * 6), 5, *([0] * 11))
    tags = {
        0x0005: _long(0x13254, order=order),
        0x0008: _short(4, order=order),
        0x0037: _short(1, order=order),
        0x004F: _short(6, order=order),
        0x007E: _long(1100, order=order),
        0x0085: _bytes(b"\0\1\10\0"),
        0x009D: _short(2048, order=order),
        0x0200: _short(100, 200, 300, 400, order=order),
        0x0201: _short(200, 100, 150, 300, order=order),
        0x0243: _bytes(bytes(70), 7),
        0x0247: _bytes(record, 7),
    }
    tags.update(override or {})
    return b"PENTAX \0" + (b"MM" if order == ">" else b"II") + _ifd(tags, order, offset=10)


def _dng(path, override=None):
    identity = [(int(row == col), 1) for row in range(3) for col in range(3)]
    tags = {
        256: _long(6304), 257: _long(4224), 258: _short(14), 262: _short(32803),
        272: _bytes(b"PENTAX K-3 Mark III\0", 2), 274: _short(6), 277: _short(1),
        305: _bytes(b"PENTAX K-3 Mark III Ver. 2.20\0", 2),
        50706: _bytes(b"\1\2\0\0"), 50708: _bytes(b"PENTAX K-3 Mark III\0", 2),
        50713: _short(2, 2), 50714: _short(100, 200, 300, 400), 50717: _short(1100),
        50719: _long(1, 1), 50720: _long(4, 4),
        50721: _rat([(x * 2, y) for x, y in identity], signed=True),
        50722: _rat(identity, signed=True),
        50728: _rat([(1, 2), (1, 1), (1, 3)]),
        50730: _rat([(-3, 4)], signed=True), 50740: _bytes(_note()),
        50778: _short(21), 50779: _short(17), 50829: _long(3, 2, 9, 8),
    }
    tags.update(override or {})
    path.write_bytes(b"II\x2a\0\x08\0\0\0" + _ifd({key: value for key, value in tags.items() if value is not None}))
    return path


class _Mosaic:
    raw_type = raw.rawpy.RawType.Flat
    sizes = SimpleNamespace(top_margin=3, left_margin=2, raw_width=6304, raw_height=4224)
    raw_pattern = np.array([[0, 1], [3, 2]])
    color_desc = b"RGBG"

    def __init__(self):
        self.raw_image_visible = np.zeros((6, 6), dtype=np.uint16)
        self.raw_image_visible[1:3, 1:3] = [[470, 380], [290, 340]]

    def raw_color(self, row, col):
        return int(self.raw_pattern[row % 2, col % 2])


def test_dng_crop_cfa_white_balance_and_baseline_are_independent(tmp_path, monkeypatch):
    path = _dng(tmp_path / "capture.dng")
    monkeypatch.setattr(raw.rawpy, "imread", lambda _: nullcontext(_Mosaic()))
    image = raw.load_raw(path)

    assert image.rgb.dtype == np.float32
    assert image.rgb.flags.c_contiguous
    expected = np.zeros((2, 2, 3))
    # First cropped tile is G1 R / B G2. ActiveArea black positions are
    # 400 300 / 200 100 there. Orientation 6 rotates the tile to [0, 1].
    expected[0, 1] = (0.2, 0.5 * (0.1 + 0.24), 0.3)
    np.testing.assert_allclose(image.rgb, expected, atol=1e-7)
    assert image.baseline_exposure == -0.75
    assert image.metadata["baseline_exposure"] == -0.75
    assert image.metadata["baseline_source"] == "DNG BaselineExposure"
    assert image.metadata["crop_origin"] == [1, 1]
    assert image.metadata["white_balance"] == [2, 1, 3, 1]
    assert image.metadata["color_space"] == "adobergb"
    assert image.metadata["mode"] == "muted"
    assert image.metadata["settings"] == {
        "saturation": 0, "hue": 2, "key": -3, "contrast": 4, "highlight": 1, "shadow": -1,
    }
    assert image.metadata["toning"] == 5
    assert image.warnings == []

    _dng(path, {50730: _rat([(2, 1)], signed=True)})
    brighter = raw.load_raw(path)
    assert brighter.baseline_exposure == 2.0
    np.testing.assert_array_equal(brighter.rgb, image.rgb)


def _q7_note(override=None):
    tags = {
        0x0005: _long(0x12F7A), 0x0008: _short(4), 0x0037: _short(0), 0x004F: _short(8),
        0x001F: _short(5), 0x0020: _short(4), 0x0067: _short(2), 0x006C: (8, 2, struct.pack("<2h", -2, 0)),
        0x007F: _short(3), 0x0085: _bytes(bytes(4)),
    }
    tags.update(override or {})
    return b"PENTAX \0II" + _ifd(tags, "<", offset=10)


_Q7 = {256: _long(4064), 257: _long(3000), 258: _short(12), 272: _bytes(b"PENTAX Q7\0", 2),
       305: _bytes(b"PENTAX Q7     Ver 1.01\0", 2), 50708: _bytes(b"PENTAX Q7\0", 2)}


def test_q7_dng_reads_its_own_geometry_and_setting_tags(tmp_path, monkeypatch):
    path = _dng(tmp_path / "q7.dng", {**_Q7, 50740: _bytes(_q7_note())})
    mosaic = _Mosaic()
    mosaic.sizes = SimpleNamespace(top_margin=3, left_margin=2, raw_width=4064, raw_height=3000)
    monkeypatch.setattr(raw.rawpy, "imread", lambda _: nullcontext(mosaic))
    image = raw.load_raw(path)
    assert (image.metadata["camera_id"], image.metadata["model"]) == ("pentax-q7", "PENTAX Q7")
    assert (image.metadata["mode"], image.metadata["toning"]) == ("bleach-bypass", 3)
    # Tag values 5, 2, 4 are the menu steps -3, +2, +1; the key tag holds the step itself.
    assert image.metadata["settings"] == {"saturation": -3, "hue": 2, "key": -2, "contrast": 1, "highlight": 0, "shadow": 0}
    assert image.warnings == [] and image.baseline_exposure == -0.75
    np.testing.assert_array_equal(raw.read_calibration(path, "pentax-q7"), [np.eye(3), np.eye(3) * 2])
    with pytest.raises(ValueError, match="same-camera"):
        raw.read_calibration(path)                               # not a K-3 Mark III file

    unknown = raw.load_raw(_dng(path, {**_Q7, 50740: _bytes(_q7_note({0x0067: _short(99), 0x004F: _short(6)}))}))
    assert unknown.metadata["settings"] is None and unknown.metadata["mode"] == "muted"
    assert unknown.warnings == ["Custom Image settings are missing", "Custom Image toning is missing or unrecognized"]
    for override, message in (({258: _short(14)}, "storage geometry"), ({50740: _bytes(_note())}, "different camera"),
                              ({305: _bytes(b"PENTAX K-3 Mark III Ver. 2.20\0", 2)}, "native")):
        with pytest.raises(ValueError, match=message):
            raw.load_raw(_dng(path, {**_Q7, 50740: _bytes(_q7_note()), **override}))


def test_pef_uses_both_greens_and_firmware_gain():
    note = raw._Tiff(BytesIO(_note()), length=len(_note()))
    note.endian(b"MM")
    fields, _ = note.ifd(10)
    _, _, black, white, wb, baseline = raw._pef_fields(note, fields)
    assert black == (100, 200, 400, 300)
    assert wb.tolist() == [2, 1, 3, 1.5]
    assert white == 1100
    assert baseline == pytest.approx(np.log2((1448 / 2048) * 700 / 16383))
    with pytest.raises(ValueError, match="exposure gain"):
        raw._pef_baseline(0, white, black)

    mosaic = _Mosaic()
    mosaic.raw_image_visible[1:3, 1:3] = [[290, 150], [430, 460]]
    rgb = raw._bayer_rgb(mosaic, (3, 2, 9, 8), (1, 1, 2, 2), black, white, wb, False)
    np.testing.assert_allclose(rgb[0, 0], [0.1, (0.1 + 0.3) / 2, 3 * 30 / 700], atol=1e-7)


@pytest.mark.parametrize(("gain", "maker_white", "black_levels", "preview_white"), [
    (1024, 1100, (100, 200, 300, 400), 1100),
    (4096, 16378, (128, 128, 128, 128), 16315),
])
def test_pef_uses_adobe_preview_policy_and_retains_native_levels(
    tmp_path, monkeypatch, gain, maker_white, black_levels, preview_white,
):
    path = tmp_path / "capture.pef"
    tags = {
        256: _long(6304), 257: _long(4224), 258: _short(14), 262: _short(32803),
        272: _bytes(b"PENTAX K-3 Mark III\0", 2), 277: _short(1), 34665: _long(0),
    }
    exif_offset = 8 + len(_ifd(tags))
    tags[34665] = _long(exif_offset)
    note = _note({
        0x009D: _short(gain, order=">"),
        0x007E: _long(maker_white, order=">"),
        0x0200: _short(*black_levels, order=">"),
    })
    exif = _ifd({37500: _bytes(note, kind=7)}, offset=exif_offset)
    path.write_bytes(b"II\x2a\0\x08\0\0\0" + _ifd(tags) + exif)

    monkeypatch.setattr(raw.rawpy, "imread", lambda _: nullcontext(_Mosaic()))
    monkeypatch.setattr(raw, "_ACTIVE_AREA", (3, 2, 9, 8))
    monkeypatch.setattr(raw, "_PEF_CROP", (1, 1, 4, 4))
    image = raw.load_raw(path)

    assert image.baseline_exposure == image.metadata["baseline_exposure"] == -0.3
    assert image.metadata["baseline_source"] == "Adobe DNG Converter 18.7 PEF model BaselineExposure"
    assert image.metadata["firmware_baseline_source"] == "PEF MakerNote exposure gain and firmware formula"
    assert image.metadata["firmware_baseline_exposure"] == pytest.approx(
        np.log2((1448 / gain) * (maker_white - max(black_levels)) / 16383)
    )
    assert image.metadata["maker_note_white_level"] == maker_white
    assert image.metadata["white_level"] == preview_white
    # First cropped tile is G1 R / B G2. Confirm preview normalization uses the effective white.
    assert image.rgb[0, 0, 0] == pytest.approx(2 * (380 - black_levels[0]) / (preview_white - black_levels[0]))


@pytest.mark.parametrize(("orientation", "expected"), [
    (1, [[1, 2, 3], [4, 5, 6]]),
    (2, [[3, 2, 1], [6, 5, 4]]),
    (3, [[6, 5, 4], [3, 2, 1]]),
    (4, [[4, 5, 6], [1, 2, 3]]),
    (5, [[1, 4], [2, 5], [3, 6]]),
    (6, [[4, 1], [5, 2], [6, 3]]),
    (7, [[6, 3], [5, 2], [4, 1]]),
    (8, [[3, 6], [2, 5], [1, 4]]),
])
def test_tiff_orientation(orientation, expected):
    actual = raw._orient(np.arange(1, 7).reshape(2, 3, 1), orientation)
    np.testing.assert_array_equal(actual[..., 0], expected)


@pytest.mark.parametrize(("data", "message"), [
    (b"XP\x2a\0\x08\0\0\0", "byte order"),
    (b"II\x2b\0\x08\0\0\0", "classic TIFF"),
    (b"II\x2a\0\x08\0\0\0\xff\xff", "directory entry count"),
    (b"II\x2a\0\x08\0\0\0\x01\0\x10", "outside"),
    (b"II\x2a\0\x08\0\0\0" + struct.pack("<HHHII", 1, 272, 2, 1000, 22) + bytes(4), "count"),
    (b"II\x2a\0\x08\0\0\0" + struct.pack("<HHHII", 1, 272, 2, 20, 65536) + bytes(4), "outside"),
])
def test_rejects_malformed_tiff_before_unpack(data, message, tmp_path):
    path = tmp_path / "invalid.pef"
    path.write_bytes(data)
    with pytest.raises(ValueError, match=message):
        raw.load_raw(path)


@pytest.mark.parametrize(("override", "message"), [
    ({262: _short(34892)}, "Linear DNG"),
    ({277: _short(4)}, "single-sample Bayer"),
    ({272: _bytes(b"PENTAX K-3 Mark III Monochrome\0", 2)}, "Unsupported camera model"),
    ({50708: _bytes(b"PENTAX K-3 Mark II\0", 2)}, "UniqueCameraModel"),
    ({305: _bytes(b"Adobe DNG Converter\0", 2)}, "native"),
    ({330: _long(8)}, "repeated RAW TIFF directory"),
    ({50728: None}, "AsShotNeutral"),
    ({50728: _rat([(0, 1), (1, 1), (1, 1)])}, "AsShotNeutral"),
    ({50730: None}, "BaselineExposure"),
    ({50730: _rat([(1, 0)], signed=True)}, "Zero denominator"),
    ({50730: _short(1)}, "type or count"),
    ({50730: _rat([(200, 1)], signed=True)}, "supported range"),
    ({50717: _short(200)}, "black or white level"),
    ({50719: _rat([(1, 2), (0, 1)])}, "Fractional"),
    ({50740: _bytes(_note({0x0243: _bytes(b"\1", 7)}))}, "Pixel Shift"),
    ({50740: _bytes(_note({0x0085: _bytes(b"\2\1\10\0")}))}, "HDR"),
])
def test_rejects_out_of_scope_dng_before_unpack(override, message, tmp_path):
    with pytest.raises(ValueError, match=message):
        raw.load_raw(_dng(tmp_path / "invalid.dng", override))


def test_calibration_requires_a_and_d65_and_orders_them(tmp_path):
    path = _dng(tmp_path / "color.dng")
    matrices = np.array(raw.read_calibration(path))
    np.testing.assert_array_equal(matrices, [np.eye(3), np.eye(3) * 2])
    _dng(path, {50779: _short(23)})
    with pytest.raises(ValueError, match="illuminant A and D65"):
        raw.read_calibration(path)
    _dng(path, {50721: _rat([(0, 1)] * 9, signed=True)})
    with pytest.raises(ValueError, match="calibration matrix"):
        raw.read_calibration(path)


def test_resize_rgb_weights_fractional_edges_in_linear_space():
    image = np.broadcast_to(np.array([0, 1, 0], dtype=np.float32)[None, :, None], (1, 3, 3))
    np.testing.assert_allclose(raw.resize_rgb(image, 2), np.full((1, 2, 3), 1 / 3), atol=1e-7)
    np.testing.assert_allclose(raw.resize_rgb(image.transpose(1, 0, 2), 2), np.full((2, 1, 3), 1 / 3), atol=1e-7)
    assert raw.resize_rgb(image, 5) is image
    with pytest.raises(ValueError, match="positive integer"):
        raw.resize_rgb(image, 0)
