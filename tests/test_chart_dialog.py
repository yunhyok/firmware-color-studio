import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColorSpace, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from firmware_color_studio import app, chart_dialog
from firmware_color_studio.chart_fit import reference_srgb
from firmware_color_studio.dcp import read_dcp
from firmware_color_studio.display import rgb_image


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def no_detection(image):
    raise ValueError("No chart candidate")


def outer_conversion(monkeypatch):
    calls = []

    def convert(image, outer):
        calls.append((image, list(outer)))
        return np.array([(30, 30), (330, 30), (330, 210), (30, 210)], dtype=float)

    monkeypatch.setattr(chart_dialog, "centers_from_outer_corners", convert)
    return calls


def test_outer_corner_fallback_autofit_raw_preview_and_export(application, tmp_path, monkeypatch):
    monkeypatch.setattr(chart_dialog, "detect_chart", no_detection)
    conversions = outer_conversion(monkeypatch)
    jpeg = tmp_path / "Donor.jpg"
    colors = reference_srgb().reshape(4, 6, 3)
    tiles = np.repeat(np.repeat(colors, 60, axis=0), 60, axis=1)
    assert rgb_image(tiles).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
    source_bytes = jpeg.read_bytes()
    parent = app.MainWindow()
    parent.raw = SimpleNamespace(rgb=np.full((10, 15, 3), .2), baseline_exposure=0.)
    dialog = chart_dialog.ChartDialog(parent)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    try:
        assert dialog.load_path(jpeg)
        assert dialog.name.text() == "Donor"
        assert dialog.fallback and not dialog.corner_diagram.isHidden()
        assert "바깥" in dialog.guide.text() or "outer" in dialog.guide.text()
        dialog.show()
        application.processEvents()
        outer = [(10, 10), (350, 10), (350, 230), (10, 230)]
        for x, y in outer:
            pos = dialog.view.mapFromScene(QPointF(x + .5, y + .5))
            QTest.mouseClick(dialog.view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        assert np.allclose(dialog.outer_corners, outer, atol=1)
        assert conversions[0][0] is dialog.image
        assert np.allclose(conversions[0][1], outer, atol=1)
        assert dialog.corners != dialog.outer_corners
        assert len(dialog.view.markers) == 24
        assert dialog.save_button.isEnabled(), messages
        assert not dialog.swatches.pixmap().isNull()
        dialog.tabs.setCurrentIndex(1)
        assert not dialog.raw_view.pixmap().isNull(), messages
        # The previous DCP must never be saved under a newly edited name or edition.
        dialog.name.setText("Camera X")
        assert dialog.result is None and not dialog.save_button.isEnabled()
        QTest.qWait(300)
        assert read_dcp(dialog.result.dcp)["ProfileName"] == "Camera X"
        dialog.edition.setCurrentIndex(1)
        assert not dialog.save_button.isEnabled()
        QTest.qWait(300)
        protected = tmp_path / "alias.dcp"
        os.link(jpeg, protected)
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(protected), ""))
        dialog.save_button.click()
        assert messages and jpeg.read_bytes() == source_bytes and dialog.isVisible()
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
        dialog.save_button.click()
        assert dialog.isVisible()
        dest = tmp_path / "result.dcp"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(dest), ""))
        dialog.save_button.click()
        assert dest.read_bytes() == dialog.result.dcp
    finally:
        dialog.close()
        parent.raw = None
        parent.close()


def test_reload_failure_undo_and_reset(application, tmp_path, monkeypatch):
    monkeypatch.setattr(chart_dialog, "detect_chart", no_detection)
    parent = app.MainWindow()
    dialog = chart_dialog.ChartDialog(parent)
    try:
        jpeg = tmp_path / "Chart.jpg"
        image = QImage(120, 80, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        assert image.save(str(jpeg))
        assert dialog.load_path(jpeg)
        dialog.select_corner(10, 10)
        dialog.select_corner(100, 10)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
        broken = tmp_path / "broken.jpg"
        broken.write_bytes(b"corrupt")
        assert not dialog.load_path(broken) and dialog.source == jpeg
        assert dialog.outer_corners == [(10, 10), (100, 10)] and not dialog.corners
        dialog.undo_button.click()
        assert dialog.outer_corners == [(10, 10)]
        dialog.reset_button.click()
        assert not dialog.outer_corners and not dialog.corners and not dialog.save_button.isEnabled()
    finally:
        dialog.close()
        parent.close()


@pytest.mark.parametrize("lang", [0, 1])
def test_automatic_success_has_no_manual_controls_or_hints(application, tmp_path, monkeypatch, lang):
    jpeg = tmp_path / "Automatic.jpg"
    colors = reference_srgb().reshape(4, 6, 3)
    tiles = np.repeat(np.repeat(colors, 60, axis=0), 60, axis=1)
    assert rgb_image(tiles).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
    detected = np.array([(30, 30), (330, 30), (330, 210), (30, 210)], dtype=float)
    images = []

    def detect(image):
        images.append(image)
        return detected

    monkeypatch.setattr(chart_dialog, "detect_chart", detect)
    parent = app.MainWindow()
    parent.lang = lang
    parent.raw = SimpleNamespace(rgb=np.full((10, 15, 3), .2), baseline_exposure=0.)
    # Detection must receive native sRGB, independently of the display's profile.
    parent.display_space = QColorSpace(QColorSpace.NamedColorSpace.AdobeRgb)
    dialog = chart_dialog.ChartDialog(parent)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    try:
        assert dialog.load_path(jpeg)
        assert images == [dialog.image]
        assert images[0].size() == QImage(str(jpeg)).size()
        assert images[0].colorSpace() == QColorSpace(QColorSpace.NamedColorSpace.SRgb)
        assert len(dialog.view.markers) == 24
        assert dialog.result is not None and dialog.save_button.isEnabled()
        assert not dialog.fallback
        assert dialog.undo_button.isHidden() and dialog.reset_button.isHidden()
        assert dialog.corner_diagram.isHidden()
        assert "모서리" not in dialog.guide.text() and "corner" not in dialog.guide.text()
        result = dialog.result
        dialog.select_corner(10, 10)
        dialog.reset()
        dialog.undo()
        assert not dialog.outer_corners and dialog.result is result
        assert not dialog.swatches.pixmap().isNull()
        dialog.tabs.setCurrentIndex(1)
        assert not dialog.raw_view.pixmap().isNull(), messages
        dialog.name.setText("Automatic Rename")
        assert dialog.result is None and not dialog.save_button.isEnabled()
        assert dialog.reset_button.isHidden() and dialog.corner_diagram.isHidden()
        assert "모서리" not in dialog.guide.text() and "corner" not in dialog.guide.text()
        QTest.qWait(300)
        assert read_dcp(dialog.result.dcp)["ProfileName"] == "Automatic Rename"
        old_dcp = dialog.result.dcp
        dialog.edition.setCurrentIndex(1)
        assert not dialog.save_button.isEnabled()
        QTest.qWait(300)
        assert dialog.result.dcp != old_dcp and dialog.save_button.isEnabled()
        dest = tmp_path / "automatic.dcp"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(dest), ""))
        dialog.save_button.click()
        assert read_dcp(dest.read_bytes())["ProfileName"] == "Automatic Rename"
    finally:
        dialog.close()
        parent.raw = None
        parent.close()


def test_consecutive_detection_failure_and_pending_refit_reset(application, tmp_path, monkeypatch):
    outer_conversion(monkeypatch)
    jpeg = tmp_path / "Automatic.jpg"
    colors = reference_srgb().reshape(4, 6, 3)
    tiles = np.repeat(np.repeat(colors, 60, axis=0), 60, axis=1)
    assert rgb_image(tiles).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
    monkeypatch.setattr(chart_dialog, "detect_chart", lambda image: np.array(
        [(30, 30), (330, 30), (330, 210), (30, 210)], dtype=float))
    parent = app.MainWindow()
    parent.lang = 1
    dialog = chart_dialog.ChartDialog(parent)
    try:
        assert dialog.load_path(jpeg) and dialog.result is not None
        dialog.name.setText("Pending")
        assert dialog.refit_timer.isActive()
        monkeypatch.setattr(chart_dialog, "detect_chart", no_detection)
        assert dialog.load_path(jpeg)
        QTest.qWait(300)
        assert not dialog.outer_corners and not dialog.corners and dialog.result is None
        assert not dialog.view.markers and not dialog.save_button.isEnabled()
        assert dialog.swatches.pixmap().isNull()
        assert dialog.guide.text().startswith("Automatic recognition failed.")
        for x, y in [(10, 10), (350, 10), (350, 230), (10, 230)]:
            dialog.select_corner(x, y)
        assert dialog.result is not None
        dialog.undo_button.click()
        assert len(dialog.outer_corners) == 3 and not dialog.corners and dialog.result is None
        dialog.select_corner(10, 230)
        assert dialog.result is not None
        dialog.reset_button.click()
        assert not dialog.outer_corners and dialog.result is None
        assert "outer" in dialog.guide.text()
        monkeypatch.setattr(chart_dialog, "detect_chart", lambda image: np.array(
            [(30, 30), (330, 30), (330, 210), (30, 210)], dtype=float))
        assert dialog.load_path(jpeg) and dialog.result is not None
        assert not dialog.fallback and not dialog.outer_corners
        assert dialog.reset_button.isHidden() and dialog.corner_diagram.isHidden()
        assert "outer" not in dialog.guide.text()
    finally:
        dialog.close()
        parent.close()


def test_fit_failure_after_detection_does_not_request_manual_corners(application, tmp_path, monkeypatch):
    jpeg = tmp_path / "Detected.jpg"
    colors = reference_srgb().reshape(4, 6, 3)
    pixels = np.repeat(np.repeat(colors, 60, axis=0), 60, axis=1)
    assert rgb_image(pixels).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
    centers = np.array([(30, 30), (330, 30), (330, 210), (30, 210)], dtype=float)
    monkeypatch.setattr(chart_dialog, "detect_chart", lambda image: centers)
    real_fit = chart_dialog.fit_chart

    def failed_fit(*args, **kwargs):
        raise ValueError("Fit unavailable")

    monkeypatch.setattr(chart_dialog, "fit_chart", failed_fit)
    parent = app.MainWindow()
    parent.lang = 1
    dialog = chart_dialog.ChartDialog(parent)
    try:
        assert dialog.load_path(jpeg)
        assert not dialog.fallback and np.allclose(dialog.corners, centers)
        assert not dialog.outer_corners and dialog.result is None
        assert dialog.reset_button.isHidden() and dialog.undo_button.isHidden()
        assert dialog.corner_diagram.isHidden()
        assert "corner" not in dialog.guide.text()
        assert "Fit unavailable" in dialog.stats.text()
        assert not dialog.save_button.isEnabled()
        monkeypatch.setattr(chart_dialog, "fit_chart", real_fit)
        dialog.name.setText("Retry via corrected name")
        QTest.qWait(300)
        assert dialog.result is not None and dialog.save_button.isEnabled()
        assert not dialog.fallback and dialog.reset_button.isHidden()
    finally:
        dialog.close()
        parent.close()


@pytest.mark.parametrize("lang", [0, 1])
def test_real_outer_conversion_autofits_after_fourth_click(application, tmp_path, monkeypatch, lang):
    monkeypatch.setattr(chart_dialog, "detect_chart", no_detection)
    jpeg = tmp_path / "Bordered.jpg"
    colors = reference_srgb().reshape(4, 6, 3)
    pixels = np.full((280, 400, 3), .025)
    for row in range(4):
        for column in range(6):
            pixels[25 + row * 60:75 + row * 60, 25 + column * 60:75 + column * 60] = colors[row, column]
    assert rgb_image(pixels).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
    parent = app.MainWindow()
    parent.lang = lang
    dialog = chart_dialog.ChartDialog(parent)
    try:
        assert dialog.load_path(jpeg)
        assert not dialog.corner_diagram.isHidden()
        names = ("짙은 피부색", "청록색", "검정", "흰색") if lang == 0 else (
            "dark skin", "bluish green", "black", "white")
        outer = [(10, 10), (389, 10), (389, 269), (10, 269)]
        for index, (x, y) in enumerate(outer):
            assert names[index] in dialog.guide.text()
            assert dialog.result is None and not dialog.save_button.isEnabled()
            dialog.select_corner(x, y)
        assert dialog.outer_corners == outer
        assert dialog.result is not None and dialog.save_button.isEnabled(), dialog.stats.text()
        assert len(dialog.view.markers) == 24
        assert dialog.corner_diagram.isHidden()
        assert np.allclose(dialog.corners, [(49.5, 49.5), (349.5, 49.5), (349.5, 229.5), (49.5, 229.5)], atol=4)
        dialog.undo_button.click()
        assert len(dialog.outer_corners) == 3 and not dialog.corners
        assert dialog.result is None and not dialog.save_button.isEnabled()
        dialog.select_corner(*outer[-1])
        assert dialog.result is not None and dialog.save_button.isEnabled()
        dialog.reset_button.click()
        for point in [outer[0]] * 4:
            dialog.select_corner(*point)
        assert not dialog.corners and dialog.result is None
        assert not dialog.save_button.isEnabled()
        assert "바깥 모서리" in dialog.guide.text() if lang == 0 else "outer corners" in dialog.guide.text()
        dialog.undo_button.click()
        assert len(dialog.outer_corners) == 3
    finally:
        dialog.close()
        parent.close()


def test_chart_action_defaults_to_jpeg_picker(application, monkeypatch):
    parent = app.MainWindow()
    calls = []
    try:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("donor.jpeg", ""))
        monkeypatch.setattr(parent, "open_chart_path", calls.append)
        parent.actions["chart"].trigger()
        parent.chart_button.click()
        assert calls == ["donor.jpeg", "donor.jpeg"]
    finally:
        parent.close()


def test_explicit_jpeg_startup_opens_chart_window(monkeypatch):
    calls = []
    window = SimpleNamespace(show=lambda: calls.append("show"), open_chart_path=calls.append)
    monkeypatch.setattr(app, "MainWindow", lambda: window)
    monkeypatch.setattr(app, "QApplication", lambda argv: SimpleNamespace(
        setApplicationName=lambda _: None, setStyle=lambda _: None,
        setStyleSheet=lambda _: None, exec=lambda: 0))
    monkeypatch.setattr(app, "QTimer", SimpleNamespace(singleShot=lambda _, callback: callback()))
    monkeypatch.setattr(app.sys, "argv", ["FirmwareColorStudio", "donor.JPEG"])
    assert app.main() == 0
    assert calls == ["show", "donor.JPEG"]
