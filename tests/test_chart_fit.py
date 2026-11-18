import numpy as np
import pytest

from firmware_color_studio import chart_fit, color_model, dcp, profiles


def test_colorimetric_targets_keep_neutral_profile_and_select_chart_edition():
    modern = chart_fit.reference_srgb()
    old = chart_fit.reference_srgb("pre2014")
    # X-Rite row A1..F1 is skin through bluish green. A4 and F4 are white and black.
    np.testing.assert_array_equal(np.rint(modern[[0, 5, 18, 23]] * 255),
                                  [[116, 79, 65], [95, 189, 172], [241, 242, 235], [50, 50, 50]])
    assert np.max(np.abs(old - modern)) > .01
    for edition, reference in (("2014+", modern), ("pre2014", old)):
        result = chart_fit.fit_chart(reference, "카메라 모양", edition=edition)
        assert result.mean_delta_e < .001
        assert result.mean_delta_e <= result.baseline_mean_delta_e
        np.testing.assert_allclose(result.predicted_srgb, reference, atol=2e-5)


def test_standalone_profile_reproduces_a_look_on_chart_and_unseen_colours():
    model = np.array([[1.05, -.03, -.02], [-.05, 1.1, -.05], [.04, -.1, 1.06]])

    def donor(srgb):
        linear = color_model.srgb_decode(srgb) @ model.T
        return color_model.srgb_encode(np.clip(linear, 0, 1)**.79)

    reference = chart_fit.reference_srgb()
    target = donor(reference)
    name = "Fictional Camera · 봄"
    fit = chart_fit.fit_chart(target, name)
    assert fit.mean_delta_e < fit.baseline_mean_delta_e / 2
    parsed = dcp.read_dcp(fit.dcp)
    assert parsed["ProfileName"] == name
    camera_model = dcp._directory(fit.dcp)[dcp.TAGS["UniqueCameraModel"]][3]
    assert bytes(camera_model).rstrip(b"\0").decode() == profiles.CAMERA_MODEL
    engine = profiles._pack(profiles.CAMERA_ID).engine
    for i, expected in enumerate(engine.dng_color_matrices(), 1):
        np.testing.assert_allclose(parsed[f"ColorMatrix{i}"], expected, atol=0.5e-6)
    offset = parsed["BaselineExposureOffset"]
    assert np.all(np.diff(parsed["curve_y"]) >= 0)
    # The exported gain maps the factory Natural middle-gray sensor exposure to Y=.18.
    raw_gray = 0.18 / 2**offset
    natural, _ = profiles.build_profile(profiles.default_recipe("natural"))
    gray = profiles.render_dcp([raw_gray] * 3, natural)
    gray_y = color_model.srgb_decode(gray) @ color_model.SRGB_TO_PCS[1]
    assert gray_y == pytest.approx(.18, abs=2e-7)
    # Independent colours, absent from the fit, driven by the same donor transform.
    unseen = np.random.default_rng(161).uniform(.17, .85, (256, 3))
    sensor = np.linalg.solve(engine.common_matrix(), color_model.srgb_decode(unseen).T).T / 2**offset
    rendered = profiles.render_dcp(sensor, fit.dcp)
    target_lab = chart_fit._lab(donor(unseen))
    residual = np.linalg.norm(chart_fit._lab(rendered) - target_lab, axis=1)
    baseline = np.linalg.norm(chart_fit._lab(unseen) - target_lab, axis=1)
    assert residual.mean() < .5 * baseline.mean()


def test_wrong_orientation_flat_exposure_and_bad_inputs_are_rejected():
    ref = chart_fit.reference_srgb()
    for unusable in (ref[::-1], np.ones_like(ref), ref * np.nan, ref[:-1], ref * 255):
        with pytest.raises(ValueError):
            chart_fit.fit_chart(unusable, "Test")
    with pytest.raises(ValueError, match="edition"):
        chart_fit.fit_chart(ref, "Test", edition="SG")
    with pytest.raises(ValueError, match="ProfileName"):
        chart_fit.fit_chart(ref, "Bad\0name")
