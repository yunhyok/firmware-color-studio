"""Conservative, offline ColorChecker Classic localization in displayed pixels."""

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .chart_fit import _lab, reference_srgb
from .chart_input import patch_centers, sample_chart


# OpenCV 4.11 MCC model geometry, not the centres returned to the application:
# https://github.com/opencv/opencv_contrib/blob/4.11.0/modules/mcc/src/dictionary.hpp
_BOX = np.array([[0, 0], [16.75, 0], [16.75, 11.25], [0, 11.25]], np.float32)
_CENTERS = np.array([[1.5, 1.5], [15.25, 1.5], [15.25, 9.75], [1.5, 9.75]], np.float32)
_REFERENCE_AB = _lab(reference_srgb())[:18, 1:]


def _quality(image, corners):
    lab = _lab(sample_chart(image, corners))
    light = lab[18:, 0]
    chroma = np.linalg.norm(lab[:, 1:], axis=1)
    if (light[0] - light[-1] < 25 or np.any(np.diff(light) > 2)
            or np.count_nonzero(np.diff(light) < -3) < 4
            or np.median(chroma[18:]) > 12 or chroma[18:].max() > 20
            or np.median(chroma[:18]) < 12):
        return None
    # Hue agreement tolerates donor tone/contrast changes without fitting away a wrong chart.
    cosine = np.sum(lab[:18, 1:] * _REFERENCE_AB, axis=1) / np.maximum(
        chroma[:18] * np.linalg.norm(_REFERENCE_AB, axis=1), 1e-8)
    if cosine.mean() < .8 or np.count_nonzero(cosine > .5) < 15:
        return None
    return float(cosine.mean())


def _orient(image, box):
    if box.shape != (4, 2) or not np.isfinite(box).all():
        return None
    matches = []
    for winding in (box, box[::-1]):
        for shift in range(4):
            ordered = np.ascontiguousarray(np.roll(winding, shift, axis=0), dtype=np.float32)
            matrix = cv2.getPerspectiveTransform(_BOX, ordered)
            centers = cv2.perspectiveTransform(_CENTERS[None], matrix)[0].astype(float)
            try:
                score = _quality(image, centers)
            except ValueError:
                continue
            if score is not None:
                matches.append((score, centers))
    if len(matches) > 1:
        raise ValueError("The chart orientation is ambiguous.")
    return matches[0] if matches else None


def _same_chart(first, second):
    size = min(np.linalg.norm(np.roll(c, -1, axis=0) - c, axis=1).min()
               for c in (first, second))
    return np.linalg.norm(first - second, axis=1).max() < .15 * size


def detect_chart(image: QImage) -> np.ndarray:
    """Return full-resolution centers 1, 6, 24, 19; reject missing/uncertain charts.

    The caller supplies the already EXIF-oriented, sRGB image. Mirrored charts
    are supported; the returned winding follows the numbered patches.
    """
    if image.isNull() or min(image.width(), image.height()) < 64:
        raise ValueError("Automatic detection needs a larger chart image.")
    parameters = cv2.mcc.DetectorParameters_create()
    parameters.minImageSize = 0  # MCC otherwise silently enlarges short panoramic frames.
    parameters.minInterCheckerDistance = 100
    parameters.maxError = .02
    candidates = []
    for limit in (900, 1400):
        # Consistent pixel scale avoids coarse MCC contours on smaller source photos.
        frame = image.scaled(limit, limit,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        if min(frame.width(), frame.height()) < 32:
            continue
        frame = frame.convertToFormat(QImage.Format.Format_RGB888)
        rgb = np.ndarray((frame.height(), frame.width(), 3), np.uint8,
                         buffer=frame.constBits(), strides=(frame.bytesPerLine(), 3, 1))
        detector = cv2.mcc.CCheckerDetector_create()
        try:
            found = detector.process(np.ascontiguousarray(rgb[..., ::-1]), cv2.mcc.MCC24,
                                     nc=32, params=parameters)
        except cv2.error as exc:
            raise ValueError("Automatic chart detection failed.") from exc
        if not found:
            continue
        checkers = detector.getListColorChecker()
        if len(checkers) >= 32:
            raise ValueError("Too many chart candidates.")
        scale = np.array([image.width() / frame.width(), image.height() / frame.height()])
        for checker in checkers:
            cost = float(checker.getCost())
            profile = np.asarray(checker.getChartsRGB())
            # Mixed patch interiors indicate a skewed box even when median hues happen to match.
            if (not np.isfinite(cost) or cost > .02 or profile.shape != (72, 5)
                    or not np.isfinite(profile).all() or np.quantile(profile[:, 2], .9) > 16):
                continue
            match = _orient(frame, np.asarray(checker.getBox()))
            if match is None:
                continue
            _, centers = match
            centers = (centers + .5) * scale - .5
            for i, (old_cost, old_centers) in enumerate(candidates):
                if _same_chart(centers, old_centers):
                    if cost < old_cost:
                        candidates[i] = (cost, centers)
                    break
            else:
                candidates.append((cost, centers))
    if not candidates:
        raise ValueError("No reliable ColorChecker Classic 24 found.")
    if len(candidates) != 1:
        raise ValueError("Multiple charts found.")
    centers = candidates[0][1]
    grid = patch_centers(centers).reshape(4, 6, 2)
    if min(np.linalg.norm(np.diff(grid, axis=axis), axis=2).min() for axis in (0, 1)) < 20:
        raise ValueError("The chart is too small for reliable automatic sampling.")
    if _quality(image, centers) is None:
        raise ValueError("The full-resolution chart is not reliable.")
    return centers
