"""Estimate an SDR DCP from the 24 measured sRGB patches of a donor JPEG.

X-Rite ColorChecker Classic reference measurements are CIELAB, D50/2°.
Numerical measurements from ColorChecker24_Before_Nov2014.txt and
ColorChecker24_After_Nov2014.txt, reordered by printed row (A1..F1 etc.).
Source: X-Rite, https://doi.org/10.5281/zenodo.3245895 .
"""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import color_model as color
from . import dcp, profiles


_LAB_AFTER_2014 = np.array([
    [37.54, 14.37, 14.92], [64.66, 19.27, 17.50], [49.32, -3.82, -22.54],
    [43.46, -12.74, 22.72], [54.94, 9.61, -24.79], [70.48, -32.26, -0.37],
    [62.73, 35.83, 56.50], [39.43, 10.75, -45.17], [50.57, 48.64, 16.67],
    [30.10, 22.54, -20.87], [71.77, -24.13, 58.19], [71.51, 18.24, 67.37],
    [28.37, 15.42, -49.80], [54.38, -39.72, 32.27], [42.43, 51.05, 28.62],
    [81.80, 2.67, 80.41], [50.63, 51.28, -14.12], [49.57, -29.71, -28.32],
    [95.19, -1.03, 2.93], [81.29, -0.57, 0.44], [66.89, -0.75, -0.06],
    [50.76, -0.13, 0.14], [35.63, -0.46, -0.48], [20.64, 0.07, -0.46],
])

_LAB_BEFORE_2014 = np.array([
    [37.986, 13.555, 14.059], [65.711, 18.130, 17.810], [49.927, -4.880, -21.905],
    [43.139, -13.095, 21.905], [55.112, 8.844, -25.399], [70.719, -33.397, -0.199],
    [62.661, 36.067, 57.096], [40.020, 10.410, -45.964], [51.124, 48.239, 16.248],
    [30.325, 22.976, -21.587], [72.532, -23.709, 57.255], [71.941, 19.363, 67.857],
    [28.778, 14.179, -50.297], [55.261, -38.342, 31.370], [42.101, 53.378, 28.190],
    [81.733, 4.039, 79.819], [51.935, 49.986, -14.574], [51.038, -28.631, -28.638],
    [96.539, -0.425, 1.186], [81.257, -0.638, -0.335], [66.766, -0.734, -0.504],
    [50.867, -0.153, -0.270], [35.656, -0.421, -1.231], [20.461, -0.079, -0.973],
])


def _reference_xyz(edition):
    if edition not in ("2014+", "pre2014"):
        raise ValueError("Unknown ColorChecker edition; use 2014+ or pre2014")
    light, a, b = (_LAB_AFTER_2014 if edition == "2014+" else _LAB_BEFORE_2014).T
    y = (light + 16) / 116
    f = np.column_stack((y + a / 500, y, y - b / 200))
    delta = 6 / 29
    return np.asarray(dcp.D50) * np.where(f > delta, f**3, 3 * delta**2 * (f - 4 / 29))


def reference_srgb(edition="2014+"):
    """Return nominal display sRGB in [0, 1], dark skin first, black last."""
    return color.srgb_encode(np.clip(_reference_xyz(edition) @ color.PCS_TO_SRGB.T, 0, 1))


def _lab(srgb):
    xyz = (color.srgb_decode(srgb) @ color.SRGB_TO_PCS.T) / dcp.D50
    delta = 6 / 29
    x, y, z = np.where(xyz > delta**3, np.cbrt(xyz), xyz / (3 * delta**2) + 4 / 29).T
    return np.column_stack((116 * y - 16, 500 * (x - y), 200 * (y - z)))


@dataclass(frozen=True)
class ChartFit:
    dcp: bytes
    predicted_srgb: np.ndarray
    mean_delta_e: float
    baseline_mean_delta_e: float
    fitted: bool = True     # False: the uncorrected profile was closer and is returned instead


@lru_cache(maxsize=8)
def _camera_exposure_offset(camera_id):
    """Anchor scene Y=0.18 to this camera's factory Natural rendering at 0 EV."""
    natural, _ = profiles.build_profile(profiles.default_recipe("natural", camera_id))
    # Bracket middle gray on the neutral WB sensor ramp, then refine locally.
    ramp = np.linspace(0, 1, 257)
    neutral = np.repeat(ramp[:, None], 3, axis=1)
    luminance = color.srgb_decode(profiles.render_dcp(neutral, natural)) @ color.SRGB_TO_PCS[1]
    if np.any(np.diff(luminance) < -1e-7) or not luminance[0] < 0.18 < luminance[-1]:
        raise ValueError("Camera's Natural profile has no monotone middle-gray anchor")
    index = np.searchsorted(luminance, 0.18)
    low, high = ramp[index - 1], ramp[index]
    for _ in range(20):
        mid = (low + high) * 0.5
        gray = profiles.render_dcp([mid, mid, mid], natural)
        if color.srgb_decode(gray) @ color.SRGB_TO_PCS[1] < 0.18:
            low = mid
        else:
            high = mid
    # Keep reference sensor predictions consistent with the serialized SRATIONAL.
    return round(float(np.log2(0.18 / ((low + high) * 0.5))), 6)


def _donor_exposure(camera_id, sensor, lightness, limit):
    """EV by which the donor exposed the chart above this camera's Natural, from the four middle greys.

    One JPEG cannot tell a donor's look from how its camera happened to expose the chart, and
    a RAW of the same scene carries that exposure a second time.  The level of the greys is
    therefore taken from Natural; the shape of the tone curve stays the donor's.
    """
    natural, _ = profiles.build_profile(profiles.default_recipe("natural", camera_id))
    low, high = -3.0, limit                       # the profile's own exposure must stay positive
    for _ in range(24):
        middle = (low + high) * 0.5
        if _lab(profiles.render_dcp(sensor, natural, middle))[:, 0].mean() < lightness.mean():
            low = middle
        else:
            high = middle
    return (low + high) * 0.5


def _fit_look(source, target):
    """Fit eight periodic hue knots shared across exposure, with a neutral anchor."""
    hue, sat, value = color.rgb_to_hsv(source).T
    target_hue, target_sat, target_value = color.rgb_to_hsv(target).T
    knots = 8
    pos = hue * knots / 6
    lo = np.floor(pos).astype(int) % knots
    frac = pos - np.floor(pos)
    eye = np.eye(knots)
    basis = (1 - frac[:, None]) * eye[lo] + frac[:, None] * eye[(lo + 1) % knots]
    second = np.roll(eye, -1, axis=1) - 2 * eye + np.roll(eye, 1, axis=1)
    penalty = 0.04 * eye + 0.12 * second.T @ second

    def solve(scale, residual):
        design = scale[:, None] * basis
        return np.linalg.solve(design.T @ design + penalty, design.T @ residual)

    hue_weight = np.sqrt(sat * target_sat)
    hue_error = ((target_hue - hue + 3) % 6 - 3) * 60
    shift = np.clip(solve(hue_weight, hue_weight * hue_error), -60, 60)
    saturation = np.clip(1 + solve(sat, target_sat - sat), 0, 2.5)
    encoded_value = color.srgb_encode(value)
    brightness = np.clip(1 + solve(sat * encoded_value, color.srgb_encode(target_value) - encoded_value),
                         0.4, 1.7)
    values = np.empty((2, knots, 2, 3))
    values[..., 0] = shift[:, None]
    values[..., 1] = saturation[:, None]
    values[:, :, 0, 2] = 1.0
    values[:, :, 1, 2] = brightness
    return color.LookTable(knots, 2, 2, values, encoding=1)


def fit_chart(patches, name, *, camera_id=profiles.CAMERA_ID, edition="2014+"):
    """Fit measured 0..1 encoded sRGB from a 6 × 4 Classic chart to a camera pack."""
    target = np.asarray(patches)
    if (target.shape != (24, 3) or target.dtype.kind not in "fiu" or not np.isfinite(target).all()
            or np.min(target) < 0 or np.max(target) > 1):
        raise ValueError("Expected 24 finite normalized sRGB patch triplets in chart order")
    name = dcp.string(name, "ProfileName").strip()
    if len(name.encode("utf-8")) > 1024 or any(127 <= ord(ch) < 160 for ch in name):
        raise ValueError("Invalid profile name")
    pack = profiles._pack(camera_id)
    target_xyz = color.srgb_decode(target) @ color.SRGB_TO_PCS.T
    target_lab = _lab(target)
    gray_light = target_lab[18:, 0]
    if (gray_light[0] - gray_light[-1] < 15 or np.any(np.diff(gray_light) > 4)
            or np.count_nonzero(np.diff(gray_light) < -2) < 3):
        raise ValueError("Check chart orientation and exposure: the six gray patches must descend from white to black")

    source_xyz = _reference_xyz(edition)
    forward = color.SRGB_TO_PCS @ pack.engine.common_matrix()
    offset = _camera_exposure_offset(camera_id)
    # Convert nominal reflectances into camera inputs *before* the DCP exposure ramp.
    sensor = np.linalg.solve(forward, source_xyz.T).T / 2**offset
    offset = round(offset - _donor_exposure(camera_id, sensor[19:23], target_lab[19:23, 0], offset), 6)
    sensor = np.linalg.solve(forward, source_xyz.T).T / 2**offset
    source_working = color.dng_working_rgb(sensor, forward, offset)
    # Slightly mix with an identity ramp to keep clipped neutral samples invertible.
    knots = np.r_[0., source_xyz[18:, 1][::-1], 1.]
    measured = np.r_[0., target_xyz[18:, 1][::-1], 1.]
    levels = 0.99 * np.maximum.accumulate(measured) + 0.01 * knots
    curve_x = np.linspace(0, 1, 257)
    curve_y = np.interp(curve_x, knots, levels)
    desired = color.rgb_tone_inverse(target_xyz @ color.PCS_TO_PROPHOTO.T, curve_x, curve_y)
    table = _fit_look(source_working[:18], desired[:18])
    matrices = [m.tolist() for m in pack.engine.dng_color_matrices()]
    tags = {
        **profiles._profile_tags(pack, forward.tolist(), matrices, name),
        "ProfileCopyright": "JPEG chart fit generated with Firmware Color Studio",
        "BaselineExposureOffset": offset,
        "ProfileToneCurve": np.column_stack((curve_x, curve_y)).tolist(),
        "ProfileLookTableDims": [table.hue, table.sat, table.val],
        "ProfileLookTableEncoding": table.encoding,
        "ProfileLookTableData": table.rows().tolist(),
    }
    data = dcp.build_dcp(tags)
    prediction = profiles.render_dcp(sensor, data)
    # Score the encoded baseline too: a colorimetric JPEG may need no look.
    identity = dcp.build_dcp({**tags, "ProfileToneCurve": [[0, 0], [1, 1]],
                              "ProfileLookTableDims": [1, 2, 2],
                              "ProfileLookTableData": [[0., 1., 1.]] * 4})
    baseline = profiles.render_dcp(sensor, identity)
    before = np.linalg.norm(_lab(baseline) - target_lab, axis=1)
    after = np.linalg.norm(_lab(prediction) - target_lab, axis=1)
    if before.mean() < after.mean():
        return ChartFit(identity, baseline, float(before.mean()), float(before.mean()), fitted=False)
    return ChartFit(data, prediction, float(after.mean()), float(before.mean()))
