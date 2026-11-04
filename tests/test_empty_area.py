# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every project closed (views/empty_area.py): the work area goes empty and
hatched with only «+» above — no tabs, no views button, no scene row, no
panels or their handles, no sheets strip, no tools. «+», File ▸ New, an
opened or a dropped file bring a project back and everything with it; the
panels come back as the user had them, and quitting from the empty area
keeps them."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDockWidget

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1300, 800)
    w.show()
    QApplication.processEvents()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _open_panels(win):
    return [d for d in win.findChildren(QDockWidget)
            if d.parent() is win and d.toggleViewAction().isChecked()]


def _doc_file(tmp_path, name="abierto.igz"):
    from core.scene import Scene
    from formats import igz
    path = tmp_path / name
    igz.save_scene(Scene(), path)
    return path


def test_closing_the_last_project_leaves_the_empty_area(win):
    panels = _open_panels(win)
    assert panels
    assert win.close_document()
    QApplication.processEvents()
    bar = win._project_tabs
    assert win.is_empty()
    assert win._empty_area.isVisible() and not win._doc_stack.isVisible()
    assert not bar.tabs.isVisible()             # no tabs…
    assert not bar.views_button.isVisible()     # …no views button…
    assert bar.plus.isVisible()                 # …only «+»
    assert win._scene_tabs.isHidden()
    assert not any(d.isVisible() for d in panels)
    assert not win._sidebar_handle.isVisible()
    assert not win._sheet_tabs.isVisible()
    assert win.windowTitle() == "IngeTrazo"


def test_plus_brings_a_project_and_everything_back(win):
    panels = _open_panels(win)
    win.close_document()
    win._project_tabs.plus.click()
    QApplication.processEvents()
    assert not win.is_empty()
    assert len(win._documents) == 1
    assert win._doc_stack.isVisible() and not win._empty_area.isVisible()
    assert win._doc_stack.currentWidget() is win._doc.slot_widget()
    assert win._project_tabs.tabs.isVisible()
    assert win._project_tabs.views_button.isVisible()
    assert all(d.toggleViewAction().isChecked() for d in panels)
    assert win._sidebar_handle.isVisible()
    assert win._sheet_tabs.isVisible()
    assert not win._scene_tabs.isHidden()


def test_file_new_leaves_it_too(win):
    win.close_document()
    win._on_new()
    assert not win.is_empty() and len(win._documents) == 1


def test_opening_a_file_leaves_it(win, tmp_path):
    path = _doc_file(tmp_path)
    win.close_document()
    assert win.open_path(path)
    assert not win.is_empty()
    assert len(win._documents) == 1 and win._doc.path == path


def test_a_file_it_cannot_read_leaves_it_empty(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    bad = tmp_path / "roto.igz"
    bad.write_text("no es un documento")
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    win.close_document()
    assert not win.open_path(bad)
    assert win.is_empty()


def _drop(widget, path):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    centre = widget.rect().center()
    enter = QDragEnterEvent(centre, Qt.CopyAction, mime, Qt.LeftButton,
                            Qt.NoModifier)
    QApplication.sendEvent(widget, enter)
    if not enter.isAccepted():
        return False
    QApplication.sendEvent(widget, QDropEvent(QPointF(centre), Qt.CopyAction,
                                              mime, Qt.LeftButton,
                                              Qt.NoModifier))
    return True


def test_a_file_dropped_on_it_opens(win, tmp_path):
    path = _doc_file(tmp_path, "soltado.igz")
    win.close_document()
    assert _drop(win._empty_area, path)
    assert not win.is_empty() and win._doc.path == path


def test_a_file_it_cannot_open_is_refused(win, tmp_path):
    other = tmp_path / "notas.txt"
    other.write_text("x")
    win.close_document()
    assert not _drop(win._empty_area, other)
    assert win.is_empty()


def test_no_tool_while_empty(win):
    win.close_document()
    assert all(not a.isEnabled() for a in win._tool_actions.values())
    win._project_tabs.plus.click()
    assert any(a.isEnabled() for a in win._tool_actions.values())


def test_quitting_from_it_keeps_the_panels(win):
    panels = _open_panels(win)
    win.close_document()
    win._saved_version = win.viewport.scene.version
    win.close()
    assert not any(d.isHidden() for d in panels)   # what saveState records


def test_closing_all_from_the_tab_menu_leaves_it_empty(win):
    from core.i18n import tr
    win._new_document()
    menu = win._build_project_tab_menu(win._doc)
    next(a for a in menu.actions()
         if a.text() == tr("Close All Projects")).trigger()
    assert win.is_empty()


def test_plus_from_the_empty_area_starts_a_new_document(win):
    """The blank project behind the area was made without what a new
    document starts with: «+» gave one without its scale figure."""
    win.close_document()
    assert not win.viewport.scene.groups
    win._project_tabs.plus.click()
    assert not win.is_empty()
    assert win.viewport.scene.groups
    assert not win._is_dirty()
