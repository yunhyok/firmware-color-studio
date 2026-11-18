"""Collect dependency license texts and draw the application's original icon."""
from hashlib import sha256
from importlib import metadata
from pathlib import Path
import shutil
import sys

from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor


# Upstream texts for the pinned Windows libraries. Source URLs are in THIRD_PARTY_NOTICES.md.
UPSTREAM_LICENSES = {
    "OpenCV/MCC-MIT.txt": "9018d65a9809d1721a38fba269d0bcd859a9c4ba088d5dd64692df41074029a2",
    "Qt/GPL-3.0-only.txt": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
    "Qt/LGPL-3.0-only.txt": "da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768",
    "LibRaw/COPYRIGHT.txt": "574c88f5dd59414cfc896293a63defbc2d525a418ed413d7ab7dcc43cf79c509",
    "rawpy/JasPer-LICENSE.txt": "4ad1bb42aff888c4403d792e6e2c5f1716d6c279fea70b296333c9d577d30b81",
    "rawpy/libjpeg-turbo-LICENSE.md": "ba6bceebcba0fdd35488477c2cca8c4632ce82c74dbfbc87d886ce6fc4433579",
    "rawpy/README.ijg": "75815e3bf6484201a3c3d17a1bbf10f2e8e3237f84df10a2357ea896db2a81d6",
    "rawpy/Little-CMS-LICENSE.txt": "6dbd60437f8ef91d8de1f08ad75882547fd4931bfcc3566a0735f28db1484d31",
    "rawpy/zlib-LICENSE.txt": "e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2",
}


def main():
    root = Path(__file__).resolve().parents[1]
    resources = root / "src" / "firmware_color_studio" / "resources"
    licenses = resources / "licenses"
    for relative, digest in UPSTREAM_LICENSES.items():
        content = (licenses / relative).read_text(encoding="utf-8")
        if sha256(content.encode("utf-8")).hexdigest() != digest:
            raise RuntimeError(f"Upstream license does not match its source: {relative}")
    app = QGuiApplication.instance() or QGuiApplication([])
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(QColor("#171b21"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#171b21"))
    for x, y, color in [(40, 40, "#6bd8ca"), (136, 40, "#e7b768"), (40, 136, "#9b94d8"), (136, 136, "#e0e8ef")]:
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(x, y, 80, 80), 16, 16)
    painter.end()
    if not image.save(str(resources / "app.ico"), "ICO"):
        raise RuntimeError("ICO writer unavailable")
    count = len(UPSTREAM_LICENSES)
    raw_license = False
    for package in ("numpy", "rawpy", "PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6", "pyinstaller"):
        dist = metadata.distribution(package)
        for relative in dist.files or []:
            if not relative.name.lower().startswith(("license", "copying", "copyright")):
                continue
            source = Path(dist.locate_file(relative))
            if not source.is_file() or source.stat().st_size > 2_000_000:
                continue
            target = licenses / package / str(relative).replace("..", "_").replace("/", "__")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            count += 1
            raw_license |= package == "rawpy" and relative.name == "LICENSE.LibRaw"
    if not raw_license:
        raise RuntimeError("LibRaw license missing from the installed rawpy distribution")
    for filename in ("LICENSE.txt", "LICENSE_PYTHON.txt"):
        python_license = Path(sys.base_prefix) / filename
        if python_license.is_file():
            shutil.copyfile(python_license, licenses / "Python-LICENSE.txt")
            count += 1
            break
    print(f"Collected {count} dependency license files and the application icon.")


if __name__ == "__main__":
    main()
