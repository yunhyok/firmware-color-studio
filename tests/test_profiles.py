"""Firmware-free tests of the public K-3 III camera pack and profile contract."""

from copy import deepcopy
from hashlib import sha256
import json
import struct

import numpy as np
import pytest

from firmware_color_studio import dcp, profiles
from firmware_color_studio.engine import PACK_DIRECTORY, SLIDERS


@pytest.mark.parametrize("mode", list(profiles.LABELS))
def test_defaults_match_the_camera_pack_and_can_be_regenerated(mode):
    manifest = json.loads((PACK_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_revision"] == "aa885bcdaee874d9b9bb18663dd62ed10263eda2"
    assert manifest["pack_version"] == profiles.PACK_VERSION
    recipe = profiles.default_recipe(mode)
    packed, report = profiles.build_profile(recipe)
    filename = manifest["default_profiles"][mode]
    record = manifest["files"][filename]
    template = (PACK_DIRECTORY / filename).read_bytes()
    assert record["sha256"] == report["default_template_sha256"] == sha256(template).hexdigest()
    assert record["bytes"] == len(template)
    assert report["dcp_sha256"] == sha256(packed).hexdigest()
    assert report["dcp_bytes"] == len(packed)
    entry = dcp._directory(template)[dcp.TAGS["ProfileName"]][0]
    assert packed[:entry + 4] == template[:entry + 4]
    assert packed[entry + 12:len(template)] == template[entry + 12:]
    assert report["packaged_default"]
    assert report["requested_settings"] == recipe["settings"]
    assert report["factory_toning_left_out"] == {"bleach-bypass": 1, "harubeni": 4}.get(mode, 0)

    label = f'{profiles.LABELS[mode]} ({manifest["mode_labels_ko"][mode]})'
    name = f"K-3 III Firmware {label}"
    assert report["profile_name"] == name
    rebuilt, rebuilt_report = profiles.build_profile({**recipe, "name": "Regenerated"})
    assert not rebuilt_report["packaged_default"]
    a, b = dcp.read_dcp(packed), dcp.read_dcp(rebuilt)
    assert a["ProfileName"] == name
    assert b["ProfileName"] == f"{label} · Regenerated"
    assert a["BaselineExposureOffset"] == b["BaselineExposureOffset"] == 0.5
    assert a["DefaultBlackRender"] == b["DefaultBlackRender"] == 1
    assert (a["LookTable"].hue, a["LookTable"].sat, a["LookTable"].val) == (90, 30, 30)
    assert a["LookTable"].encoding == b["LookTable"].encoding == 1
    # The upstream reproducibility check allows last-bit differences between NumPy builds.
    for key in ("ForwardMatrix1", "ForwardMatrix2", "ColorMatrix1", "ColorMatrix2", "curve_x", "curve_y"):
        np.testing.assert_allclose(a[key], b[key], rtol=0, atol=2e-6)
    np.testing.assert_allclose(a["LookTable"].data, b["LookTable"].data, rtol=0, atol=2e-5)


def test_mode_information_is_detached_and_fixed_controls_use_effective_settings():
    records = profiles.list_modes()
    assert {mode for mode, record in records.items() if record["plain_dcp"]} == set(profiles.LABELS)
    assert not records["gold"]["plain_dcp"]
    assert records["bright"]["defaults"]["contrast"] == 1
    assert records["bright"]["label"] == "Bright (선명하게)"
    assert records["natural"]["label"] == "Natural (자연스럽게)"
    assert records["vibrant"]["label"] == "Vibrant (강렬 색감)"
    assert records["radiant"]["label"] == "Radiant (팝튠)"
    assert records["gold"]["label"] == "Gold (골드)"
    assert records["flat"]["defaults"]["contrast"] == -4
    assert set(records["natural"]["defaults"]) == set(SLIDERS)
    assert all(records["natural"]["controls"].values())
    assert not any(records["reversal-film"]["controls"].values())
    assert {mode for mode, info in records.items() if info["toning"]} == {"muted", "bleach-bypass", "harubeni"}
    records["natural"]["defaults"]["saturation"] = 4
    assert profiles.default_recipe()["settings"]["saturation"] == 0

    recipe = profiles.default_recipe("reversal-film")
    recipe["settings"]["contrast"] = -4
    data, report = profiles.build_profile(recipe)
    assert data == profiles.build_profile(profiles.default_recipe("reversal-film"))[0]
    assert report["requested_settings"]["contrast"] == -4
    assert report["effective_settings"]["contrast"] == 0
    assert report["profile_name"] == "K-3 III Firmware Reversal Film (리버설 필름)"


def test_custom_name_color_space_calibration_and_settings():
    recipe = profiles.default_recipe("bright")
    calibration = [
        [[0.73, -0.12, -0.14], [-0.42, 1.33, 0.27], [-0.03, 0.12, 0.61]],
        [[0.71, -0.15, -0.10], [-0.44, 1.31, 0.27], [-0.06, 0.13, 0.55]],
    ]
    recipe.update(color_space="adobergb", calibration=calibration)
    recipe["settings"]["contrast"] = 0
    assert profiles.profile_name(recipe) == "K-3 III Firmware Bright (선명하게) con+0 (AdobeRGB)"
    recipe["name"] = "활기 +1"
    data, report = profiles.build_profile(recipe)
    parsed = dcp.read_dcp(data)
    assert report["profile_name"] == parsed["ProfileName"] == "Bright (선명하게) · 활기 +1"
    assert not report["packaged_default"]
    assert report["color_space"] == "adobergb"
    assert report["effective_settings"]["contrast"] == 0
    np.testing.assert_allclose(parsed["ColorMatrix1"], calibration[0], rtol=0, atol=1e-6)
    np.testing.assert_allclose(parsed["ColorMatrix2"], calibration[1], rtol=0, atol=1e-6)
    assert data == profiles.build_profile(recipe)[0]


@pytest.mark.parametrize("space", ["srgb", "adobergb"])
def test_full_firmware_toning_changes_neutrals_and_plain_dcp_rejects_it(space):
    recipe = profiles.default_recipe("bleach-bypass")
    recipe["color_space"] = space
    sample = np.full(3, 0.125)
    plain = profiles.camera_for_recipe(recipe).render(sample)
    recipe["toning"] = 1
    green = profiles.camera_for_recipe(recipe).render(sample)
    assert np.ptp(plain) < 1e-3
    assert green[1] - green[0] > 0.01
    with pytest.raises(ValueError, match="toning.*enhanced profile"):
        profiles.build_profile(recipe)


@pytest.mark.parametrize("changes", [
    {"schema_version": True},
    {"schema_version": 2},
    {"camera_id": "different-camera"},
    {"pack_version": "2.19-1"},
    {"mode": []},
    {"mode": "auto"},
    {"color_space": "sRGB"},
    {"color_space": {}},
    {"toning": 9},
    {"toning": True},
    {"toning": 1},
    {"name": "broken\0name"},
    {"name": "a" * 1025},
    {"calibration": [[[1, 0, 0]]]},
    {"calibration": [[[0] * 3 for _ in range(3)]] * 2},
    {"calibration": [[[float("inf")] * 3 for _ in range(3)]] * 2},
    {"calibration": [[[10**1500] * 3 for _ in range(3)]] * 2},
    {"runtime": {"arbitrary_gain": 1}},
    {"extra": "unexpected"},
])
def test_reject_invalid_recipe_fields(changes):
    with pytest.raises(ValueError):
        profiles.validate_recipe({**profiles.default_recipe(), **changes})


@pytest.mark.parametrize("value", [True, 5, -5, 0.0, None, "3"])
def test_reject_invalid_settings(value):
    recipe = profiles.default_recipe()
    recipe["settings"]["contrast"] = value
    with pytest.raises(ValueError, match="contrast"):
        profiles.validate_recipe(recipe)


def test_recipe_json_round_trip_and_failed_replacement(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    recipe = profiles.default_recipe("muted")
    recipe["toning"] = 6
    recipe["name"] = "  흐린 보라  "
    normalized = profiles.validate_recipe(recipe)
    original = deepcopy(recipe)
    profiles.save_recipe(path, recipe)
    assert recipe == original
    assert profiles.load_recipe(path) == normalized
    assert normalized["name"] == "흐린 보라"
    stable = path.read_bytes()
    profiles.save_recipe(path, normalized)
    assert path.read_bytes() == stable

    def fail(*args):
        raise PermissionError("injected interruption")

    monkeypatch.setattr(profiles.os, "replace", fail)
    with pytest.raises(PermissionError, match="injected interruption"):
        profiles.save_recipe(path, profiles.default_recipe())
    assert path.read_bytes() == stable
    assert list(tmp_path.iterdir()) == [path]


def test_loading_rejects_duplicate_fields_and_oversized_input(tmp_path):
    path = tmp_path / "profile.json"
    path.write_bytes(b'{"mode":"bright","mode":"natural"}')
    with pytest.raises(ValueError, match="Duplicate"):
        profiles.load_recipe(path)
    path.write_bytes(b" " * (profiles.MAX_RECIPE_BYTES + 1))
    with pytest.raises(ValueError, match="64 KiB"):
        profiles.load_recipe(path)


@pytest.mark.parametrize(("baseline", "expected"), [
    (-1.15, [0.542997156, 0.601032472, 0.661869625]),
    (-0.5, [0.665439155, 0.715479793, 0.769596857]),
    (0.175, [0.797385556, 0.840089818, 0.883099520]),
])
def test_seeded_render_matches_upstream_natural_reference(baseline, expected):
    # From upstream firmware_color_model.dng_render and the published Natural DCP.
    camera_rgb = np.random.default_rng(4896).random((3, 3, 3)) * 0.5
    data, _ = profiles.build_profile(profiles.default_recipe())
    image = profiles.render_dcp(camera_rgb, data, baseline)
    assert image.shape == camera_rgb.shape
    assert np.all((0 <= image) & (image <= 1))
    np.testing.assert_allclose(image[0, 0], expected, rtol=0, atol=2e-8)
    with pytest.raises(ValueError, match="finite RGB"):
        profiles.render_dcp([0, np.nan, 1], data, baseline)
    with pytest.raises(ValueError, match="baseline_exposure"):
        profiles.render_dcp(camera_rgb, data, float("inf"))


def test_dcp_rejects_truncation_bad_offsets_shapes_and_floats():
    original, _ = profiles.build_profile(profiles.default_recipe())
    count = struct.unpack_from("<H", original, 8)[0]
    entries = {struct.unpack_from("<H", original, at)[0]: at for at in range(10, 10 + count * 12, 12)}

    with pytest.raises(ValueError, match="directory offset"):
        dcp.read_dcp(original[:4] + b"\xff" * 4 + original[8:])
    with pytest.raises(ValueError, match="truncated DCP directory"):
        dcp.read_dcp(original[:17])
    with pytest.raises(ValueError, match="outside its data area"):
        dcp.read_dcp(original[:-2])

    corrupt = bytearray(original)
    table = entries[dcp.TAGS["ProfileLookTableData"]]
    struct.pack_into("<I", corrupt, table + 8, 8)
    with pytest.raises(ValueError, match="outside its data area"):
        dcp.read_dcp(bytes(corrupt))

    corrupt = bytearray(original)
    struct.pack_into("<I", corrupt, table + 4, 3)
    with pytest.raises(ValueError, match="invalid DCP field ProfileLookTableData"):
        dcp.read_dcp(bytes(corrupt))
    corrupt = bytearray(original)
    struct.pack_into("<f", corrupt, struct.unpack_from("<I", corrupt, table + 8)[0], float("nan"))
    with pytest.raises(ValueError, match="invalid DCP LookTable entries"):
        dcp.read_dcp(bytes(corrupt))
    corrupt = bytearray(original)
    matrix = entries[dcp.TAGS["ForwardMatrix1"]]
    struct.pack_into("<i", corrupt, struct.unpack_from("<I", corrupt, matrix + 8)[0] + 4, 0)
    with pytest.raises(ValueError, match="zero denominator"):
        dcp.read_dcp(bytes(corrupt))

def test_camera_pack_routing_uses_each_manifest(tmp_path, monkeypatch):
    camera_id = "synthetic-test-pack"
    primary = profiles._pack(profiles.CAMERA_ID)
    manifest = {
        **primary.manifest,
        "camera_id": camera_id,
        "camera_model": "Synthetic Test Body",
        "pack_version": "test-1",
        "profile_name_prefix": "Synthetic",
        "mode_labels_ko": {"natural": "시험"},
        "default_profiles": {},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    pack = profiles._CameraPack(tmp_path, {"natural": "Natural Test"}, primary.load_engine)
    monkeypatch.setitem(profiles._PACKS, camera_id, pack)
    assert list(profiles.list_modes(camera_id)) == ["natural"]
    recipe = profiles.default_recipe(camera_id=camera_id)
    assert recipe["pack_version"] == "test-1"
    with pytest.raises(ValueError, match="pack_version"):
        profiles.validate_recipe({**recipe, "pack_version": profiles.PACK_VERSION})
    data, report = profiles.build_profile(recipe)
    assert report["camera_id"] == camera_id
    assert dcp.read_dcp(data)["ProfileName"] == "Synthetic Natural Test (시험)"


def test_gold_camera_recipe_dispatches_and_plain_dcp_rejects():
    recipe = profiles.default_recipe("gold")
    camera = profiles.camera_for_recipe(recipe)
    assert camera.curves.shape == (3, 4096)
    assert np.ptp(camera.render([0.125, 0.125, 0.125])) > 0.01
    with pytest.raises(ValueError, match="Gold requires an enhanced profile"):
        profiles.build_profile(recipe)

def test_public_color_tables_hash_matches_the_source_manifest():
    manifest = json.loads((PACK_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    name = "k3iii-color-tables.json"
    data = (PACK_DIRECTORY / name).read_bytes()
    assert manifest["files"][name]["bytes"] == len(data)
    assert manifest["files"][name]["sha256"] == sha256(data).hexdigest()
