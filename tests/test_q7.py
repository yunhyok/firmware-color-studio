"""The PENTAX Q7 camera pack.

The integer values asserted here were compared with the firmware routines run in a CPU
emulator (tools/q7/check_port.py); they keep the port from drifting without the firmware.
"""
import hashlib
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from firmware_color_studio import app, cli, dcp, profiles
from firmware_color_studio.engine import Engine, SLIDERS
from firmware_color_studio.q7_engine import MODES, PACK_DIRECTORY, Q7Engine

Q7 = "pentax-q7"
PATCHES = np.array([[0.0625] * 3, [0.18] * 3, [0.5] * 3, [0.2, 0.12, 0.08], [0.06, 0.12, 0.08], [0.05, 0.07, 0.12]])


@pytest.fixture(scope="module")
def engine():
    return Q7Engine.load()


def test_pack_file_matches_its_manifest():
    manifest = json.loads((PACK_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["camera_id"] == Q7 and manifest["camera_model"] == "PENTAX Q7"
    for name, record in manifest["files"].items():
        data = (PACK_DIRECTORY / name).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == (record["bytes"], record["sha256"])
    assert set(manifest["mode_labels_ko"]) == set(MODES)


def test_factory_settings_come_from_the_custom_image_records(engine):
    want = {
        "natural": (0, 0, 0, 0), "bright": (0, 0, 0, 1), "portrait": (0, 0, 0, 0), "landscape": (0, 0, 0, 1),
        "vibrant": (0, 0, 0, 0), "radiant": (0, 0, 2, 3), "muted": (0, 0, 4, -3), "bleach-bypass": (0, 0, -4, 4),
        "reversal-film": (0, 0, 0, 0), "monochrome": (0, 0, 0, 0),
    }
    for mode, values in want.items():
        factory = engine.factory_settings(mode)
        assert tuple(factory[name] for name in ("saturation", "hue", "key", "contrast")) == values, mode
        assert factory["highlight"] == factory["shadow"] == 0
    assert [engine.factory_toning(mode) for mode in ("muted", "bleach-bypass", "natural")] == [0, 1, 0]
    assert {mode: entry["id"] for mode, entry in engine.modes.items()} == {
        "natural": 0, "bright": 1, "portrait": 2, "landscape": 3, "vibrant": 4, "muted": 5, "reversal-film": 6,
        "bleach-bypass": 7, "radiant": 8, "monochrome": 10}


def test_controls_per_custom_image(engine):
    offered = {mode: {name for name in SLIDERS if entry["sliders"][name] == "slider"} for mode, entry in engine.modes.items()}
    assert offered["natural"] == offered["radiant"] == {"saturation", "hue", "key", "contrast"}
    assert offered["muted"] == offered["bleach-bypass"] == {"saturation", "key", "contrast"}
    assert offered["monochrome"] == {"key", "contrast"}
    assert offered["reversal-film"] == set()
    assert engine.settings("natural", highlight=3, shadow=-2, hue=1)["highlight"] == 0
    assert engine.settings("muted", hue=3)["hue"] == 0
    with pytest.raises(ValueError):
        engine.settings("natural", saturation=5)


def test_colour_matrix_values(engine):
    assert engine.color_matrix("natural") == [352, -108, 12, -85, 403, -62, 0, -135, 391]
    assert engine.color_matrix("bright", 2) == [465, -178, -31, -130, 528, -142, -23, -267, 546]
    for mode, entry in engine.modes.items():
        for saturation in range(-4, 5):
            matrix = engine.color_matrix(mode, saturation)
            assert [sum(matrix[3 * row:3 * row + 3]) for row in range(3)] == [256] * 3      # white stays white
    # Monochrome: three equal rows before the diagonal is replaced, which moves each by at most one step.
    assert engine.color_matrix("monochrome") == [56, 189, 11, 55, 190, 11, 55, 189, 12]


def test_yc_and_chroma_offsets(engine):
    assert engine.yc("natural") == [77, 150, 29, -43, -85, 128, 128, -107, -21]
    assert engine.yc("natural", 3, adobe_rgb=True) == [55, 173, 28, -42, -82, 125, 87, -83, -4]
    assert engine.yc("bleach-bypass", 3) == engine.yc("bleach-bypass", 0)                   # no hue control
    k3 = Engine.load().tables["toning"]["chroma_offsets"]["srgb"]
    assert [list(engine.chroma_offset("muted", toning)) for toning in range(9)] == k3       # the K-3 III kept these values
    assert engine.chroma_offset("natural", 0) == (0, 0)
    assert engine.chroma_offset("bleach-bypass", 1, "adobergb") == (-9.25, -11.0)


def test_gamma_tables(engine):
    table = engine.gamma("natural")
    assert (len(table), table[0], table[16], table[256], table[1024], table[2048], table[4095]) == (4096, 0, 183, 1917, 3314, 3850, 4095)
    assert table[256] == 4095 * 7552 // 16130                # level 256 is the reference grey, 118/255 after scaling
    assert all(a <= b for a, b in zip(table, table[1:]))
    assert [engine.gamma("bright", 1, 1)[index] for index in (256, 1024)] == [2153, 3518]
    reversal = engine.gamma("reversal-film", 4, -4)
    assert reversal == engine.gamma("reversal-film") and [reversal[index] for index in (256, 1024, 2048)] == [1917, 3627, 4000]
    brighter, darker = engine.gamma("natural", key=2), engine.gamma("natural", key=-2)
    assert brighter[256] > table[256] > darker[256]
    assert engine.gamma("natural", contrast=3)[64] < table[64] < engine.gamma("natural", contrast=-3)[64]


def test_dng_matrices_match_the_published_matrix_of_the_same_sensor(engine):
    # LibRaw colordata.cpp lists this D65 matrix for the Q-S1, which shares the Q7's sensor.
    published = np.array([12995, -5593, -1107, -1879, 10139, 2027, -64, 1233, 4919]).reshape(3, 3) / 10000
    illuminant_a, d65 = engine.dng_color_matrices()
    assert np.abs(d65 - published).max() < 5e-5
    assert np.abs(illuminant_a - d65).max() > 0.1
    assert np.allclose(engine.common_matrix().sum(axis=1), 1.0)


def test_dark_chroma_suppression_only_touches_dark_colours(engine):
    camera = engine.camera("natural")
    plain = engine.camera("natural")
    plain.shadow_chroma = None
    dark, mid, neutral = np.array([0.02, 0.005, 0.005]), np.array([0.3, 0.1, 0.1]), np.array([0.01] * 3)
    assert np.allclose(camera.encode(mid), plain.encode(mid), atol=2e-3)
    assert np.allclose(camera.encode(neutral), plain.encode(neutral), atol=2e-3)
    assert np.ptp(camera.encode(dark)) < np.ptp(plain.encode(dark)) - 0.01


@pytest.mark.parametrize("mode", list(MODES))
def test_profiles_build_and_render_like_the_camera_model(mode):
    recipe = profiles.default_recipe(mode, Q7)
    data, report = profiles.build_profile(recipe)
    assert b"PENTAX Q7\x00" in data and b"K-3" not in data
    assert report["profile_name"].startswith("Q7 Firmware ") and not report["packaged_default"]
    assert dcp.read_dcp(data)["BaselineExposureOffset"] == 0.0
    camera = profiles.camera_for_recipe(recipe)
    assert np.abs(profiles.render_dcp(PATCHES, data) - camera.render(PATCHES)).max() < 0.03


def test_recipes_are_checked_against_the_q7_pack():
    recipe = profiles.default_recipe("natural", Q7)
    assert recipe["camera_id"] == Q7 and recipe["pack_version"] == "1.01-1"
    assert profiles.list_cameras() == {"pentax-k3iii": "PENTAX K-3 Mark III", Q7: "PENTAX Q7"}
    assert set(profiles.list_modes(Q7)) == set(MODES)
    with pytest.raises(ValueError):
        profiles.default_recipe("satobi", Q7)                 # a K-3 Mark III Custom Image
    with pytest.raises(ValueError):
        profiles.validate_recipe({**recipe, "toning": 2})
    with pytest.raises(ValueError):
        profiles.validate_recipe({**recipe, "pack_version": profiles.PACK_VERSION})
    toned = profiles.validate_recipe({**profiles.default_recipe("muted", Q7), "toning": 2})
    with pytest.raises(ValueError):
        profiles.build_profile(toned)                          # needs the DCP + XMP bundle
    k3, _ = profiles.build_profile({**profiles.default_recipe("natural"), "name": "x"})
    assert dcp.read_dcp(k3)["BaselineExposureOffset"] == 0.5


def test_enhanced_bundle_carries_toning():
    from firmware_color_studio.enhanced import build_enhanced, render_enhanced
    recipe = {**profiles.default_recipe("bleach-bypass", Q7), "toning": 1}
    bundle = build_enhanced(recipe)
    assert bundle.report["camera_id"] == Q7 and bundle.report["xmp_filename"].startswith("pentax-q7-bleach-bypass-")
    rendered = render_enhanced(PATCHES[:2], bundle, 0.0)
    assert np.abs(rendered - profiles.camera_for_recipe(recipe).render(PATCHES[:2])).max() < 0.02
    assert rendered[0, 1] > rendered[0, 0]                     # green toning


def test_preview_inputs_between_cameras():
    rgb = np.array([[0.2, 0.2, 0.2], [0.4, 0.1, 0.05]])
    same, baseline = profiles.preview_inputs(rgb, -0.3, profiles.CAMERA_ID)
    assert same is rgb and baseline == -0.3
    converted, baseline = profiles.preview_inputs(rgb, -0.3, Q7)
    assert baseline == pytest.approx(0.2)                      # the tone curve gets the K-3 III pack's level
    assert np.allclose(converted[0], rgb[0])                   # neutral stays neutral
    k3, q7 = (profiles._pack(camera).engine.common_matrix() for camera in (profiles.CAMERA_ID, Q7))
    assert np.allclose(converted @ q7.T, rgb @ k3.T)           # the same linear sRGB through either sensor matrix


def test_verify_covers_the_q7_pack():
    report = cli.verify()
    assert set(report["cameras"][Q7]) == set(MODES)
    assert all(record["render_ok"] for record in report["cameras"][Q7].values())
    assert len({record["sha256"] for record in report["cameras"][Q7].values()}) == len(MODES)


def test_cli_writes_a_q7_recipe_and_exports_it(monkeypatch, tmp_path):
    recipe, output = tmp_path / "bright.json", tmp_path / "bright.dcp"
    monkeypatch.setattr(sys, "argv", ["fcs", "recipe", str(recipe), "--camera", Q7, "--mode", "bright"])
    assert cli.main() == 0
    assert json.loads(recipe.read_text(encoding="utf-8"))["settings"]["contrast"] == 1
    assert cli.main() == 1                                     # never overwrites
    monkeypatch.setattr(sys, "argv", ["fcs", "export", str(recipe), str(output)])
    assert cli.main() == 0
    assert b"PENTAX Q7\x00" in output.read_bytes()


def test_window_switches_camera(monkeypatch):
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(app.STYLE)
    window = app.MainWindow()
    try:
        modes = lambda: [window.mode_list.item(i).data(0x0100) for i in range(window.mode_list.count())]
        assert window.recipe["camera_id"] == profiles.CAMERA_ID and "gold" in modes()
        window.camera.setCurrentIndex(window.camera.findData(Q7))
        assert window.recipe["camera_id"] == Q7 and modes() == list(MODES)
        assert window.reference.count() == len(MODES) and "Q7" in window.file_label.text()
        assert window.controls["highlight"][0].isHidden() and not window.controls["contrast"][0].isHidden()
        window._set_recipe(profiles.default_recipe("bleach-bypass", Q7))
        assert window.tone.isEnabled() and not window.controls["hue"][0].isEnabled()
        shown = []
        monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(args[2]))
        window.import_calibration()
        assert shown == [window.tr_text("other_calibration")]
        window._set_recipe(profiles.default_recipe("satobi"))  # a K-3 Mark III recipe brings its camera back
        assert window.camera.currentData() == profiles.CAMERA_ID and "satobi" in modes()
        assert not window.controls["highlight"][0].isHidden()
        assert app.MainWindow().recipe["camera_id"] == Q7      # the camera chosen in the menu is remembered
    finally:
        window.close()
