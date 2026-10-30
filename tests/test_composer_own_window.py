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
        assert comp._window is win               # still works on this model
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
        comp.setGeometry(QRect(40, 30, 620, 460))
        comp.close()
        assert QSettings().value("composer/geometry")
        from views.composer import ComposerWindow
        again = ComposerWindow(win)
        try:
            assert again.size().width() == 620
            assert again.size().height() == 460
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
