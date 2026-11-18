"""Enhanced-profile export and offline rendering checks with synthetic RGB."""

from dataclasses import replace
from hashlib import md5, sha256
from itertools import permutations
from io import BytesIO
import json
import struct
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import zlib

import numpy as np
import pytest

from firmware_color_studio import color_model, dcp, enhanced, profiles

CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
# Adobe DNG SDK 1.7.1, dng_big_table.cpp DecodeFromString.
DIGITS = {char: n for n, char in enumerate(
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"
)}


def normalized(matrix):
    # SDK dng_color_space::SetMatrixToPCS: scale each XYZ row to D50.
    return np.diag(np.asarray(dcp.D50) / (matrix @ np.ones(3))) @ matrix


def direct_srgb(camera, rgb):
    to_srgb = np.linalg.inv(normalized(color_model.SRGB_TO_PCS)) @ normalized(camera.to_pcs)
    return np.clip(color_model.srgb_encode(camera.decode(camera.render(rgb)) @ to_srgb.T), 0, 1)


def read_lut(xmp):
    description = ET.fromstring(xmp).find(f".//{RDF}Description")
    fingerprint = description.attrib[CRS + "RGBTable"]
    text = description.attrib[CRS + f"Table_{fingerprint}"]
    compressed = bytearray()
    for start in range(0, len(text), 5):
        part = text[start:start + 5]
        word = sum(DIGITS[char] * 85**place for place, char in enumerate(part))
        compressed.extend(word.to_bytes(len(part) - 1, "little"))
    stream = zlib.decompress(compressed[4:])
    assert len(stream) == struct.unpack_from("<I", compressed)[0]
    assert md5(stream, usedforsecurity=False).hexdigest().upper() == fingerprint
    table_type, version, dimensions, divisions = struct.unpack_from("<4I", stream)
    assert (table_type, version, dimensions, divisions) == (1, 1, 3, 32)
    assert struct.unpack_from("<3I2d", stream, len(stream) - 28) == (2, 1, 0, 1.0, 1.0)
    assert len(stream) == 16 + 6 * divisions**3 + 28
    table = np.frombuffer(stream[16:-28], dtype="<u2").reshape((divisions,) * 3 + (3,))
    positions = np.array([(i * 65535 + divisions // 2) // (divisions - 1) for i in range(divisions)], dtype=np.uint16)
    return description, table + np.stack(np.meshgrid(positions, positions, positions, indexing="ij"), axis=-1)


def test_xmp_stream_and_zip_are_deterministic_and_use_the_quantized_table():
    recipe = profiles.default_recipe("muted")
    recipe.update(name="Green Test & 시험", toning=1)
    bundle = enhanced.build_enhanced(recipe)
    desc, samples = read_lut(bundle.xmp)
    base = dcp.read_dcp(bundle.dcp)
    assert desc.attrib[CRS + "PresetType"] == "Look"
    assert desc.attrib[CRS + "SupportsSceneReferred"] == "True"
    assert desc.attrib[CRS + "SupportsOutputReferred"] == "False"
    assert desc.attrib[CRS + "CameraProfile"] == base["ProfileName"] == bundle.report["base_profile_name"]
    assert desc.attrib[CRS + "CameraModelRestriction"] == profiles.CAMERA_MODEL
    assert desc.attrib[CRS + "UUID"] == bundle.report["uuid"]
    assert desc.find(f"{CRS}Name/{RDF}Alt/{RDF}li").text == profiles.profile_name(recipe)
    assert base["BaselineExposureOffset"] == 0.5
    np.testing.assert_array_equal(base["curve_x"], base["curve_y"])
    assert np.all(base["LookTable"].rows() == [0.0, 1.0, 1.0])
    np.testing.assert_array_equal(samples, bundle._samples)
    assert not bundle._samples.flags.writeable
    assert sha256(bundle.xmp).hexdigest() == bundle.report["xmp_sha256"]
    assert sha256(bundle.dcp).hexdigest() == bundle.report["dcp_sha256"]

    zipped = enhanced.bundle_zip(bundle)
    repeated = enhanced.build_enhanced(recipe)
    assert zipped == enhanced.bundle_zip(repeated)
    with ZipFile(BytesIO(zipped)) as archive:
        dcp_name, xmp_name = bundle.report["dcp_filename"], bundle.report["xmp_filename"]
        recipe_name = xmp_name[:-4] + ".json"
        assert archive.namelist() == [dcp_name, xmp_name, recipe_name, "README.txt"]
        assert archive.read(dcp_name) == bundle.dcp
        assert archive.read(xmp_name) == bundle.xmp
        assert json.loads(archive.read(recipe_name)) == recipe
        readme = archive.read("README.txt")
        assert base["ProfileName"].encode("utf-8") in readme
        assert dcp_name.encode() in readme and xmp_name.encode() in readme
    assert dcp_name == f"pentax-k3iii-base-v2-2.20-1-{base['ProfileName'].split()[-1]}.dcp"
    assert xmp_name == f"pentax-k3iii-muted-{bundle.report['uuid'][:8].lower()}.xmp"
    other = enhanced.build_enhanced({**recipe, "toning": 2})
    # Unpacked into the same folders, two bundles share the base and keep both looks.
    assert other.dcp == bundle.dcp
    assert other.report["dcp_filename"] == dcp_name
    assert other.report["xmp_filename"] != xmp_name
    calibrated = enhanced.build_enhanced({**recipe, "calibration": [np.eye(3).tolist(), (np.eye(3) * 1.1).tolist()]})
    assert calibrated.dcp != bundle.dcp
    assert calibrated.report["dcp_filename"] != dcp_name
    assert other.report["uuid"] != bundle.report["uuid"]
    assert other.report["rgb_table_fingerprint"] != bundle.report["rgb_table_fingerprint"]
    for changed in [{**recipe, "color_space": "adobergb"},
                    {**recipe, "settings": {**recipe["settings"], "saturation": 4}}]:
        different_matrix = enhanced.build_enhanced(changed)
        assert different_matrix.dcp != bundle.dcp
        assert different_matrix.report["dcp_filename"] != dcp_name
        assert different_matrix.report["base_profile_name"] != bundle.report["base_profile_name"]
        assert different_matrix.report["uuid"] != bundle.report["uuid"]


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_tetrahedral_interpolates_selected_vertices(order):
    table = np.array([0, 9020, 32000, 4111, 49222, 575, 65535, 3918], dtype=np.uint16)
    table = np.repeat(table.reshape(2, 2, 2, 1), 3, axis=3)
    point = np.zeros(3)
    point[list(order)] = (0.9, 0.6, 0.2)
    first = tuple(int(k == order[0]) for k in range(3))
    second = tuple(int(k in order[:2]) for k in range(3))
    expected = (0.1 * table[0, 0, 0] + 0.3 * table[first] + 0.4 * table[second] + 0.2 * table[1, 1, 1]) / 65535
    np.testing.assert_allclose(enhanced._tetrahedral(point, table), expected, rtol=0, atol=1e-15)
    np.testing.assert_array_equal(enhanced._tetrahedral(np.ones(3), table), table[-1, -1, -1] / 65535)


@pytest.mark.parametrize(("mode", "toning"), [("natural", 0), ("muted", 7), ("bleach-bypass", 1), ("harubeni", 4), ("gold", 0)])
@pytest.mark.parametrize("space", ["srgb", "adobergb"])
def test_enhanced_rgb_matches_firmware_formula_over_the_full_sensor_cube(mode, toning, space):
    recipe = profiles.default_recipe(mode)
    recipe.update(toning=toning, color_space=space)
    bundle = enhanced.build_enhanced(recipe)
    camera = profiles.camera_for_recipe(recipe)
    axis = np.linspace(0, 1, 17)
    grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), -1).reshape(-1, 3)
    rgb = np.concatenate([grid, np.random.default_rng(864).uniform(0, 1, size=(5000, 3))])
    expected = direct_srgb(camera, rgb)
    exported = enhanced.render_enhanced(rgb, bundle, baseline_exposure=-0.5)
    error = np.abs(exported - expected) * 255.0
    assert error.mean() < 0.65
    assert np.percentile(error, 95) < 1.4
    assert np.percentile(error, 99) < 3.5
    assert error.max() < 25  # Explicit bound includes gamut faces; not just mean/p95.

    neutral = enhanced.render_enhanced(np.full(3, 0.125), bundle, baseline_exposure=-0.5)
    if mode == "bleach-bypass":
        assert neutral[1] - neutral[0] > 0.01
    elif mode == "gold":
        assert np.ptp(neutral) > 0.08
        assert bundle.report["camera_notes"]["exposure_gain"] == 8192
    elif not toning:
        assert np.ptp(neutral) < 1e-3


@pytest.mark.parametrize("ev", [-2., -1., 0., .5, 1.])
def test_enhanced_applies_sdk_exposure_after_the_serialized_matrix_before_the_lut(ev):
    bundle = enhanced.build_enhanced(profiles.default_recipe("bright"))
    base = dcp.read_dcp(bundle.dcp)
    raw = np.array([0.125, 0.25, 0.5])
    # SDK SetForwardMatrix rounds to 1e-4, then dng_color_spec normalizes rows.
    units = base["ForwardMatrix1"] * 10000
    rounded = np.sign(units) * np.floor(abs(units) + .5) / 10000
    to_working = np.linalg.inv(normalized(color_model.PROPHOTO_TO_PCS)) @ normalized(rounded)
    after_base = np.clip(raw @ to_working.T, 0, 1)
    after_exposure = np.clip(after_base * 2 ** max(ev, 0), 0, 1)
    if ev < 0:
        after_exposure = color_model.dng_tone(after_exposure, base["curve_x"], base["curve_y"], ev)
    _, samples = read_lut(bundle.xmp)
    code = enhanced._tetrahedral(color_model.srgb_encode(after_exposure), samples)
    to_srgb = np.linalg.inv(normalized(color_model.SRGB_TO_PCS)) @ normalized(color_model.PROPHOTO_TO_PCS)
    expected = color_model.srgb_encode(np.clip(color_model.srgb_decode(code) @ to_srgb.T, 0, 1))
    np.testing.assert_allclose(enhanced.render_enhanced(raw, bundle, baseline_exposure=ev - .5), expected, atol=1e-12)


@pytest.mark.parametrize(("space", "rgb", "expected"), [
    ("adobergb", [0.7850411286188153, 0.7747761263451224, 0.20276238894425247],
     [0.93472445, 0.94950487, 0.26636081]),
    ("srgb", [0.20953687713522073, 0.8608416551900554, 0.9950363874156818],
     [0, 0.99848265625, 0.996859375]),
])
def test_gold_clipping_boundary_regressions(space, rgb, expected):
    # The former Adobe blue=0 reference was wrong: gamma(0) must retain table[0].
    recipe = profiles.default_recipe("gold")
    recipe["color_space"] = space
    rgb = np.asarray(rgb)
    camera = profiles.camera_for_recipe(recipe)
    direct = direct_srgb(camera, rgb)
    lut = enhanced.render_enhanced(rgb, enhanced.build_enhanced(recipe), -0.5)
    np.testing.assert_allclose(direct, expected, atol=1e-8)
    assert np.max(abs(lut - direct)) * 255 < 1.5


@pytest.mark.parametrize("mode", ["muted", "bleach-bypass", "harubeni"])
@pytest.mark.parametrize("space", ["srgb", "adobergb"])
@pytest.mark.parametrize("tone", range(1, 9))
def test_every_tint_preserves_bounded_full_cube_accuracy(mode, space, tone):
    recipe = profiles.default_recipe(mode)
    recipe.update(color_space=space, toning=tone)
    camera = profiles.camera_for_recipe(recipe)
    axis = np.linspace(0, 1, 9)
    rgb = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), -1).reshape(-1, 3)
    actual = enhanced.render_enhanced(rgb, enhanced.build_enhanced(recipe), -.5)
    error = abs(actual - direct_srgb(camera, rgb)) * 255
    assert error.mean() < .4
    assert np.percentile(error, 99) < 3.5
    assert error.max() < 25


def test_remaining_adobe_rgb_tint_boundary_has_an_explicit_error_bound():
    # Worst input found by the documented 198-recipe synthetic sweep. The
    # 32-cube still interpolates across the final sRGB clipping boundary.
    recipe = profiles.default_recipe("muted")
    recipe.update(color_space="adobergb", toning=1)
    recipe["settings"]["key"] = -4
    rgb = np.array([0.27657142871675555, 0.8396712484216707, 0.030468958490673992])
    camera = profiles.camera_for_recipe(recipe)
    direct = direct_srgb(camera, rgb)
    actual = enhanced.render_enhanced(rgb, enhanced.build_enhanced(recipe), -.5)
    np.testing.assert_allclose(direct, [0, 0.9984821891, 0], atol=1e-8)
    assert np.max(abs(actual - direct)) * 255 < 28.1  # v2 measured 29.48.


def test_harubeni_dark_red_near_the_firmware_chroma_gain_break():
    recipe = profiles.default_recipe("harubeni")
    recipe.update(color_space="adobergb", toning=1)
    recipe["settings"]["highlight"] = -4
    rgb = np.array([0.03125, 0.71875, 0.3125])
    target = direct_srgb(profiles.camera_for_recipe(recipe), rgb)
    bundle = enhanced.build_enhanced(recipe)
    _, exported_samples = read_lut(bundle.xmp)
    actual = enhanced.render_enhanced(rgb, replace(bundle, _samples=exported_samples), -.5)
    # v3's 10.674 red error exceeded this recipe's v2 maximum of 8.629.
    assert np.max(abs(actual - target)) * 255 < 8.629


@pytest.mark.parametrize(("space", "v3_sha256"), [
    ("srgb", "9efe23ba9d9cdc197a833bda1ddb6d2d40a90970f380744e8fe46d4f8f37e678"),
    ("adobergb", "5c017e5260a4d1e8651ec35485bc312d420f684c197a42897b97c8869b082c2c"),
])
def test_monochrome_keeps_published_v3_quantized_table(space, v3_sha256):
    recipe = profiles.default_recipe("monochrome")
    recipe["color_space"] = space
    _, exported = read_lut(enhanced.build_enhanced(recipe).xmp)
    assert sha256(exported.astype("<u2").tobytes()).hexdigest() == v3_sha256


def test_v4_bake_preserves_analytic_wireframe_neutral_diagonal_and_published_v2_base():
    recipe = profiles.default_recipe("gold")
    bundle = enhanced.build_enhanced(recipe)
    assert bundle.report["format_version"] == 4
    assert bundle.report["base_format_version"] == 2
    camera = profiles.camera_for_recipe(recipe)
    calibration = profiles._pack(recipe["camera_id"]).engine.dng_color_matrices()
    raw_forward = color_model.PROPHOTO_TO_PCS @ camera.matrix
    matrix_digest = sha256(np.asarray([*calibration, raw_forward], dtype="<f8").tobytes()).hexdigest()[:12]
    base = dcp.read_dcp(bundle.dcp)
    published_digest = "7de5b8abbe0e"
    name_prefix = "K-3 III Firmware Base (기본 프로파일) 2 2.20-1 "
    assert base["ProfileName"] == name_prefix + matrix_digest
    # v2 hashed the unrounded matrix. BLAS kernels can change the name suffix
    # at the last floating-point bit while emitting identical DCP rationals.
    actual_name = (base["ProfileName"] + "\0").encode()
    assert bundle.dcp.count(actual_name) == 1
    canonical = bundle.dcp.replace(actual_name, (name_prefix + published_digest + "\0").encode(), 1)
    assert sha256(canonical).hexdigest() == "9645264bd0a7e5f81aadede14d82dd4ccf7d7eac63ffa944156fb2614cc71f22"
    forward = base["ForwardMatrix1"]
    indices = np.array(list(np.ndindex(32, 32, 32)))
    wireframe = np.count_nonzero((indices == 0) | (indices == 31), axis=1) >= 2
    neutral = np.all(indices == indices[:, :1], axis=1)
    anchored = indices[wireframe | neutral]
    correction = camera.matrix @ np.linalg.inv(enhanced._working_matrix(forward))
    encoded = camera.encode(color_model.srgb_decode(anchored / 31.0) @ correction.T)
    to_working = np.linalg.solve(normalized(color_model.PROPHOTO_TO_PCS), normalized(camera.to_pcs))
    target = color_model.srgb_encode(np.clip(camera.decode(encoded) @ to_working.T, 0., 1.))
    quantized = np.floor(target * 65535.0 + 0.5).astype(np.uint16)
    _, samples = read_lut(bundle.xmp)
    np.testing.assert_array_equal(samples[tuple(anchored.T)], quantized)


def test_all_cc0_matrices_preserve_white_and_bound_sdk_rounding():
    engine = profiles._pack(profiles.CAMERA_ID).engine
    corners = np.array(list(np.ndindex(2, 2, 2)))
    for mode in profiles.list_modes():
        for space in [False, True]:
            for saturation in range(-4, 5):
                matrix = np.asarray(engine.cc0(mode, saturation=saturation, adobe_rgb=space)).reshape(3, 3) / 256
                np.testing.assert_array_equal(matrix.sum(axis=1), np.ones(3))
                # The writer stores 1e-6 SRATIONALs before SDK reading/rounding.
                forward = np.round(color_model.PROPHOTO_TO_PCS @ matrix, 6)
                effective = enhanced._working_matrix(forward)
                assert np.max(abs(corners @ (effective - matrix).T)) < .0005
                np.testing.assert_allclose(effective.sum(axis=1), np.ones(3), atol=1e-14)
                assert abs(np.linalg.det(effective)) > 1e-5
