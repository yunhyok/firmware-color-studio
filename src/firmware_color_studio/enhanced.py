"""Bake and render an Adobe enhanced profile from a firmware colour recipe."""

from dataclasses import dataclass, field
from hashlib import md5, sha256
from io import BytesIO
from itertools import product
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
_FORMAT_VERSION = 4


def _normalized_matrix(matrix: np.ndarray) -> np.ndarray:
    # dng_color_space::SetMatrixToPCS and NormalizeForwardMatrix both map white
    # to exact D50, rather than retaining the rounded published row sums.
    return matrix * (np.asarray(dcp.D50) / matrix.sum(axis=1))[:, None]


_PROPHOTO_TO_PCS = _normalized_matrix(color_model.PROPHOTO_TO_PCS)
_PCS_TO_PROPHOTO = np.linalg.inv(_PROPHOTO_TO_PCS)
_PROPHOTO_TO_SRGB = np.linalg.inv(_normalized_matrix(color_model.SRGB_TO_PCS)) @ _PROPHOTO_TO_PCS


def _working_matrix(forward: np.ndarray) -> np.ndarray:
    """SDK camera-to-ProPhoto transform after reading the serialized DCP."""
    scaled = np.rint(forward.ravel() * dcp.MATRIX_DENOMINATOR).astype(np.int64)
    rounded = np.asarray(dcp.sdk_read_matrix(scaled, "ForwardMatrix1")).reshape(3, 3)
    return _PCS_TO_PROPHOTO @ _normalized_matrix(rounded)


@dataclass(frozen=True)
class EnhancedBundle:
    dcp: bytes
    xmp: bytes
    recipe: dict
    report: dict
    _samples: np.ndarray = field(repr=False, compare=False)


def _base_dcp(pack, recipe: dict, camera: color_model.CameraColour) -> tuple[bytes, str, str]:
    matrices = recipe["calibration"]
    if matrices is None:
        matrices = [matrix.tolist() for matrix in pack.engine.dng_color_matrices()]
    # Adobe's intermediate RGB coordinates carry CC0 output here. Its [0,1]
    # clip then matches the firmware's pre-gamma clip; the paired XMP restores
    # their colour-space meaning. This base must never be reused across CC0s.
    forward = color_model.PROPHOTO_TO_PCS @ camera.matrix
    base_digest = sha256(np.asarray([*matrices, forward], dtype="<f8").tobytes()).hexdigest()[:12]
    prefix = pack.manifest["profile_name_prefix"]
    name = f'{prefix} {pack.manifest.get("base_profile_label", "Base")} 2 {recipe["pack_version"]} {base_digest}'
    data = dcp.build_dcp({
        **profiles._profile_tags(pack, forward.tolist(), matrices, name),
        "ProfileToneCurve": [[0.0, 0.0], [1.0, 1.0]],
        "ProfileLookTableDims": [1, 2, 2],
        "ProfileLookTableEncoding": 0,
        "ProfileLookTableData": [[0.0, 1.0, 1.0]] * 4,
    })
    return data, name, f'{recipe["camera_id"]}-base-v2-{recipe["pack_version"]}-{base_digest}.dcp'


def _lut(camera: color_model.CameraColour, base_forward: np.ndarray) -> np.ndarray:
    # Odd indices are midpoints of the seven tetrahedral edge directions.
    correction = camera.matrix @ np.linalg.inv(_working_matrix(base_forward))
    to_prophoto = _PCS_TO_PROPHOTO @ _normalized_matrix(camera.to_pcs)

    def evaluate(linear_input):
        encoded = camera.encode(linear_input @ correction.T)
        output = camera.decode(encoded) @ to_prophoto.T
        return color_model.srgb_encode(np.clip(output, 0.0, 1.0))

    grid = color_model.srgb_decode(np.linspace(0.0, 1.0, 2 * GRID_SIZE - 1))
    nonlinear = evaluate(np.stack(np.meshgrid(grid, grid, grid, indexing="ij"), axis=-1))
    nodes = nonlinear[::2, ::2, ::2].copy()
    counts = np.zeros(nodes.shape[:3] + (1,))
    edges = []
    for direction in product((0, 1), repeat=3):
        if not any(direction):
            continue
        lower = tuple(slice(None, -1) if step else slice(None) for step in direction)
        upper = tuple(slice(1, None) if step else slice(None) for step in direction)
        # Face nodes learn only from tetrahedral edges in that face.
        interior = tuple(slice(1, -1) if step else slice(None) for step in direction)
        parity = tuple(slice(step, None, 2) for step in direction)
        edges.append((lower, upper, interior, parity))
        counts[interior] += 2
    # Two clipped channels land on the cube wireframe (zero or two neighbours).
    # Preserve those 1D responses and the diagonal used by neutral camera RGB.
    weight = np.where(counts > 2, 1.0 / (counts + 2.0), 0.0)
    diagonal = np.arange(GRID_SIZE)
    weight[diagonal, diagonal, diagonal] = 0.0
    for _ in range(4):
        update = np.zeros_like(nodes)
        for lower, upper, interior, parity in edges:
            residual = nonlinear[parity] - (nodes[lower] + nodes[upper]) * 0.5
            update[interior] += residual[lower] + residual[upper]
        nodes = np.clip(nodes + update * weight, 0.0, 1.0)
    # Start from the serialized v3 interpolant, including its rounding to 16 bits.
    previous = np.floor(nodes * 65535.0 + 0.5).astype("<u2")
    if not camera.csp_enable or camera.chroma_fixed:
        return previous
    # Only the chroma-suppression stage can introduce its gain discontinuities.
    borders = np.asarray(camera.csp_border)
    widths = np.diff(np.r_[0, borders])
    left = np.asarray(camera.csp_offset[:-1]) + np.asarray(camera.csp_gain[:-1]) * widths / 8
    jumps = borders[np.clip(left, 0, 1023) != np.clip(camera.csp_offset[1:], 0, 1023)]
    if not len(jumps):
        return previous
    node_input = np.stack(np.meshgrid(grid[::2], grid[::2], grid[::2], indexing="ij"), axis=-1)
    gamma = camera.gamma(np.clip(node_input @ correction.T, 0.0, 1.0))
    luma = (gamma @ (camera.yc[0] / 256.0)) * 1023.0
    # Use the darkest signed display channel only to locate the sRGB transfer toe.
    native_nodes = nonlinear[::2, ::2, ::2]
    darkest = np.min(color_model.srgb_decode(native_nodes) @ _PROPHOTO_TO_SRGB.T, axis=-1)
    low, high, toe = luma.copy(), luma.copy(), darkest.copy()
    for lower, upper, _, _ in edges:
        low[lower] = np.minimum(low[lower], luma[upper])
        low[upper] = np.minimum(low[upper], luma[lower])
        high[lower] = np.maximum(high[lower], luma[upper])
        high[upper] = np.maximum(high[upper], luma[lower])
        toe[lower] = np.minimum(toe[lower], darkest[upper])
        toe[upper] = np.minimum(toe[upper], darkest[lower])
    crosses = np.any((low[..., None] <= jumps) & (high[..., None] >= jumps), axis=-1)
    movable = (weight[..., 0] > 0.0) & crosses & (toe <= 0.0031308)
    if not movable.any():
        return previous
    nodes = previous.astype(np.float64) / 65535.0

    def display_code(code):
        linear = color_model.srgb_decode(code) @ _PROPHOTO_TO_SRGB.T
        return color_model.srgb_encode(np.clip(linear, 0.0, 1.0))

    def exceeds_two_codes(target, predicted):
        return np.max(np.abs(display_code(target) - display_code(predicted)), axis=-1) > 2 / 255

    sharp = np.empty(nonlinear.shape[:3], dtype=bool)
    sharp[::2, ::2, ::2] = exceeds_two_codes(nonlinear[::2, ::2, ::2], nodes)
    for lower, upper, _, parity in edges:
        sharp[parity] = exceeds_two_codes(nonlinear[parity], (nodes[lower] + nodes[upper]) * 0.5)
    cells = np.zeros((GRID_SIZE - 1,) * 3, dtype=bool)
    for offset in product(range(3), repeat=3):
        cells |= sharp[tuple(slice(i, i + 2 * (GRID_SIZE - 1), 2) for i in offset)]
    incident = np.zeros_like(cells)
    for direction in product((0, 1), repeat=3):
        incident |= movable[tuple(slice(step, step + GRID_SIZE - 1) for step in direction)]
    cells &= incident
    if not cells.any():
        return previous
    refined = nodes.copy()
    _refine_sharp_cells(refined, cells, nonlinear, evaluate, movable)
    refined = np.floor(refined * 65535.0 + 0.5) / 65535.0
    # The half step retains the ordinary interpolation accuracy of the v3 table.
    nodes += 0.5 * (refined - nodes)
    return np.floor(nodes * 65535.0 + 0.5).astype("<u2")


def _refine_sharp_cells(nodes, cells, half_targets, evaluate, movable):
    """Reduce large interpolation errors on a shared quarter-cell lattice."""
    side = 4 * (GRID_SIZE - 1) + 1
    selected = np.zeros((side,) * 3, dtype=bool)
    for offset in product(range(5), repeat=3):
        selected[tuple(slice(i, i + side - 1, 4) for i in offset)] |= cells
    points = np.flatnonzero(selected)
    node_ids = np.arange(GRID_SIZE ** 3)
    node_xyz = np.column_stack(np.unravel_index(node_ids, nodes.shape[:3]))
    node_codes = nodes.reshape(-1, 3)
    to_prophoto = np.linalg.inv(_PROPHOTO_TO_SRGB)
    batches = []
    batch_size = 32768
    for start in range(0, len(points), batch_size):
        quarter = np.column_stack(np.unravel_index(points[start:start + batch_size], selected.shape))
        coordinates = quarter / 4
        indices, weights = _tetrahedron(coordinates, GRID_SIZE)
        half = np.all(quarter % 2 == 0, axis=1)
        target = np.empty_like(coordinates)
        target[half] = half_targets[tuple((quarter[half] // 2).T)]
        target[~half] = evaluate(color_model.srgb_decode(coordinates[~half] / (GRID_SIZE - 1)))
        linear = color_model.srgb_decode(target) @ _PROPHOTO_TO_SRGB.T

        # A boundary vertex can only learn from points lying on that same face.
        vertices = node_xyz[indices]
        on_face = np.all(((vertices != 0) | (quarter[:, None] == 0))
                         & ((vertices != GRID_SIZE - 1) | (quarter[:, None] == side - 1)), axis=-1)
        # Quarter-lattice weights are exactly representable in float32.
        weights = weights.astype(np.float32)
        batches.append((indices.astype(np.uint16), weights, weights * on_face, linear, color_model.srgb_encode(linear)))

    mask = movable.ravel()
    for _ in range(4):
        numerator = np.zeros_like(node_codes)
        denominator = np.ones_like(node_codes)
        for indices, weights, eligible, target, target_code in batches:
            prediction = np.sum(node_codes[indices] * weights[..., None], axis=1)
            linear = color_model.srgb_decode(prediction) @ _PROPHOTO_TO_SRGB.T
            delta = target - linear
            error = target_code - color_model.srgb_encode(linear)
            slope = np.divide(error, delta, out=np.ones_like(delta), where=np.abs(delta) > 1e-9)
            # Iteratively reweighted sixth-power loss in signed sRGB code. The
            # signed extension retains out-of-gamut working-space differences.
            priority = np.maximum(np.abs(error) * 255, 1.0) ** 4 * np.clip(slope, 0.5, 12.92) ** 2
            flat = indices.ravel()
            for ch in range(3):
                contribution = eligible * priority[:, ch, None]
                numerator[:, ch] += np.bincount(flat, (contribution * delta[:, ch, None]).ravel(), len(node_ids))
                denominator[:, ch] += np.bincount(flat, contribution.ravel(), len(node_ids))
        linear = color_model.srgb_decode(node_codes) + (numerator / denominator) @ to_prophoto.T
        proposal = color_model.srgb_encode(np.clip(linear, 0.0, 1.0))
        node_codes[mask] = (node_codes[mask] + proposal[mask]) * 0.5


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
    """Return a CC0 base DCP and the paired XMP for the remaining colour stages."""
    recipe = profiles.validate_recipe(recipe)
    pack = profiles._pack(recipe["camera_id"])
    camera = profiles.camera_for_recipe(recipe)
    base, base_name, base_filename = _base_dcp(pack, recipe, camera)
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
        # Installed side by side, bundles must not replace each other's files: the XMP name
        # follows its UUID, the base DCP name its CC0 matrix and calibration.
        "dcp_filename": base_filename,
        "xmp_filename": f'{recipe["camera_id"]}-{recipe["mode"]}-{identifier[:8].lower()}.xmp',
        "baseline_exposure_offset": profiles.baseline_exposure_offset(recipe["camera_id"]),
        "lut_grid": [GRID_SIZE] * 3,
        "lut_domain": "ProPhoto RGB primaries, sRGB transfer",
        "base_transform": "firmware CC0 in intermediate ProPhoto coordinates; paired XMP required",
        "base_format_version": 2,
        "format_version": _FORMAT_VERSION,
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


def _tetrahedron(scaled: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the four tetrahedral vertex indices and their interpolation weights."""
    lower = np.minimum(scaled.astype(np.intp), size - 2)
    fraction = scaled - lower
    order = np.argsort(-fraction, axis=-1)
    high, middle, low = np.moveaxis(np.take_along_axis(fraction, order, axis=-1), -1, 0)

    stride = np.array([size**2, size, 1], dtype=np.intp)
    origin = lower @ stride
    first_step = stride[order[..., 0]]
    second_step = stride[order[..., 1]]
    indices = np.stack((origin, origin + first_step, origin + first_step + second_step, origin + stride.sum()), axis=-1)
    return indices, np.stack((1 - high, high - middle, middle - low, low), axis=-1)


def _tetrahedral(rgb: np.ndarray, samples: np.ndarray) -> np.ndarray:
    size = samples.shape[0]
    indices, weights = _tetrahedron(np.clip(rgb, 0.0, 1.0) * (size - 1), size)
    table = samples.reshape(-1, 3)
    result = np.zeros_like(rgb, dtype=np.float64)
    for i in range(4):
        result += table[indices[..., i]] * weights[..., i, None]
    return result / 65535.0


def _render_prophoto(camera_rgb, bundle: EnhancedBundle, baseline_exposure=0.0) -> np.ndarray:
    """Render the serialized DCP and quantized XMP to linear working-space RGB."""
    rgb, exposure = profiles._render_inputs(camera_rgb, baseline_exposure)
    base = profiles._render_profile(bundle.dcp)
    ev = exposure + base["BaselineExposureOffset"]
    working = np.clip(rgb, 0.0, 1.0) @ _working_matrix(base["ForwardMatrix1"]).T
    # SDK RefBaselineABCtoRGB clips before its positive exposure ramp. The two
    # clips commute when the ramp gain is >=1; negative EV uses the tone stage.
    working = np.clip(working * (2.0 ** max(ev, 0.0)), 0.0, 1.0)
    if ev < 0.0:
        working = color_model.dng_tone(working, base["curve_x"], base["curve_y"], ev)
    code = _tetrahedral(color_model.srgb_encode(working), bundle._samples)
    return color_model.srgb_decode(code)


def render_enhanced(camera_rgb, bundle: EnhancedBundle, baseline_exposure=0.0) -> np.ndarray:
    """Render the serialized DCP and quantized XMP as encoded sRGB."""
    linear = _render_prophoto(camera_rgb, bundle, baseline_exposure) @ _PROPHOTO_TO_SRGB.T
    return np.clip(color_model.srgb_encode(linear), 0.0, 1.0)


def bundle_zip(bundle: EnhancedBundle) -> bytes:
    """Build the deterministic archive handed to Adobe Profile Import."""
    output = BytesIO()
    readme = (
        "Firmware Color Studio enhanced profile\n\n"
        f'Profile: {bundle.report["profile_name"]}\n'
        f'Required base profile: {bundle.report["base_profile_name"]}\n\n'
        "Import the archive through Adobe's Import Profiles and Presets dialog. "
        f'If installing files individually, put {bundle.report["dcp_filename"]} in CameraRaw/CameraProfiles '
        f'and {bundle.report["xmp_filename"]} in CameraRaw/Settings. '
        "Bundles with the same colour matrix and calibration share one base profile file. "
        "The enhanced profile matches its base by the name recorded inside the DCP.\n\n"
        "Use the paired DCP and XMP together. The offline preview uses their exported quantized data. "
        "Adobe's render also depends on the process version, raw processing, and edit settings.\n"
    ).encode("utf-8")
    files = {
        bundle.report["dcp_filename"]: bundle.dcp,
        bundle.report["xmp_filename"]: bundle.xmp,
        bundle.report["xmp_filename"][:-4] + ".json": _recipe_json(bundle.recipe).encode("utf-8"),
        "README.txt": readme,
    }
    with ZipFile(output, "w") as archive:
        for name, data in files.items():
            entry = ZipInfo(name)
            entry.create_system = 3
            archive.writestr(entry, data, compress_type=ZIP_DEFLATED, compresslevel=6)
    return output.getvalue()
