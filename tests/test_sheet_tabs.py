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


def test_the_plus_tab_opens_the_composer_on_a_new_sheet(monkeypatch):
    """A fresh document has no sheets, and a strip that only said «Model»
    gave no way into the composer (Marco, 0.3.13 Flatpak: «no aparece
    compositor de láminas abajo»). «+» is AutoCAD's new-layout tab."""
    win = _window(monkeypatch)
    try:
        tabs = win._sheet_tabs
        assert tabs.names() == ["Model"]
        assert tabs.plus_index() == 1
        assert tabs.tabText(tabs.plus_index()) == "+"
        tabs.click(tabs.plus_index())
        comp = win._composer
        assert comp.isVisible()
        assert len(win.viewport.scene.compositions) == 1      # the first sheet, once
        assert comp._sheet_tabs.current() == 0
        assert win._sheet_tabs.names() == ["Model", comp.comp.name]
        comp._sheet_tabs.click(comp._sheet_tabs.plus_index())  # «+» in the composer
        assert len(win.viewport.scene.compositions) == 2
        assert comp._sheet_tabs.current() == 1
        win._sheet_tabs.click(win._sheet_tabs.plus_index())    # «+» in the model window
        assert len(win.viewport.scene.compositions) == 3
        assert comp.comp is win.viewport.scene.compositions[2]
        assert win._sheet_tabs.current() is None
    finally:
        _close(win)


def test_a_mouse_click_hands_over_after_the_press_and_the_strips_end_right(monkeypatch):
    """QTabBar makes the pressed tab current AFTER the clicked signal; a
    hand-over run inside the signal left the composer's strip marking
    «Model» and the model window's marking the sheet — and rebuilt the
    strip under a press in progress."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win = _window(monkeypatch)
    try:
        win.show()
        win._sheet_tabs.click(1)                          # first sheet, composer up
        comp = win._composer
        ct = comp._sheet_tabs
        QTest.mouseClick(ct, Qt.LeftButton, Qt.NoModifier, ct.tabRect(0).center())
        _app.processEvents()
        assert ct.current() == 0                          # still marks its sheet
        assert win._sheet_tabs.current() is None
        mt = win._sheet_tabs
        QTest.mouseClick(mt, Qt.LeftButton, Qt.NoModifier, mt.tabRect(1).center())
        _app.processEvents()
        assert mt.current() is None                       # the model window shows the model
        assert ct.current() == 0
        comp._on_comp_add()
        QTest.mouseClick(ct, Qt.LeftButton, Qt.NoModifier, ct.tabRect(1).center())
        _app.processEvents()
        assert comp.comp is win.viewport.scene.compositions[0]
        assert ct.current() == 0
    finally:
        _close(win)


def test_a_hint_or_a_hand_over_does_not_rebuild_the_tabs(monkeypatch):
    win = _window(monkeypatch)
    try:
        tabs = win._sheet_tabs
        seen = []
        orig = tabs.removeTab
        monkeypatch.setattr(tabs, "removeTab", lambda i: (seen.append(i), orig(i)))
        tabs.refresh([], None)                            # same names: untouched
        win.statusBar().showMessage("hint", 10)
        assert seen == []
        from core.composition import Composicion
        win.viewport.scene.compositions.append(Composicion(name="Planta"))
        win._update_title()
        assert seen                                       # a new sheet does rebuild
    finally:
        _close(win)


def test_model_tab_steps_the_composer_aside_when_it_overlaps_the_model_window(monkeypatch):
    """The hand-over never guesses (Wayland may refuse to raise, Windows
    keeps an owned window on top): overlapping, the composer hides at
    once; side by side it stays; a sheet tab brings it back as it was."""
    win = _window(monkeypatch)
    try:
        win.show()
        win._sheet_tabs.click(1)
        comp = win._composer
        monkeypatch.setattr(type(comp), "_covers", lambda self, other: True)
        comp._sheet_tabs.click(0)                        # «Model»
        assert not comp.isVisible()                      # stepped aside at once
        win._sheet_tabs.click(1)                         # …and comes back
        assert comp.isVisible()
        monkeypatch.setattr(type(comp), "_covers", lambda self, other: False)
        comp._sheet_tabs.click(0)                        # two monitors: stays
        assert comp.isVisible()
    finally:
        _close(win)


def test_ctrl_s_in_the_composer_saves_the_whole_document(monkeypatch):
    """The sheets are part of the document, but the model window's Save
    shortcut never reached the composer (Marco, 2026-09-08)."""
    win = _window(monkeypatch)
    try:
        win.show()
        win._sheet_tabs.click(1)
        comp = win._composer
        calls = []
        monkeypatch.setattr(win, "_on_save", lambda: calls.append("save"))
        monkeypatch.setattr(win, "_on_save_as", lambda: calls.append("save_as"))
        comp.save_document()
        comp.save_document_as()
        assert calls == ["save", "save_as"]
    finally:
        _close(win)


def test_sheet_tab_menu_renames_duplicates_and_deletes(monkeypatch):
    """Right-click on a sheet tab, in either window (Marco, 2026-09-08:
    «desde los botones de lámina de abajo con el menú del mouse las
    opciones de copiar, duplicar, eliminar lámina o cambiar nombre»)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QMessageBox
    from core.composition import Composicion, TextoItem
    win = _window(monkeypatch)
    try:
        scene = win.viewport.scene
        planta = Composicion(name="Planta")
        planta.texts.append(TextoItem(text="hola"))
        scene.compositions.append(planta)
        scene.compositions.append(Composicion(name="Cortes"))
        win._update_title()
        # the strip hands the sheet index and a position to the owner
        seen = []
        tabs = win._sheet_tabs
        monkeypatch.setattr(tabs, "_on_menu", lambda i, pos: seen.append(i))
        rect = tabs.tabRect(2)                            # «Cortes»
        tabs.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Mouse, rect.center(), tabs.mapToGlobal(rect.center())))
        assert seen == [1]
        # the operations, through the composer (created, never shown)
        comp = win._ensure_composer()
        assert not comp.isVisible()
        comp.rename_sheet(0, "Planta general")
        assert scene.compositions[0].name == "Planta general"
        assert tabs.names() == ["Model", "Planta general", "Cortes"]
        comp.duplicate_sheet(0)
        assert [c.name for c in scene.compositions] == [
            "Planta general", "Planta general (copy)", "Cortes"]
        assert scene.compositions[1].texts[0].text == "hola"
        assert scene.compositions[1] is not scene.compositions[0]
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Yes))
        told = []
        monkeypatch.setattr(QMessageBox, "information",
                            staticmethod(lambda *a, **k: told.append(a[2])))
        assert comp.delete_sheet(1, win)
        assert [c.name for c in scene.compositions] == ["Planta general", "Cortes"]
        assert tabs.names() == ["Model", "Planta general", "Cortes"]
        # the last sheet stays
        comp.delete_sheet(0, win)
        assert not comp.delete_sheet(0, win)             # refused, told why
        assert len(scene.compositions) == 1 and told
    finally:
        _close(win)
