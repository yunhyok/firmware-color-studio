import struct

import numpy as np
import pytest
from PySide6.QtGui import QColor, QColorSpace, QImage

from firmware_color_studio.chart_input import load_chart_jpeg, patch_centers, sample_chart


def qimage(rgb):
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    return QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                  QImage.Format.Format_RGB888).copy()


def segment(path, marker, payload):
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8"
    path.write_bytes(data[:2] + marker + struct.pack(">H", len(payload) + 2) + payload + data[2:])


def exif(make, model):
    tags = []
    area = b""
    for tag, text in [(271, make), (272, model)]:
        data = text.encode() + b"\0"
        if len(data) <= 4:
            value = data.ljust(4, b"\0")
        else:
            value = struct.pack("<I", 8 + 2 + 3 * 12 + 4 + len(area))
            area += data
        tags.append(struct.pack("<HHI", tag, 2, len(data)) + value)
    tags.append(struct.pack("<HHIHH", 274, 3, 1, 6, 0))
    return b"Exif\0\0II" + struct.pack("<HIH", 42, 8, len(tags)) + b"".join(tags) + bytes(4) + area


@pytest.mark.parametrize(("make", "model", "expected"), [
    ("NIKON CORPORATION", "NIKON Z 8", "NIKON Z 8"),
    ("SONY", "ILCE-7M4", "SONY ILCE-7M4"),
])
def test_camera_name_orientation_and_filename_fallback(tmp_path, make, model, expected):
    pixels = np.zeros((32, 48, 3), np.uint8)
    pixels[:, :24] = [200, 60, 82]
    pixels[:, 24:] = [64, 164, 182]
    path = tmp_path / "차트 참고.jpg"
    assert qimage(pixels).save(str(path), "JPEG", 97)
    assert load_chart_jpeg(path).name == path.stem
    segment(path, b"\xff\xe1", exif(make, model))
    chart = load_chart_jpeg(path)
    assert chart.name == expected
    assert (chart.image.width(), chart.image.height()) == (32, 48)
    np.testing.assert_allclose(chart.image.pixelColor(12, 8).getRgb()[:3], pixels[10, 10], atol=3)


def test_display_p3_icc_is_converted_before_sampling(tmp_path):
    image = QImage(120, 100, QImage.Format.Format_RGB888)
    image.fill(QColor(180, 75, 99))
    path = tmp_path / "reference.jpg"
    assert image.save(str(path), "JPEG", 100)
    plain = load_chart_jpeg(path).image
    p3 = QColorSpace(QColorSpace.NamedColorSpace.DisplayP3)
    segment(path, b"\xff\xe2", b"ICC_PROFILE\0\x01\x01" + bytes(p3.iccProfile()))
    chart = load_chart_jpeg(path)
    assert chart.image.colorSpace() == QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    corners = [[12, 12], [107, 12], [107, 87], [12, 87]]
    raw = sample_chart(plain, corners)
    converted = sample_chart(chart.image, corners)
    # Linear Display P3 to linear sRGB, D65 (CSS Color 4 sample conversions).
    linear = ((raw + 0.055) / 1.055) ** 2.4
    expected = linear @ np.array([[1.22494, -0.22494, 0.], [-0.04206, 1.04206, 0.],
                                  [-0.01964, -0.07865, 1.09827]]).T
    expected = 1.055 * expected ** (1 / 2.4) - 0.055
    np.testing.assert_allclose(converted, expected, atol=1.5 / 255)
    assert np.max(abs(converted - raw)) > .03


def test_unusable_icc_and_nonjpeg_fail(tmp_path):
    path = tmp_path / "fake.jpg"
    img = QImage(60, 60, QImage.Format.Format_RGB32)
    img.fill(QColor(1, 2, 3))
    assert img.save(str(path), "PNG")
    with pytest.raises(ValueError, match="JPEG"):
        load_chart_jpeg(path)
    assert img.save(str(path), "JPEG")
    segment(path, b"\xff\xe2", b"ICC_PROFILE\0\x01\x01" + bytes(100))
    with pytest.raises(ValueError, match="profile"):
        load_chart_jpeg(path)


def test_damaged_metadata_keeps_clean_editable_filename(tmp_path):
    path = tmp_path / "chart\x7f.jpg"
    img = QImage(24, 24, QImage.Format.Format_RGB32)
    img.fill(QColor(100, 120, 140))
    assert img.save(str(path), "JPEG")
    segment(path, b"\xff\xe1", b"Exif\0\0II*")
    assert load_chart_jpeg(path).name == "chart"


def test_oversized_header_includes_resize_hint(tmp_path, monkeypatch):
    path = tmp_path / "large.jpg"
    img = QImage(24, 24, QImage.Format.Format_RGB32)
    img.fill(QColor(100, 120, 140))
    assert img.save(str(path), "JPEG")
    data = bytearray(path.read_bytes())
    sof = data.index(b"\xff\xc0")
    struct.pack_into(">HH", data, sof + 5, 8736, 11648)
    path.write_bytes(data)
    monkeypatch.setattr("firmware_color_studio.chart_input.QImageReader.allocationLimit", lambda self: 256)
    with pytest.raises(ValueError, match="smaller JPEG"):
        load_chart_jpeg(path)


@pytest.mark.parametrize("color_space", [2, 65535])
def test_exif_adobe_rgb_and_embedded_profile_precedence(tmp_path, color_space):
    # Big-endian TIFF with ExifIFD ColorSpace and InteropIFD index R03.
    def ifd(tags):
        return struct.pack(">H", len(tags)) + b"".join(tags) + bytes(4)

    data = b"MM" + struct.pack(">HI", 42, 8)
    data += ifd([struct.pack(">HHII", 34665, 4, 1, 26)])
    data += ifd([struct.pack(">HHIHH", 40961, 3, 1, color_space, 0),
                 struct.pack(">HHII", 40965, 4, 1, 56)])
    data += ifd([struct.pack(">HHI4s", 1, 2, 4, b"R03\0")])
    path = tmp_path / "chart.jpg"
    image = QImage(20, 20, QImage.Format.Format_RGB32)
    image.fill(QColor(125, 96, 70))
    assert image.save(str(path), "JPEG", 100)
    untagged = load_chart_jpeg(path).image
    srgb = untagged.colorSpace()
    expected = untagged.copy()
    expected.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb))
    expected = expected.convertedToColorSpace(srgb, QImage.Format.Format_RGB888)
    segment(path, b"\xff\xe1", b"Exif\0\0" + data)
    assert load_chart_jpeg(path).image.pixelColor(10, 10) == expected.pixelColor(10, 10)
    segment(path, b"\xff\xe2", b"ICC_PROFILE\0\x01\x01" + bytes(srgb.iccProfile()))
    assert load_chart_jpeg(path).image.pixelColor(10, 10) == untagged.pixelColor(10, 10)


def test_projective_turned_chart_and_padding_with_outliers():
    transform = np.array([[2, -34, 180], [29, 8, 25], [.018, -.018, 1.]])
    yy, xx = np.indices((211, 217))
    back = np.stack((xx, yy, np.ones_like(xx)), axis=-1) @ np.linalg.inv(transform).T
    uv = back[..., :2] / back[..., 2:]
    cell = np.rint(uv).astype(int)
    inner = (np.abs(cell - uv) < .34).all(axis=-1)
    valid = inner & (cell >= [0, 0]).all(axis=-1) & (cell < [6, 4]).all(axis=-1)
    colors = np.random.default_rng(42).integers(15, 240, (24, 3), dtype=np.uint8)
    pixels = np.full((*xx.shape, 3), 252, np.uint8)
    pixels[valid] = colors[(cell[..., 1] * 6 + cell[..., 0])[valid]]
    positions = np.array([[x, y, 1] for y in range(4) for x in range(6)]) @ transform.T
    centers = positions[:, :2] / positions[:, 2:]
    corners = centers[[0, 5, 23, 18]]
    for x, y in np.rint(centers).astype(int):
        pixels[y, x] = 255
    np.testing.assert_allclose(patch_centers(corners), centers)
    np.testing.assert_array_equal(sample_chart(qimage(pixels), corners), colors / 255.)


@pytest.mark.parametrize("corners", [
    [(10, 10), (70, 70), (10, 70), (70, 10)],
    [(10, 10), (70, 10), (70, 10), (10, 60)],
    [(10, 10), (20, 10), (20, 25), (10, 25)],
    [(0, 10), (70, 10), (70, 60), (0, 60)],
    [(10, 10), (70, 10), (70, 60), (10, float("nan"))],
])
def test_refuse_crossed_collapsed_tiny_and_partial_patches(corners):
    image = QImage(80, 80, QImage.Format.Format_RGB888)
    with pytest.raises(ValueError):
        sample_chart(image, corners)
