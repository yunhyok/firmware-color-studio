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

    monkeypatch.setattr(chart_dialog, "orient_outer_corners", convert)
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
    parent.raw = SimpleNamespace(rgb=np.full((10, 15, 3), .2), baseline_exposure=0., metadata={"camera_id": "pentax-k3iii"})
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
        # Renaming keeps the estimate and the RAW preview on screen; Save writes the name then shown.
        shown = dialog.result
        dialog.name.setText("Camera X")
        assert dialog.result is shown and dialog.save_button.isEnabled()
        assert dialog.tabs.currentIndex() == 1 and not dialog.swatches.pixmap().isNull()
        dialog.name.setText("  ")
        assert dialog.result is shown and not dialog.save_button.isEnabled()
        assert "이름" in dialog.guide.text() or "name" in dialog.guide.text()
        dialog.name.setText("Camera X")
        # Another edition is another estimate; the preview follows it without leaving its tab.
        dialog.edition.setCurrentIndex(1)
        assert dialog.result is not shown and dialog.save_button.isEnabled()
        assert dialog.tabs.currentIndex() == 1
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
        assert read_dcp(dest.read_bytes())["ProfileName"] == "Camera X"
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
    parent.raw = SimpleNamespace(rgb=np.full((10, 15, 3), .2), baseline_exposure=0., metadata={"camera_id": "pentax-k3iii"})
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
        assert dialog.result is result and dialog.save_button.isEnabled()
        assert dialog.tabs.currentIndex() == 1
        assert dialog.reset_button.isHidden() and dialog.corner_diagram.isHidden()
        assert "모서리" not in dialog.guide.text() and "corner" not in dialog.guide.text()
        old_dcp = dialog.result.dcp
        dialog.edition.setCurrentIndex(1)
        assert dialog.result.dcp != old_dcp and dialog.save_button.isEnabled()
        dest = tmp_path / "automatic.dcp"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(dest), ""))
        dialog.save_button.click()
        assert read_dcp(dest.read_bytes())["ProfileName"] == "Automatic Rename"
    finally:
        dialog.close()
        parent.raw = None
        parent.close()


def test_consecutive_detection_failure_resets_the_previous_estimate(application, tmp_path, monkeypatch):
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
        monkeypatch.setattr(chart_dialog, "detect_chart", no_detection)
        assert dialog.load_path(jpeg)
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
        dialog.edition.setCurrentIndex(1)
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


def bordered_chart(tmp_path, turns=0):
    colors = reference_srgb().reshape(4, 6, 3)
    pixels = np.full((280, 400, 3), .025)
    for row in range(4):
        for column in range(6):
            pixels[25 + row * 60:75 + row * 60, 25 + column * 60:75 + column * 60] = colors[row, column]
    jpeg = tmp_path / "Bordered.jpg"
    turned = np.rot90(pixels, turns).copy()
    assert rgb_image(turned).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
    return jpeg, turned.shape[1], turned.shape[0]


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (1, 2, 3, 0), (2, 3, 0, 1), (0, 3, 2, 1), (0, 2, 1, 3), (3, 1, 0, 2)])
@pytest.mark.parametrize("turns", [0, 1, 2])
def test_outer_corners_in_any_order_follow_the_printed_arrangement(application, tmp_path, monkeypatch, order, turns):
    monkeypatch.setattr(chart_dialog, "detect_chart", no_detection)
    jpeg, width, height = bordered_chart(tmp_path, turns)
    parent = app.MainWindow()
    dialog = chart_dialog.ChartDialog(parent)
    try:
        assert dialog.load_path(jpeg)
        outer = [(10, 10), (width - 11, 10), (width - 11, height - 11), (10, height - 11)]
        for index in order:
            dialog.select_corner(*outer[index])
        assert dialog.result is not None and dialog.save_button.isEnabled(), dialog.stats.text()
        # Whatever was clicked first, patch 1 is dark skin and patch 19 is white.
        np.testing.assert_allclose(dialog.patches, reference_srgb(), atol=4 / 255)
        assert dialog.corner_diagram.isHidden() and len(dialog.view.markers) == 24
    finally:
        dialog.close()
        parent.close()


@pytest.mark.parametrize("lang", [0, 1])
def test_unreadable_arrangement_keeps_the_clicked_order_and_explains_failure(application, tmp_path, monkeypatch, lang):
    monkeypatch.setattr(chart_dialog, "detect_chart", no_detection)
    jpeg = tmp_path / "Monochrome.jpg"
    gray = np.repeat(reference_srgb().mean(axis=1, keepdims=True), 3, axis=1).reshape(4, 6, 3)
    pixels = np.full((280, 400, 3), .025)
    for row in range(4):
        for column in range(6):
            pixels[25 + row * 60:75 + row * 60, 25 + column * 60:75 + column * 60] = gray[row, column]
    assert rgb_image(pixels).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
    parent = app.MainWindow()
    parent.lang = lang
    dialog = chart_dialog.ChartDialog(parent)
    try:
        assert dialog.load_path(jpeg)
        outer = [(10, 10), (389, 10), (389, 269), (10, 269)]
        for index in (0, 1, 2, 3):
            dialog.select_corner(*outer[index])
        # Hue cannot identify a monochrome chart, so the documented click order decides.
        assert dialog.result is not None
        np.testing.assert_allclose(dialog.patches, gray.reshape(24, 3), atol=4 / 255)
        dialog.reset_button.click()
        for index in (2, 3, 0, 1):
            dialog.select_corner(*outer[index])
        assert dialog.result is None and not dialog.save_button.isEnabled()
        assert not dialog.corner_diagram.isHidden() and "①→④" in dialog.guide.text()
        assert ("회색 여섯 칸" if lang == 0 else "six gray patches") in dialog.stats.text()
    finally:
        dialog.close()
        parent.close()


def test_enter_in_the_name_field_saves_instead_of_opening_another_jpeg(application, tmp_path, monkeypatch):
    jpeg, _, _ = bordered_chart(tmp_path)
    monkeypatch.setattr(chart_dialog, "detect_chart", lambda image: np.array(
        [(49.5, 49.5), (349.5, 49.5), (349.5, 229.5), (49.5, 229.5)]))
    asked = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (asked.append("open") or ("", "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (asked.append("save") or ("", "")))
    parent = app.MainWindow()
    dialog = chart_dialog.ChartDialog(parent)
    try:
        assert dialog.load_path(jpeg)
        dialog.show()
        application.processEvents()
        dialog.name.setFocus()
        QTest.keyClick(dialog.name, Qt.Key.Key_Return)
        assert asked == ["save"]
        dialog.name.clear()
        QTest.keyClick(dialog.name, Qt.Key.Key_Return)
        assert asked == ["save"]
    finally:
        dialog.close()
        parent.close()


def test_several_charts_and_unfitted_results_are_explained(application, tmp_path, monkeypatch):
    jpeg, _, _ = bordered_chart(tmp_path)

    def several(image):
        raise chart_dialog.MultipleCharts("Multiple charts found.")

    monkeypatch.setattr(chart_dialog, "detect_chart", several)
    parent = app.MainWindow()
    parent.lang = 1
    dialog = chart_dialog.ChartDialog(parent)
    try:
        assert dialog.load_path(jpeg)
        assert dialog.fallback and dialog.guide.text().startswith("Several charts are visible.")
        for point in [(10, 10), (389, 10), (389, 269), (10, 269)]:
            dialog.select_corner(*point)
        # These patches are the nominal colors, so a fitted look cannot improve on the plain profile.
        assert not dialog.result.fitted
        assert "uncorrected profile" in dialog.stats.text() and "→" not in dialog.stats.text()
        fit = dialog.result
        improved = type(fit)(fit.dcp, fit.predicted_srgb, 4.0, 9.0)
        monkeypatch.setattr(chart_dialog, "fit_chart", lambda *args, **kwargs: improved)
        dialog.edition.setCurrentIndex(1)
        assert "9.0 before → 4.0 after fitting" in dialog.stats.text()
    finally:
        dialog.close()
        parent.close()


def test_korean_messages_cover_existing_error_texts():
    from pathlib import Path
    import firmware_color_studio

    package = Path(firmware_color_studio.__file__).parent
    source = (package / "chart_input.py").read_text(encoding="utf-8") + (package / "chart_fit.py").read_text(encoding="utf-8")
    for english in chart_dialog._KOREAN:
        assert english in source


def test_builtin_look_needs_no_jpeg_and_a_jpeg_replaces_it(application, tmp_path, monkeypatch):
    parent = app.MainWindow()
    parent.raw = SimpleNamespace(rgb=np.full((10, 15, 3), .2), baseline_exposure=0., metadata={"camera_id": "pentax-k3iii"})
    dialog = chart_dialog.ChartDialog(parent)
    monkeypatch.setattr(chart_dialog.QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "look.dcp"), ""))
    try:
        assert dialog.looks.count() == 7 and not dialog.save_button.isEnabled()
        dialog.choose_look(2)
        assert dialog.name.text() == "Sony DSC-P200" and dialog.result is not None and dialog.save_button.isEnabled()
        assert not dialog.edition.isEnabled() and not dialog.fallback and dialog.source is None
        assert not dialog.swatches.pixmap().isNull() and dialog.tabs.isTabEnabled(1)
        dialog.tabs.setCurrentIndex(1)
        assert not dialog.raw_view.pixmap().isNull()
        dialog.save()
        assert read_dcp((tmp_path / "look.dcp").read_bytes())["ProfileName"] == "Sony DSC-P200"
        # A chart JPEG takes over again.
        jpeg = tmp_path / "Donor.jpg"
        tiles = np.repeat(np.repeat(reference_srgb().reshape(4, 6, 3), 60, axis=0), 60, axis=1)
        assert rgb_image(tiles).convertToFormat(QImage.Format.Format_RGB888).save(str(jpeg), quality=98)
        monkeypatch.setattr(chart_dialog, "detect_chart", lambda image: np.array([(30, 30), (330, 30), (330, 210), (30, 210)], float))
        assert dialog.load_path(jpeg)
        assert dialog.look is None and dialog.looks.currentIndex() == 0 and dialog.edition.isEnabled()
        assert dialog.name.text() == "Donor" and dialog.result is not None
    finally:
        dialog.close()
        parent.close()
