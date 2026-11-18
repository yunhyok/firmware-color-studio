"""Exercise actual offline MCC, including coordinate and orientation contracts."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from firmware_color_studio import chart_detect
from firmware_color_studio.chart_fit import reference_srgb
from firmware_color_studio.chart_input import load_chart_jpeg, sample_chart


def qimage(pixels):
    pixels = np.ascontiguousarray(pixels, dtype=np.uint8)
    return QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0],
                  QImage.Format.Format_RGB888).copy()


def chart(patches=None):
    patches = reference_srgb() if patches is None else patches
    pixels = np.full((600, 900, 3), 120, np.uint8)
    pixels[80:530, 100:770] = 20
    for i, color in enumerate(np.rint(patches * 255).astype(np.uint8)):
        x, y = 110 + (i % 6) * 110, 90 + (i // 6) * 110
        pixels[y:y + 100, x:x + 100] = color
    return pixels, np.array([[160., 140.], [710., 140.], [710., 470.], [160., 470.]])


@pytest.mark.parametrize("turns", range(4))
@pytest.mark.parametrize("mirror", [False, True])
def test_actual_detector_orders_rotated_and_mirrored_patch_centers(turns, mirror):
    pixels, expected = chart()
    for _ in range(turns):
        expected = np.column_stack((expected[:, 1], pixels.shape[1] - 1 - expected[:, 0]))
        pixels = np.rot90(pixels)
    if mirror:
        expected[:, 0] = pixels.shape[1] - 1 - expected[:, 0]
        pixels = pixels[:, ::-1]
    image = qimage(pixels)
    result = chart_detect.detect_chart(image)
    assert result.shape == (4, 2)
    np.testing.assert_allclose(result, expected, atol=20)
    np.testing.assert_allclose(sample_chart(image, result), reference_srgb(), atol=1 / 255)


def test_perspective_and_full_resolution_coordinates():
    pixels, expected = chart()
    matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [899, 0], [899, 599], [0, 599]]),
                                        np.float32([[90, 40], [1000, 130], [920, 720], [40, 560]]))
    pixels = cv2.warpPerspective(pixels, matrix, (1100, 800), borderValue=(100, 100, 100))
    expected = cv2.perspectiveTransform(expected[None], matrix)[0]
    pixels = cv2.resize(pixels, None, fx=4, fy=4)
    expected = (expected + .5) * 4 - .5
    image = qimage(pixels)
    result = chart_detect.detect_chart(image)
    np.testing.assert_allclose(result, expected, atol=65)
    np.testing.assert_allclose(sample_chart(image, result), reference_srgb(), atol=1 / 255)


def test_two_distinct_real_detections_are_rejected():
    pixels, _ = chart()
    with pytest.raises(ValueError, match="Multiple"):
        chart_detect.detect_chart(qimage(np.hstack((pixels, pixels))))


@pytest.mark.parametrize("kind", ["plain", "noise", "gray", "scrambled", "low_contrast"])
def test_no_chart_and_unreliable_color_arrangements_are_rejected(kind):
    ref = reference_srgb()
    if kind == "plain":
        pixels = np.full((600, 900, 3), 120, np.uint8)
    elif kind == "noise":
        pixels = np.random.default_rng(22).integers(0, 256, (600, 900, 3), dtype=np.uint8)
    elif kind == "gray":
        pixels, _ = chart(np.repeat(ref.mean(axis=1, keepdims=True), 3, axis=1))
    elif kind == "scrambled":
        ref[:18] = ref[:18][::-1]
        pixels, _ = chart(ref)
    else:
        pixels, _ = chart(.5 + .05 * (ref - .5))
    with pytest.raises(ValueError):
        chart_detect.detect_chart(qimage(pixels))


def test_null_and_tiny_images_are_rejected():
    for image in (QImage(), qimage(np.zeros((30, 40, 3), np.uint8))):
        with pytest.raises(ValueError, match="larger"):
            chart_detect.detect_chart(image)


def test_upscaling_does_not_make_a_tiny_chart_acceptable():
    pixels, _ = chart()
    pixels = cv2.resize(pixels, (90, 60), interpolation=cv2.INTER_AREA)
    pixels = np.pad(pixels, ((20, 20), (20, 20), (0, 0)), constant_values=120)
    with pytest.raises(ValueError):
        chart_detect.detect_chart(qimage(pixels))


class Checker:
    def __init__(self, box):
        self.box = np.asarray(box, np.float32)

    def getBox(self):
        return self.box

    def getCost(self):
        return .001

    def getChartsRGB(self):
        return np.zeros((72, 5))


def fake_detector(monkeypatch, boxes):
    class Detector:
        def process(self, *args, **kwargs):
            return True

        def getListColorChecker(self):
            return [Checker(box) for box in boxes]

    monkeypatch.setattr(chart_detect.cv2.mcc, "CCheckerDetector_create", Detector)


def test_duplicate_detections_and_mcc_wrong_winding_are_resolved(monkeypatch):
    pixels, expected = chart()
    box = np.array([[100, 80], [770, 80], [770, 530], [100, 530]], np.float32)
    fake_detector(monkeypatch, [box, np.roll(box, 2, axis=0), box[::-1], box + [2, -1]])
    np.testing.assert_allclose(chart_detect.detect_chart(qimage(pixels)), expected, atol=.001)


@pytest.mark.parametrize("box", [np.zeros((4, 2)), np.full((4, 2), np.nan),
                                [[-500, -500], [0, 0], [500, 500], [100, 100]]])
def test_invalid_detector_geometry_is_rejected(monkeypatch, box):
    pixels, _ = chart()
    fake_detector(monkeypatch, [box])
    with pytest.raises(ValueError, match="No reliable"):
        chart_detect.detect_chart(qimage(pixels))


def test_mixed_patch_interiors_are_rejected_even_when_medians_match(monkeypatch):
    pixels, _ = chart()
    fake_detector(monkeypatch, [[[100, 80], [770, 80], [770, 530], [100, 530]]])
    profile = np.zeros((72, 5))
    profile[:, 2] = 30
    monkeypatch.setattr(Checker, "getChartsRGB", lambda self: profile)
    with pytest.raises(ValueError, match="No reliable"):
        chart_detect.detect_chart(qimage(pixels))


@pytest.mark.parametrize("name", ["chart", "natural"])
def test_local_small_still_life_chart_does_not_return_a_skewed_grid(name):
    root = Path(__file__).resolve().parents[1] / ".research/chart-v020/lightroom/output/live"
    path = root / name / "K3IIIhSLI0000100NR0.tif"
    if not path.is_file():
        pytest.skip("Local physical still-life photograph is not distributed")
    with pytest.raises(ValueError):
        chart_detect.detect_chart(QImage(str(path)))


def test_mcc_gets_bgr_and_bounded_frames_with_no_internal_enlargement(monkeypatch):
    seen = []

    class Detector:
        def process(self, bgr, chart_type, *, nc, params):
            seen.append(bgr.shape)
            assert max(bgr.shape[:2]) <= 1400
            assert params.minImageSize == 0
            assert nc > 1 and chart_type == cv2.mcc.MCC24
            np.testing.assert_array_equal(bgr[0, 0], [233, 67, 19])
            return False

    monkeypatch.setattr(chart_detect.cv2.mcc, "CCheckerDetector_create", Detector)
    image = QImage(6001, 4000, QImage.Format.Format_RGB888)
    image.fill(QColor(19, 67, 233))
    with pytest.raises(ValueError, match="No reliable"):
        chart_detect.detect_chart(image)
    assert len(seen) == 2


@pytest.mark.parametrize("name", ["opencv-chart.jpg", "ColorChecker100423.jpg"])
@pytest.mark.parametrize("scale", [1, .5])
def test_local_real_donors_match_independent_manual_patch_samples(name, scale):
    root = Path(__file__).resolve().parents[1] / ".research" / "chart-v020"
    if not (root / name).is_file() or not (root / "cases.json").is_file():
        pytest.skip("Local real donor photographs are not distributed with the application")
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    image = load_chart_jpeg(root / name).image
    expected = np.asarray(cases[name]["corners"], float)
    if scale != 1:
        image = image.scaled(round(image.width() * scale), round(image.height() * scale))
        expected = (expected + .5) * scale - .5
    result = chart_detect.detect_chart(image)
    pitch = np.linalg.norm(expected[1] - expected[0]) / 5
    assert np.linalg.norm(result - expected, axis=1).max() < .2 * pitch
    manual = sample_chart(image, expected)
    np.testing.assert_allclose(sample_chart(image, result), manual, atol=5 / 255)
