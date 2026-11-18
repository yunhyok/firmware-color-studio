import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from firmware_color_studio import app, chart_dialog
from firmware_color_studio.chart_fit import reference_srgb
from firmware_color_studio.dcp import read_dcp
from firmware_color_studio.display import rgb_image


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def test_corner_picking_estimate_raw_preview_and_export(application, tmp_path, monkeypatch):
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
        dialog.show()
        application.processEvents()
        for x, y in [(30, 30), (330, 30), (330, 210), (30, 210)]:
            pos = dialog.view.mapFromScene(QPointF(x + .5, y + .5))
            QTest.mouseClick(dialog.view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        assert len(dialog.view.markers) == 24
        assert dialog.fit_button.isEnabled() and not dialog.save_button.isEnabled()
        dialog.fit_button.click()
        assert dialog.save_button.isEnabled(), messages
        assert not dialog.swatches.pixmap().isNull()
        dialog.tabs.setCurrentIndex(1)
        assert not dialog.raw_view.pixmap().isNull(), messages
        # The previous DCP must never be saved under a newly edited name or edition.
        dialog.name.setText("Camera X")
        assert dialog.result is None and not dialog.save_button.isEnabled()
        dialog.fit_button.click()
        assert read_dcp(dialog.result.dcp)["ProfileName"] == "Camera X"
        dialog.edition.setCurrentIndex(1)
        assert not dialog.save_button.isEnabled()
        dialog.fit_button.click()
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
        assert dialog.corners == [(10, 10), (100, 10)]
        dialog.undo_button.click()
        assert dialog.corners == [(10, 10)]
        dialog.reset_button.click()
        assert not dialog.corners and not dialog.fit_button.isEnabled()
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
