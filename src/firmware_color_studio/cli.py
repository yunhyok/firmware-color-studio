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


def verify() -> dict:
    modes = {}
    rgb = np.random.default_rng(220).uniform(0.01, 0.8, (16, 16, 3))
    for mode in list_modes():
        if mode == "gold":
            from .enhanced import build_enhanced, render_enhanced
            bundle = build_enhanced(default_recipe(mode))
            preview = render_enhanced(rgb, bundle, -0.5)
            data = bundle.xmp
        else:
            data, _ = build_profile(default_recipe(mode))
            preview = render_dcp(rgb, data, -0.5)
        if preview.shape != rgb.shape or not np.isfinite(preview).all() or preview.min() < 0 or preview.max() > 1:
            raise ValueError(f"invalid {mode} rendering")
        modes[mode] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "render_ok": True}
    return {"version": __version__, "status": "passed", "modes": modes, "firmware_required": False}


def main():
    parser = argparse.ArgumentParser(description="Firmware-derived color profiles; no photographic fitting.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="verify packaged defaults and a synthetic rendering")
    check.add_argument("--report", type=Path, required=True)
    export = commands.add_parser("export", help="export a saved recipe")
    export.add_argument("recipe", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--enhanced", action="store_true", help="write a DCP+XMP ZIP")
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

