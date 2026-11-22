"""The built-in user guide: every file it refers to is shipped, and the app shows it without a web browser."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import re

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from firmware_color_studio.app import MainWindow, STYLE
from firmware_color_studio.help import GUIDE


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    yield app


def test_guide_refers_only_to_files_and_anchors_it_has():
    html = GUIDE.read_text(encoding="utf-8")
    pictures = re.findall(r'<img src="([^"]+)"', html)
    assert len(pictures) >= 12
    assert all((GUIDE.parent / name).is_file() for name in pictures)
    links = set(re.findall(r'href="([^"]+)"', html))
    assert links and all(link.startswith("#") for link in links)        # nothing needs a network
    assert {link[1:] for link in links} <= set(re.findall(r'<a name="([^"]+)"', html))


def test_help_menu_shows_the_guide_inside_the_app(application):
    window = MainWindow()
    try:
        assert window.help_menu.title() == "도움말"
        assert window.actions["guide"].shortcut().toString() == "F1"
        window.actions["guide"].trigger()
        browser = window.guide.browser
        assert "Lightroom에 프로파일 추가하기" in browser.toPlainText()
        picture = browser.loadResource(QTextDocument.ResourceType.ImageResource, QUrl("images/concept.png"))
        assert picture.width() / picture.devicePixelRatio() == 900       # the width the page gives it
        browser.scrollToAnchor("lightroom")
        assert browser.verticalScrollBar().value() > 0
        window.actions["guide"].trigger()                                # a second F1 raises the same window
        assert window.guide.browser is browser
        window.language.setCurrentIndex(1)
        assert window.help_menu.title() == "Help" and window.actions["guide"].text() == "User guide"
    finally:
        window.close()
