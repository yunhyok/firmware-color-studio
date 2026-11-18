"""Select ColorChecker Classic patches from a JPEG and export their estimated look."""
from pathlib import Path
import re

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget, QVBoxLayout,
)

from .app import ImageView, checked_output, write_output
from .chart_fit import fit_chart
from .chart_input import load_chart_jpeg, patch_centers, sample_chart
from .display import rgb_image
from .profiles import render_dcp
from .raw import resize_rgb


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
        font = QFont(painter.font())
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        for number, (x, y) in self.markers:
            p = transform.map(QPointF(x + .5, y + .5))
            badge = QRectF(p.x() - 9, p.y() - 9, 18, 18)
            painter.setPen(QPen(QColor("#83eddf"), 1))
            painter.setBrush(QColor(17, 24, 29, 205))
            painter.drawEllipse(badge)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(number))
        painter.restore()


class ChartDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.lang = parent.lang
        self.raw = parent.raw
        self.sources = set(parent.source_paths)
        self.display_space = parent.display_space
        self.source = self.image = self.result = None
        self.corners = []
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
        self.edition.currentIndexChanged.connect(self.changed)
        header.addWidget(self.edition)
        reload_button = QPushButton(self.t("다른 JPEG 열기", "Open another JPEG"))
        reload_button.clicked.connect(self.open_jpeg)
        header.addWidget(reload_button)
        layout.addLayout(header)
        self.guide = QLabel()
        self.guide.setWordWrap(True)
        self.guide.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.guide)
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
        self.reset_button = QPushButton(self.t("다시 지정", "Reset points"))
        self.reset_button.clicked.connect(self.reset)
        controls.addWidget(self.reset_button)
        controls.addStretch()
        controls.addWidget(QLabel(parent.tr_text("name")))
        self.name = QLineEdit()
        self.name.setMaxLength(120)
        self.name.setMinimumWidth(180)
        self.name.textChanged.connect(self.changed)
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
        self.fit_button = QPushButton(self.t("색감 추정", "Estimate look"))
        self.fit_button.clicked.connect(self.estimate)
        actions.addWidget(self.fit_button)
        self.save_button = QPushButton(self.t("DCP 저장…", "Save DCP…"))
        self.save_button.setObjectName("primary")
        self.save_button.setStyleSheet("QPushButton:disabled { background:#29323e; color:#8796a4; }")
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        close_button = QPushButton(self.t("닫기", "Close"))
        close_button.clicked.connect(self.reject)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self.changed()

    def t(self, ko, en):
        return (ko, en)[self.lang]

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
        self.corners.clear()
        self.name.setText(photo.name)
        self.changed()
        return True

    def select_corner(self, x, y):
        if self.image is not None and len(self.corners) < 4:
            self.corners.append((x, y))
            self.changed()

    def undo(self):
        if self.corners:
            self.corners.pop()
            self.changed()

    def reset(self):
        self.corners.clear()
        self.changed()

    def changed(self):
        self.result = None
        self.stats.clear()
        self.swatches.clear()
        self.tabs.setCurrentIndex(0)
        self.tabs.setTabEnabled(1, False)
        self.save_button.setEnabled(False)
        n = len(self.corners)
        numbers = (1, 6, 24, 19)
        self.view.markers = list(zip(numbers, self.corners))
        self.undo_button.setEnabled(bool(n))
        self.reset_button.setEnabled(bool(n))
        valid = n == 4
        if valid:
            try:
                self.view.markers = list(enumerate(patch_centers(self.corners), 1))
                self.guide.setText(self.t("번호가 24개 패치의 가운데에 있는지 확인한 뒤 색감 추정을 누르세요.",
                                          "Check that each number falls on its patch center, then select Estimate look."))
            except ValueError as error:
                valid = False
                self.guide.setText(self.t("모서리를 다시 지정하세요. ", "Reselect the corners. ") + str(error))
        else:
            names = self.t(("짙은 피부색", "청록색", "검정", "흰색"),
                           ("dark skin", "bluish green", "black", "white"))
            self.guide.setText(self.t(
                f"{n + 1}/4 · {numbers[n]}번 {names[n]} 패치의 가운데를 클릭하세요.  "
                "지정 순서  1 → 6 → 24 → 19  ·  마우스 휠로 확대",
                f"{n + 1}/4 · Click the center of patch {numbers[n]} ({names[n]}).  "
                "Corner order  1 → 6 → 24 → 19  ·  Scroll to zoom"))
        self.view.viewport().update()
        self.fit_button.setEnabled(valid and bool(self.name.text().strip()))

    def warn(self, error):
        QMessageBox.warning(self, self.parent().tr_text("error"), str(error))

    def estimate(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            patches = sample_chart(self.image, self.corners)
            result = fit_chart(patches, self.name.text().strip(), edition=self.edition.currentData())
        except (ValueError, OSError) as error:
            self.stats.setText(self.t("색감 추정 실패 · ", "Estimation failed · ") + str(error))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.result = result
        # Two swatches per patch, in the chart's row order.
        paired = np.stack([patches, result.predicted_srgb], axis=1).reshape(4, 12, 3)
        swatches = np.repeat(np.repeat(paired, 16, axis=0), 15, axis=1)
        swatches[::16] = swatches[:, ::30] = .13
        self.swatches.setPixmap(QPixmap.fromImage(rgb_image(swatches, self.display_space)))
        self.stats.setText(self.t(
            "각 패치의 왼쪽은 JPEG, 오른쪽은 추정 결과입니다.\n"
            f"24패치 평균 ΔE76  {result.baseline_mean_delta_e:.1f} → {result.mean_delta_e:.1f}",
            "Each patch shows the JPEG on the left and the estimate on the right.\n"
            f"Mean ΔE76 across 24 patches  {result.baseline_mean_delta_e:.1f} → {result.mean_delta_e:.1f}"))
        self.tabs.setTabEnabled(1, self.raw is not None)
        self.fit_button.setEnabled(False)
        self.save_button.setEnabled(True)
        self.guide.setText(self.t("색감 추정을 마쳤습니다. 아래에서 패치 차이를 확인한 뒤 DCP를 저장하세요.",
                                  "Review the fitted patch colors below, then save the DCP."))

    def preview_raw(self, index):
        if index == 1 and self.raw is not None and self.result is not None:
            try:
                rgb = resize_rgb(self.raw.rgb, 720)
                fitted = render_dcp(rgb, self.result.dcp, self.raw.baseline_exposure)
                self.raw_view.set_image(rgb_image(fitted, self.display_space))
            except (ValueError, OSError) as error:
                self.tabs.setCurrentIndex(0)
                self.warn(error)

    def save(self):
        if self.result is None:
            return
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.name.text()).strip(" .") or "Chart"
        # A prefix also keeps camera names such as CON from becoming Windows device paths.
        suggested = self.source.with_name(f"Pentax - {stem}.dcp")
        path, _ = QFileDialog.getSaveFileName(self, self.save_button.text(), str(suggested), "DNG camera profile (*.dcp)")
        if path:
            try:
                checked = checked_output(path, ".dcp", self.sources | {self.source})
                write_output(checked, self.result.dcp)
            except (OSError, ValueError) as error:
                self.warn(error)
                return
            self.parent().statusBar().showMessage(f"{self.parent().tr_text('saved')} · {checked}")
            self.accept()
