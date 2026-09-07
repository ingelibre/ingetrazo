# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Model | Sheet 1 | Sheet 2 … strip at the bottom of both windows
(Marco, 2026-09-07: «como lo tiene AutoCAD»). One click takes you from the
model to any sheet and back; both strips follow the document's sheets; each
window's strip marks what THAT window shows."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _window(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    return win


def _close(win):
    comp = getattr(win, "_composer", None)
    if comp is not None:
        comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_the_main_window_strip_lists_model_and_the_document_sheets(monkeypatch):
    win = _window(monkeypatch)
    try:
        tabs = win._sheet_tabs
        assert tabs.names()[0] == "Model"
        assert tabs.current() is None                    # this window = the model
        from core.composition import Composicion
        win.viewport.scene.compositions.append(Composicion(name="Planta"))
        win.viewport.scene.compositions.append(Composicion(name="Cortes"))
        win._update_title()                              # what open/new call
        assert tabs.names() == ["Model", "Planta", "Cortes"]
        assert tabs.current() is None
    finally:
        _close(win)


def test_a_sheet_tab_opens_the_composer_on_that_sheet(monkeypatch):
    win = _window(monkeypatch)
    try:
        from core.composition import Composicion
        win.viewport.scene.compositions.append(Composicion(name="Planta"))
        win.viewport.scene.compositions.append(Composicion(name="Cortes"))
        win._update_title()
        win._sheet_tabs.click(2)                         # «Cortes»
        comp = win._composer
        assert comp.isVisible()
        assert comp.comp is win.viewport.scene.compositions[1]
        # the composer's strip marks its sheet, the main window's the model
        assert comp._sheet_tabs.names() == ["Model", "Planta", "Cortes"]
        assert comp._sheet_tabs.current() == 1
        assert win._sheet_tabs.current() is None
        comp._sheet_tabs.click(1)                        # «Planta», from the composer
        assert comp.comp is win.viewport.scene.compositions[0]
        assert comp._sheet_tabs.current() == 0
    finally:
        _close(win)


def test_both_strips_follow_added_renamed_and_deleted_sheets(monkeypatch):
    win = _window(monkeypatch)
    try:
        win._sheet_tabs.click(1)                         # the default sheet
        comp = win._composer
        n0 = len(win.viewport.scene.compositions)
        comp._on_comp_add()
        assert len(win._sheet_tabs.names()) == n0 + 2    # Model + sheets
        assert comp._sheet_tabs.current() == n0          # the new one is open
        comp.comp_combo.setEditText("Detalles")
        comp._on_comp_rename()
        assert win._sheet_tabs.names()[-1] == "Detalles"
        assert comp._sheet_tabs.names()[-1] == "Detalles"
        monkeypatch.setattr("views.composer.QMessageBox.question",
                            lambda *a, **k: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.Yes)
        comp._on_comp_del()
        assert len(win._sheet_tabs.names()) == n0 + 1
        assert comp._sheet_tabs.current() == 0
    finally:
        _close(win)


def test_the_model_tab_brings_the_model_window_back(monkeypatch):
    win = _window(monkeypatch)
    try:
        win.show()
        win._sheet_tabs.click(1)
        comp = win._composer
        win.hide()                                       # as if behind / minimised
        comp._sheet_tabs.click(0)                        # «Model» from the composer
        assert win.isVisible()
        assert comp._sheet_tabs.current() == 0           # still marks its sheet
        assert win._sheet_tabs.current() is None
    finally:
        _close(win)


def test_the_strip_sits_in_the_status_bar_and_outlives_a_hint(monkeypatch):
    """Same row as the measurements box, and a temporary status message
    must not hide it (a plain QStatusBar hides normal widgets while a
    message shows)."""
    win = _window(monkeypatch)
    try:
        win.show()
        bar = win.statusBar()
        assert win._sheet_tabs.parent() is bar
        standing = bar.currentMessage()
        bar.showMessage("Selected everything", 50)
        assert bar.currentMessage() == "Selected everything"
        assert not win._sheet_tabs.isHidden()
        _app.processEvents()
        import time
        t0 = time.monotonic()
        while bar.currentMessage() != standing and time.monotonic() - t0 < 2:
            _app.processEvents()
        assert bar.currentMessage() == standing     # the hint comes back
        win._sheet_tabs.click(1)
        comp = win._composer
        assert comp._sheet_tabs.parent() is comp.statusBar()
    finally:
        _close(win)


def test_the_standing_hint_never_widens_the_window(monkeypatch):
    """The main window's hint is a long line; as a permanent label it must
    not become the window's minimum width (Marco could not maximise)."""
    win = _window(monkeypatch)
    try:
        win.show()
        bar = win.statusBar()
        assert len(bar.currentMessage()) > 100          # the long hint is set
        # a plain QLabel with this hint asked for ~2200 px; the app's own
        # floor (toolbars, docks) is under 1000 on the offscreen platform
        assert win.minimumSizeHint().width() < 1000
        win.resize(700, 500)
        _app.processEvents()
        assert win.width() < 1000                       # it shrank
        assert bar.currentMessage().startswith("Orbit") # full text kept
    finally:
        _close(win)
