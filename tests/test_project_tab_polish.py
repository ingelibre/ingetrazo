# SPDX-License-Identifier: GPL-3.0-or-later
"""The compact project strip keeps its controls functional."""
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QTabBar
from views.documents import Document, ProjectTabBar

_app = QApplication.instance() or QApplication([])


def test_new_and_reordered_close_buttons_target_the_right_document():
    strip = ProjectTabBar()
    first, second = Document(), Document()
    for doc, name in ((first, 'One'), (second, 'Two')):
        strip.add(doc)
        strip.set_label(doc, name, False)
    strip.tabs.moveTab(0, 1)
    events = []
    strip.newRequested.connect(lambda: events.append('new'))
    strip.closeRequested.connect(events.append)
    strip.plus.click()
    strip.tabs.tabButton(1, QTabBar.RightSide).click()
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()
    assert events == ['new', first]
    assert strip.plus.focusPolicy() != Qt.NoFocus
    assert strip.tabs.tabButton(1, QTabBar.RightSide).focusPolicy() != Qt.NoFocus
    strip.close()


def test_plus_stays_near_short_tabs_and_keeps_space_to_scroll():
    strip = ProjectTabBar()
    doc = Document()
    strip.add(doc)
    strip.set_label(doc, 'Untitled', False)
    strip.resize(450, 40)
    strip.show()
    _app.processEvents()
    bar = strip.tabs
    assert strip.plus.x() - (bar.x() + bar.tabRect(0).right() + 1) <= 8
    assert strip.plus.width() == strip.plus.height() == 24
    strip.close()
