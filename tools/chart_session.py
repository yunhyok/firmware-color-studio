"""One ColorChecker, eight cameras: the measurements in docs/chart-session-validation.json.

usage: session.py PHOTO_DIRECTORY OUTPUT.json [DCP_DIRECTORY]
Reads the photographs only.  Needs exiftool on PATH for the JPEGs stored inside the RAW files.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import numpy as np
from PySide6.QtGui import QGuiApplication, QImage

from firmware_color_studio import __version__, chart_detect, chart_fit, chart_input, color_model as color, dcp, profiles, raw
from firmware_color_studio.raw import load_raw

APP = QGuiApplication.instance() or QGuiApplication([])
PHOTOS, OUTPUT = Path(sys.argv[1]), Path(sys.argv[2])
DCP_DIRECTORY = Path(sys.argv[3]) if len(sys.argv) > 3 else None
NAMES = ["dark skin", "light skin", "blue sky", "foliage", "blue flower", "bluish green", "orange", "purplish blue",
         "moderate red", "purple", "yellow green", "orange yellow", "blue", "green", "red", "yellow", "magenta", "cyan",
         "white", "neutral 8", "neutral 6.5", "neutral 5", "neutral 3.5", "black"]
PAIRS = {"pentax-q7": "20261122-IMGP1138.DNG", "pentax-k3iii": "20261121-IMGP9361.DNG"}
# The cameras' own developments of the two DNGs, one JPEG per Custom Image (in-camera RAW development).
DEVELOPED = {"pentax-q7": [f"IMGP{n}.JPG" for n in range(1142, 1153)],
             "pentax-k3iii": [f"IMGP{n}.JPG" for n in range(9422, 9436)]}
DONORS = ["20260111-102_4186.JPG", "20261121-DSC00007.JPG", "20261121-DSC00017.JPG", "20261121-DSC07687.JPG",
          "20261121-PICT0121.JPG", "20100101-SAM_1737.SRW"]


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stored_jpeg(path, tag):
    return subprocess.run(["exiftool", "-b", f"-{tag}", str(path)], capture_output=True, check=True).stdout


def lab(srgb):
    return chart_fit._lab(np.asarray(srgb, dtype=float))


def delta_e(a, b):
    return np.linalg.norm(lab(a) - lab(b), axis=1)


def raw_patches(rgb, corners):
    """The 81 inner samples per patch that chart_input.sample_chart takes, on linear camera RGB."""
    offsets = np.linspace(-0.2, 0.2, 9)
    xy = np.stack(np.meshgrid(offsets, offsets), axis=-1).reshape(81, 2)
    positions = chart_input._project(chart_input._homography(corners), chart_input._GRID[:, None, :] + xy)
    x, y = np.rint(positions).astype(int).transpose(2, 0, 1)
    return np.median(rgb[y, x], axis=1).astype(float)


def scores(predicted, target):
    de = delta_e(predicted, target)
    worst = int(de.argmax())
    return {"mean_delta_e76": round(float(de.mean()), 2), "colour_patches": round(float(de[:18].mean()), 2),
            "grey_patches": round(float(de[18:].mean()), 2),
            "grey_lightness_error": round(float(np.abs(lab(predicted)[18:, 0] - lab(target)[18:, 0]).mean()), 2),
            "maximum": round(float(de.max()), 2), "worst_patch": NAMES[worst]}


def jpeg_note(path, camera_id):
    """Maker note of a camera JPEG: Custom Image and settings, and the white balance it was developed with."""
    data = path.read_bytes()
    start = data.index(b"Exif\0\0") + 6
    reader = raw._Tiff(BytesIO(data[start:start + int.from_bytes(data[start - 8:start - 6], "big") - 8]))
    first, _ = reader.ifd(reader.root())
    model_id = next(camera["model_id"] for camera in raw._CAMERAS.values() if camera["camera_id"] == camera_id)
    note, fields = raw._pentax_note(reader, first, False, model_id)
    info, warnings = raw._capture_info(note, fields, camera_id)
    red, green, _, blue = note.numbers(fields, 0x0201, (3,), (4,))
    return info, warnings, np.array([red / green, 1.0, blue / green])


def grey_matched(render, target):
    """Exposure (EV, step 0.01) at which the six grey patches agree best in lightness, and the scores there."""
    best = min((float(np.abs(lab(render(ev))[18:, 0] - lab(target)[18:, 0]).mean()), ev)
               for ev in (round(-1.5 + 0.01 * i, 2) for i in range(301)))
    return {"exposure_ev": best[1], **scores(render(best[1]), target)}


report = {"studio_version": __version__, "delta_e": "CIE 1976, D50, between encoded sRGB patch medians",
          "patch_sampling": "median of 81 samples in the inner 40 % of each patch (chart_input.sample_chart)",
          "pairs": {}, "donors": {}}
frames = {}
for camera_id, name in PAIRS.items():
    path = PHOTOS / name
    frame = load_raw(path)
    jpeg = QImage.fromData(stored_jpeg(path, "SubIFD1:PreviewImage"), "JPEG").convertToFormat(QImage.Format.Format_RGB888)
    corners = chart_detect.detect_chart(jpeg)
    target = chart_input.sample_chart(jpeg, corners)
    scale = frame.rgb.shape[1] / jpeg.width()
    patches = raw_patches(frame.rgb, corners * scale)
    frames[camera_id] = (frame, patches, target, corners, jpeg.width())
    info = frame.metadata
    recipe = profiles.default_recipe(info["mode"], camera_id)
    recipe["settings"] = info["settings"]
    data, _ = profiles.build_profile(recipe)
    camera = profiles.camera_for_recipe(recipe)
    offset = profiles.baseline_exposure_offset(camera_id)
    entry = {
        "raw": {"file": name, "sha256": sha256(path), "model": info["model"], "format": info["format"],
                "baseline_exposure": round(info["baseline_exposure"], 6), "white_level": info["white_level"],
                "black_level": info["black_level"], "white_balance": [round(v, 6) for v in info["white_balance"]],
                "half_resolution": [info["width"], info["height"]]},
        "camera_jpeg": {"source": "JPEG stored in the DNG (SubIFD1 PreviewImage)", "size": [jpeg.width(), jpeg.height()],
                        "chart_detected_automatically": True, "patch_centres_1_6_24_19": np.round(corners, 1).tolist()},
        "recipe": {"mode": recipe["mode"], "settings": recipe["settings"], "source": "the shot's settings in the maker note",
                   "factory_settings": profiles.default_recipe(info["mode"], camera_id)["settings"]},
        "profile": {"name": profiles.profile_name(recipe), "baseline_exposure_offset": offset, "dcp_sha256": hashlib.sha256(data).hexdigest()},
        "dcp_with_the_file_baseline_exposure": scores(profiles.render_dcp(patches, data, info["baseline_exposure"]), target),
        "dcp_grey_matched": grey_matched(lambda ev: profiles.render_dcp(patches, data, info["baseline_exposure"] + ev), target),
        "other_custom_images_with_the_file_baseline_exposure": {
            mode: scores(profiles.render_dcp(patches, profiles.build_profile(profiles.default_recipe(mode, camera_id))[0],
                                             info["baseline_exposure"]), target)
            for mode in ("natural", "bright", "portrait", "vibrant")},
        "patches": [{"name": NAMES[i], "camera_jpeg": np.round(target[i] * 255).astype(int).tolist(),
                     "dcp": np.round(profiles.render_dcp(patches, data, info["baseline_exposure"])[i] * 255).astype(int).tolist(),
                     "raw_white_balanced": np.round(patches[i], 4).tolist()} for i in range(24)],
    }
    if camera_id == "pentax-q7":
        engine = profiles._pack(camera_id).engine
        s = engine.settings(recipe["mode"], **recipe["settings"])
        # This file's BaselineExposure and the pack's offset cancel, so the model takes the sensor level as it is.
        entry["camera_model_at_sensor_level"] = scores(camera.render(patches), target)
        sampled = engine.camera(recipe["mode"], **recipe["settings"])
        sampled.table = None                                 # gamma(matrix x RGB) without the table, and without dark chroma suppression
        entry["without_the_table"] = {
            "what": "colour matrix, clip and gamma table applied directly (no 9 x 9 x 9 table)",
            "sensor_level": scores(sampled.render(patches), target)}
        half = engine.camera(recipe["mode"], **recipe["settings"])
        half.table = None
        half.curves = np.stack([np.array(engine.gamma(recipe["mode"], s["key"], s["contrast"], ratio=0), dtype=float)] * 3)
        entry["without_the_table"]["fallback_gain_v256_grey_matched"] = grey_matched(lambda ev: half.render(patches * 2 ** ev), target)
        entry["without_the_table"]["nominal_gain_v512_grey_matched"] = grey_matched(lambda ev: sampled.render(patches * 2 ** ev), target)
        entry["table_grey_matched"] = grey_matched(lambda ev: camera.render(patches * 2 ** ev), target)
        # The same table with the other common rule, to show which one the camera's hardware follows.
        basic, nodes = camera.table

        def trilinear(camera_rgb):
            code = np.interp(np.clip(camera_rgb, 0.0, 1.0) * 4095.0, np.arange(4096.0), basic)
            position = np.interp(code, color._TABLE_LEVELS, np.arange(9.0))
            index = np.minimum(position.astype(int), 7)
            fraction = position - index
            return sum(np.prod(np.where(corner, fraction, 1 - fraction), axis=-1, keepdims=True)
                       * nodes[tuple((index + corner).T)] for corner in np.ndindex(2, 2, 2)) / 4095.0

        other = engine.camera(recipe["mode"], **recipe["settings"])
        other._table_codes = trilinear
        entry["table_interpolated_trilinearly"] = {"sensor_level": scores(other.render(patches), target),
                                                   "grey_matched": grey_matched(lambda ev: other.render(patches * 2 ** ev), target)}
    report["pairs"][camera_id] = entry
    print(camera_id, entry["dcp_with_the_file_baseline_exposure"], entry["dcp_grey_matched"])

for name in DONORS:
    path = PHOTOS / name
    with tempfile.TemporaryDirectory() as directory:
        jpeg_path = path
        source = "camera JPEG"
        if path.suffix.upper() == ".SRW":
            jpeg_path = Path(directory) / (path.stem + ".jpg")
            jpeg_path.write_bytes(stored_jpeg(path, "JpgFromRaw"))
            source = "JPEG stored in the SRW (JpgFromRaw)"
        photo = chart_input.load_chart_jpeg(jpeg_path)
    try:
        corners, detected = chart_detect.detect_chart(photo.image), True
    except ValueError as error:
        report["donors"][name] = {"sha256": sha256(path), "chart_detected_automatically": False, "error": str(error)}
        print(name, "NOT DETECTED", error)
        continue
    target = chart_input.sample_chart(photo.image, corners)
    label = photo.name if path.suffix.upper() != ".SRW" else "SAMSUNG EX1"
    entry = {"sha256": sha256(path), "source": source, "profile_name": label, "size": [photo.image.width(), photo.image.height()],
             "chart_detected_automatically": detected, "patch_centres_1_6_24_19": np.round(corners, 1).tolist(),
             "patches": np.round(target * 255).astype(int).tolist(), "cameras": {}}
    for camera_id, (frame, patches, own_jpeg, *_) in frames.items():
        fitted = chart_fit.fit_chart(target, label, camera_id=camera_id)
        natural, _ = profiles.build_profile(profiles.default_recipe("natural", camera_id))
        baseline = frame.metadata["baseline_exposure"]
        # v0.2.2 kept the donor's exposure of the chart in the profile: the same tables with a larger offset.
        removed = chart_fit._camera_exposure_offset(camera_id) - dcp.read_dcp(fitted.dcp)["BaselineExposureOffset"]
        entry["cameras"][camera_id] = {
            "donor_exposure_removed_ev": round(removed, 3),
            "fit_on_reference_colours": {"before": round(fitted.baseline_mean_delta_e, 2), "after": round(fitted.mean_delta_e, 2),
                                         "look_used": fitted.fitted},
            "dcp_sha256": hashlib.sha256(fitted.dcp).hexdigest(),
            "on_the_pentax_raw": {
                "generated_dcp": scores(profiles.render_dcp(patches, fitted.dcp, baseline), target),
                "generated_dcp_with_the_v0_2_2_anchor": scores(profiles.render_dcp(patches, fitted.dcp, baseline + removed), target),
                "generated_dcp_grey_matched": grey_matched(lambda ev: profiles.render_dcp(patches, fitted.dcp, baseline + ev), target),
                "pentax_natural": scores(profiles.render_dcp(patches, natural, baseline), target),
                "pentax_natural_grey_matched": grey_matched(lambda ev: profiles.render_dcp(patches, natural, baseline + ev), target),
                "pentax_camera_jpeg": scores(own_jpeg, target),
            },
        }
        if DCP_DIRECTORY is not None:
            DCP_DIRECTORY.mkdir(parents=True, exist_ok=True)
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label).strip("-")
            (DCP_DIRECTORY / f"{camera_id}-chart-{safe}.dcp").write_bytes(fitted.dcp)
        row = entry["cameras"][camera_id]["on_the_pentax_raw"]
        print(f"{name:26s} {camera_id:13s} fit {fitted.baseline_mean_delta_e:5.2f}->{fitted.mean_delta_e:5.2f}  on RAW: DCP {row['generated_dcp']['mean_delta_e76']:5.2f}"
              f" (grey-matched {row['generated_dcp_grey_matched']['mean_delta_e76']:5.2f} at {row['generated_dcp_grey_matched']['exposure_ev']:+.2f} EV)"
              f"  Natural {row['pentax_natural']['mean_delta_e76']:5.2f} ({row['pentax_natural_grey_matched']['mean_delta_e76']:5.2f})"
              f"  camera JPEG {row['pentax_camera_jpeg']['mean_delta_e76']:5.2f}")
    report["donors"][name] = entry

report["developments"] = {}
for camera_id, names in DEVELOPED.items():
    frame, patches, _, corners, preview_width = frames[camera_id]
    baseline = frame.metadata["baseline_exposure"]
    shot = np.array(frame.metadata["white_balance"])[:3]
    rows = report["developments"][camera_id] = {}
    for name in names:
        path = PHOTOS / name
        info, warnings, balance = jpeg_note(path, camera_id)
        photo = chart_input.load_chart_jpeg(path)
        try:
            target, located = chart_input.sample_chart(photo.image, chart_detect.detect_chart(photo.image)), "found automatically"
        except ValueError:                       # no colours to find the chart by (monochrome, cross processing, Gold)
            target = chart_input.sample_chart(photo.image, corners * photo.image.width() / preview_width)
            located = "position taken from the JPEG stored in the DNG"
        mode = info["mode"]
        entry = {"sha256": sha256(path), "size": [photo.image.width(), photo.image.height()], "custom_image": mode,
                 "settings": info["settings"], "toning": info["toning"], "color_space": info["color_space"], "chart": located,
                 "white_balance": [round(float(v), 6) for v in balance],
                 "white_balance_differs_from_the_shot": bool(np.abs(balance - shot).max() > 1e-6)}
        rows[name] = entry
        if mode not in profiles.list_modes(camera_id) or info["settings"] is None:
            entry["profile"] = None
            print(f"{name} {camera_id:13s} {mode}: no profile for this Custom Image")
            continue
        developed = np.minimum(patches * balance / shot, 1.0)       # the white balance of this development
        recipe = profiles.default_recipe(mode, camera_id)
        factory = dict(recipe["settings"])
        recipe.update(settings=info["settings"], color_space=info["color_space"], toning=info["toning"] or 0)
        enhanced = bool(recipe["toning"]) or mode == "gold"
        if enhanced:
            from firmware_color_studio.enhanced import build_enhanced, render_enhanced
            rendered = render_enhanced(developed, build_enhanced(recipe), baseline)
        else:
            rendered = profiles.render_dcp(developed, profiles.build_profile(recipe)[0], baseline)
        entry.update(profile="DCP + XMP" if enhanced else "DCP", profile_name=profiles.profile_name(recipe),
                     changed_from_factory={key: value for key, value in info["settings"].items() if value != factory[key]},
                     **scores(rendered, target))
        if camera_id == "pentax-q7" and not enhanced:
            # v0.3.0 had no highlight chroma suppression; this file's exposure cancels, so the model takes the patches as they are.
            plain = profiles.camera_for_recipe(recipe)
            plain.csp_enable = False
            entry["camera_model_without_highlight_chroma_suppression"] = scores(plain.render(developed), target)
        print(f"{name} {camera_id:13s} {mode:14s} mean {entry['mean_delta_e76']:5.2f}  colours {entry['colour_patches']:5.2f}  greys {entry['grey_patches']:5.2f}"
              f"  max {entry['maximum']:5.2f} ({entry['worst_patch']})  {entry['changed_from_factory'] or ''}")

OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
