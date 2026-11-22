"""Draw the figures and take the screenshots of the built-in user guide.

usage: python tools/build_help_images.py [DIRECTORY_WITH_CAMERA_PHOTOS]

Writes src/firmware_color_studio/resources/help/images/.  Every picture is twice as wide as
the page shows it (help.py and web browsers scale it down).  Needs a desktop session for the
platform's fonts; the windows it grabs are never put on the screen.  The camera photographs
(Wikimedia Commons, see the guide's credits) are only resized, from the directory given.
"""
import json
import math
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from firmware_color_studio import app, chart_dialog, chart_fit, color_model, profiles     # noqa: E402
from firmware_color_studio.cli import DEMO_RAW                                             # noqa: E402
from firmware_color_studio.display import rgb_image                                        # noqa: E402
from firmware_color_studio.raw import load_raw, resize_rgb                                 # noqa: E402

OUT = ROOT / "src" / "firmware_color_studio" / "resources" / "help" / "images"
INK, SOFT = "#1f2933", "#52606d"
BLUE, GREEN, AMBER, GREY, RED = ("#e8f1fd", "#3b82c4"), ("#e6f6ec", "#3a9b62"), ("#fdf3dc", "#c48a1a"), ("#f1f3f5", "#8896a5"), "#e5484d"


def font(size, bold=False):
    f = QFont("Malgun Gothic")
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def canvas(width, height):
    image = QImage(2 * width, 2 * height, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    p = QPainter(image)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    p.scale(2, 2)
    return image, p


def save(image, p, name):
    p.end()
    assert image.save(str(OUT / name)), name
    print(name, image.width(), "x", image.height())


def box(p, x, y, w, h, text, colors=BLUE, size=13, bold=False):
    p.setPen(QPen(QColor(colors[1]), 1.5))
    p.setBrush(QColor(colors[0]))
    p.drawRoundedRect(QRectF(x, y, w, h), 8, 8)
    text_at(p, x + 6, y + 3, w - 12, h - 6, text, size, INK, bold, Qt.AlignmentFlag.AlignCenter)


def text_at(p, x, y, w, h, text, size=12, color=SOFT, bold=False, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
    p.setPen(QColor(color))
    p.setFont(font(size, bold))
    p.drawText(QRectF(x, y, w, h), int(align | Qt.TextFlag.TextWordWrap), text)


def arrow(p, x1, y1, x2, y2, color=SOFT):
    p.setPen(QPen(QColor(color), 2))
    p.setBrush(QColor(color))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    angle = math.atan2(y2 - y1, x2 - x1)
    tip = QPointF(x2, y2)
    p.drawPolygon(QPolygonF([tip, QPointF(x2 - 9 * math.cos(angle - 0.4), y2 - 9 * math.sin(angle - 0.4)),
                             QPointF(x2 - 9 * math.cos(angle + 0.4), y2 - 9 * math.sin(angle + 0.4))]))


def badge(p, x, y, number, radius=11):
    p.setPen(QPen(QColor("#ffffff"), 2))
    p.setBrush(QColor(RED))
    p.drawEllipse(QPointF(x, y), radius, radius)
    p.setPen(QColor("#ffffff"))
    p.setFont(font(round(radius * 1.25), True))
    p.drawText(QRectF(x - radius, y - radius, 2 * radius, 2 * radius), int(Qt.AlignmentFlag.AlignCenter), str(number))


def chain(p, y, height, items, x=20, width=860, gap=26):
    """Boxes of equal width joined by arrows; items are (text, colours)."""
    w = (width - gap * (len(items) - 1)) / len(items)
    for i, (text, colors) in enumerate(items):
        left = x + i * (w + gap)
        box(p, left, y, w, height, text, colors)
        if i:
            arrow(p, left - gap + 3, y + height / 2, left - 3, y + height / 2)


# -- figures ---------------------------------------------------------------------------------------

def concept():
    image, p = canvas(900, 400)
    box(p, 20, 30, 220, 76, "카메라 펌웨어\n색 표와 계산식", AMBER)
    box(p, 20, 162, 220, 76, "내 RAW 사진\nPEF · DNG", GREY)
    box(p, 20, 294, 220, 76, "다른 카메라의 색감\n내장 색감 · 차트 JPEG", GREY)
    box(p, 330, 110, 240, 180, "Firmware Color Studio\n\n카메라의 색 처리를 그대로 계산\n미리보기 · 조정 · 내보내기", BLUE, 14, True)
    box(p, 660, 60, 220, 62, "DCP 프로파일", GREEN, 14, True)
    box(p, 660, 140, 220, 62, "DCP + XMP 묶음 (ZIP)", GREEN, 14, True)
    box(p, 660, 268, 220, 92, "Lightroom · Camera Raw\nRAW를 카메라 JPEG의\n색으로 현상", GREY)
    arrow(p, 240, 68, 328, 150)
    text_at(p, 292, 64, 120, 34,"미리 꺼내\n프로그램에 내장", 11)
    arrow(p, 240, 200, 328, 200)
    text_at(p, 252, 176, 80, 20, "미리보기", 11)
    arrow(p, 240, 332, 328, 250)
    text_at(p, 292, 302, 100, 20, "24패치의 색", 11)
    arrow(p, 570, 170, 658, 96)
    arrow(p, 570, 200, 658, 172)
    text_at(p, 580, 206, 80, 20, "내보내기", 11)
    arrow(p, 770, 202, 770, 266)
    text_at(p, 780, 222, 110, 20, "프로파일 가져오기", 11)
    save(image, p, "concept.png")


def workflow():
    image, p = canvas(900, 130)
    steps = ["① RAW 열기\n(없어도 됨)", "② 카메라와\n프로파일 고르기", "③ 채도·색상·\n밝기·대비 조정", "④ 프로파일\n내보내기", "⑤ Lightroom에서\n가져와 적용"]
    chain(p, 30, 70, [(s, GREEN if i == 4 else BLUE) for i, s in enumerate(steps)])
    save(image, p, "workflow.png")


def pipelines():
    image, p = canvas(900, 400)
    text_at(p, 20, 8, 600, 24, "PENTAX K-3 Mark III — 단계를 차례로 적용", 14, INK, True)
    chain(p, 40, 74, [("화이트밸런스된\n센서 RGB", GREY), ("색 행렬\n채도·모드·센서", BLUE), ("감마 곡선\n밝기·대비\n하이라이트·섀도", BLUE),
                      ("YC 변환\n색상", BLUE), ("채도 억제\n밝기에 따라", BLUE), ("카메라 JPEG", GREEN)])
    text_at(p, 20, 150, 600, 24, "PENTAX Q7 — 표를 미리 만들어 한 번에 찾아 씀", 14, INK, True)
    chain(p, 182, 74, [("화이트밸런스된\n센서 RGB", GREY), ("기본 감마", BLUE), ("9 × 9 × 9 색 표\n색 행렬 + 감마\n사면체 보간", BLUE),
                       ("YC 변환\n색상 · 조색", BLUE), ("하이라이트\n채도 억제", BLUE), ("카메라 JPEG", GREEN)])
    arrow(p, 450, 270, 450, 306)
    box(p, 130, 308, 640, 70, "Studio는 같은 계산을 한 뒤 그 결과를 DNG 프로파일의 세 가지 표로 옮깁니다\n"
                               "ForwardMatrix (센서 행렬) · ProfileToneCurve (톤 곡선) · ProfileLookTable (색 보정표)", AMBER)
    save(image, p, "pipelines.png")


def reverse_engineering():
    image, p = canvas(900, 250)
    chain(p, 24, 78, [("펌웨어 파일\n리코가 배포한\n업데이트 파일", AMBER), ("압축 풀기\n프로그램 복원", BLUE), ("색 표와 루틴 찾기\n이름 · 주소", BLUE),
                      ("CPU 에뮬레이터로\n루틴 실행", BLUE), ("같은 계산을\nPython으로 옮김", BLUE)])
    arrow(p, 800, 102, 800, 146)
    # The second row runs back from right to left.
    for i, label in enumerate(("출력 대조\n모든 설정에서\n값이 같은지", "카메라 JPEG과 비교\nColorChecker 24패치", "DCP · XMP 프로파일")):
        box(p, 690 - i * 216, 148, 190, 78, label, GREEN)
        if i:
            arrow(p, 903 - i * 216, 187, 883 - i * 216, 187)
    text_at(p, 20, 150, 250, 70, "카메라에 손대지 않습니다.\n모든 분석은 PC에서 했고 펌웨어를\n고치거나 설치하지 않았습니다.", 12)
    save(image, p, "reverse-engineering.png")


def lightroom():
    image, p = canvas(900, 300)
    titles = ["① 현상(Develop) 모듈의\n기본(Basic) 패널", "② 프로파일 브라우저", "③ 파일 고르기", "④ 목록에서 선택"]
    for i, title in enumerate(titles):
        x = 20 + i * 220
        p.setPen(QPen(QColor(GREY[1]), 1.5))
        p.setBrush(QColor("#fbfcfd"))
        p.drawRoundedRect(QRectF(x, 20, 200, 260), 8, 8)
        text_at(p, x + 10, 26, 180, 40, title, 12, INK, True)
        if i:
            arrow(p, x - 19, 150, x - 2, 150)
    box(p, 32, 84, 132, 34, "프로파일: Adobe 색상", GREY, 11)
    box(p, 170, 84, 38, 34, "▦", AMBER, 15, True)
    text_at(p, 32, 126, 178, 60, "프로파일 이름 오른쪽의\n네모 네 개 아이콘\n(Profile Browser)을 누릅니다.", 11)
    box(p, 252, 84, 38, 34, "+", AMBER, 16, True)
    box(p, 252, 126, 176, 34, "프로파일 가져오기…", BLUE, 11)
    text_at(p, 252, 168, 178, 80, "브라우저 왼쪽 위의 + 를\n누르고 프로파일 가져오기\n(Import Profiles…)를\n고릅니다.", 11)
    box(p, 472, 84, 176, 30, "natural.dcp", GREEN, 11)
    box(p, 472, 120, 176, 30, "bleach-bypass.zip", GREEN, 11)
    text_at(p, 472, 158, 178, 90, "Studio에서 내보낸 DCP나\nZIP을 고르고 가져오기를\n누릅니다. ZIP은 풀지 않고\n그대로 고릅니다.", 11)
    box(p, 692, 84, 176, 46, "프로파일 ▸\nK-3 III Firmware Natural", BLUE, 10)
    box(p, 692, 136, 176, 46, "Firmware Color Studio ▸\n…Bleach Bypass (Green)", BLUE, 10)
    text_at(p, 692, 190, 178, 80, "그 카메라의 RAW를 열어 둔\n상태에서만 보입니다.\n눌러서 적용하고 닫기를\n누릅니다.", 11)
    save(image, p, "lightroom-import.png")


def validation():
    report = json.loads((ROOT / "docs" / "chart-session-validation.json").read_text(encoding="utf-8"))
    image, p = canvas(900, 400)
    korean = {"pentax-q7": "PENTAX Q7 — 10개 Custom Image", "pentax-k3iii": "PENTAX K-3 Mark III — 13개 Custom Image"}
    for column, camera_id in enumerate(("pentax-q7", "pentax-k3iii")):
        left = 20 + column * 450
        rows = [(profiles._pack(camera_id).labels[row["custom_image"]], row["mean_delta_e76"])
                for row in report["developments"][camera_id].values() if row.get("profile")]
        text_at(p, left, 6, 420, 24, korean[camera_id], 14, INK, True)
        for tick in (1, 2, 3):
            p.setPen(QPen(QColor("#cbd2d9"), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(left + 126 + tick * 62, 36), QPointF(left + 126 + tick * 62, 366))
            text_at(p, left + 116 + tick * 62, 366, 20, 16, str(tick), 10, SOFT, align=Qt.AlignmentFlag.AlignCenter)
        for i, (name, value) in enumerate(rows):
            y = 40 + i * 25
            text_at(p, left, y, 118, 20, name, 11, INK, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BLUE[1] if column == 0 else GREEN[1]))
            p.drawRoundedRect(QRectF(left + 126, y + 3, value * 62, 14), 3, 3)
            text_at(p, left + 132 + value * 62, y, 60, 20, f"{value:.2f}", 11, INK)
    text_at(p, 20, 382, 860, 18, "카메라가 직접 현상한 JPEG과 같은 설정의 프로파일을 ColorChecker 24패치에서 비교한 평균 색차 (ΔE76). 작을수록 같습니다.", 11)
    save(image, p, "validation.png")


def tone_curves():
    image, p = canvas(900, 360)
    left, top, w, h = 70, 20, 520, 290
    p.setPen(QPen(QColor("#cbd2d9"), 1))
    for i in range(5):
        p.drawLine(QPointF(left + i * w / 4, top), QPointF(left + i * w / 4, top + h))
        p.drawLine(QPointF(left, top + i * h / 4), QPointF(left + w, top + i * h / 4))
    text_at(p, left, top + h + 6, w, 20, "장면의 밝기 (어두움 → 밝음)", 12, SOFT, align=Qt.AlignmentFlag.AlignCenter)
    p.save()
    p.translate(24, top + h / 2)
    p.rotate(-90)
    text_at(p, -150, -12, 300, 20, "사진에 기록되는 밝기", 12, SOFT, align=Qt.AlignmentFlag.AlignCenter)
    p.restore()
    modes = [("natural", "#3b82c4"), ("bright", "#e5484d"), ("flat", "#3a9b62"), ("radiant", "#c48a1a"), ("bleach-bypass", "#7c5cc4")]
    for i, (mode, colour) in enumerate(modes):
        name = profiles.LABELS[mode]
        x, y = profiles.camera_for_recipe(profiles.default_recipe(mode)).tone_curve(257)
        points = QPolygonF([QPointF(left + color_model.srgb_encode(a) * w, top + h - color_model.srgb_encode(b) * h) for a, b in zip(x, y)])
        p.setPen(QPen(QColor(colour), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(points)
        p.drawLine(QPointF(620, 44 + i * 30), QPointF(650, 44 + i * 30))
        text_at(p, 658, 34 + i * 30, 240, 20, name, 12, INK)
    text_at(p, 620, 200, 270, 110, "K-3 Mark III 프로파일에 담기는 톤 곡선입니다(출고값). 펌웨어의 표와 "
                                   "밝기·대비 설정에서 계산하며, 조절 항목을 바꾸면 이 곡선이 바뀝니다.", 12)
    save(image, p, "tone-curves.png")


def chart_image(patches):
    """A drawn ColorChecker Classic, 900 x 600, as tests/test_chart_detect.py draws it: the detector finds it."""
    pixels = np.full((600, 900, 3), 120, np.uint8)
    pixels[80:530, 100:770] = 20
    for index, rgb in enumerate(np.rint(patches * 255).astype(np.uint8)):
        x, y = 110 + (index % 6) * 110, 90 + (index // 6) * 110
        pixels[y:y + 100, x:x + 100] = rgb
    return pixels


def chart_qimage(patches=None):
    pixels = chart_image(chart_fit.reference_srgb() if patches is None else patches)
    return QImage(pixels.data, 900, 600, pixels.strides[0], QImage.Format.Format_RGB888).copy()


def colorchecker():
    image, p = canvas(900, 310)
    p.drawImage(QRectF(20, 5, 450, 300), chart_qimage())
    for index in range(24):
        row, col = divmod(index, 6)
        light = index in (1, 5, 6, 10, 11, 15, 18, 19, 20)
        text_at(p, 20 + 55 + col * 55, 5 + 45 + row * 55, 50, 50, str(index + 1), 15, INK if light else "#ffffff", True, Qt.AlignmentFlag.AlignCenter)
    for number, (x, y) in enumerate(((70, 45), (405, 45), (405, 270), (70, 270)), 1):
        badge(p, x, y, number, 12)
    text_at(p, 500, 10, 380, 290,
            "ColorChecker Classic의 24패치\n\n1번은 짙은 피부색, 6번은 청록, 19번은 흰색, 24번은 검정입니다. "
            "아래 줄 여섯 개(19~24)가 회색 단계입니다.\n\n"
            "자동 인식에 실패했을 때는 차트 바깥 테두리의 네 모서리를 누릅니다. 순서는 상관없지만, "
            "색으로 방향을 알 수 없는 사진에서는 ① 짙은 피부색 쪽 → ② 청록 쪽 → ③ 검정 쪽 → ④ 흰색 쪽 순서를 씁니다.", 13, INK,
            align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    save(image, p, "colorchecker.png")


def looks_grid():
    frame = load_raw(DEMO_RAW)
    rgb = resize_rgb(frame.rgb, 600)
    cells = [(profiles.LABELS[mode], app.render_recipe(rgb, profiles.default_recipe(mode), frame.baseline_exposure)[0])
             for mode in ("natural", "bright", "landscape", "muted", "bleach-bypass", "monochrome")]
    cells += [(f"내장 색감 · {name}", profiles.render_dcp(rgb, chart_fit.fit_look(name).dcp, frame.baseline_exposure))
              for name in list(chart_fit.builtin_looks())[:3]]
    height = round(280 * rgb.shape[0] / rgb.shape[1])
    image, p = canvas(900, 3 * (height + 34) + 6)
    for i, (name, rendered) in enumerate(cells):
        row, col = divmod(i, 3)
        x, y = 20 + col * 290, 6 + row * (height + 34)
        p.drawImage(QRectF(x, y, 280, height), rgb_image(rendered))
        text_at(p, x, y + height + 2, 280, 24, name, 12, INK, align=Qt.AlignmentFlag.AlignCenter)
    save(image, p, "looks-grid.png")


# -- screenshots -------------------------------------------------------------------------------------

def settle(application, done, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        application.processEvents()
        time.sleep(0.02)
        if done():
            break
    application.processEvents()
    assert done(), "the window did not settle"


def grab(widget, name, shown_width, marks):
    """Grab a widget, number the given child widgets and store it at twice `shown_width`."""
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    ratio = image.devicePixelRatio()
    image.setDevicePixelRatio(1)                    # paint in the image's own pixels
    p = QPainter(image)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    for number, child, (dx, dy) in marks:
        corner = child.mapTo(widget, QPoint(0, 0))
        badge(p, (corner.x() + dx) * ratio, (corner.y() + dy) * ratio, number, 9 * ratio)
    p.end()
    image = image.scaledToWidth(2 * shown_width, Qt.TransformationMode.SmoothTransformation)
    assert image.save(str(OUT / name)), name
    print(name, image.width(), "x", image.height())


def screenshots(application):
    window = app.MainWindow()
    window.language.setCurrentIndex(0)
    window.camera.setCurrentIndex(window.camera.findData(profiles.CAMERA_ID))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.resize(1200, 800)
    window.show()
    window.load_raw_path(DEMO_RAW)
    settle(application, lambda: window.raw is not None and not window.jobs and not window.preview_pending and window.preview_size == 1000)
    window._set_recipe({**profiles.default_recipe("bright"), "settings": {**profiles.default_recipe("bright")["settings"], "saturation": 1}})
    settle(application, lambda: not window.jobs and not window.preview_pending and window.preview_size == 1000)
    grab(window, "main-window.png", 900, [
        (1, window.menuBar(), (100, 11)), (2, window.camera, (-4, 2)), (3, window.open_button, (-4, 2)), (4, window.chart_button, (-4, 2)),
        (5, window.looks_button, (-4, 2)), (6, window.language, (-4, 2)), (7, window.mode_list, (4, 6)), (8, window.reference, (window.reference.width() + 4, 4)),
        (9, window.before, (14, 14)), (10, window.after, (14, 14)), (11, window.adjust_heading, (104, 16)),
        (12, window.output_format, (-4, 4)), (13, window.export_button, (-4, 6)), (14, window.statusBar(), (410, 10))])

    panel = window.adjust_heading.parentWidget()        # the whole adjustment panel, also what is scrolled away
    grab(panel, "adjust-panel.png", round(panel.width() * .75), [])

    dialog = chart_dialog.ChartDialog(window)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dialog.looks.setCurrentIndex(2)
    dialog.choose_look(2)
    dialog.show()
    dialog.tabs.setCurrentIndex(1)                  # the look on the RAW that is open
    application.processEvents()
    grab(dialog, "looks-dialog.png", 645, [(1, dialog.looks, (-4, 2)), (2, dialog.tabs.tabBar(), (dialog.tabs.tabBar().width() + 12, 12)), (3, dialog.name, (dialog.name.width() - 16, 16)),
                                           (4, dialog.swatches, (6, 6)), (5, dialog.stats, (-2, 10)), (6, dialog.save_button, (-4, 4))])
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "Example camera.jpg"
        # The chart as another camera renders it: the colours of the first built-in look.
        assert chart_qimage(next(iter(chart_fit.builtin_looks().values()))[0]).save(str(path), "JPEG", 95)
        assert dialog.load_path(path) and dialog.result is not None
    dialog.tabs.setCurrentIndex(0)
    application.processEvents()
    after_name = dialog.filename.fontMetrics().horizontalAdvance(dialog.filename.text()) + 14
    grab(dialog, "chart-dialog.png", 645, [(1, dialog.filename, (after_name, 9)), (2, dialog.edition, (dialog.edition.width(), 2)), (3, dialog.view, (16, 16)),
                                          (4, dialog.name, (dialog.name.width() - 16, 16)), (5, dialog.swatches, (6, 6)), (6, dialog.save_button, (-4, 4))])
    dialog.close()
    window.close()


def photographs(source):
    for name in ("pentax-k3iii.jpg", "pentax-q7.jpg"):
        image = QImage(str(Path(source) / name)).scaledToWidth(440, Qt.TransformationMode.SmoothTransformation)
        assert not image.isNull() and image.save(str(OUT / name), "JPEG", 88), name
        print(name, image.width(), "x", image.height())


if __name__ == "__main__":
    application = QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(app.STYLE)
    # The window stores its language and camera; keep this run out of the user's own preferences.
    scratch = tempfile.TemporaryDirectory()
    app.QSettings = lambda *args: QSettings(str(Path(scratch.name) / "preferences.ini"), QSettings.Format.IniFormat)
    OUT.mkdir(parents=True, exist_ok=True)
    for figure in (concept, workflow, pipelines, reverse_engineering, lightroom, validation, tone_curves, colorchecker, looks_grid):
        figure()
    screenshots(application)
    if len(sys.argv) > 1:
        photographs(sys.argv[1])
