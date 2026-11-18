"""Repeatable profile export and installer smoke checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from . import __version__
from .profiles import build_profile, default_recipe, list_modes, load_recipe, render_dcp


DEMO_RAW = Path(__file__).parent / "data" / "demo" / "color-cube.dng"
DEMO_RAW_SHA256 = "1e3352ccba0db428fd2a183718fc857fb283b1d43ad704305e5094c19e0a0428"


def verify() -> dict:
    from .raw import load_raw, resize_rgb

    with DEMO_RAW.open("rb") as stream:
        demo_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if demo_digest != DEMO_RAW_SHA256:
        raise ValueError("bundled color cube RAW does not match the published source checksum")
    frame = load_raw(DEMO_RAW)
    rgb = resize_rgb(frame.rgb, 64)
    modes = {}
    comparison = {}
    for mode in list_modes():
        if mode == "gold":
            from .enhanced import build_enhanced, render_enhanced
            bundle = build_enhanced(default_recipe(mode))
            preview = render_enhanced(rgb, bundle, frame.baseline_exposure)
            data = bundle.xmp
        else:
            data, _ = build_profile(default_recipe(mode))
            preview = render_dcp(rgb, data, frame.baseline_exposure)
        if preview.shape != rgb.shape or not np.isfinite(preview).all() or preview.min() < 0 or preview.max() > 1:
            raise ValueError(f"invalid {mode} rendering")
        modes[mode] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "render_ok": True}
        if mode in ("natural", "bright"):
            comparison[mode] = preview
    maximum_difference = float(np.max(np.abs(comparison["natural"] - comparison["bright"])))
    if maximum_difference <= 1 / 255:
        raise ValueError("bundled color cube renderings do not distinguish Natural and Bright")
    demo = {
        "file": DEMO_RAW.name, "sha256": demo_digest, "model": frame.metadata["model"],
        "width": frame.metadata["width"], "height": frame.metadata["height"],
        "baseline_exposure": frame.baseline_exposure, "natural_bright_max_difference": maximum_difference,
    }
    return {"version": __version__, "status": "passed", "modes": modes, "demo": demo, "firmware_required": False}


def main():
    parser = argparse.ArgumentParser(description="Firmware and chart-based camera profiles for Lightroom.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="verify packaged defaults and render the bundled demo RAW")
    check.add_argument("--report", type=Path, required=True)
    export = commands.add_parser("export", help="export a saved recipe")
    export.add_argument("recipe", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--enhanced", action="store_true", help="write a DCP+XMP ZIP")
    chart = commands.add_parser("chart-fit", help="estimate a Pentax DCP from a Classic 24 chart JPEG")
    chart.add_argument("jpeg", type=Path)
    chart.add_argument("output", type=Path)
    chart.add_argument("--corners", type=float, nargs=8, required=True, metavar="N",
                       help="oriented JPEG pixel coordinates x y for patch centers 1, 6, 24, 19 in that order")
    chart.add_argument("--name", help="profile name (defaults to the JPEG camera name or filename stem)")
    chart.add_argument("--edition", choices=("2014+", "pre2014"), default="2014+",
                       help="Classic chart formulation, November 2014 and later or earlier")
    preview = commands.add_parser("preview", help="render a half-resolution RAW color preview to PNG")
    preview.add_argument("raw", type=Path)
    preview.add_argument("output", type=Path)
    preview.add_argument("--recipe", type=Path)
    preview.add_argument("--mode", default="natural")
    preview.add_argument("--size", type=int, default=1000)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            data = json.dumps(verify(), indent=2).encode() + b"\n"
            with args.report.open("xb") as stream:
                stream.write(data)
        elif args.command == "chart-fit":
            from .chart_fit import fit_chart
            from .chart_input import load_chart_jpeg, sample_chart

            if args.output.suffix.lower() != ".dcp":
                raise ValueError("chart-fit output must be .dcp")
            if args.output.exists():
                raise FileExistsError(args.output)
            photo = load_chart_jpeg(args.jpeg)
            corners = np.asarray(args.corners).reshape(4, 2)
            fitted = fit_chart(sample_chart(photo.image, corners), photo.name if args.name is None else args.name,
                               edition=args.edition)
            with args.output.open("xb") as stream:
                stream.write(fitted.dcp)
            if sys.stdout is not None:
                print(f"Mean patch Delta E76: {fitted.baseline_mean_delta_e:.2f} -> {fitted.mean_delta_e:.2f}")
        elif args.command == "export":
            recipe = load_recipe(args.recipe)
            if args.enhanced:
                from .enhanced import build_enhanced, bundle_zip
                data = bundle_zip(build_enhanced(recipe))
            else:
                data, _ = build_profile(recipe)
            with args.output.open("xb") as stream:
                stream.write(data)
        else:
            from PySide6.QtGui import QGuiApplication
            from .display import rgb_image
            from .raw import load_raw, resize_rgb
            if not 32 <= args.size <= 4096:
                raise ValueError("preview size must be within 32..4096")
            if args.output.suffix.lower() != ".png":
                raise ValueError("preview output must be .png")
            if args.output.exists():
                raise FileExistsError(args.output)
            application = QGuiApplication.instance() or QGuiApplication([])
            frame = load_raw(args.raw)
            recipe = load_recipe(args.recipe) if args.recipe else default_recipe(args.mode)
            rgb = resize_rgb(frame.rgb, args.size)
            if recipe["toning"] or recipe["mode"] == "gold":
                from .enhanced import build_enhanced, render_enhanced
                pixels = render_enhanced(rgb, build_enhanced(recipe), frame.baseline_exposure)
            else:
                data, _ = build_profile(recipe)
                pixels = render_dcp(rgb, data, frame.baseline_exposure)
            if not rgb_image(pixels).save(str(args.output), "PNG"):
                raise OSError("could not save PNG")
        return 0
    except Exception as error:
        if args.command == "verify" and not args.report.exists():
            args.report.write_text(json.dumps({"version": __version__, "status": "failed", "error": str(error)}, indent=2), encoding="utf-8")
        if sys.stderr is not None:
            print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
