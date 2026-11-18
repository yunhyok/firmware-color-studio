"""Read a reference JPEG and sample a perspective-projected ColorChecker Classic."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColorSpace, QImage, QImageReader

from .raw import _Tiff


@dataclass(frozen=True)
class ChartJpeg:
    image: QImage
    name: str


def _camera_string(reader, fields, tag):
    try:
        value = reader.string(fields, tag)
    except ValueError:
        return ""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())


def _jpeg_metadata(path):
    """Only inspect the JPEG's length-delimited segments before the first scan."""
    exif = None
    has_icc = False
    with path.open("rb") as stream:
        if stream.read(2) != b"\xff\xd8":
            raise ValueError("Select a JPEG image.")
        while stream.read(1) == b"\xff":
            marker = stream.read(1)
            while marker == b"\xff":
                marker = stream.read(1)
            if marker in (b"\xda", b"\xd9"):
                break
            size = int.from_bytes(stream.read(2), "big") - 2
            if size < 0:
                raise ValueError("Invalid JPEG header.")
            segment = stream.read(size)
            if len(segment) != size:
                raise ValueError("Truncated JPEG header.")
            if marker == b"\xe1" and segment.startswith(b"Exif\0\0") and exif is None:
                exif = segment[6:]
            if marker == b"\xe2" and segment.startswith(b"ICC_PROFILE\0"):
                has_icc = True

    make = model = ""
    adobe_rgb = False
    if exif:
        reader = _Tiff(BytesIO(exif))
        try:
            fields, _ = reader.ifd(reader.root())
            make = _camera_string(reader, fields, 271)
            model = _camera_string(reader, fields, 272)
            sub_ifd = reader.scalar(fields, 34665, (4,), optional=True)
            if sub_ifd:
                sub_fields, _ = reader.ifd(sub_ifd)
                space = reader.scalar(sub_fields, 40961, (3,), optional=True)
                adobe_rgb = space == 2
                interop = reader.scalar(sub_fields, 40965, (4,), optional=True)
                if space == 65535 and interop:
                    interop_fields, _ = reader.ifd(interop)
                    adobe_rgb = reader.string(interop_fields, 1) == "R03"
        except ValueError:
            pass  # Damaged optional EXIF is common in otherwise readable JPEGs.
    if make and model and not model.casefold().startswith(make.split()[0].casefold()):
        model = f"{make} {model}"
    fallback = "".join(ch for ch in path.stem if ch.isprintable()).strip()
    return model or make or fallback or "Chart profile", has_icc, adobe_rgb


def load_chart_jpeg(path: str | Path) -> ChartJpeg:
    """Decode and orient the JPEG; all returned coordinates are displayed pixels."""
    path = Path(path)
    name, has_icc, adobe_rgb = _jpeg_metadata(path)
    reader = QImageReader(str(path), b"JPEG")
    reader.setAutoTransform(True)
    size, limit = reader.size(), reader.allocationLimit()
    # Qt charges at least four bytes per pixel against its decoder memory limit.
    if size.isValid() and limit > 0 and size.width() * size.height() * 4 > limit * 1024 ** 2:
        raise ValueError(f"JPEG dimensions exceed the {limit} MiB decoder limit. Export a smaller JPEG.")
    image = reader.read()
    if image.isNull():
        raise ValueError(f"Unable to read reference JPEG: {reader.errorString()}")
    srgb = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    if not image.colorSpace().isValid():
        if has_icc or image.format() == QImage.Format.Format_CMYK8888:
            raise ValueError("This JPEG needs a usable RGB color profile. Export an sRGB JPEG.")
        image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb) if adobe_rgb else srgb)
    image = image.convertedToColorSpace(srgb, QImage.Format.Format_RGB888)
    if image.isNull():
        raise ValueError("Unable to convert the JPEG's color profile to sRGB.")
    return ChartJpeg(image, name)


_GRID = np.array([(x, y) for y in range(4) for x in range(6)], dtype=float)


def _homography(corners):
    points = np.asarray(corners, dtype=float)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("Select four finite patch centers in chart order.")
    edges = np.roll(points, -1, axis=0) - points
    turns = np.cross(edges, np.roll(edges, -1, axis=0))
    if not ((turns > 1e-6).all() or (turns < -1e-6).all()):
        raise ValueError("The four patch centers must form a convex quadrilateral in chart order.")
    source = _GRID[[0, 5, 23, 18]]
    equations = np.zeros((8, 8))
    homogeneous = np.column_stack((source, np.ones(4)))
    equations[::2, :3] = homogeneous
    equations[1::2, 3:6] = homogeneous
    equations[:, 6:] = -np.repeat(source, 2, axis=0) * points.reshape(-1, 1)
    try:
        coeff = np.linalg.solve(equations, points.ravel())
    except np.linalg.LinAlgError as exc:
        raise ValueError("The selected patch centers are degenerate.") from exc
    return np.append(coeff, 1).reshape(3, 3)


def _project(matrix, coordinates):
    xyw = coordinates @ matrix[:, :2].T + matrix[:, 2]
    if (xyw[..., 2] <= 1e-10).any():
        raise ValueError("The selected perspective leaves part of the chart unresolved.")
    return xyw[..., :2] / xyw[..., 2:]


def patch_centers(corners) -> np.ndarray:
    """Corners are the centers of patches 1, 6, 24, 19 in that order."""
    return _project(_homography(corners), _GRID)


def sample_chart(image: QImage, corners) -> np.ndarray:
    """Median of 81 projected inner-patch samples, row-major, encoded sRGB 0…1."""
    if image.isNull():
        raise ValueError("Load the chart JPEG before selecting patches.")
    matrix = _homography(corners)
    offsets = np.linspace(-0.2, 0.2, 9)
    xy = np.stack(np.meshgrid(offsets, offsets), axis=-1).reshape(81, 2)
    positions = _project(matrix, _GRID[:, None, :] + xy)
    if (positions < 0).any() or (positions > [image.width() - 1, image.height() - 1]).any():
        raise ValueError("Part of a chart patch lies outside the image.")
    # Require at least two pixels across the narrowest projected inner patch.
    quad = positions[:, [0, 8, 80, 72]]
    edges = np.roll(quad, -1, axis=1) - quad
    height = abs(np.cross(edges, np.roll(edges, -1, axis=1))) / np.linalg.norm(edges, axis=2)
    if height.min() < 2:
        raise ValueError("The chart is too small or too oblique to sample reliably.")
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    pixels = np.ndarray((rgb.height(), rgb.width(), 3), dtype=np.uint8, buffer=rgb.constBits(),
                        strides=(rgb.bytesPerLine(), 3, 1))
    x, y = np.rint(positions).astype(int).transpose(2, 0, 1)
    return np.median(pixels[y, x], axis=1) / 255.0
