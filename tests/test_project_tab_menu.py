# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A project tab's right-click menu: New, Open…, Save, Save As…, Close,
Close the ones to the right / to the left, Close all — and the project's
scenes as tabs. The project right-clicked comes to the front first, so
Save and Save As act on it; each one closed asks only about itself."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication, QMessageBox

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _three(win):
    """Three projects, A B C, with B in front."""
    a = win._doc
    b = win._new_document()
    c = win._new_document()
    win.activate_document(b)
    return a, b, c


def _actions(menu):
    return {a.text(): a for a in menu.actions() if a.text()}


def test_the_menu_offers_files_closing_and_scenes(win):
    from core.i18n import tr
    a, b, c = _three(win)
    menu = win._build_project_tab_menu(b)
    acts = _actions(menu)
    for text in ("New", "Open…", "Save", "Save As…", "Close Project",
                 "Close Projects to the Right", "Close Projects to the Left",
                 "Close All Projects", "Show scenes as tabs"):
        assert tr(text) in acts, text
    assert acts[tr("Save")].shortcut().toString()      # shortcuts shown
    menu.close()


def test_left_and_right_are_offered_only_when_there_are(win):
    from core.i18n import tr
    a, b, c = _three(win)
    first = _actions(win._build_project_tab_menu(a))
    last = _actions(win._build_project_tab_menu(c))
    assert not first[tr("Close Projects to the Left")].isEnabled()
    assert first[tr("Close Projects to the Right")].isEnabled()
    assert not last[tr("Close Projects to the Right")].isEnabled()
    assert last[tr("Close Projects to the Left")].isEnabled()


def test_close_to_the_right(win):
    from core.i18n import tr
    a, b, c = _three(win)
    _actions(win._build_project_tab_menu(b))[
        tr("Close Projects to the Right")].trigger()
    assert win._documents == [a, b]


def test_close_to_the_left(win):
    from core.i18n import tr
    a, b, c = _three(win)
    _actions(win._build_project_tab_menu(b))[
        tr("Close Projects to the Left")].trigger()
    assert win._documents == [b, c]


def test_close_all_leaves_one_empty_project(win):
    from core.i18n import tr
    a, b, c = _three(win)
    _actions(win._build_project_tab_menu(b))[
        tr("Close All Projects")].trigger()
    assert len(win._documents) == 1
    assert win._documents[0] not in (a, b, c)
    assert not win._is_dirty()


def test_a_cancel_stops_closing_the_rest(win, monkeypatch):
    a, b, c = _three(win)
    win.activate_document(a)
    win.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    win.viewport.scene.version += 1               # A: unsaved
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.Cancel)
    assert not win.close_documents([a, b, c])
    assert win._documents == [a, b, c]            # stopped at A


def test_the_project_right_clicked_comes_to_the_front(win, monkeypatch):
    a, b, c = _three(win)
    shown = []

    class _Menu:                                   # not a real (modal) one
        def exec(self, pos):
            shown.append(win._doc)
    monkeypatch.setattr(win, "_build_project_tab_menu", lambda doc: _Menu())
    win._project_tab_menu(c, win.mapToGlobal(win.rect().center()))
    assert win._doc is c and shown == [c]


def test_save_from_the_menu_saves_that_project(win, tmp_path, monkeypatch):
    from core.i18n import tr
    from views import main_window
    a, b, c = _three(win)
    target = tmp_path / "desde-el-menu.igz"
    monkeypatch.setattr(main_window.file_dialogs, "getSaveFileName",
                        lambda *a_, **k: (str(target), ""))
    _actions(win._build_project_tab_menu(b))[tr("Save")].trigger()
    assert target.is_file()
    assert b.path == target
