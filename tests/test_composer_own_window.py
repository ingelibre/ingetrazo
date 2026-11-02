# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet composer is a window of its own, not one owned by the model
window. Owned, under Windows it had no taskbar button, stayed above the model
and, minimised, shrank to a stub over the model's bottom-left corner that
could not be moved. On its own it minimises to the taskbar, names the
document it holds, comes back out of the taskbar from the model's sheet tab,
remembers where it was and goes away with the model."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _window(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    return MainWindow()


def _close(win):
    comp = getattr(win, "_composer", None)
    if comp is not None:
        comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_the_composer_is_not_owned_by_the_model_window(monkeypatch):
    win = _window(monkeypatch)
    try:
        comp = win._ensure_composer()
        assert comp.parent() is None             # no owner: a taskbar button
        assert comp.isWindow()
        # Still works on this model — through its project's host (#1066).
        assert getattr(comp._window, "_host_window", comp._window) is win
    finally:
        _close(win)


def test_a_minimised_composer_comes_back_from_the_sheet_tab(monkeypatch):
    win = _window(monkeypatch)
    try:
        win.show()
        win._on_open_composer()
        comp = win._composer
        comp.showMinimized()
        assert comp.isMinimized()
        win._sheet_tabs.click(1)                  # the model's sheet tab
        assert comp.isVisible()
        assert not comp.isMinimized()
    finally:
        _close(win)


def test_a_minimised_model_comes_back_from_the_model_tab(monkeypatch):
    win = _window(monkeypatch)
    try:
        win.show()
        win._on_open_composer()
        comp = win._composer
        win.showMinimized()
        monkeypatch.setattr(type(comp), "_covers", lambda self, other: False)
        comp._sheet_tabs.click(0)                 # «Model»
        assert not win.isMinimized()
    finally:
        _close(win)


def test_the_composer_title_names_the_document(monkeypatch, tmp_path):
    win = _window(monkeypatch)
    try:
        comp = win._ensure_composer()
        win._current_path = tmp_path / "vivienda.igz"
        win._update_title()
        title = comp.windowTitle()
        assert title.startswith("Sheet composer")
        assert "vivienda.igz" in title
    finally:
        _close(win)


def test_the_composer_remembers_its_place(monkeypatch):
    QSettings().remove("composer/geometry")
    win = _window(monkeypatch)
    try:
        comp = win._ensure_composer()
        comp.show()
        # Above the composer's minimum height (461 px here) and inside the
        # smallest screen it may restore onto: restoreGeometry clamps both.
        comp.setGeometry(QRect(40, 30, 700, 600))
        assert (comp.width(), comp.height()) == (700, 600)
        comp.close()
        assert QSettings().value("composer/geometry")
        from views.composer import ComposerWindow
        again = ComposerWindow(win)
        try:
            assert again.size().width() == 700
            assert again.size().height() == 600
        finally:
            again.close()
    finally:
        _close(win)
        QSettings().remove("composer/geometry")


def test_closing_the_model_closes_the_composer(monkeypatch):
    win = _window(monkeypatch)
    win.show()
    win._on_open_composer()
    comp = win._composer
    assert comp.isVisible()
    monkeypatch.setattr(type(win), "_confirm_discard", lambda self, title: True)
    win.close()
    assert not comp.isVisible()


# ---- with several projects open, one composer each (#1066) ----------------
def _settle(ms: int = 0) -> None:
    """Run the event loop — deleteLater included, which processEvents()
    alone never runs."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _second_project(win):
    """Leave the first project with work in it, so File ▸ New opens a tab."""
    from PySide6.QtGui import QVector3D as V
    from core.history import AddEdgeCommand
    win.viewport.history.execute(AddEdgeCommand(V(0, 0, 0), V(1, 0, 0)))
    win.viewport.notify_scene_changed()
    win._on_new()
    assert len(win.documents()) == 2


def _clean_all(win):
    for d in win.documents():
        d.saved_content = d.viewport.scene.content_version


def test_each_project_has_its_own_composer_named_after_it(monkeypatch, tmp_path):
    win = _window(monkeypatch)
    try:
        win.show()
        win._current_path = tmp_path / "casa.igz"
        win._on_open_composer()
        comp_a = win._composer
        assert "casa.igz" in comp_a.windowTitle()
        _second_project(win)
        assert not comp_a.isVisible()            # stepped aside with its tab
        win._on_open_composer()
        comp_b = win._composer
        assert comp_b is not comp_a
        assert comp_b.parent() is None and comp_a.parent() is None
        assert "casa.igz" not in comp_b.windowTitle()
        win.activate_document(win.documents()[0])
        assert comp_a.isVisible() and not comp_b.isVisible()
        assert "casa.igz" in comp_a.windowTitle()
    finally:
        _clean_all(win)
        win.close()


def test_closing_a_tab_with_its_composer_open_lets_it_go(monkeypatch):
    import gc
    import weakref
    win = _window(monkeypatch)
    try:
        win.show()
        _second_project(win)
        win._on_open_composer()
        _settle()                                # its first show settles
        doc = win.active_document()
        shown = win._composer.isVisible()
        comp = weakref.ref(win._composer)
        assert shown
        assert win.close_document(doc, ask=False)
        del doc
        for _ in range(2):
            _settle()
            gc.collect()
        assert comp() is None, "the closed project's composer is still alive"
        assert len(win.documents()) == 1
    finally:
        _clean_all(win)
        win.close()


def test_quitting_closes_the_composer_of_every_project(monkeypatch):
    win = _window(monkeypatch)
    win.show()
    win._on_open_composer()
    comp_a = win._composer
    _second_project(win)
    win._on_open_composer()
    comp_b = win._composer
    win.activate_document(win.documents()[0])      # A in front, B's hidden
    assert comp_a.isVisible()
    _clean_all(win)
    win.close()
    assert not comp_a.isVisible() and not comp_b.isVisible()


def test_undo_in_a_composer_stays_in_its_project(monkeypatch):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from core.composition import FormaItem
    win = _window(monkeypatch)
    try:
        win.show()
        win._on_open_composer()
        comp_a = win._composer
        shape = FormaItem(kind="rect", x_mm=10.0, y_mm=10.0)
        comp_a.comp.shapes = [shape]
        comp_a._rebuild_canvas()
        for it in comp_a.canvas.items():
            if getattr(it, "model", None) is shape:
                it.setSelected(True)
        comp_a._view.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert shape.x_mm == 11.0
        _second_project(win)
        win._on_open_composer()
        assert not win._composer.history.undo()  # B has nothing to undo
        win.activate_document(win.documents()[0])
        assert win._composer is comp_a
        assert comp_a.history.undo() and shape.x_mm == 10.0
    finally:
        _clean_all(win)
        win.close()
