# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Edit ▸ Select None (Ctrl+T): the counterpart of Select All (Ctrl+A).

Emptying the selection is a change of what is SHOWN, not of the document:
the scene version moves so the colour caches and the tray refresh, but the
"unsaved changes" mark does not — the same rule issue #38 set for Select
All and Invert Selection.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence, QVector3D
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _square(mesh, x0, size=1.0):
    return mesh.add_face([V(x0, 0), V(x0 + size, 0),
                          V(x0 + size, size), V(x0, size)])


def _loose(scene):
    return set(scene.edges) | set(scene.faces)


def _action(win):
    """The window's Ctrl+T owner, the way the menu holds it."""
    from PySide6.QtGui import QAction
    acts = [a for a in win.findChildren(QAction)
            if a.shortcut() == QKeySequence("Ctrl+T")]
    assert len(acts) == 1                     # one owner: never ambiguous
    return acts[0]


# ---- the core rule ----------------------------------------------------------

def test_clear_selection_empties_it_and_moves_the_view():
    scene = Scene()
    a = _square(scene.mesh, 0)
    b = _square(scene.mesh, 5)
    scene.select([a, b, *_loose(scene)])
    before = scene.version
    content_before = scene.content_version

    scene.clear_selection()

    assert not scene.selection
    assert scene.version > before                  # the GL caches refresh
    assert scene.content_version == content_before  # but it is not an edit


def test_clear_selection_on_an_empty_selection_is_a_no_op():
    scene = Scene()
    before = scene.version
    scene.clear_selection()
    assert not scene.selection
    assert scene.version == before                 # nothing to redraw


# ---- the window: menu, shortcut, status bar, configurability ----------------

def test_edit_menu_offers_it():
    from core.i18n import source_of
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        assert source_of(_action(win).text()) == "Select None"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_it_empties_the_selection_without_dirtying_the_document():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        a = _square(scene.mesh, 0)
        b = _square(scene.mesh, 5)
        scene.select([a, b, *_loose(scene)])
        win._saved_version = scene.version         # as if just saved
        assert not win._is_dirty()

        seen: list = []
        win.viewport.sceneVersionChanged.connect(seen.append)
        _action(win).trigger()

        assert not scene.selection
        assert seen and seen[-1] == scene.version  # the tray hears about it
        assert win.statusBar().currentMessage()
        assert not win._is_dirty()                 # view-only, not an edit
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_shortcut_is_configurable_like_any_other(monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox
    from views.main_window import MainWindow
    from views.shortcuts import ShortcutsPanel, action_key, collect_actions
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    QSettings().remove("shortcuts")
    win = MainWindow()
    try:
        act = next(a for a in collect_actions(win)
                   if action_key(a) == "text:Select None")
        assert ShortcutsPanel(win).assign(act, [QKeySequence("Ctrl+Alt+N")])
        assert [s.toString() for s in act.shortcuts()] == ["Ctrl+Alt+N"]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
        QSettings().remove("shortcuts")
