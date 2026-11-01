# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Extensions that swap the central widget keep working with the project
tabs (#1066).

An extension written before the tabs takes the window's central widget to
be the viewport: the MultiView extension checks ``centralWidget() is
app.viewport``, takes it with ``takeCentralWidget()``, puts its grid of
views (holding that viewport) in its place with ``setCentralWidget()``, and
later does the reverse. With the tab bar the real central widget is the
tab area, so the extension refused to start. Now those three calls work on
one project's place in the viewport stack, and the tabs stay."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout,  # noqa: E402
                               QWidget)

_app = QApplication.instance() or QApplication([])


def _settle(ms: int = 0) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for d in w.documents():
        d.saved_content = d.viewport.scene.content_version
    w.close()


class _GridOfViews:
    """The calls a multi-view extension makes, in its order: it keeps the
    viewport of the day it was set up, as MultiView does."""

    def __init__(self, window):
        self.window = window
        self.main_vp = window.viewport
        self.container = None
        self.active = False

    def activate(self) -> bool:
        if self.window.centralWidget() is not self.main_vp:
            return False                      # "close the other workspace first"
        self.window.takeCentralWidget()
        if self.container is None:
            self.container = QWidget()
            QVBoxLayout(self.container)
        self.container.layout().addWidget(self.main_vp)
        self.window.setCentralWidget(self.container)
        self.container.show()
        self.main_vp.show()
        self.active = True
        return True

    def deactivate(self) -> None:
        self.container.layout().removeWidget(self.main_vp)
        self.container.hide()
        self.main_vp.setParent(self.window)
        self.window.takeCentralWidget()
        self.container.setParent(self.window)
        self.container.hide()
        self.window.setCentralWidget(self.main_vp)
        self.main_vp.show()
        self.active = False


def _shown(win):
    return win._doc_stack.currentWidget()


def test_the_central_widget_an_extension_sees_is_the_viewport(win):
    assert win.centralWidget() is win.viewport
    # Qt's own central widget is still the tab area.
    assert QMainWindow.centralWidget(win) is win._doc_area
    win._new_document()
    assert win.centralWidget() is win.viewport


def test_a_grid_of_views_takes_the_viewport_and_keeps_the_tabs(win):
    first = win.active_document()
    grid = _GridOfViews(win)
    assert grid.activate()
    assert QMainWindow.centralWidget(win) is win._doc_area
    assert _shown(win) is grid.container
    assert win.viewport.parent() is grid.container
    assert win.viewport is first.viewport
    assert win.centralWidget() is grid.container
    assert not win._project_tabs.isHidden()
    grid.deactivate()
    assert _shown(win) is first.viewport
    assert first.stand_in is None
    assert win.centralWidget() is first.viewport
    assert win._doc_stack.count() == 1
    # Again: the second time the extension reuses its container.
    assert grid.activate() and _shown(win) is grid.container
    grid.deactivate()
    assert _shown(win) is first.viewport and win._doc_stack.count() == 1


def test_switching_tabs_with_the_grid_on(win):
    first = win.active_document()
    grid = _GridOfViews(win)
    grid.activate()
    second = win._new_document()
    assert win.active_document() is second
    assert _shown(win) is second.viewport
    win.activate_document(first)
    assert _shown(win) is grid.container
    win.activate_document(second)
    # Turning it off from the other tab puts the first project's viewport
    # back in ITS place and leaves the tab in front alone.
    grid.deactivate()
    assert _shown(win) is second.viewport
    assert first.slot_widget() is first.viewport
    assert win._doc_stack.indexOf(first.viewport) >= 0
    win.activate_document(first)
    assert _shown(win) is first.viewport
    assert win._doc_stack.count() == 2


def test_in_another_tab_the_extension_declines_and_nothing_moves(win):
    grid = _GridOfViews(win)
    second = win._new_document()
    assert not grid.activate()
    assert _shown(win) is second.viewport
    assert win._doc_stack.count() == 2


def test_closing_the_replaced_project_leaves_no_stand_in(win, monkeypatch):
    first = win.active_document()
    grid = _GridOfViews(win)
    grid.activate()
    win._new_document()
    win.close_document(first, ask=False)
    _settle()
    assert win._doc_stack.count() == 1
    assert _shown(win) is win.viewport


def test_set_without_take_never_deletes_a_viewport(win):
    """Qt deletes a central widget replaced without taking it first: an
    extension's stand-in, yes; a project's viewport, never."""
    vp = win.viewport
    panel = QWidget()
    win.setCentralWidget(panel)
    _settle()
    assert _shown(win) is panel
    assert vp.scene is not None and vp.parent() is win._doc_stack
    win.setCentralWidget(vp)
    _settle()
    assert _shown(win) is vp
    with pytest.raises(RuntimeError):
        panel.objectName()                    # the stand-in was deleted
