"""Enhanced-profile export and offline rendering checks with synthetic RGB."""

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
    assert dcp_name == f"pentax-k3iii-base-2.20-1-{base['ProfileName'].split()[-1]}.dcp"
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


@pytest.mark.parametrize(("mode", "toning"), [("natural", 0), ("bleach-bypass", 1), ("gold", 0)])
@pytest.mark.parametrize("space", ["srgb", "adobergb"])
def test_enhanced_rgb_matches_firmware_formula_over_seeded_working_gamut(mode, toning, space):
    recipe = profiles.default_recipe(mode)
    recipe.update(toning=toning, color_space=space)
    bundle = enhanced.build_enhanced(recipe)
    camera = profiles.camera_for_recipe(recipe)
    rgb = np.random.default_rng(864).uniform(0.02, 0.6, size=(5000, 3))
    base = dcp.read_dcp(bundle.dcp)
    p = rgb @ (color_model.PCS_TO_PROPHOTO @ base["ForwardMatrix1"]).T
    within_gamut = np.all((p > 0.05) & (p < 0.95), axis=1)
    rgb = rgb[within_gamut]
    expected = camera.decode(camera.render(rgb)) @ (color_model.PCS_TO_SRGB @ camera.to_pcs).T
    expected = color_model.srgb_encode(np.clip(expected, 0.0, 1.0))
    exported = enhanced.render_enhanced(rgb, bundle, baseline_exposure=-0.5)
    error = np.abs(exported - expected) * 255.0
    assert error.mean() < 0.65
    assert np.percentile(error, 95) < 1.4

    neutral = enhanced.render_enhanced(np.full(3, 0.125), bundle, baseline_exposure=-0.5)
    if toning:
        assert neutral[1] - neutral[0] > 0.01
    elif mode == "gold":
        assert np.ptp(neutral) > 0.08
        assert bundle.report["camera_notes"]["exposure_gain"] == 8192
    else:
        assert np.ptp(neutral) < 1e-3


def test_enhanced_applies_negative_exposure_to_the_base_before_the_lut():
    bundle = enhanced.build_enhanced(profiles.default_recipe("bright"))
    base = dcp.read_dcp(bundle.dcp)
    raw = np.array([0.125, 0.25, 0.5])
    after_base = color_model.dng_working_rgb(raw, base["ForwardMatrix1"], -1.0)
    after_exposure = color_model.dng_tone(after_base, base["curve_x"], base["curve_y"], -1.0)
    _, samples = read_lut(bundle.xmp)
    code = enhanced._tetrahedral(color_model.srgb_encode(after_exposure), samples)
    expected = color_model.srgb_encode(np.clip(color_model.srgb_decode(code) @ color_model.PROPHOTO_TO_SRGB.T, 0, 1))
    np.testing.assert_allclose(enhanced.render_enhanced(raw, bundle, baseline_exposure=-1.5), expected, atol=1e-12)


def test_gold_clipping_boundary_limit_is_reproducible():
    # Track this documented LUT limit; improving the sampler should update the evidence.
    recipe = profiles.default_recipe("gold")
    recipe["color_space"] = "adobergb"
    rgb = np.array([0.7850411286188153, 0.7747761263451224, 0.20276238894425247])
    camera = profiles.camera_for_recipe(recipe)
    direct = color_model.srgb_encode(np.clip(
        camera.decode(camera.render(rgb)) @ (color_model.PCS_TO_SRGB @ camera.to_pcs).T, 0, 1))
    lut = enhanced.render_enhanced(rgb, enhanced.build_enhanced(recipe), -0.5)
    np.testing.assert_allclose(direct, [0.9353315653, 0.9510393681, 0], atol=1e-8)
    np.testing.assert_allclose(lut, [0.9350822111, 0.9495093095, 0.2319131177], atol=1e-8)
