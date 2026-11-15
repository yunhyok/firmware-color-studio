"""Bake and render an Adobe enhanced profile from a firmware colour recipe."""

from dataclasses import dataclass, field
from hashlib import md5, sha256
from io import BytesIO
import json
import struct
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
import zlib

import numpy as np

from . import color_model, dcp, profiles

GRID_SIZE = 32
# Adobe DNG SDK 1.7.1, dng_big_table.cpp: XMP big-table alphabet.
_ALPHABET = b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#"
_CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_FORMAT_VERSION = 1


@dataclass(frozen=True)
class EnhancedBundle:
    dcp: bytes
    xmp: bytes
    recipe: dict
    report: dict
    _samples: np.ndarray = field(repr=False, compare=False)


def _base_dcp(pack, recipe: dict) -> tuple[bytes, str]:
    matrices = recipe["calibration"]
    if matrices is None:
        matrices = [matrix.tolist() for matrix in pack.engine.dng_color_matrices()]
    calibration_digest = sha256(np.asarray(matrices, dtype="<f8").tobytes()).hexdigest()[:12]
    prefix = pack.manifest["profile_name_prefix"]
    name = f'{prefix} {pack.manifest.get("base_profile_label", "Base")} {recipe["pack_version"]} {calibration_digest}'
    forward = (color_model.SRGB_TO_PCS @ pack.engine.common_matrix()).tolist()
    data = dcp.build_dcp({
        **profiles._profile_tags(pack, forward, matrices, name),
        "ProfileToneCurve": [[0.0, 0.0], [1.0, 1.0]],
        "ProfileLookTableDims": [1, 2, 2],
        "ProfileLookTableEncoding": 0,
        "ProfileLookTableData": [[0.0, 1.0, 1.0]] * 4,
    })
    return data, name


def _lut(camera: color_model.CameraColour, base_forward: np.ndarray) -> np.ndarray:
    grid = np.linspace(0.0, 1.0, GRID_SIZE)
    lut_input = np.stack(np.meshgrid(grid, grid, grid, indexing="ij"), axis=-1)
    prophoto = color_model.srgb_decode(lut_input)
    # Invert the serialized base transform. Grid points beyond the sensor gamut
    # extend by clamping negative sensor values, as in the upstream DCP builder.
    to_sensor = np.linalg.inv(color_model.PCS_TO_PROPHOTO @ base_forward)
    sensor = np.maximum(prophoto @ to_sensor.T, 0.0)
    encoded = camera.encode(sensor @ camera.matrix.T)
    output = camera.decode(encoded) @ (color_model.PCS_TO_PROPHOTO @ camera.to_pcs).T
    nonlinear = color_model.srgb_encode(np.clip(output, 0.0, 1.0))
    return np.floor(nonlinear * 65535.0 + 0.5).astype("<u2")


def _table_stream(samples: np.ndarray) -> bytes:
    """SDK RGB-table stream, also the byte sequence covered by its MD5 fingerprint."""
    size = samples.shape[0]
    index = (np.arange(size, dtype=np.uint32) * 65535 + (size >> 1)) // (size - 1)
    identity = np.stack(np.meshgrid(index, index, index, indexing="ij"), axis=-1)
    # 16-bit modular differences from identity, B index fastest.
    deltas = (samples - identity).astype("<u2").tobytes()
    head = struct.pack("<4I", 1, 1, 3, size)  # RGB table type, version, dimensions, divisions
    tail = struct.pack("<3I2d", 2, 1, 0, 1.0, 1.0)  # ProPhoto, sRGB transfer, clip, min/max amount
    return head + deltas + tail


def _as_xmp_string(stream: bytes) -> str:
    """Encode a compressed SDK big table using its little-endian base-85 dialect."""
    block = struct.pack("<I", len(stream)) + zlib.compress(stream)
    output = bytearray()
    for (value,) in struct.iter_unpack("<I", block + b"\0" * (-len(block) % 4)):
        for _ in range(5):
            value, digit = divmod(value, 85)
            output.append(_ALPHABET[digit])
    return output[:len(block) + (len(block) + 3) // 4].decode("ascii")


def _xmp(pack, name: str, base_name: str, identifier: str, fingerprint: str, stream: bytes) -> bytes:
    root = ET.Element("x:xmpmeta", {"xmlns:x": "adobe:ns:meta/", "xmlns:rdf": _RDF, "xmlns:crs": _CRS})
    rdf = ET.SubElement(root, "rdf:RDF")
    attributes = {
        "PresetType": "Look",
        "UUID": identifier,
        "SupportsAmount": "False",
        "SupportsColor": "True",
        "SupportsMonochrome": "False",
        "SupportsHighDynamicRange": "False",
        "SupportsNormalDynamicRange": "True",
        "SupportsSceneReferred": "True",
        "SupportsOutputReferred": "False",
        "CameraModelRestriction": pack.manifest["camera_model"],
        "Copyright": pack.manifest["profile_copyright"],
        "Version": "10.3",
        "ProcessVersion": "10.0",
        "CameraProfile": base_name,
        "RGBTable": fingerprint,
        "RGBTableAmount": "1",
        f"Table_{fingerprint}": _as_xmp_string(stream),
        "HasSettings": "True",
    }
    desc = ET.SubElement(rdf, "rdf:Description", {"rdf:about": "", **{f"crs:{k}": v for k, v in attributes.items()}})
    for tag, value in (("Name", name), ("Group", "Firmware Color Studio")):
        alt = ET.SubElement(ET.SubElement(desc, f"crs:{tag}"), "rdf:Alt")
        ET.SubElement(alt, "rdf:li", {"xml:lang": "x-default"}).text = value
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _recipe_json(recipe: dict) -> str:
    return json.dumps(recipe, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def build_enhanced(recipe: dict) -> EnhancedBundle:
    """Return a neutral base DCP and an XMP containing the full firmware look."""
    recipe = profiles.validate_recipe(recipe)
    pack = profiles._pack(recipe["camera_id"])
    camera = profiles.camera_for_recipe(recipe)
    base, base_name = _base_dcp(pack, recipe)
    samples = _lut(camera, dcp.read_dcp(base)["ForwardMatrix1"])
    samples.setflags(write=False)
    stream = _table_stream(samples)
    fingerprint = md5(stream, usedforsecurity=False).hexdigest().upper()
    base_sha = sha256(base).hexdigest()
    recipe_sha = sha256(_recipe_json(recipe).encode("utf-8")).hexdigest()
    identifier = uuid5(
        NAMESPACE_URL, f"firmware-color-studio:{_FORMAT_VERSION}:{recipe_sha}:{base_sha}:{fingerprint}"
    ).hex.upper()
    name = profiles.profile_name(recipe)
    xmp = _xmp(pack, name, base_name, identifier, fingerprint, stream)
    report = {
        "camera_id": recipe["camera_id"],
        "pack_version": recipe["pack_version"],
        "mode": recipe["mode"],
        "requested_settings": recipe["settings"].copy(),
        "effective_settings": pack.engine.settings(recipe["mode"], **recipe["settings"]),
        "color_space": recipe["color_space"],
        "toning": recipe["toning"],
        "profile_name": name,
        "base_profile_name": base_name,
        "baseline_exposure_offset": profiles.BASELINE_EXPOSURE_OFFSET,
        "lut_grid": [GRID_SIZE] * 3,
        "lut_domain": "ProPhoto RGB primaries, sRGB transfer",
        "lut_bits": 16,
        "lut_interpolation": "tetrahedral",
        "rgb_table_fingerprint": fingerprint,
        "uuid": identifier,
        "recipe_sha256": recipe_sha,
        "dcp_sha256": base_sha,
        "xmp_sha256": sha256(xmp).hexdigest(),
    }
    if camera.notes:
        report["camera_notes"] = camera.notes
    return EnhancedBundle(base, xmp, recipe, report, samples)


def _tetrahedral(rgb: np.ndarray, samples: np.ndarray) -> np.ndarray:
    """Interpolate the four vertices ordered by the three fractional coordinates."""
    size = samples.shape[0]
    scaled = np.clip(rgb, 0.0, 1.0) * (size - 1)
    lower = np.minimum(scaled.astype(np.intp), size - 2)
    fraction = scaled - lower
    order = np.argsort(-fraction, axis=-1)
    high, middle, low = np.moveaxis(np.take_along_axis(fraction, order, axis=-1), -1, 0)

    stride = np.array([size**2, size, 1], dtype=np.intp)
    origin = lower @ stride
    first_step = stride[order[..., 0]]
    second_step = stride[order[..., 1]]
    table = samples.reshape(-1, 3)
    interpolated = (
        (1 - high)[..., None] * table[origin]
        + (high - middle)[..., None] * table[origin + first_step]
        + (middle - low)[..., None] * table[origin + first_step + second_step]
        + low[..., None] * table[origin + stride.sum()]
    )
    return interpolated / 65535.0


def render_enhanced(camera_rgb, bundle: EnhancedBundle, baseline_exposure=0.0) -> np.ndarray:
    """Render the neutral DCP then the quantized XMP LUT, to encoded sRGB."""
    rgb, exposure = profiles._render_inputs(camera_rgb, baseline_exposure)
    base = profiles._render_profile(bundle.dcp)
    ev = exposure + base["BaselineExposureOffset"]
    working = color_model.dng_working_rgb(rgb, base["ForwardMatrix1"], ev)
    if ev < 0.0:
        working = color_model.dng_tone(working, base["curve_x"], base["curve_y"], ev)
    code = _tetrahedral(color_model.srgb_encode(working), bundle._samples)
    linear = color_model.srgb_decode(code) @ color_model.PROPHOTO_TO_SRGB.T
    return np.clip(color_model.srgb_encode(linear), 0.0, 1.0)


def bundle_zip(bundle: EnhancedBundle) -> bytes:
    """Build the deterministic archive handed to Adobe Profile Import."""
    output = BytesIO()
    readme = (
        "Firmware Color Studio enhanced profile\n\n"
        f'Profile: {bundle.report["profile_name"]}\n'
        f'Required base profile: {bundle.report["base_profile_name"]}\n\n'
        "Import the archive through Adobe's Import Profiles and Presets dialog. "
        "If installing files individually, put base.dcp in CameraRaw/CameraProfiles "
        "and profile.xmp in CameraRaw/Settings. Use distinct filenames when installing multiple bundles. "
        "The enhanced profile matches its base by the name recorded inside the DCP.\n\n"
        "The offline preview uses the exported quantized LUT over the neutral DCP. "
        "Adobe's render also depends on the process version, raw processing, and edit settings.\n"
    ).encode("utf-8")
    files = {
        "base.dcp": bundle.dcp,
        "profile.xmp": bundle.xmp,
        "recipe.json": _recipe_json(bundle.recipe).encode("utf-8"),
        "README.txt": readme,
    }
    with ZipFile(output, "w") as archive:
        for name, data in files.items():
            entry = ZipInfo(name)
            entry.create_system = 3
            archive.writestr(entry, data, compress_type=ZIP_DEFLATED, compresslevel=6)
    return output.getvalue()
