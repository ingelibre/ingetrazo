# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ctrl+0 (clean screen) hides every bar and the menu bar; the commands
must keep answering all the same: the tools' keys (L for Line…), F3, the
measures typed into the value box — and the status bar, with the tool's
hint and that box, stays in sight."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A throwaway INI for every QSettings() the windows open."""
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def _settle():
    for _ in range(3):
        _app.processEvents()


@pytest.fixture
def win(settings_file):
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    _settle()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _press(win, key):
    win.viewport.setFocus()
    QTest.keyClick(win.viewport, key)
    _settle()
    return win._tool_key(win.viewport.active_tool)


def _clean(win, on=True):
    win._act_clean_screen.setChecked(on)
    _settle()


def test_tool_keys_still_pick_the_tool_in_clean_screen(win):
    """Before the fix L, R, M… did nothing once Ctrl+0 had hidden the
    bars: a shortcut only fires while a widget holding it is visible."""
    _clean(win)
    assert not any(tb.isVisible() for tb in win.findChildren(QToolBar))
    assert _press(win, Qt.Key_L) == "line"
    QTest.keyClick(win.viewport, Qt.Key_Escape)
    assert _press(win, Qt.Key_R) == "rectangle"


def test_every_tool_shortcut_is_live_in_clean_screen(win):
    """All of them, not a hand-made list: each tool action with a key is
    carried by a widget that stays visible."""
    _clean(win)
    dead = []
    for key, act in win._tool_actions.items():
        if not act.shortcuts():
            continue
        if not any(w.isVisible() for w in act.associatedObjects()
                   if hasattr(w, "isVisible")):
            dead.append(key)
    assert dead == []


def test_the_status_bar_stays_with_hint_and_value_box(win):
    _clean(win)
    bar = win.statusBar()
    assert bar.isVisible()
    assert not win.menuBar().isVisible()
    assert _press(win, Qt.Key_L) == "line"
    assert win.status_hint                       # the tool's hint is there
    assert win._vcb_value.isVisible()           # and the value box
    _clean(win, False)
    assert bar.isVisible() and win.menuBar().isVisible()


def test_f3_opens_the_command_search_in_clean_screen(win):
    _clean(win)
    win.viewport.setFocus()
    QTest.keyClick(win.viewport, Qt.Key_F3)
    _settle()
    box = getattr(win, "_command_search", None)
    assert box is not None and box.isVisible()
    box.hide()


def test_leaving_clean_screen_gives_the_window_its_own_actions_back(win):
    before = list(win.actions())
    _clean(win)
    assert len(win.actions()) > len(before)
    _clean(win, False)
    assert win.actions() == before
    # Twice in a row: nothing piles up.
    _clean(win)
    _clean(win, False)
    assert win.actions() == before
    assert _press(win, Qt.Key_L) == "line"       # the bars answer again


def test_a_plugin_toolbar_key_works_in_clean_screen(win):
    """Bars added later (plugins) are picked up the same way."""
    hits = []
    tb = win.addToolBar("plugin_bar")
    act = QAction("Plugin thing", win)
    act.setShortcut(QKeySequence("Ctrl+Alt+Shift+J"))
    act.triggered.connect(lambda: hits.append(1))
    tb.addAction(act)
    _settle()
    _clean(win)
    win.viewport.setFocus()
    QTest.keyClick(win.viewport, Qt.Key_J,
                   Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
    _settle()
    assert hits == [1]


def test_two_hidden_actions_on_one_key_do_not_cancel_each_other(win):
    """Qt fires neither of two live actions on one key; only the first
    hidden one is carried to the window."""
    hits = []
    for name in ("first", "second"):
        tb = win.addToolBar(name)
        act = QAction(name, win)
        act.setShortcut(QKeySequence("Ctrl+Alt+Shift+K"))
        act.triggered.connect(lambda _c=False, n=name: hits.append(n))
        tb.addAction(act)
    _settle()
    _clean(win)
    win.viewport.setFocus()
    QTest.keyClick(win.viewport, Qt.Key_K,
                   Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
    _settle()
    assert hits == ["first"]


def test_the_composer_keeps_its_status_bar_and_bar_keys(settings_file, monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    main = MainWindow()
    comp = ComposerWindow(main)
    main._composer = comp
    try:
        hits = []
        tb = comp.addToolBar("plugin_bar")
        act = QAction("Plugin thing", comp)
        act.setShortcut(QKeySequence("Ctrl+Alt+Shift+J"))
        act.triggered.connect(lambda: hits.append(1))
        tb.addAction(act)
        comp.resize(1200, 800)
        comp.show()
        _settle()
        before = list(comp.actions())
        comp._act_clean_screen.setChecked(True)
        _settle()
        assert comp.statusBar().isVisible()
        assert not tb.isVisible()
        comp._view.setFocus()
        QTest.keyClick(comp._view, Qt.Key_J,
                       Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        _settle()
        assert hits == [1]
        comp._act_clean_screen.setChecked(False)
        _settle()
        assert comp.actions() == before
    finally:
        comp.close()
        main._saved_version = main.viewport.scene.version
        main.close()


def _move_mouse(widget, x, y):
    """A mouse move over ``widget`` at (x, y), as the window system sends
    it (the button's watcher listens to the whole application)."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    local = QPointF(x, y)
    glob = QPointF(widget.mapToGlobal(local.toPoint()))
    ev = QMouseEvent(QEvent.MouseMove, local, glob, Qt.NoButton,
                     Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(widget, ev)
    _settle()


def _wait_fade(fader):
    """Let the fade timer run out (short, not the 3 s of real use)."""
    fader._timer.setInterval(30)
    if fader._timer.isActive():
        fader._timer.start()
    QTest.qWait(120)
    _settle()


def test_the_exit_button_goes_after_a_few_seconds(win):
    """Marco: «el botón salir de la pantalla limpia debería desaparecer
    después de unos segundos»."""
    from views.clean_screen import ExitButtonFader
    assert 2000 <= ExitButtonFader.HIDE_MS <= 5000
    _clean(win)
    btn, fader = win._clean_exit_btn, win._clean_exit_fader
    assert btn.isVisible() and fader._timer.isActive()
    _wait_fade(fader)
    assert not btn.isVisible()
    assert win._act_clean_screen.isChecked()     # still in clean screen


def test_the_exit_button_comes_back_near_its_corner(win):
    _clean(win)
    btn, fader = win._clean_exit_btn, win._clean_exit_fader
    _wait_fade(fader)
    area = win._doc_stack
    _move_mouse(win.viewport, 40, area.height() // 2)      # far from it
    assert not btn.isVisible()
    _move_mouse(win.viewport, win.viewport.width() - 30, 20)   # the corner
    assert btn.isVisible()
    assert btn.x() + btn.width() <= win.viewport.width() and btn.y() == 12
    # Resting there it stays; once the mouse leaves, it goes again.
    _wait_fade(fader)
    assert btn.isVisible()
    _move_mouse(win.viewport, 40, area.height() // 2)
    _wait_fade(fader)
    assert not btn.isVisible()
    # And a click on it still leaves clean screen.
    _move_mouse(win.viewport, win.viewport.width() - 30, 20)
    btn.click()
    _settle()
    assert not win._act_clean_screen.isChecked() and not btn.isVisible()


def test_leaving_clean_screen_stops_watching_the_mouse(win):
    _clean(win)
    fader = win._clean_exit_fader
    _clean(win, False)
    assert not fader._timer.isActive()
    _move_mouse(win.viewport, win.viewport.width() - 30, 20)
    assert not win._clean_exit_btn.isVisible()


def test_the_composer_exit_button_goes_and_comes_back(settings_file, monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    main = MainWindow()
    comp = ComposerWindow(main)
    main._composer = comp
    try:
        comp.resize(1200, 800)
        comp.show()
        _settle()
        comp._act_clean_screen.setChecked(True)
        _settle()
        btn, fader = comp._clean_exit_btn, comp._clean_exit_fader
        assert btn.isVisible()
        _wait_fade(fader)
        assert not btn.isVisible()
        view = comp._view
        _move_mouse(view.viewport(), view.viewport().width() - 30, 20)
        assert btn.isVisible()
        comp._act_clean_screen.setChecked(False)
        _settle()
        assert not btn.isVisible()
    finally:
        comp.close()
        main._saved_version = main.viewport.scene.version
        main.close()
