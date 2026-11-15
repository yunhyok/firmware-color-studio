"""Versioned recipes, camera pack defaults, profile export and offline DCP rendering."""

from dataclasses import dataclass, field
from functools import cached_property, lru_cache
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

import numpy as np

from . import color_model, dcp
from .engine import Engine, PACK_DIRECTORY, SLIDERS
from .gold import gold_camera

CAMERA_ID = "pentax-k3iii"
CAMERA_MODEL = "PENTAX K-3 Mark III"
PACK_VERSION = "2.20-1"
BASELINE_EXPOSURE_OFFSET = 0.5
LOOK_DIMS = (90, 30, 30)
TONE_POINTS = 257
MAX_RECIPE_BYTES = 64 * 1024
LABELS = {
    "natural": "Natural", "bright": "Bright", "portrait": "Portrait", "landscape": "Landscape",
    "vibrant": "Vibrant", "radiant": "Radiant", "muted": "Muted", "flat": "Flat",
    "bleach-bypass": "Bleach Bypass", "reversal-film": "Reversal Film", "monochrome": "Monochrome",
    "satobi": "SATOBI", "harubeni": "HARUBENI", "katen": "KATEN", "kyushu": "KYUSHU", "fuyuno": "FUYUNO",
}


@dataclass(frozen=True)
class _CameraPack:
    directory: Path
    labels: dict
    load_engine: Callable[[], Engine]
    enhanced_modes: dict = field(default_factory=dict)

    def label(self, mode: str) -> str:
        english = self.labels[mode]
        korean = self.manifest.get("mode_labels_ko", {}).get(mode)
        return f"{english} ({korean})" if korean else english

    @cached_property
    def manifest(self) -> dict:
        return json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))

    @cached_property
    def engine(self) -> Engine:
        return self.load_engine()


_PACKS = {CAMERA_ID: _CameraPack(PACK_DIRECTORY, {**LABELS, "gold": "Gold"}, Engine.load, {"gold": gold_camera})}


def _pack(camera_id) -> _CameraPack:
    if not isinstance(camera_id, str) or camera_id not in _PACKS:
        raise ValueError(f"unsupported camera: {camera_id!r}")
    return _PACKS[camera_id]


def list_modes(camera_id=CAMERA_ID) -> dict:
    pack = _pack(camera_id)
    engine = pack.engine
    return {
        mode: {
            "label": pack.label(mode),
            "defaults": engine.factory_settings(mode),
            "controls": {key: engine.modes[mode]["sliders"][key] == "slider" for key in SLIDERS},
            "toning": bool(engine.modes[mode]["toning"]),
            "plain_dcp": mode not in pack.enhanced_modes,
        }
        for mode in pack.labels
    }


def default_recipe(mode="natural", camera_id=CAMERA_ID) -> dict:
    pack = _pack(camera_id)
    if not isinstance(mode, str) or mode not in pack.labels:
        raise ValueError(f"unsupported Custom Image: {mode!r}")
    return {
        "schema_version": 1,
        "camera_id": camera_id,
        "pack_version": pack.manifest["pack_version"],
        "mode": mode,
        "settings": pack.engine.factory_settings(mode),
        "color_space": "srgb",
        "toning": 0,
        "name": "",
        "calibration": None,
        "runtime": {},
    }


def validate_recipe(recipe: dict) -> dict:
    """Validate a recipe and return a detached copy in canonical field order."""
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be a JSON object")
    mode = recipe.get("mode")
    camera_id = recipe.get("camera_id")
    normalized = default_recipe(mode, camera_id)
    pack = _pack(camera_id)
    if recipe.keys() - normalized.keys():
        raise ValueError("recipe contains unknown fields")
    if type(recipe.get("schema_version")) is not int or recipe["schema_version"] != 1:
        raise ValueError("recipe schema_version must be 1")
    version = normalized["pack_version"]
    if recipe.get("pack_version") != version:
        raise ValueError(f"recipe pack_version must be {version}")

    settings = recipe.get("settings")
    if not isinstance(settings, dict) or settings.keys() != set(SLIDERS):
        raise ValueError("settings must contain exactly saturation, hue, key, contrast, highlight and shadow")
    for key in SLIDERS:
        value = settings[key]
        if type(value) is not int or not -4 <= value <= 4:
            raise ValueError(f"{key} must be an integer within -4..+4")
        normalized["settings"][key] = value

    color_space = recipe.get("color_space")
    if not isinstance(color_space, str) or color_space not in color_model.RGB_SPACES:
        raise ValueError("color_space must be srgb or adobergb")
    toning = recipe.get("toning")
    if type(toning) is not int or not 0 <= toning <= 8:
        raise ValueError("toning must be an integer within 0..8")
    if toning and not pack.engine.modes[mode]["toning"]:
        raise ValueError(f"{pack.labels[mode]} does not have a toning control")

    name = recipe.get("name", "")
    if not isinstance(name, str) or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in name):
        raise ValueError("name must be a string without control characters")
    name = name.strip()
    if len(name.encode("utf-8")) > 1024:
        raise ValueError("name must fit within 1024 UTF-8 bytes")

    calibration = recipe.get("calibration")
    if calibration is not None:
        if not isinstance(calibration, list) or len(calibration) != 2:
            raise ValueError("calibration must contain ColorMatrix1 and ColorMatrix2")
        for index, matrix in enumerate(calibration, 1):
            dcp.matrix(matrix, f"ColorMatrix{index}")
        calibration = [[[float(value) for value in row] for row in matrix] for matrix in calibration]

    runtime = recipe.get("runtime", {})
    if not isinstance(runtime, dict) or runtime:
        raise ValueError("runtime must be an empty object for this Custom Image")
    normalized.update(color_space=color_space, toning=toning, name=name, calibration=calibration)
    return normalized


def _profile_name(pack: _CameraPack, recipe: dict, effective: dict) -> str:
    mode = recipe["mode"]
    label = pack.label(mode)
    if recipe["name"]:
        return f'{label} · {recipe["name"]}'
    engine = pack.engine
    factory = engine.settings(mode, **engine.factory_settings(mode))
    suffix = "".join(f" {key[:3]}{value:+d}" for key, value in effective.items() if value != factory[key])
    if recipe["color_space"] == "adobergb":
        suffix += " (AdobeRGB)"
    if recipe["toning"]:
        color = engine.tables["toning"]["names"][recipe["toning"]]
        suffix += f" ({color.capitalize()})"
    return f'{pack.manifest["profile_name_prefix"]} {label}{suffix}'


def profile_name(recipe: dict) -> str:
    recipe = validate_recipe(recipe)
    pack = _pack(recipe["camera_id"])
    return _profile_name(pack, recipe, pack.engine.settings(recipe["mode"], **recipe["settings"]))


def camera_for_recipe(recipe: dict) -> color_model.CameraColour:
    recipe = validate_recipe(recipe)
    pack = _pack(recipe["camera_id"])
    mode = recipe["mode"]
    if mode in pack.enhanced_modes:
        return pack.enhanced_modes[mode](pack.engine, recipe["settings"], recipe["color_space"], recipe["runtime"])
    return pack.engine.camera(mode, recipe["color_space"], toning=recipe["toning"], **recipe["settings"])


def _profile_tags(pack: _CameraPack, forward, matrices, name: str) -> dict:
    return {
        "provenance": pack.manifest["source_repository"],
        "UniqueCameraModel": pack.manifest["camera_model"],
        "ProfileName": name,
        "ProfileCopyright": pack.manifest["profile_copyright"],
        "ProfileEmbedPolicy": 0,
        "CalibrationIlluminant1": 17,
        "CalibrationIlluminant2": 21,
        "ColorMatrix1": matrices[0],
        "ColorMatrix2": matrices[1],
        "ForwardMatrix1": forward,
        "ForwardMatrix2": forward,
        "BaselineExposureOffset": BASELINE_EXPOSURE_OFFSET,
        "DefaultBlackRender": 1,
    }


def _assemble_profile(pack: _CameraPack, camera: color_model.CameraColour, common, matrices, name: str) -> bytes:
    x, y = camera.tone_curve(TONE_POINTS)
    table = color_model.build_look_table(camera, x, y, *LOOK_DIMS, forward_base=common)
    return dcp.build_dcp({
        **_profile_tags(pack, camera.forward_matrix(common).tolist(), matrices, name),
        "ProfileToneCurve": np.column_stack((x, y)).tolist(),
        "ProfileLookTableDims": list(LOOK_DIMS),
        "ProfileLookTableEncoding": 1,
        "ProfileLookTableData": table.rows().tolist(),
    })

def build_profile(recipe: dict) -> tuple[bytes, dict]:
    recipe = validate_recipe(recipe)
    if recipe["toning"]:
        raise ValueError("toning changes neutral colours and requires an enhanced profile")
    pack = _pack(recipe["camera_id"])
    engine = pack.engine
    mode, space, requested = recipe["mode"], recipe["color_space"], recipe["settings"]
    if mode in pack.enhanced_modes:
        raise ValueError(f"{pack.labels[mode]} requires an enhanced profile")
    factory = engine.factory_settings(mode)
    effective = engine.settings(mode, **requested)
    name = _profile_name(pack, recipe, effective)
    calibration = recipe["calibration"]
    default_path = pack.manifest["default_profiles"].get(mode)
    packaged = (default_path is not None and not recipe["name"] and calibration is None and space == "srgb"
                and effective == engine.settings(mode, **factory))
    template_sha = None
    if packaged:
        template = (pack.directory / default_path).read_bytes()
        template_sha = hashlib.sha256(template).hexdigest()
        if template_sha != pack.manifest["files"][default_path]["sha256"]:
            raise ValueError(f"packaged DCP for {mode} does not match its camera pack hash")
        data = dcp.rename_profile(template, name)
    else:
        camera = engine.camera(mode, space, **requested)
        matrices = calibration if calibration is not None else [matrix.tolist() for matrix in engine.dng_color_matrices()]
        data = _assemble_profile(pack, camera, engine.common_matrix(), matrices, name)
    digest = hashlib.sha256(data).hexdigest()
    return data, {
        "camera_id": recipe["camera_id"],
        "pack_version": recipe["pack_version"],
        "mode": mode,
        "profile_name": name,
        "requested_settings": requested,
        "effective_settings": effective,
        "factory_settings": factory,
        "factory_toning_left_out": engine.factory_toning(mode),
        "color_space": space,
        "custom_calibration": calibration is not None,
        "forward_matrix_source": "sensor matrix shared by all Custom Images",
        "look_table_dims": list(LOOK_DIMS),
        "tone_curve_points": TONE_POINTS,
        "packaged_default": packaged,
        "default_template_sha256": template_sha,
        "dcp_bytes": len(data),
        "dcp_sha256": digest,
    }


@lru_cache(maxsize=4)
def _render_profile(data: bytes) -> dict:
    return dcp.read_dcp(data)


def _render_inputs(camera_rgb, baseline_exposure):
    """Check RGB and BaselineExposure accepted by the offline renderers."""
    rgb = np.asarray(camera_rgb)
    if rgb.ndim == 0 or rgb.shape[-1] != 3 or rgb.dtype.kind not in "fiu" or not np.isfinite(rgb).all():
        raise ValueError("camera RGB must contain finite RGB triplets")
    exposure = dcp.number(baseline_exposure, "baseline_exposure")
    if not -32 <= exposure <= 32:
        raise ValueError("baseline_exposure must be within -32..32 EV")
    return rgb, exposure


def render_dcp(camera_rgb, dcp_bytes: bytes, baseline_exposure=0.0) -> np.ndarray:
    """Render white-balanced, camera-linear RGB to encoded sRGB in 0..1."""
    rgb, exposure = _render_inputs(camera_rgb, baseline_exposure)
    if not isinstance(dcp_bytes, bytes):
        raise ValueError("DCP data must be bytes")
    profile = _render_profile(dcp_bytes)
    linear = color_model.dng_render(
        rgb, profile["ForwardMatrix1"], profile["LookTable"],
        profile["curve_x"], profile["curve_y"], exposure + profile["BaselineExposureOffset"],
    )
    return np.clip(color_model.srgb_encode(linear), 0.0, 1.0)


def load_recipe(path) -> dict:
    with Path(path).open("rb") as source:
        raw = source.read(MAX_RECIPE_BYTES + 1)
    if len(raw) > MAX_RECIPE_BYTES:
        raise ValueError("recipe exceeds 64 KiB")
    try:
        recipe = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=dcp.unique_fields)
    except RecursionError as error:
        raise ValueError("recipe JSON is nested too deeply") from error
    return validate_recipe(recipe)


def save_recipe(path, recipe: dict) -> None:
    """Atomically create or replace a recipe after validation."""
    path = Path(path)
    payload = json.dumps(validate_recipe(recipe), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".recipe-", delete=False) as output:
            temporary = Path(output.name)
            output.write(payload.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
