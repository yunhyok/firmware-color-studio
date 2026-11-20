"""Select ColorChecker Classic patches from a JPEG and export their estimated look."""
from pathlib import Path
import re

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget, QVBoxLayout,
)

from .app import ImageView, checked_output, write_output
from .chart_detect import MultipleCharts, detect_chart, orient_outer_corners
from .chart_fit import fit_chart, reference_srgb
from .chart_input import load_chart_jpeg, patch_centers, sample_chart
from .display import rgb_image
from .profiles import preview_inputs, render_dcp
from .raw import resize_rgb


# The estimate shown in the window does not depend on the name; Save writes the name then in the field.
_PREVIEW_NAME = "Chart profile"
# Messages of chart_input and chart_fit that a wrong selection or a poor photo can produce.
_KOREAN = {
    "Check chart orientation and exposure: the six gray patches must descend from white to black":
        "회색 여섯 칸이 흰색에서 검정 순으로 어두워지지 않습니다. 차트 방향과 노출을 확인하세요.",
    "Part of a chart patch lies outside the image.": "패치 일부가 사진 밖에 있습니다.",
    "The chart is too small or too oblique to sample reliably.":
        "차트가 너무 작거나 심하게 기울어 색을 읽을 수 없습니다.",
    "The four patch centers must form a convex quadrilateral in chart order.":
        "네 점이 사각형을 이루지 않습니다.",
    "Select the four outer chart corners inside the photo.": "네 모서리는 사진 안에 있어야 합니다.",
    "The selected perspective leaves part of the chart unresolved.":
        "선택한 원근으로는 차트 전체를 읽을 수 없습니다.",
}


def _badge(painter, center, number):
    badge = QRectF(center.x() - 9, center.y() - 9, 18, 18)
    painter.setPen(QPen(QColor("#83eddf"), 1))
    painter.setBrush(QColor(17, 24, 29, 205))
    painter.drawEllipse(badge)
    painter.setPen(Qt.GlobalColor.white)
    painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(number))


def _badge_font(painter):
    font = QFont(painter.font())
    font.setPixelSize(11)
    font.setBold(True)
    painter.setFont(font)


def corner_diagram(ratio=1.0) -> QPixmap:
    """A miniature Classic chart with its outer corners numbered in selection order."""
    pixmap = QPixmap(round(190 * ratio), round(128 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    panel = QRectF(14, 14, 162, 100)
    painter.setPen(QPen(QColor("#83eddf"), 1.5))
    painter.setBrush(QColor("#0c0e11"))
    painter.drawRect(panel)
    painter.setPen(Qt.PenStyle.NoPen)
    for index, (red, green, blue) in enumerate(np.rint(reference_srgb() * 255).astype(int).tolist()):
        painter.setBrush(QColor(red, green, blue))
        painter.drawRect(QRectF(panel.left() + 8.5 + index % 6 * 25, panel.top() + 7.25 + index // 6 * 22.5, 20, 18))
    _badge_font(painter)
    corners = (panel.topLeft(), panel.topRight(), panel.bottomRight(), panel.bottomLeft())
    for number, corner in enumerate(corners, 1):
        _badge(painter, corner, number)
    painter.end()
    return pixmap


class ChartView(QGraphicsView):
    clicked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setMinimumSize(300, 180)
        self.setBackgroundBrush(QColor("#11151a"))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.markers = []
        self.zoom = 1.0

    def set_image(self, image):
        self.scene().clear()
        self.scene().addPixmap(QPixmap.fromImage(image))
        self.setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self.zoom = 1.0
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.zoom == 1.0 and not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        change = event.angleDelta().y()
        if change:
            zoom = min(16.0, max(1.0, self.zoom * 1.3 ** (change / 120)))
            self.scale(zoom / self.zoom, zoom / self.zoom)
            self.zoom = zoom
            if zoom == 1.0:
                self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            p = self.mapToScene(event.position().toPoint())
            bounds = self.sceneRect()
            if not bounds.isEmpty() and bounds.contains(p):
                self.clicked.emit(float(np.clip(p.x() - .5, 0, bounds.width() - 1)),
                                  float(np.clip(p.y() - .5, 0, bounds.height() - 1)))
                event.accept()
                return
        super().mousePressEvent(event)

    def drawForeground(self, painter, rect):
        # Keep patch numbers readable as the preview zooms or changes size.
        transform = painter.worldTransform()
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _badge_font(painter)
        for number, (x, y) in self.markers:
            _badge(painter, transform.map(QPointF(x + .5, y + .5)), number)
        painter.restore()


class ChartDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.lang = parent.lang
        self.camera_id = parent.recipe["camera_id"]
        self.sources = set(parent.source_paths)
        self.display_space = parent.display_space
        self.source = self.image = self.patches = self.result = None
        self.corners = []
        self.outer_corners = []
        self.fallback = False
        self.detection_status = ""
        self.problem = ""
        self.setAcceptDrops(True)
        self.setWindowTitle(parent.tr_text("chart"))
        self.resize(860, 680)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.filename = QLabel()
        self.filename.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(self.filename, 1)
        header.addWidget(QLabel(self.t("차트 제조 시기", "Chart production date")))
        self.edition = QComboBox()
        self.edition.addItem(self.t("2014년 11월 이후", "Nov 2014 and later"), "2014+")
        self.edition.addItem(self.t("2014년 11월 이전", "Before Nov 2014"), "pre2014")
        self.edition.setToolTip(self.t(
            "차트를 만든 시기입니다. 촬영 날짜와 다를 수 있습니다. 모르면 기본값을 두세요.",
            "When the chart was made, which can differ from the shooting date. Keep the default if unsure."))
        self.edition.currentIndexChanged.connect(self.estimate)
        header.addWidget(self.edition)
        reload_button = QPushButton(self.t("다른 JPEG 열기", "Open another JPEG"))
        reload_button.clicked.connect(self.open_jpeg)
        header.addWidget(reload_button)
        layout.addLayout(header)
        guidance = QHBoxLayout()
        self.guide = QLabel()
        self.guide.setWordWrap(True)
        self.guide.setTextFormat(Qt.TextFormat.PlainText)
        guidance.addWidget(self.guide, 1)
        self.corner_diagram = QLabel()
        self.corner_diagram.setPixmap(corner_diagram(self.devicePixelRatioF()))
        self.corner_diagram.setToolTip(self.t(
            "차트 바깥 테두리의 네 모서리입니다. ① 짙은 피부색 쪽, ② 청록색 쪽, ③ 검정 쪽, ④ 흰색 쪽",
            "The four corners of the outer chart border: ① dark skin, ② bluish green, ③ black, ④ white side"))
        guidance.addWidget(self.corner_diagram)
        layout.addLayout(guidance)
        self.tabs = QTabWidget()
        self.view = ChartView()
        self.view.clicked.connect(self.select_corner)
        self.tabs.addTab(self.view, self.t("ColorChecker Classic 24패치", "ColorChecker Classic 24"))
        self.raw_view = ImageView()
        self.tabs.addTab(self.raw_view, self.t("현재 Pentax RAW 미리보기", "Current Pentax RAW preview"))
        self.tabs.currentChanged.connect(self.preview_raw)
        layout.addWidget(self.tabs, 1)
        controls = QHBoxLayout()
        self.undo_button = QPushButton(self.t("한 점 취소", "Undo last point"))
        self.undo_button.clicked.connect(self.undo)
        controls.addWidget(self.undo_button)
        self.reset_button = QPushButton(self.t("바깥 모서리 다시 지정", "Redo outer corners"))
        self.reset_button.clicked.connect(self.reset)
        controls.addWidget(self.reset_button)
        controls.addStretch()
        controls.addWidget(QLabel(parent.tr_text("name")))
        self.name = QLineEdit()
        self.name.setMaxLength(120)
        self.name.setMinimumWidth(180)
        self.name.setPlaceholderText(self.t("Lightroom에 표시할 이름", "Name shown in Lightroom"))
        self.name.textChanged.connect(self._name_changed)
        controls.addWidget(self.name)
        layout.addLayout(controls)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setTextFormat(Qt.TextFormat.PlainText)
        self.swatches = QLabel()
        results = QHBoxLayout()
        results.addWidget(self.swatches)
        results.addWidget(self.stats, 1)
        layout.addLayout(results)
        actions = QHBoxLayout()
        actions.addStretch()
        self.save_button = QPushButton(self.t("DCP 저장…", "Save DCP…"))
        self.save_button.setObjectName("primary")
        self.save_button.setStyleSheet("QPushButton:disabled { background:#29323e; color:#8796a4; }")
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        close_button = QPushButton(self.t("닫기", "Close"))
        close_button.clicked.connect(self.reject)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        # Enter in the name field saves. Without a default, Qt gives it to the first button: Open another JPEG.
        for button in (reload_button, self.undo_button, self.reset_button, close_button):
            button.setAutoDefault(False)
        self.save_button.setDefault(True)
        self.refresh()

    def t(self, ko, en):
        return (ko, en)[self.lang]

    def message(self, error):
        text = str(error)
        return _KOREAN.get(text, text) if self.lang == 0 else text

    @property
    def raw(self):
        """The RAW shown in the main window, which may finish loading after this dialog opened."""
        return self.parent().raw

    def open_jpeg(self):
        path, _ = QFileDialog.getOpenFileName(self, self.windowTitle(), "", "JPEG (*.jpg *.jpeg *.JPG *.JPEG)")
        if path:
            self.load_path(path)

    def load_path(self, path):
        try:
            photo = load_chart_jpeg(path)
        except (OSError, ValueError) as error:
            self.warn(error)
            return False
        self.fallback = False
        self.detection_status = ""
        self.source = Path(path)
        self.image = photo.image
        self.filename.setText(self.source.name)
        self.filename.setToolTip(str(self.source))
        displayed = self.image
        if self.display_space.isValid() and self.image.colorSpace() != self.display_space:
            converted = self.image.convertedToColorSpace(self.display_space)
            if not converted.isNull():
                displayed = converted
        self.view.set_image(displayed)
        self.corners = []
        self.outer_corners = []
        self._clear_fit()
        self.name.setText(photo.name)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            corners = np.asarray(detect_chart(self.image), dtype=float)
            patch_centers(corners)
        except MultipleCharts:
            self.begin_fallback(self.t(
                "차트가 여러 개 보입니다. 사용할 차트의 바깥 테두리 네 모서리를 지정하세요.",
                "Several charts are visible. Select the four outer border corners of the chart to use."))
        except ValueError:
            self.begin_fallback(self.t(
                "차트를 자동 인식하지 못했습니다. 차트 바깥 테두리의 네 모서리를 지정하세요.",
                "Automatic recognition failed. Select the four corners of the outer chart border."))
        else:
            self.corners = corners.tolist()
            self.estimate()
        finally:
            QApplication.restoreOverrideCursor()
        return True

    def select_corner(self, x, y):
        if not self.fallback or self.image is None or len(self.outer_corners) >= 4:
            return
        self.outer_corners.append((x, y))
        if len(self.outer_corners) < 4:
            self.refresh()
            return
        try:
            # Any click order works while the printed colors identify the chart's direction.
            corners = np.asarray(orient_outer_corners(self.image, self.outer_corners), dtype=float)
            patch_centers(corners)
        except ValueError as error:
            self.problem = self.message(error)
            self.refresh()
        else:
            self.corners = corners.tolist()
            self.estimate()

    def undo(self):
        if self.fallback and self.outer_corners:
            self.outer_corners.pop()
            self.corners = []
            self._clear_fit()
            self.refresh()

    def reset(self):
        if self.fallback:
            self.outer_corners = []
            self.corners = []
            self._clear_fit()
            self.refresh()

    def begin_fallback(self, status):
        self.fallback = True
        self.outer_corners = []
        self.corners = []
        self.detection_status = status
        self._clear_fit()
        self.refresh()

    def _clear_fit(self):
        self.patches = self.result = None
        self.problem = ""

    def _name_changed(self):
        # The name only labels the saved file's profile, so the estimate on screen stays.
        self.guide.setText(self._guide())
        self.save_button.setEnabled(self.result is not None and bool(self.name.text().strip()))

    def _guide(self):
        n = len(self.outer_corners)
        if self.result is not None:
            text = self.t("색감 추정을 마쳤습니다. 24개 번호와 아래 패치 차이를 확인한 뒤 DCP를 저장하세요.",
                          "Review the 24 numbered patches and fitted colors below, then save the DCP.")
            if not self.name.text().strip():
                text += "\n" + self.t("프로파일 이름을 입력하면 저장할 수 있습니다.",
                                      "Enter a profile name to enable saving.")
            return text
        if self.fallback and n < 4:
            names = self.t(("짙은 피부색", "청록색", "검정", "흰색"),
                           ("dark skin", "bluish green", "black", "white"))
            return self.detection_status + "\n" + self.t(
                f"{n + 1}/4 · {names[n]} 패치 쪽의 차트 바깥 모서리를 클릭하세요. "
                "순서가 달라도 색 배열로 방향을 맞춥니다.  마우스 휠로 확대",
                f"{n + 1}/4 · Click the outer chart corner on the {names[n]} side. "
                "A different order is corrected from the printed colors.  Scroll to zoom")
        if self.fallback:
            return self.t(
                "바깥 모서리를 확인하세요. '한 점 취소' 또는 '바깥 모서리 다시 지정'으로 수정할 수 있습니다. "
                "색 배열로 방향을 알 수 없는 사진은 그림의 ①→④ 순서로 지정하세요.",
                "Check the outer corners. Use Undo last point or Redo outer corners to correct them. "
                "When the colors cannot show the direction, select them in the pictured ①→④ order.")
        if self.problem:
            return self.t("자동 색감 추정에 실패했습니다. 아래 오류를 확인하세요.",
                          "Automatic estimation failed. Review the error below.")
        return ""

    def refresh(self):
        """Show the current selection, estimate and what the user can do next."""
        n = len(self.outer_corners)
        done = self.result is not None
        self.undo_button.setVisible(self.fallback)
        self.reset_button.setVisible(self.fallback)
        self.undo_button.setEnabled(bool(n))
        self.reset_button.setEnabled(bool(n))
        self.corner_diagram.setVisible(self.fallback and not done)
        selecting = self.fallback and n < 4
        self.view.setCursor(Qt.CursorShape.CrossCursor if selecting else Qt.CursorShape.ArrowCursor)
        if len(self.corners) == 4:
            self.view.markers = list(enumerate(patch_centers(self.corners), 1))
        else:
            self.view.markers = list(enumerate(self.outer_corners, 1)) if self.fallback else []
        self.view.viewport().update()
        self.guide.setText(self._guide())
        if done:
            # Two swatches per patch, in the chart's row order.
            paired = np.stack([self.patches, self.result.predicted_srgb], axis=1).reshape(4, 12, 3)
            swatches = np.repeat(np.repeat(paired, 24, axis=0), 20, axis=1)
            swatches[::24] = swatches[:, ::40] = .13
            self.swatches.setPixmap(QPixmap.fromImage(rgb_image(swatches, self.display_space)))
            before, after = self.result.baseline_mean_delta_e, self.result.mean_delta_e
            self.stats.setText(self.t(
                "각 칸의 왼쪽은 JPEG, 오른쪽은 이 DCP의 예측입니다.\n", "Each cell shows the JPEG on the left "
                "and this DCP's prediction on the right.\n") + (self.t(
                    f"24패치 평균 색차 ΔE76 · 보정 전 {before:.1f} → 보정 후 {after:.1f}",
                    f"Mean ΔE76 over 24 patches · {before:.1f} before → {after:.1f} after fitting")
                if self.result.fitted else self.t(
                    f"24패치 평균 색차 ΔE76 · {before:.1f} (색 보정표가 오차를 줄이지 못해 보정 없는 기준 프로파일을 저장합니다)",
                    f"Mean ΔE76 over 24 patches · {before:.1f} (a fitted look did not reduce it, "
                    "so the uncorrected profile is saved)")))
        else:
            self.swatches.clear()
            self.stats.setText(self.t("색감 추정 실패 · ", "Estimation failed · ") + self.problem if self.problem else "")
        previewable = done and self.raw is not None
        if not previewable:
            self.tabs.setCurrentIndex(0)
        self.tabs.setTabEnabled(1, previewable)
        if previewable and self.tabs.currentIndex() == 1:
            self.preview_raw(1)
        self.save_button.setEnabled(done and bool(self.name.text().strip()))

    def warn(self, error):
        QMessageBox.warning(self, self.parent().tr_text("error"), str(error))

    def estimate(self, *_):
        self._clear_fit()
        if self.image is not None and len(self.corners) == 4:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                patches = sample_chart(self.image, self.corners)
                self.result = fit_chart(patches, _PREVIEW_NAME, camera_id=self.camera_id, edition=self.edition.currentData())
                self.patches = patches
            except (ValueError, OSError) as error:
                self.problem = self.message(error)
            finally:
                QApplication.restoreOverrideCursor()
        self.refresh()
        return self.result is not None

    def preview_raw(self, index):
        if index == 1 and self.raw is not None and self.result is not None:
            try:
                rgb, baseline = preview_inputs(resize_rgb(self.raw.rgb, 720), self.raw.baseline_exposure, self.camera_id)
                fitted = render_dcp(rgb, self.result.dcp, baseline)
                self.raw_view.set_image(rgb_image(fitted, self.display_space))
            except (ValueError, OSError) as error:
                self.tabs.setCurrentIndex(0)
                self.warn(error)

    def save(self):
        name = self.name.text().strip()
        if self.result is None or not name:
            return
        try:
            named = fit_chart(self.patches, name, camera_id=self.camera_id, edition=self.edition.currentData())
        except ValueError as error:
            self.warn(self.message(error))
            return
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "Chart"
        # A prefix also keeps camera names such as CON from becoming Windows device paths.
        suggested = self.source.with_name(f"Pentax - {stem}.dcp")
        path, _ = QFileDialog.getSaveFileName(self, self.save_button.text(), str(suggested), "DNG camera profile (*.dcp)")
        if path:
            try:
                checked = checked_output(path, ".dcp", self.sources | {self.source})
                write_output(checked, named.dcp)
            except (OSError, ValueError) as error:
                self.warn(error)
                return
            self.result = named
            self.parent().statusBar().showMessage(f"{self.parent().tr_text('saved')} · {checked}")
            self.accept()

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in (".jpg", ".jpeg")
               for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in (".jpg", ".jpeg"):
                path = url.toLocalFile()
                # Return to the dragging application before reading the file.
                QTimer.singleShot(0, lambda: self.load_path(path))
                event.acceptProposedAction()
                break
