import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from firmware_color_studio import app
from firmware_color_studio.app import MainWindow, STYLE, checked_output, render_recipe
from firmware_color_studio.display import rgb_image
from firmware_color_studio.profiles import default_recipe


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    yield app


@pytest.mark.parametrize("raw_arg", [None, "explicit.PEF", "explicit.dng"])
def test_main_loads_explicit_raw_or_bundled_demo_after_show(monkeypatch, raw_arg):
    events = []
    gui = SimpleNamespace(
        setApplicationName=lambda _: None, setStyle=lambda _: None,
        setStyleSheet=lambda _: None, exec=lambda: 0,
    )
    window = SimpleNamespace(
        show=lambda: events.append("show"),
        load_raw_path=lambda path: events.append(Path(path)),
    )
    monkeypatch.setattr(app, "QApplication", lambda _: gui)
    monkeypatch.setattr(app, "MainWindow", lambda: window)
    monkeypatch.setattr(sys, "argv", ["firmware-color-studio"] + ([raw_arg] if raw_arg else []))

    assert app.main() == 0
    assert events == ["show", Path(raw_arg) if raw_arg else app.DEMO_RAW]


def test_controls_keep_recipe_and_visible_settings_together(application):
    window = MainWindow()
    try:
        window._set_recipe(default_recipe("bright"))
        assert window.controls["contrast"][0].value() == 1
        window.controls["key"][1].setValue(2)
        assert window.recipe["settings"]["key"] == 2
        window._reset()
        assert window.recipe["settings"]["key"] == 0
        assert window.recipe["mode"] == "bright"
        window._set_recipe(default_recipe("reversal-film"))
        assert all(not slider.isEnabled() for slider, _ in window.controls.values())
        window._set_recipe(default_recipe("bleach-bypass"))
        assert window.tone.isEnabled()
        assert not window.controls["hue"][0].isEnabled()
        assert window.controls["highlight"][0].isEnabled()
    finally:
        window.close()


def test_late_raw_completion_cannot_replace_newer_image(application):
    window = MainWindow()
    try:
        original = object()
        window.raw = original
        window.generation["raw"] = 2
        window._job_done("raw", 1, object(), None)
        assert window.raw is original
    finally:
        window.raw = None
        window.close()


def test_srgb_display_preserves_black_neutral_and_white(application):
    pixels = np.array([[[0., 0., 0.], [.5, .5, .5], [1., 1., 1.]]])
    image = rgb_image(pixels)
    assert image.colorSpace().isValid()
    assert image.pixelColor(0, 0).red() == 0
    assert image.pixelColor(1, 0).red() == image.pixelColor(1, 0).green() == 128
    assert image.pixelColor(2, 0).red() == 255


def test_failed_raw_load_keeps_the_displayed_image(application, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    window = MainWindow()
    monkeypatch.setattr(window, "_start_job", lambda *args: None)
    try:
        shown = SimpleNamespace(rgb=np.zeros((2, 2, 3), np.float32), warnings=[], metadata={})
        window.raw = shown
        window.preview_cache = {480: shown.rgb}
        window.load_raw_path("unsupported.dng")
        assert window.raw is shown
        window._job_done("raw", window.generation["raw"], None, ("Unsupported camera model", ""))
        assert window.raw is shown
        assert window.preview_cache
        loaded = SimpleNamespace(rgb=shown.rgb, warnings=["note"], metadata={
            "path": "next.dng", "model": "PENTAX K-3 Mark III", "width": 2, "height": 2})
        previews, thumbs = window.generation["preview"], window.generation["thumbs"]
        window.load_raw_path("next.dng")
        window._job_done("raw", window.generation["raw"], loaded, None)
        assert window.raw is loaded
        assert window.preview_cache == {}
        assert window.generation["preview"] > previews and window.generation["thumbs"] > thumbs
    finally:
        window.raw = None
        window.close()


@pytest.mark.parametrize("method", ["save_current_recipe", "export_profile"])
def test_gui_refuses_raw_as_save_target(application, tmp_path, monkeypatch, method):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    raw = tmp_path / "untouched.DNG"
    raw.write_bytes(b"original RAW")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(raw), ""))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    window = MainWindow()
    try:
        getattr(window, method)()
        assert warnings
        assert not window.jobs
        assert raw.read_bytes() == b"original RAW"
    finally:
        window.close()


def test_output_refuses_input_alias(tmp_path):
    raw = tmp_path / "input.DNG"
    raw.write_bytes(b"original")
    alias = tmp_path / "alias.dcp"
    os.link(raw, alias)
    with pytest.raises(ValueError, match="input file"):
        checked_output(alias, ".dcp", [raw])


def test_gold_and_toning_select_enhanced(application):
    window = MainWindow()
    try:
        window._set_recipe(default_recipe("gold"))
        assert window.output_format.currentData() == "xmp"
        assert not window.output_format.model().item(0).isEnabled()
        recipe = default_recipe("bleach-bypass")
        recipe["toning"] = 3
        window._set_recipe(recipe)
        assert window.output_format.currentData() == "xmp"
        window._set_recipe(default_recipe())
        assert window.output_format.model().item(0).isEnabled()
        # Only the selection that Gold or toning forced is undone.
        assert window.output_format.currentData() == "dcp"
        window.output_format.setCurrentIndex(1)
        window._set_recipe(default_recipe("gold"))
        window._set_recipe(default_recipe())
        assert window.output_format.currentData() == "xmp"
        window.language.setCurrentIndex(1)
        assert window.rendition.text().startswith("DCP + XMP")
        window.output_format.setCurrentIndex(0)
        window.language.setCurrentIndex(0)
        assert window.rendition.text().startswith("DCP 미리보기")
    finally:
        window.close()


def test_gold_reference_renders():
    result, report = render_recipe(np.full((2, 3, 3), .2), default_recipe("gold"), -.5)
    assert result.shape == (2, 3, 3)
    assert np.isfinite(result).all()


def test_one_export_at_a_time(application, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    calls = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "test.dcp"), ""))
    window = MainWindow()
    monkeypatch.setattr(window, "_start_job", lambda *args: calls.append(args))
    try:
        window.export_profile()
        window.export_profile()
        assert len(calls) == 1
        assert not window.export_button.isEnabled()
        window._job_done("export", window.generation["export"], "saved", None)
        assert not window.export_running
        assert window.export_button.isEnabled()
    finally:
        window.close()


def test_color_space_change_refreshes_default_thumbnails(application, monkeypatch):
    window = MainWindow()
    calls = []
    monkeypatch.setattr(window, "_thumbnails", lambda: calls.append(window.recipe["color_space"]))
    try:
        window.space.setCurrentIndex(1)
        assert calls == ["adobergb"]
        window._set_recipe(default_recipe())
        assert calls == ["adobergb", "srgb"]
    finally:
        window.close()


def test_dropped_chart_jpeg_opens_after_the_drop_returns(application, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    from firmware_color_studio import app as app_module

    window = MainWindow()
    opened, deferred = [], []
    monkeypatch.setattr(window, "open_chart_path", opened.append)
    monkeypatch.setattr(app_module, "QTimer", SimpleNamespace(singleShot=lambda delay, call: deferred.append(call)))
    try:
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile("/photos/donor.JPG")])
        window.dropEvent(SimpleNamespace(mimeData=lambda: data))
        # A modal dialog inside the drop would keep the dragging application waiting.
        assert not opened and len(deferred) == 1
        deferred[0]()
        assert opened == ["/photos/donor.JPG"]
    finally:
        window.close()


def test_menu_title_and_demo_label_follow_the_language(application):
    from firmware_color_studio.cli import DEMO_RAW

    window = MainWindow()
    try:
        window.language.setCurrentIndex(0)
        assert window.file_menu.title() == "파일"
        window.raw = SimpleNamespace(rgb=None, warnings=[], metadata={
            "path": str(DEMO_RAW), "model": "PENTAX K-3 Mark III", "width": 3096, "height": 2064})
        window.language.setCurrentIndex(1)
        assert window.file_menu.title() == "File"
        assert window.file_label.text().startswith("Demo photo · color-cube.dng")
        window.raw.metadata["path"] = "/photos/IMGP0001.PEF"
        window.language.setCurrentIndex(0)
        assert window.file_label.text().startswith("IMGP0001.PEF")
        assert window.chart_button.toolTip()
    finally:
        window.raw = None
        window.close()
