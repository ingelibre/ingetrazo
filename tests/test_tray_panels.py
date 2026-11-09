# SPDX-License-Identifier: GPL-3.0-or-later
"""Side-tray tabs the user can hide and bring back (Marco, 29-09: «cuando
tenga demasiadas pestañas… configurar para no mostrar, solo cuando el
usuario lo requiera»), and the «AI» tab the assistant and the MCP bridge
share."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QTabBar


@pytest.fixture
def win():
    QApplication.instance() or QApplication([])
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _dock(win, name):
    return next(d for d in win._sidebar_docks() if d.objectName() == name)


def _ext_action(win, text):
    ext = win._ext_menu
    return next(a for a in ext.actions() if a.text() == text)


def test_the_panels_menu_lists_every_tray_tab_extensions_included(win):
    win._fill_panels_menu(win._panels_menu)
    titles = [a.text() for a in win._panels_menu.actions() if a.isCheckable()]
    assert titles == [d.windowTitle() for d in win._sidebar_docks()]
    names = {d.objectName() for d in win._sidebar_docks()}
    assert {"tray_properties", "tray_bim", "tray_georef",
            "extension_ai", "extension_render_blender"} <= names


def test_hiding_a_tab_is_remembered_and_the_next_window_keeps_it_away(win):
    from views.main_window import MainWindow
    bim = _dock(win, "tray_bim")
    win.set_tray_shown(bim, False)
    assert bim.isHidden()
    assert "tray_bim" in win._hidden_tray_names(QSettings())
    other = MainWindow()
    try:
        assert _dock(other, "tray_bim").isHidden()
        assert not _dock(other, "tray_properties").isHidden()
    finally:
        other._saved_version = other.viewport.scene.version
        other.close()
    win._show_all_trays()
    assert not bim.isHidden()
    assert "tray_bim" not in win._hidden_tray_names(QSettings())


def test_the_menu_entry_hides_and_shows_its_tab(win):
    menu = win._panels_menu
    win._fill_panels_menu(menu)
    render = _dock(win, "extension_render_blender")
    act = next(a for a in menu.actions() if a.text() == render.windowTitle())
    assert act.isChecked()
    act.trigger()
    assert render.isHidden()
    win._fill_panels_menu(menu)
    act = next(a for a in menu.actions() if a.text() == render.windowTitle())
    assert not act.isChecked()
    act.trigger()
    assert not render.isHidden()


def test_asking_for_a_tab_unfolds_a_folded_sidebar(win):
    ai = _dock(win, "extension_ai")
    win._act_sidebar.setChecked(False)              # Ctrl+F5: the right side
    from PySide6.QtCore import Qt
    assert all(d.isHidden() for d in win._sidebar_docks()
               if win.dockWidgetArea(d) != Qt.LeftDockWidgetArea)
    win.set_tray_shown(ai, True)
    assert win._act_sidebar.isChecked()
    assert not ai.isHidden()


def test_the_assistant_and_the_bridge_share_one_ai_tab(win):
    from PySide6.QtWidgets import QWidget
    # Plugins load by path, so match the classes by name.
    def having(dock, cls):
        return [w for w in dock.findChildren(QWidget)
                if type(w).__name__ == cls]
    ai = _dock(win, "extension_ai")
    assert having(ai, "AsistentePanel") and having(ai, "BridgeSection")
    assert sum(1 for d in win._sidebar_docks()
               if having(d, "AsistentePanel")) == 1
    assert win._ai_assistant in having(ai, "AsistentePanel")


def test_ctrl_shift_a_brings_back_a_hidden_ai_tab(win):
    ai = _dock(win, "extension_ai")
    win.set_tray_shown(ai, False)
    act = _ext_action(win, "AI Assistant")
    assert act.shortcut().toString() == "Ctrl+Shift+A"
    act.trigger()
    assert not ai.isHidden()
    assert "extension_ai" not in win._hidden_tray_names(QSettings())


def test_the_bridge_section_starts_and_stops(win, monkeypatch):
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    section = win._ai_bridge_section
    assert not section.running
    assert section._text.isHidden()
    _ext_action(win, "AI Bridge (MCP)").trigger()
    try:
        assert section.running
        assert section.section.header.isChecked()
        port = win._ai_bridge.port
        assert f"127.0.0.1:{port}" in section._text.toPlainText()
        assert not section._text.isHidden()
    finally:
        section.stop()
    assert not section.running
    assert section._text.isHidden()


def test_a_right_click_on_the_tray_tabs_is_recognised(win):
    win.resize(1200, 800)
    win.show()
    QApplication.processEvents()
    bars = [b for b in win.findChildren(QTabBar)
            if b.isVisible() and b.count() >= 3
            and win.rect().contains(b.mapTo(win, b.rect().center()))]
    assert bars, "the side trays are tabbed"
    bar = bars[0]
    pos = bar.mapTo(win, bar.tabRect(0).center())
    assert win._tray_tab_bar_at(pos)
    vp_pos = win.viewport.mapTo(win, win.viewport.rect().center())
    assert not win._tray_tab_bar_at(vp_pos)


def test_the_prompt_takes_several_lines_and_enter_sends(win):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    panel = win._ai_assistant
    box = panel._input
    sent = []
    box.submitted.disconnect(panel._on_send)       # no model to talk to
    box.submitted.connect(lambda: sent.append(box.text()))
    box.setText("una casa")
    box.moveCursor(box.textCursor().MoveOperation.End)
    shift = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier)
    box.keyPressEvent(shift)
    box.insertPlainText("con techo a dos aguas")
    assert box.text() == "una casa\ncon techo a dos aguas" and not sent
    box.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                                Qt.NoModifier))
    assert sent == ["una casa\ncon techo a dos aguas"]
    assert box.minimumHeight() >= 2 * box.fontMetrics().lineSpacing()


def test_a_tab_saved_floating_comes_back_among_the_tabs(win):
    # Floating tabs were tried and dropped (Marco, 29-09): a layout saved
    # while one floated must not leave it loose — nor can a tab float now.
    from PySide6.QtWidgets import QDockWidget
    from views.main_window import MainWindow
    win.resize(1300, 850)
    win.show()
    QApplication.processEvents()
    ai = _dock(win, "extension_ai")
    assert not ai.features() & QDockWidget.DockWidgetFloatable
    ai.setFeatures(ai.features() | QDockWidget.DockWidgetFloatable)
    ai.setFloating(True)                   # as the reverted feature left it
    QApplication.processEvents()
    win._saved_version = win.viewport.scene.version
    win.close()                            # the layout is saved floating
    again = MainWindow()
    try:
        again.resize(1300, 850)
        again.show()
        QApplication.processEvents()
        back = _dock(again, "extension_ai")
        assert not back.isFloating()
        assert back in again.tabifiedDockWidgets(again.tray)
        assert back.titleBarWidget() is not None
    finally:
        again._saved_version = again.viewport.scene.version
        again.close()
