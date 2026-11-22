"""A small offline workspace for firmware-derived camera looks."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, QSize, QSettings
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from . import __version__
from .cli import DEMO_RAW
from .display import monitor_space, rgb_image
from .profiles import (CAMERA_ID, build_profile, camera_info, default_recipe, list_cameras, list_modes, load_recipe,
                       preview_inputs, render_dcp, save_recipe, validate_recipe)
from .raw import load_raw, read_calibration, resize_rgb


TEXT = {
    "open": ("RAW 열기", "Open RAW"), "empty": ("PEF·DNG 또는 차트 JPEG를 끌어 놓으세요", "Drop a PEF, DNG or chart JPEG here"),
    "no_recorded": ("이 RAW에는 지원하는 Custom Image 설정이 없습니다", "No supported Custom Image settings in this RAW."),
    "chart": ("차트 JPEG → DCP", "Chart JPEG → DCP"), "file": ("파일", "File"), "demo": ("데모 사진", "Demo photo"),
    "help": ("도움말", "Help"), "guide": ("사용 설명서", "User guide"),
    "looks": ("다른 카메라 색감", "Other cameras' looks"),
    "looks_tip": ("Kodak, Sony, Konica Minolta, Samsung 카메라의 내장 색감으로 선택한 카메라용 DCP를 만듭니다",
                  "Make a DCP for the selected camera from the built-in looks of Kodak, Sony, Konica Minolta and Samsung cameras"),
    "chart_tip": ("다른 카메라로 찍은 ColorChecker Classic JPEG의 색감을 선택한 카메라용 DCP로 만듭니다",
                  "Estimate a DCP for the selected camera from another camera's ColorChecker Classic JPEG"),
    "camera_tip": ("프로파일을 만들 카메라", "Camera the profiles are made for"),
    "cross_note": ("이 미리보기는 다른 카메라의 RAW를 두 카메라의 센서 행렬로 환산한 근사입니다",
                   "This preview converts another camera's RAW through both sensor matrices; it is approximate"),
    "profiles": ("카메라 프로파일", "Camera profiles"), "adjust": ("프로파일 조정", "Profile controls"),
    "baseline": ("비교 기준", "Reference"), "current": ("현재 프로파일", "Current profile"),
    "factory": ("출고값으로 복원", "Reset to factory"), "recorded": ("촬영 설정 가져오기", "Use shot settings"),
    "name": ("프로파일 이름", "Profile name"), "name_hint": ("비워 두면 설정에 따라 생성", "Automatic name when empty"),
    "export": ("프로파일 내보내기", "Export profile"), "save": ("레시피 저장", "Save recipe"),
    "load": ("레시피 열기", "Open recipe"), "calibration": ("내 DNG 보정 행렬 가져오기", "Import body calibration from DNG"),
    "clear_calibration": ("공개 보정 행렬 사용", "Use reference calibration"),
    "color_space": ("카메라 색공간", "Camera color space"), "format": ("출력 형식", "Export format"),
    "toning": ("조색", "Toning"), "info": ("상세 정보", "Details"), "error": ("처리할 수 없습니다", "Cannot process request"),
    "ready": ("RAW 없이도 프로파일을 만들 수 있습니다", "Profiles can be exported without a RAW file"),
    "loading": ("RAW를 읽는 중…", "Reading RAW…"), "rendering": ("프로파일을 계산하는 중…", "Rendering profiles…"),
    "saved": ("저장했습니다", "Saved"), "reference_calibration": ("공개 연구의 기준 기기 보정", "Reference-body calibration"),
    "body_calibration": ("사용자 DNG의 기기 보정", "Body calibration from your DNG"),
    "limits": ("색 비교용 ½ 해상도 · 샤프니스/노이즈 감소 제외", "½-resolution color preview · no sharpening or denoise"),
    "dcp_note": ("DCP 미리보기 · 카메라 JPEG와 동일한 현상을 보장하지 않습니다", "DCP reference preview · not a camera JPEG rendering"),
    "xmp_note": ("DCP + XMP · 고채도/클리핑 경계에서 LUT 근사 오차 가능", "DCP + XMP · LUT approximation can diverge at saturated/clipped colors"),
    "tone_note": ("DCP는 조색을 담을 수 없습니다. XMP 묶음을 선택하세요.", "DCP cannot encode this tint. Select the XMP bundle."),
    "overwrite": ("같은 이름의 파일을 바꾸시겠습니까?", "Replace the existing file?"),
}
CONTROL_LABELS = {
    "saturation": ("채도", "Saturation"), "hue": ("색상", "Hue"), "key": ("밝기 (Key)", "Key brightness"),
    "contrast": ("대비", "Contrast"), "highlight": ("하이라이트 대비", "Highlight contrast"), "shadow": ("섀도 대비", "Shadow contrast"),
}
TONES = [("끔", "Off"), ("그린", "Green"), ("옐로", "Yellow"), ("오렌지", "Orange"), ("레드", "Red"),
         ("마젠타", "Magenta"), ("퍼플", "Purple"), ("블루", "Blue"), ("시안", "Cyan")]
STYLE = """
QMainWindow, QWidget { background:#171b21; color:#e4e9ef; font-family:'Segoe UI','Malgun Gothic'; font-size:12px; }
QLabel#brand { font-size:23px; font-weight:650; color:#f6f8fc; }
QLabel#muted { color:#9aa9bb; }
QLabel#section { font-weight:650; color:#c4ceda; padding:8px 0; }
QLabel#image { background:#11151a; border:1px solid #303946; border-radius:8px; color:#93a3b7; }
QFrame#panel { background:#1d232b; border:1px solid #303946; border-radius:8px; }
QPushButton { background:#29323e; border:1px solid #405065; border-radius:5px; padding:8px 12px; }
QPushButton:hover { background:#344154; } QPushButton:disabled { color:#657182; }
QPushButton#primary { background:#5ed5c5; color:#0c2725; font-weight:650; border:0; }
QLineEdit,QComboBox,QSpinBox { padding:7px; background:#11171e; border:1px solid #3b485a; border-radius:4px; }
QComboBox QAbstractItemView { background:#202b37; selection-background-color:#3b6971; }
QListWidget { border:0; background:#171b21; outline:0; }
QListWidget::item { border:1px solid #303946; border-radius:5px; background:#202730; padding:5px; margin:3px; }
QListWidget::item:selected { border:2px solid #5ed5c5; background:#263e43; color:#f3f8fc; }
QSlider::groove:horizontal { height:4px; background:#3a4655; border-radius:2px; }
QSlider::handle:horizontal { background:#6bd8ca; width:13px; margin:-5px 0; border-radius:6px; }
QSlider:disabled::handle:horizontal { background:#596270; }
QSplitter::handle { background:#171b21; width:8px; }
QProgressBar { border:0; background:#26313d; height:3px; } QProgressBar::chunk { background:#5ed5c5; }
QMenuBar,QMenu { background:#1d232b; } QMenu::item:selected { background:#355065; }
QToolTip { color:#eef4fa; background:#27323e; border:1px solid #677a90; }
"""


class JobSignals(QObject):
    done = Signal(str, int, object, object)


class Job(QRunnable):
    def __init__(self, kind, serial, function):
        super().__init__()
        self.kind, self.serial, self.function = kind, serial, function
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.done.emit(self.kind, self.serial, self.function(), None)
        except Exception as error:
            self.signals.done.emit(self.kind, self.serial, None, (str(error), traceback.format_exc()))


class ImageView(QLabel):
    def __init__(self):
        super().__init__()
        self.setObjectName("image")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(180, 180)
        self._pixmap = None

    def set_image(self, image):
        self._pixmap = QPixmap.fromImage(image)
        self._fit()

    def _fit(self):
        if self._pixmap is not None:
            # Fit in device pixels; a pixmap sized in logical pixels is enlarged again on a scaled display.
            ratio = self.devicePixelRatioF()
            pixmap = self._pixmap.scaled((self.size() - QSize(12, 12)) * ratio, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            self.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


def write_output(path: Path, data: bytes):
    # Replace only after the caller's save dialog confirms an existing filename.
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def checked_output(path, suffix, sources=()):
    path = Path(path)
    if path.suffix.lower() != suffix:
        raise ValueError(f"Save this output with the {suffix} extension.")
    if path.resolve().suffix.lower() in (".dng", ".pef"):
        raise ValueError("A RAW file cannot be an output destination.")
    for source in sources:
        source = Path(source)
        if path.resolve() == source.resolve() or (path.exists() and source.exists() and path.samefile(source)):
            raise ValueError("An input file cannot be an output destination.")
    return path


def render_recipe(rgb, recipe, baseline, enhanced=False, source_id=CAMERA_ID):
    rgb, baseline = preview_inputs(rgb, baseline, recipe["camera_id"], source_id)
    if enhanced or recipe["mode"] == "gold" or recipe.get("toning"):
        from .enhanced import build_enhanced, render_enhanced
        bundle = build_enhanced(recipe)
        return render_enhanced(rgb, bundle, baseline), bundle.report
    data, report = build_profile(recipe)
    return render_dcp(rgb, data, baseline), report


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.preferences = QSettings("Yunhyok", "FirmwareColorStudio")
        self.lang = int(self.preferences.value("language", 0))
        camera_id = self.preferences.value("camera", CAMERA_ID)
        self.recipe = default_recipe("natural", camera_id if camera_id in list_cameras() else CAMERA_ID)
        self.raw = None
        self.source_paths = set()
        self.preview_cache = {}
        self.preview_size = 480
        self.export_running = False
        self.format_forced = False
        self.last_report = {}
        self.last_error = ""
        self.generation = {"raw": 0, "preview": 0, "thumbs": 0, "export": 0}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.jobs = {}
        self.preview_running = False
        self.preview_pending = False
        self.thumb_pending = False
        self.closing = False
        self.setAcceptDrops(True)
        self.setWindowTitle(f"Firmware Color Studio {__version__}")
        self.resize(1480, 940)
        self.setMinimumSize(1120, 720)
        icon = Path(__file__).parent / "resources" / "app.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.display_space, self.display_description = monitor_space()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._render)
        self.refine_timer = QTimer(self)
        self.refine_timer.setSingleShot(True)
        self.refine_timer.timeout.connect(self._refine_preview)
        self._setup()
        self._translate()
        self._sync_controls()
        self.statusBar().showMessage(self.tr_text("ready"))

    def tr_text(self, key):
        return TEXT[key][self.lang]

    def _setup(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 12)
        top = QHBoxLayout()
        self.brand = QLabel("Firmware Color Studio")
        self.brand.setObjectName("brand")
        top.addWidget(self.brand)
        top.addStretch()
        self.camera = QComboBox()
        for camera_id, model in list_cameras().items():
            self.camera.addItem(model, camera_id)
        self.camera.currentIndexChanged.connect(self._camera_changed)
        top.addWidget(self.camera)
        self.open_button = QPushButton()
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_raw)
        top.addWidget(self.open_button)
        self.chart_button = QPushButton()
        self.chart_button.clicked.connect(self.open_chart)
        top.addWidget(self.chart_button)
        self.looks_button = QPushButton()
        self.looks_button.clicked.connect(self.open_looks)
        top.addWidget(self.looks_button)
        self.language = QComboBox()
        self.language.addItems(["한국어", "English"])
        self.language.setCurrentIndex(self.lang)
        self.language.currentIndexChanged.connect(self._language_changed)
        top.addWidget(self.language)
        layout.addLayout(top)
        self.file_label = QLabel(self._camera_text())
        self.file_label.setObjectName("muted")
        self.file_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.file_label)
        splitter = QSplitter()
        left = QWidget()
        left.setMinimumWidth(294)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self.profile_heading = QLabel()
        self.profile_heading.setObjectName("section")
        left_layout.addWidget(self.profile_heading)
        self.mode_list = QListWidget()
        self.mode_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.mode_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.mode_list.setMovement(QListWidget.Movement.Static)
        self.mode_list.setIconSize(QSize(104, 72))
        self.mode_list.setGridSize(QSize(132, 136))
        self.mode_list.setWordWrap(True)
        self.mode_list.setUniformItemSizes(True)
        self.mode_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.mode_list.currentItemChanged.connect(self._mode_changed)
        left_layout.addWidget(self.mode_list)
        splitter.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        self.reference_label = QLabel()
        heading.addWidget(self.reference_label)
        self.reference = QComboBox()
        self.reference.currentIndexChanged.connect(self._request_preview)
        self._fill_modes()
        heading.addWidget(self.reference)
        heading.addStretch()
        self.current_label = QLabel()
        heading.addWidget(self.current_label)
        center_layout.addLayout(heading)
        image_row = QHBoxLayout()
        self.before, self.after = ImageView(), ImageView()
        image_row.addWidget(self.before)
        image_row.addWidget(self.after)
        center_layout.addLayout(image_row, 1)
        self.rendition = QLabel()
        self.rendition.setObjectName("muted")
        self.rendition.setWordWrap(True)
        center_layout.addWidget(self.rendition)
        self.limit_label = QLabel()
        self.limit_label.setObjectName("muted")
        center_layout.addWidget(self.limit_label)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setTextFormat(Qt.TextFormat.PlainText)
        self.warning_label.setStyleSheet("color:#edc27e; padding:4px 0;")
        center_layout.addWidget(self.warning_label)
        splitter.addWidget(center)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(5)
        right_layout.setContentsMargins(12, 0, 0, 0)
        self.adjust_heading = QLabel()
        self.adjust_heading.setObjectName("section")
        right_layout.addWidget(self.adjust_heading)
        self.form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._settings_changed)
        self.name_label = QLabel()
        self.form.addRow(self.name_label, self.name_edit)
        self.space = QComboBox()
        self.space.addItems(["sRGB", "Adobe RGB"])
        self.space.currentIndexChanged.connect(self._settings_changed)
        self.space_label = QLabel()
        self.form.addRow(self.space_label, self.space)
        right_layout.addLayout(self.form)
        self.controls = {}
        self.control_labels = {}
        for name in CONTROL_LABELS:
            label = QLabel()
            right_layout.addWidget(label)
            row = QHBoxLayout()
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-4, 4)
            slider.setTickInterval(1)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            spin = QSpinBox()
            spin.setRange(-4, 4)
            spin.setFixedWidth(62)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(self._settings_changed)
            row.addWidget(slider, 1)
            row.addWidget(spin)
            right_layout.addLayout(row)
            self.controls[name] = (slider, spin)
            self.control_labels[name] = label
        self.tone_label = QLabel()
        right_layout.addWidget(self.tone_label)
        self.tone = QComboBox()
        self.tone.currentIndexChanged.connect(self._settings_changed)
        right_layout.addWidget(self.tone)
        self.factory_button = QPushButton()
        self.factory_button.clicked.connect(self._reset)
        right_layout.addWidget(self.factory_button)
        self.recorded_button = QPushButton()
        self.recorded_button.setEnabled(False)
        self.recorded_button.clicked.connect(self._use_recorded)
        right_layout.addWidget(self.recorded_button)
        self.calibration_label = QLabel()
        self.calibration_label.setObjectName("muted")
        self.calibration_label.setWordWrap(True)
        right_layout.addWidget(self.calibration_label)
        right_layout.addStretch()
        scroll.setWidget(right)
        controls_panel = QWidget()
        controls_panel.setMinimumWidth(300)
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(scroll, 1)
        self.format_label = QLabel()
        controls_layout.addWidget(self.format_label)
        self.output_format = QComboBox()
        self.output_format.addItem("DCP", "dcp")
        try:
            from .enhanced import build_enhanced  # noqa: F401
            self.output_format.addItem("DCP + XMP (ZIP)", "xmp")
        except ImportError:
            pass
        self.output_format.currentIndexChanged.connect(self._request_preview)
        controls_layout.addWidget(self.output_format)
        self.export_button = QPushButton()
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.export_profile)
        controls_layout.addWidget(self.export_button)
        self.save_button = QPushButton()
        self.save_button.clicked.connect(self.save_current_recipe)
        controls_layout.addWidget(self.save_button)
        splitter.addWidget(controls_panel)
        splitter.setSizes([300, 810, 320])
        layout.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.setCentralWidget(root)
        self.actions = {}
        self.file_menu, self.help_menu = self.menuBar().addMenu(""), self.menuBar().addMenu("")
        self.guide = None
        for key, shortcut, callback in [
            ("open", "Ctrl+O", self.open_raw), ("load", "Ctrl+Shift+O", self.open_saved_recipe),
            ("chart", "", self.open_chart), ("looks", "", self.open_looks),
            ("save", "Ctrl+S", self.save_current_recipe), ("export", "Ctrl+E", self.export_profile),
            ("calibration", "", self.import_calibration), ("clear_calibration", "", self.clear_calibration),
            ("guide", "F1", self.open_guide), ("info", "", self.show_details),
        ]:
            action = QAction(self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            (self.help_menu if key in ("guide", "info") else self.file_menu).addAction(action)
            self.actions[key] = action

    def _camera_text(self):
        info = camera_info(self.recipe["camera_id"])
        return f'{info["model"]} · Firmware {info["firmware_version"]}'

    def _fill_modes(self):
        """Custom Images of the recipe's camera in the profile list and the reference menu."""
        widgets = (self.mode_list, self.reference, self.camera)
        for widget in widgets:
            widget.blockSignals(True)
        self.camera.setCurrentIndex(self.camera.findData(self.recipe["camera_id"]))
        self.mode_list.clear()
        self.reference.clear()
        for mode, info in list_modes(self.recipe["camera_id"]).items():
            item = QListWidgetItem(info["label"].replace(" (", "\n("))
            item.setToolTip(info["label"])
            item.setSizeHint(QSize(126, 130))
            item.setData(Qt.ItemDataRole.UserRole, mode)
            self.mode_list.addItem(item)
            self.reference.addItem(info["label"], mode)
            if mode == self.recipe["mode"]:
                self.mode_list.setCurrentItem(item)
        for widget in widgets:
            widget.blockSignals(False)

    def _camera_changed(self, *_):
        camera_id = self.camera.currentData()
        if camera_id == self.recipe["camera_id"]:
            return
        self.preferences.setValue("camera", camera_id)
        # A body calibration belongs to the camera it was read from.
        self._set_recipe(default_recipe("natural", camera_id))

    def _translate(self):
        for widget, key in [(self.open_button,"open"),(self.chart_button,"chart"),(self.looks_button,"looks"),(self.profile_heading,"profiles"),(self.adjust_heading,"adjust"),
                            (self.reference_label,"baseline"),(self.name_label,"name"),(self.space_label,"color_space"),
                            (self.tone_label,"toning"),(self.factory_button,"factory"),(self.recorded_button,"recorded"),
                            (self.export_button,"export"),(self.save_button,"save"),(self.format_label,"format"),
                            (self.limit_label,"limits")]:
            widget.setText(self.tr_text(key))
        self.file_menu.setTitle(self.tr_text("file"))
        self.help_menu.setTitle(self.tr_text("help"))
        self.chart_button.setToolTip(self.tr_text("chart_tip"))
        self.looks_button.setToolTip(self.tr_text("looks_tip"))
        self.camera.setToolTip(self.tr_text("camera_tip"))
        self._update_file_label()
        self.name_edit.setPlaceholderText(self.tr_text("name_hint"))
        for name, label in self.control_labels.items():
            label.setText(CONTROL_LABELS[name][self.lang])
        self.tone.blockSignals(True)
        selected = self.tone.currentIndex()
        self.tone.clear()
        self.tone.addItems([pair[self.lang] for pair in TONES])
        self.tone.setCurrentIndex(max(0, selected))
        self.tone.blockSignals(False)
        for key, action in self.actions.items():
            action.setText(self.tr_text(key))
        if self.raw is None:
            self.before.setText(self.tr_text("empty"))
            self.after.setText(self.tr_text("empty"))
        self._update_calibration_label()
        self._sync_format()
        self._update_rendition()

    def _update_rendition(self):
        text = self.tr_text("dcp_note" if self.output_format.currentData() == "dcp" else "xmp_note")
        if self.raw is not None and self.recipe["camera_id"] != self.raw.metadata["camera_id"]:
            text += "\n" + self.tr_text("cross_note")
        self.rendition.setText(text)

    def _update_file_label(self):
        if self.raw is None:
            self.file_label.setText(self._camera_text())
            return
        info = self.raw.metadata
        name = Path(info["path"]).name
        if Path(info["path"]) == DEMO_RAW:
            # The app opened this bundled photograph itself.
            name = f'{self.tr_text("demo")} · {name}'
        text = f"{name}  ·  {info['model']}  ·  {info['width']} × {info['height']}"
        if self.recipe["camera_id"] != info["camera_id"]:
            text += f"  →  {self._camera_text()}"
        self.file_label.setText(text)

    def _language_changed(self, value):
        self.lang = value
        self.preferences.setValue("language", value)
        self._translate()

    def _sync_controls(self):
        modes = list_modes(self.recipe["camera_id"])
        mode = modes[self.recipe["mode"]]
        for name, pair in self.controls.items():         # a control no Custom Image of this camera has is left out
            offered = any(info["controls"][name] for info in modes.values())
            for widget in (self.control_labels[name], *pair):
                widget.setVisible(offered)
        widgets = [self.name_edit, self.space, self.tone]
        widgets += [w for pair in self.controls.values() for w in pair]
        for widget in widgets:
            widget.blockSignals(True)
        self.name_edit.setText(self.recipe.get("name", ""))
        self.space.setCurrentIndex(int(self.recipe["color_space"] == "adobergb"))
        for name, (slider, spin) in self.controls.items():
            slider.setValue(self.recipe["settings"][name])
            spin.setValue(self.recipe["settings"][name])
            slider.setEnabled(mode["controls"][name])
            spin.setEnabled(mode["controls"][name])
        self.tone.setEnabled(mode["toning"])
        self.tone.setCurrentIndex(self.recipe.get("toning", 0))
        for widget in widgets:
            widget.blockSignals(False)
        self._update_calibration_label()

    def _update_calibration_label(self):
        self.calibration_label.setText(self.tr_text("body_calibration" if self.recipe.get("calibration") else "reference_calibration"))

    def _sync_format(self):
        requires_xmp = self.recipe["mode"] == "gold" or bool(self.recipe.get("toning"))
        self.output_format.model().item(0).setEnabled(not requires_xmp)
        if requires_xmp and self.output_format.currentData() == "dcp":
            self.format_forced = True
            self.output_format.setCurrentIndex(1)
        elif not requires_xmp and self.format_forced:
            # Gold or toning selected XMP; the user's own choice of XMP is kept.
            self.format_forced = False
            self.output_format.setCurrentIndex(0)
        self.current_label.setText(list_modes(self.recipe["camera_id"])[self.recipe["mode"]]["label"])

    def _settings_changed(self, *_):
        previous_space = self.recipe["color_space"]
        self.recipe["settings"] = {name: slider.value() for name, (slider, _) in self.controls.items()}
        self.recipe["name"] = self.name_edit.text()
        self.recipe["color_space"] = "adobergb" if self.space.currentIndex() else "srgb"
        self.recipe["toning"] = max(0, self.tone.currentIndex())
        self._sync_format()
        self._request_preview()
        if self.recipe["color_space"] != previous_space:
            self.generation["thumbs"] += 1
            self._thumbnails()

    def _mode_changed(self, current, previous=None):
        if current is None:
            return
        calibration = self.recipe.get("calibration")
        color_space = self.recipe["color_space"]
        self.recipe = default_recipe(current.data(Qt.ItemDataRole.UserRole), self.recipe["camera_id"])
        self.recipe.update(calibration=calibration, color_space=color_space)
        self._sync_controls()
        self._sync_format()
        self._request_preview()

    def _reset(self):
        self._mode_changed(self.mode_list.currentItem())

    def _set_recipe(self, recipe):
        previous = (self.recipe["camera_id"], self.recipe["color_space"], self.recipe["calibration"])
        self.recipe = validate_recipe(recipe)
        if self.recipe["camera_id"] != previous[0]:
            self._fill_modes()
            self._update_file_label()
            self._update_rendition()
        self.mode_list.blockSignals(True)
        for i in range(self.mode_list.count()):
            if self.mode_list.item(i).data(Qt.ItemDataRole.UserRole) == self.recipe["mode"]:
                self.mode_list.setCurrentRow(i)
                break
        self.mode_list.blockSignals(False)
        self._sync_controls()
        self._sync_format()
        self._request_preview()
        if previous != (self.recipe["camera_id"], self.recipe["color_space"], self.recipe["calibration"]):
            self.generation["thumbs"] += 1
            self._thumbnails()

    def _start_job(self, kind, function):
        serial = self.generation[kind]
        job = Job(kind, serial, function)
        self.jobs[(kind, serial)] = job
        job.signals.done.connect(self._job_done)
        self.pool.start(job)
        self.progress.show()

    def _request_preview(self, *_):
        self.generation["preview"] += 1
        self.preview_size = 480
        self.refine_timer.stop()
        self.preview_pending = True
        self.timer.start(180)

    def _refine_preview(self):
        if self.raw is not None and not self.preview_running and not self.preview_pending:
            self.preview_size = 1000
            self.generation["preview"] += 1
            self._render()

    def _render(self):
        if self.preview_running or self.raw is None or self.closing:
            return
        self.preview_running, self.preview_pending = True, False
        recipe = copy.deepcopy(self.recipe)
        frame = self.raw
        reference = default_recipe(self.reference.currentData(), recipe["camera_id"])
        reference.update(calibration=recipe.get("calibration"), color_space=recipe["color_space"])
        output_format = self.output_format.currentData()
        size, cache = self.preview_size, self.preview_cache
        self.statusBar().showMessage(self.tr_text("rendering"))
        def work():
            if size not in cache:
                cache[size] = resize_rgb(frame.rgb, size)
            rgb = cache[size]
            source = frame.metadata["camera_id"]
            before, _ = render_recipe(rgb, reference, frame.baseline_exposure, source_id=source)
            after, report = render_recipe(rgb, recipe, frame.baseline_exposure, output_format == "xmp", source)
            return before, after, report, size
        self._start_job("preview", work)

    def _thumbnails(self):
        frame = self.raw
        if frame is None:
            return
        generation = self.generation["thumbs"]
        calibration = copy.deepcopy(self.recipe.get("calibration"))
        space, camera_id = self.recipe["color_space"], self.recipe["camera_id"]
        def work():
            rgb = resize_rgb(frame.rgb, 160)
            previews = {}
            for mode in list_modes(camera_id):
                if self.closing or self.generation["thumbs"] != generation:
                    break
                recipe = default_recipe(mode, camera_id)
                recipe.update(calibration=calibration, color_space=space)
                previews[mode], _ = render_recipe(rgb, recipe, frame.baseline_exposure, source_id=frame.metadata["camera_id"])
            return previews
        self._start_job("thumbs", work)

    def _job_done(self, kind, serial, result, error):
        self.jobs.pop((kind, serial), None)
        if not self.jobs:
            self.progress.hide()
        if self.closing:
            return
        if kind == "preview":
            self.preview_running = False
        if kind == "export":
            self.export_running = False
            self.export_button.setEnabled(True)
            self.actions["export"].setEnabled(True)
        if serial != self.generation[kind]:
            if kind == "preview" and self.preview_pending:
                self.timer.start(1)
            return
        if error:
            self.last_error = error[1]
            self.warning_label.setText(error[0])
            self.statusBar().showMessage(self.tr_text("error"))
            if kind in ("raw", "export"):
                QMessageBox.warning(self, self.tr_text("error"), error[0])
        elif kind == "raw":
            self.raw = result
            self.preview_cache = {}
            camera_id = result.metadata["camera_id"]
            if camera_id != self.recipe["camera_id"] and Path(result.metadata["path"]) != DEMO_RAW:
                self._set_recipe(default_recipe("natural", camera_id))      # profiles are for the camera that took the RAW
            self._update_rendition()
            self.generation["thumbs"] += 1
            self._update_file_label()
            self.recorded_button.setEnabled(bool(result.metadata.get("settings")))
            self.warning_label.setText("\n".join(result.warnings))
            self._request_preview()
            self._thumbnails()
        elif kind == "preview":
            before, after, self.last_report, size = result
            self.before.set_image(rgb_image(before, self.display_space))
            self.after.set_image(rgb_image(after, self.display_space))
            self._update_rendition()
            warnings = list(self.raw.warnings)
            if self.recipe["mode"] in ("bleach-bypass", "harubeni") and self.recipe.get("toning", 0) == 0:
                warnings.append("조색 끔 · Toning off")
            self.warning_label.setText("\n".join(warnings))
            self.statusBar().showMessage(f"{self.last_report.get('profile_name', self.recipe['mode'])}  ·  {self.display_description}")
            if size == 480:
                self.refine_timer.start(650)
        elif kind == "thumbs":
            for i in range(self.mode_list.count()):
                item = self.mode_list.item(i)
                mode = item.data(Qt.ItemDataRole.UserRole)
                if mode in result:
                    pixmap = QPixmap.fromImage(rgb_image(result[mode], self.display_space))
                    icon = QIcon()
                    for state in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
                        icon.addPixmap(pixmap, state)
                    item.setIcon(icon)
        elif kind == "export":
            self.statusBar().showMessage(f"{self.tr_text('saved')}: {result}")
        if kind == "preview" and self.preview_pending:
            self.timer.start(1)

    def open_raw(self, *_):
        path, _ = QFileDialog.getOpenFileName(self, self.tr_text("open"), "", "Camera RAW (*.pef *.PEF *.dng *.DNG)")
        if path:
            self.load_raw_path(path)

    def load_raw_path(self, path):
        # The displayed RAW stays in use until this one has loaded; a failed load keeps it.
        self.source_paths.add(Path(path))
        self.generation["raw"] += 1
        self.statusBar().showMessage(self.tr_text("loading"))
        self._start_job("raw", lambda: load_raw(path))

    def _use_recorded(self):
        if self.raw is None:
            return
        info = self.raw.metadata
        mode, camera_id = info.get("mode"), info["camera_id"]
        if mode not in list_modes(camera_id) or not info.get("settings"):
            QMessageBox.information(self, self.tr_text("info"), self.tr_text("no_recorded"))
            return
        recipe = default_recipe(mode, camera_id)        # the settings are those of the camera that took the RAW
        recipe.update(settings=info["settings"], color_space=info.get("color_space", "srgb"), toning=info.get("toning") or 0,
                      calibration=self.recipe.get("calibration") if self.recipe["camera_id"] == camera_id else None)
        try:
            self._set_recipe(recipe)
        except ValueError as error:
            QMessageBox.warning(self, self.tr_text("error"), str(error))

    def open_saved_recipe(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr_text("load"), "", "Profile recipe (*.json)")
        if path:
            try:
                self._set_recipe(load_recipe(path))
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, self.tr_text("error"), str(error))

    def save_current_recipe(self):
        path, _ = QFileDialog.getSaveFileName(self, self.tr_text("save"), f"{self.recipe['mode']}.json", "Profile recipe (*.json)")
        if path:
            try:
                path = checked_output(path, ".json", self.source_paths)
                save_recipe(path, self.recipe)
                self.statusBar().showMessage(f"{self.tr_text('saved')}: {path}")
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, self.tr_text("error"), str(error))

    def export_profile(self):
        if self.export_running:
            return
        recipe = copy.deepcopy(self.recipe)
        enhanced = self.output_format.currentData() == "xmp"
        extension = "zip" if enhanced else "dcp"
        path, _ = QFileDialog.getSaveFileName(self, self.tr_text("export"), f"{recipe['mode']}.{extension}",
                                            f"{'DCP + XMP bundle' if enhanced else 'DNG camera profile'} (*.{extension})")
        if not path:
            return
        try:
            path = checked_output(path, f".{extension}", self.source_paths)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, self.tr_text("error"), str(error))
            return
        self.export_running = True
        self.export_button.setEnabled(False)
        self.actions["export"].setEnabled(False)
        self.generation["export"] += 1
        def work():
            if enhanced:
                from .enhanced import build_enhanced, bundle_zip
                data = bundle_zip(build_enhanced(recipe))
            else:
                data, _ = build_profile(recipe)
            write_output(Path(path), data)
            return path
        self._start_job("export", work)

    def import_calibration(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr_text("calibration"), "", "DNG (*.dng *.DNG)")
        if path:
            try:
                recipe = copy.deepcopy(self.recipe)
                recipe["calibration"] = read_calibration(path, recipe["camera_id"])
                self.source_paths.add(Path(path))
                self._set_recipe(recipe)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, self.tr_text("error"), str(error))

    def clear_calibration(self):
        self.recipe["calibration"] = None
        self._update_calibration_label()
        self._request_preview()
        self.generation["thumbs"] += 1
        self._thumbnails()

    def open_chart(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr_text("chart"), "", "JPEG (*.jpg *.jpeg *.JPG *.JPEG)")
        if path:
            self.open_chart_path(path)

    def open_chart_path(self, path):
        from .chart_dialog import ChartDialog
        dialog = ChartDialog(self)
        try:
            if dialog.load_path(path):
                dialog.exec()
        finally:
            dialog.deleteLater()

    def open_looks(self):
        """The chart dialog on the first built-in look; no JPEG is needed."""
        from .chart_dialog import ChartDialog
        dialog = ChartDialog(self)
        try:
            dialog.looks.setCurrentIndex(1)
            dialog.choose_look(1)
            dialog.exec()
        finally:
            dialog.deleteLater()

    def open_guide(self):
        """The user guide in the app's own viewer; one window, raised when it is already open."""
        from .help import GuideWindow
        if self.guide is None:
            self.guide = GuideWindow(self)
        self.guide.show()
        self.guide.raise_()
        self.guide.activateWindow()

    def show_details(self):
        box = QMessageBox(self)
        box.setWindowTitle(self.tr_text("info"))
        box.setText(f"Firmware Color Studio {__version__}\n{self._camera_text()}\nhttps://github.com/yunhyok/firmware-color-studio")
        box.setInformativeText(self.tr_text("limits"))
        box.setDetailedText(json.dumps({"recipe": self.recipe, "profile": self.last_report,
                                       "raw": self.raw.metadata if self.raw else None,
                                       "display": self.display_description}, ensure_ascii=False, indent=2) + "\n" + self.last_error)
        box.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in (".pef", ".dng", ".jpg", ".jpeg") for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            suffix = Path(path).suffix.lower()
            if suffix in (".pef", ".dng"):
                self.load_raw_path(path)
                break
            if suffix in (".jpg", ".jpeg"):
                # The dialog is modal: opened inside the drop, it would hold up the dragging application.
                QTimer.singleShot(0, lambda: self.open_chart_path(path))
                break

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not getattr(self, "screen_connected", False):
            handle.screenChanged.connect(self._screen_changed)
            self.screen_connected = True
            self._screen_changed(self.screen())

    def _screen_changed(self, screen):
        self.display_space, self.display_description = monitor_space(int(self.winId()))
        self._request_preview()
        self.generation["thumbs"] += 1
        self._thumbnails()

    def closeEvent(self, event):
        self.closing = True
        self.timer.stop()
        self.refine_timer.stop()
        self.pool.clear()
        self.pool.waitForDone()
        super().closeEvent(event)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("verify", "export", "preview", "chart-fit"):
        from .cli import main as cli_main
        return cli_main()
    application = QApplication(sys.argv)
    application.setApplicationName("Firmware Color Studio")
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if len(sys.argv) == 2 and Path(sys.argv[1]).suffix.lower() in (".pef", ".dng"):
        window.load_raw_path(sys.argv[1])
    elif len(sys.argv) == 2 and Path(sys.argv[1]).suffix.lower() in (".jpg", ".jpeg"):
        path = sys.argv[1]
        QTimer.singleShot(0, lambda: window.open_chart_path(path))
    elif len(sys.argv) == 1:
        window.load_raw_path(DEMO_RAW)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
