import json
import sys

import pytest

from firmware_color_studio import cli


def test_verify_renders_bundled_camera_raw():
    report = cli.verify()
    demo = report["demo"]
    assert report["status"] == "passed"
    assert demo["file"] == "color-cube.dng"
    assert demo["sha256"] == "1e3352ccba0db428fd2a183718fc857fb283b1d43ad704305e5094c19e0a0428"
    assert demo["model"] == "PENTAX K-3 Mark III"
    assert (demo["width"], demo["height"]) == (3096, 2064)
    assert demo["baseline_exposure"] == pytest.approx(-0.8372650146484375)
    assert demo["natural_bright_max_difference"] > 1 / 255
    assert report["modes"]["natural"]["render_ok"]
    assert report["modes"]["bright"]["render_ok"]


def test_verify_reports_missing_demo(monkeypatch, tmp_path):
    missing = tmp_path / "missing.dng"
    report_file = tmp_path / "report.json"
    monkeypatch.setattr(cli, "DEMO_RAW", missing)
    monkeypatch.setattr(sys, "argv", ["fcs", "verify", "--report", str(report_file)])

    assert cli.main() == 1
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert missing.name in report["error"]
