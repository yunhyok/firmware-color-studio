"""The user guide, shown by the app itself: it needs no web browser."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QTextDocument
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

GUIDE = Path(__file__).parent / "resources" / "help" / "index.html"


class _Browser(QTextBrowser):
    def loadResource(self, kind, url):
        # Figures are stored at twice the width the page gives them.  Qt would scale them
        # roughly while painting; hand it the pixels of this screen instead.
        path = self.source().resolved(url).toLocalFile()
        if kind == QTextDocument.ResourceType.ImageResource and path:
            image = QImage(path)
            if not image.isNull():
                ratio = self.devicePixelRatioF()
                image = image.scaledToWidth(max(1, round(image.width() / 2 * ratio)),
                                            Qt.TransformationMode.SmoothTransformation)
                image.setDevicePixelRatio(ratio)
                return image
        return super().loadResource(kind, url)


class GuideWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        korean = parent.lang == 0
        self.setWindowTitle(parent.tr_text("guide"))
        self.resize(1010, 780)
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        self.browser = _Browser()
        # The page is dark text on white whatever the application's own style is.
        self.browser.setStyleSheet("QTextBrowser { background:#ffffff; color:#1f2933; }")
        self.browser.setOpenExternalLinks(True)
        self.browser.setSource(QUrl.fromLocalFile(str(GUIDE)))
        for text, action in ((("뒤로", "Back")[not korean], self.browser.backward),
                             (("처음으로", "Contents")[not korean], lambda: self.browser.setSource(QUrl.fromLocalFile(str(GUIDE)))),
                             (("웹 브라우저로 열기", "Open in a web browser")[not korean],
                              lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(GUIDE))))):
            button = QPushButton(text)
            button.setAutoDefault(False)
            button.clicked.connect(action)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addWidget(self.browser, 1)
