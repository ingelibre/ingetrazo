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
        # The model window goes model ↔ ONE sheet (the last opened; the
        # first before any): all the sheets are tabs in the composer.
        assert tabs.names() == ["Model", "Planta"]
        assert tabs.plus_index() is None
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
        win._sheet_tabs.click(1)                         # «Planta», the first
        comp = win._composer
        assert comp.isVisible()
        assert comp.comp is win.viewport.scene.compositions[0]
        # the composer's strip lists every sheet and marks its own
        assert comp._sheet_tabs.names() == ["Model", "Planta", "Cortes"]
        assert comp._sheet_tabs.current() == 0
        assert win._sheet_tabs.current() is None
        comp._sheet_tabs.click(2)                        # «Cortes», from the composer
        assert comp.comp is win.viewport.scene.compositions[1]
        assert comp._sheet_tabs.current() == 1
        # …and the model window now offers «Cortes» to go back to.
        assert win._sheet_tabs.names() == ["Model", "Cortes"]
    finally:
        _close(win)


def test_both_strips_follow_added_renamed_and_deleted_sheets(monkeypatch):
    win = _window(monkeypatch)
    try:
        win._sheet_tabs.click(1)                         # the default sheet
        comp = win._composer
        n0 = len(win.viewport.scene.compositions)
        comp._on_comp_add()
        assert len(comp._sheet_tabs.names()) == n0 + 2   # Model + sheets
        assert len(win._sheet_tabs.names()) == 2         # Model + the open one
        assert comp._sheet_tabs.current() == n0          # the new one is open
        comp.comp_combo.setEditText("Detalles")
        comp._on_comp_rename()
        assert win._sheet_tabs.names()[-1] == "Detalles"
        assert comp._sheet_tabs.names()[-1] == "Detalles"
        monkeypatch.setattr("views.composer.QMessageBox.question",
                            lambda *a, **k: __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.Yes)
        comp._on_comp_del()
        assert len(comp._sheet_tabs.names()) == n0 + 1
        assert len(win._sheet_tabs.names()) == 2
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
        # The standing hint is one line per tool now; a long one (a wordy
        # translation, a long flash) must still never widen the window.
        long_hint = "Select objects. " * 12
        # The window's own hint refresh (a timer) would put the real hint
        # back over this stand-in mid-test — the flake this test had.
        win._update_status_hint = lambda: None
        bar.showMessage(long_hint)
        assert len(bar.currentMessage()) > 100
        # a plain QLabel with this hint asked for ~2200 px; the app's own
        # floor (toolbars, docks) is under 1000 on the offscreen platform
        assert win.minimumSizeHint().width() < 1000
        win.resize(700, 500)
        _app.processEvents()
        assert win.width() < 1000                       # it shrank
        assert bar.currentMessage() == long_hint        # full text kept
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
    """The hand-over never guesses (Wayland may refuse to raise a
    window): overlapping, the composer hides at once; side by side it
    stays; a sheet tab brings it back as it was."""
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
        # (the model window's strip shows one sheet: «Planta», the first)
        rect = tabs.tabRect(1)
        tabs.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Mouse, rect.center(), tabs.mapToGlobal(rect.center())))
        assert seen == [0]
        # the operations, through the composer (created, never shown)
        comp = win._ensure_composer()
        assert not comp.isVisible()
        comp.rename_sheet(0, "Planta general")
        assert scene.compositions[0].name == "Planta general"
        assert tabs.names() == ["Model", "Planta general"]
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
        assert tabs.names() == ["Model", "Planta general"]
        # the last sheet stays
        comp.delete_sheet(0, win)
        assert not comp.delete_sheet(0, win)             # refused, told why
        assert len(scene.compositions) == 1 and told
    finally:
        _close(win)


def test_many_sheets_scroll_within_a_width_budget():
    """Past its budget the strip keeps every tab and shows QTabBar's ◀ ▶
    scroll buttons, so the hint keeps its room (Marco, 23-09: he preferred
    this to folding the tabs into a menu); the logical API — names,
    current, click — does not change."""
    from PySide6.QtCore import Qt
    from views.sheet_tabs import SheetTabs
    seen = []
    tabs = SheetTabs(None, lambda: seen.append("model"),
                     lambda i: seen.append(i), lambda: seen.append("new"))
    names = [f"Lámina {i}" for i in range(1, 9)]
    tabs.refresh(names, 2)
    tabs.set_budget(250)
    assert tabs.count() == 1 + len(names) + 1          # every tab kept
    assert tabs.maximumWidth() == 250
    assert tabs.usesScrollButtons()
    assert tabs.elideMode() == Qt.ElideNone             # scroll, not squeeze
    assert tabs.names() == ["Model"] + names
    assert tabs.current() == 2
    tabs.click(5)                                       # «Lámina 5»
    assert seen == [4]


def test_the_model_window_returns_to_the_last_sheet(monkeypatch):
    """Sheet 2 → Model → the sheet tab brings back sheet 2 (Marco, 23-09)."""
    win = _window(monkeypatch)
    try:
        from core.composition import Composicion
        for name in ("Planta", "Cortes", "Detalles"):
            win.viewport.scene.compositions.append(Composicion(name=name))
        win._update_title()
        win._sheet_tabs.click(1)                         # into the composer
        comp = win._composer
        comp._sheet_tabs.click(2)                        # «Cortes»
        comp._sheet_tabs.click(0)                        # back to the model
        assert win._sheet_tabs.names() == ["Model", "Cortes"]
        win._sheet_tabs.click(1)                         # the sheet tab again
        assert comp.comp is win.viewport.scene.compositions[1]
    finally:
        _close(win)


# ---- #1184: the strip takes the free width, arrows only when it must --------

def _settle(ms=40):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _arrows(tabs):
    from PySide6.QtWidgets import QToolButton
    return [b for b in tabs.findChildren(QToolButton) if b.isVisible()]


def _composer_with(win, count):
    from core.composition import Composicion
    win.viewport.scene.compositions[:] = [
        Composicion(name=f"L-{i + 1:02d} Planta de trazo general")
        for i in range(count)]
    win._update_title()
    if getattr(win, "_composer", None) is None:
        win._sheet_tabs.click(1)
    comp = win._composer
    comp._refresh_sheet_tabs()
    comp.show_sheet(0)
    return comp


def _assert_right_end_untouched(comp):
    bar = comp.statusBar()
    assert bar.tabs.geometry().right() < bar._msg.x()
    for w in (comp.auto_check, comp._pos_label, comp._zoom_combo):
        assert w.width() >= w.sizeHint().width()
        assert bar._msg.geometry().right() < w.x()
        assert w.geometry().right() < bar.width()


def test_five_sheets_on_a_wide_bar_show_whole_without_arrows(monkeypatch):
    """The strip had a fixed share of the bar: 2,5 tabs and arrows with
    500 px free beside them (Marco, #1184)."""
    win = _window(monkeypatch)
    try:
        comp = _composer_with(win, 5)
        comp.show()
        comp.resize(1920, 900)
        _settle()
        comp.statusBar().showMessage("Select objects. " * 12)
        _settle()
        tabs = comp._sheet_tabs
        assert tabs.width() == tabs.sizeHint().width()
        assert not _arrows(tabs)
        _assert_right_end_untouched(comp)
    finally:
        _close(win)


@pytest.mark.parametrize("width", [1920, 1366])
def test_many_sheets_scroll_and_leave_the_hint_a_useful_stub(monkeypatch, width):
    win = _window(monkeypatch)
    try:
        comp = _composer_with(win, 30)
        comp.show()
        comp.resize(width, 900)
        _settle()
        bar = comp.statusBar()
        bar.showMessage("Select objects. " * 12)
        _settle()
        tabs = comp._sheet_tabs
        assert _arrows(tabs)                         # the arrows stay
        assert tabs.width() > width * 0.3            # ... past the old share
        chars = bar._msg.width() / bar._msg.fontMetrics().averageCharWidth()
        assert chars >= 40                           # the hint still reads
        _assert_right_end_untouched(comp)
        assert tabs.x() < 20                         # glued to the left
        comp.show_sheet(24)                          # the marked tab is in view
        _settle()
        rect = tabs.tabRect(tabs.currentIndex())
        assert rect.left() >= 0 and rect.right() <= tabs.width()
    finally:
        _close(win)


def test_the_budget_follows_a_resize_and_a_rename(monkeypatch):
    win = _window(monkeypatch)
    try:
        comp = _composer_with(win, 5)
        comp.show()
        comp.resize(1920, 900)
        _settle()
        tabs = comp._sheet_tabs
        assert not _arrows(tabs)
        comp.resize(1100, 900)                       # narrower: they scroll
        _settle()
        assert _arrows(tabs)
        _assert_right_end_untouched(comp)
        comp.resize(1920, 900)                       # wider: the arrows go
        _settle()
        assert not _arrows(tabs)
        assert tabs.width() == tabs.sizeHint().width()
        # Long names eat the room with no resize at all ...
        comp.resize(1100, 900)
        sheets = win.viewport.scene.compositions
        long_names = [s.name for s in sheets]
        for i, s in enumerate(sheets):
            s.name = f"L{i}"
        comp._refresh_sheet_tabs()
        _settle()
        assert not _arrows(tabs)
        for s, name in zip(sheets, long_names):
            s.name = name
        comp._refresh_sheet_tabs()
        _settle()
        assert _arrows(tabs)
        _assert_right_end_untouched(comp)
        for i, s in enumerate(sheets):               # ... and give it back
            s.name = f"L{i}"
        comp._refresh_sheet_tabs()
        _settle()
        assert not _arrows(tabs)
    finally:
        _close(win)


def test_a_new_sheet_while_the_composer_is_hidden_is_not_squeezed(monkeypatch):
    """A hidden QTabBar does not announce its new size: the composer came up
    with the arrows on three short tabs."""
    win = _window(monkeypatch)
    try:
        comp = _composer_with(win, 1)
        comp.hide()
        _settle()
        win._sheet_tabs.click(1)
        comp.show_sheet(0)
        comp.show()
        comp.resize(1920, 900)
        _settle()
        assert comp._sheet_tabs.width() == comp._sheet_tabs.sizeHint().width()
        assert not _arrows(comp._sheet_tabs)
    finally:
        _close(win)


@pytest.mark.parametrize("width", [1920, 1366])
def test_the_main_window_keeps_its_two_tabs_and_its_long_hint(monkeypatch, width):
    win = _window(monkeypatch)
    try:
        _composer_with(win, 30)
        win._composer.hide()
        win._update_status_hint = lambda: None
        win.show()
        win.resize(width, 900)
        _settle()
        bar = win.statusBar()
        bar.showMessage("Select objects. " * 12)
        _settle()
        tabs = win._sheet_tabs
        assert len(tabs.names()) == 2
        assert tabs.width() == tabs.sizeHint().width()
        assert not _arrows(tabs)
        assert bar._msg.width() >= int(width * bar.MESSAGE_SHARE) - 1
        assert bar._msg.x() + bar._msg.width() <= width
    finally:
        _close(win)


# ---- #1184: a very long name is cut on its tab, and only there --------------

_LONG = ("Planta de arquitectura general", "Cortes y elevaciones del bloque",
         "Instalaciones sanitarias nivel", "Estructuras de cimentacion gen",
         "Detalles constructivos de obra")


def _strip(names, current=None):
    from views.sheet_tabs import SheetTabs
    tabs = SheetTabs(None, lambda: None, lambda i: None, lambda: None)
    tabs.refresh(names, current)
    return tabs


def test_a_long_name_is_cut_on_its_tab_and_whole_everywhere_else():
    from PySide6.QtCore import Qt
    tabs = _strip([_LONG[0], "Planta"])
    assert tabs.elideMode() == Qt.ElideNone             # never squeezed by Qt
    assert tabs.names() == ["Model", _LONG[0], "Planta"]
    cut = tabs.tabText(1)
    assert cut.endswith("…") and _LONG[0].startswith(cut[:-1])
    assert _LONG[0] in tabs.tabToolTip(1)
    assert tabs.tabText(2) == "Planta"                  # a short one as it is
    assert "Planta" not in tabs.tabToolTip(2)
    assert tabs.tabText(0) == "Model"


def test_a_name_that_fits_is_not_cut():
    from views.sheet_tabs import SheetTabs
    tabs = _strip(["x"])
    room = SheetTabs.LABEL_MAX_CHARS * tabs.fontMetrics().averageCharWidth()
    name = "i"
    while tabs.fontMetrics().horizontalAdvance(name + "ii") < room:
        name += "i"
    tabs.refresh([name], None)
    assert tabs.tabText(1) == name


def test_two_names_cut_alike_keep_their_own_tooltip():
    """What the tab reads did not change, the name did: a rebuild decided
    on the text shown left the old name in the tooltip."""
    a, b = _LONG[0] + " A", _LONG[0] + " B"
    tabs = _strip([a])
    text = tabs.tabText(1)
    tabs.refresh([b], None)
    assert tabs.tabText(1) == text
    assert b in tabs.tabToolTip(1) and a not in tabs.tabToolTip(1)
    assert tabs.names() == ["Model", b]


@pytest.mark.parametrize("budget", [120, 250, 600])
def test_a_tight_budget_scrolls_and_never_squeezes_a_name(budget):
    """However little room there is: the arrows, not «L…»."""
    tabs = _strip(list(_LONG))
    tabs.set_budget(budget)
    tabs.show()
    _settle()
    for i in range(1, 1 + len(_LONG)):
        assert tabs.tabRect(i).width() == tabs.tabSizeHint(i).width()
        assert len(tabs.tabText(i)) >= 15
        assert tabs.fontMetrics().horizontalAdvance(tabs.tabText(i)) \
            <= tabs.tabRect(i).width()
    tabs.close()


def test_five_long_names_fit_at_the_laptops_width_and_model_stays(monkeypatch):
    """Marco's screen, 1536 logical px, at the tests' 9 pt font: going to
    the last sheet scrolled «Model» out with room to spare."""
    win = _window(monkeypatch)
    try:
        from core.composition import Composicion
        win.viewport.scene.compositions[:] = [
            Composicion(name=n) for n in _LONG]
        win._update_title()
        win._sheet_tabs.click(1)
        comp = win._composer
        comp.show()
        comp.resize(1536, 800)
        _settle()
        comp.show_sheet(4)
        _settle()
        tabs = comp._sheet_tabs
        assert tabs.names() == ["Model", *_LONG]
        assert not _arrows(tabs)
        assert tabs.tabRect(0).left() == 0              # «Model» in view
        last = tabs.tabRect(tabs.currentIndex())
        assert last.right() <= tabs.width()
        _assert_right_end_untouched(comp)
        chars = comp.statusBar()._msg.width() \
            / comp.statusBar()._msg.fontMetrics().averageCharWidth()
        assert chars >= 40                              # the hint's room stays
    finally:
        _close(win)

