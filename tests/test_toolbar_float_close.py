# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A floating toolbar looks like a small window — a title strip on top
with a × that closes it where it is (2026-10-16: «cuando dejo flotante
una barra de herramientas no tengo la opción de cruz de cerrarlo», then
«que se vea más como una ventana, con la cruz arriba»); docked, it has
neither. Any toolbar the window gets — later ones and a plugin's plain
QToolBar too («que sea aplicable a futuras barras y plugins»)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QToolBar,
                               QToolButton, QWidget)

_app = QApplication.instance() or QApplication([])


def _floating_state(win: QMainWindow, tb: QToolBar) -> QByteArray:
    """``win``'s saved layout with ``tb`` marked floating — what Qt keeps
    for a bar the user tore off. A drag cannot be replayed offscreen, but
    restoring this floats the bar the way Qt itself does (topLevelChanged
    and all). Each toolbar entry is: name, shown byte, pos, size, then two
    packed geometry words whose low bit says «floating»."""
    state = bytearray(bytes(win.saveState()))
    name = tb.objectName().encode("utf-16-be")
    entry = len(name).to_bytes(4, "big") + name
    at = state.find(entry)
    assert at >= 0, "toolbar not in the saved state"
    geom0 = at + len(entry) + 1 + 4 + 4
    state[geom0:geom0 + 8] = (0x00320065).to_bytes(4, "big") \
        + (0x00640020).to_bytes(4, "big")
    return QByteArray(bytes(state))


def _float(win: QMainWindow, tb: QToolBar) -> None:
    assert win.restoreState(_floating_state(win, tb))
    for _ in range(3):
        _app.processEvents()
    assert tb.isFloating()


def _close_button(tb: QToolBar) -> QToolButton:
    btn = tb.findChild(QToolButton, "float_close_button")
    assert btn is not None, "the toolbar has no close button"
    return btn


def _strip(tb: QToolBar):
    strip = tb.findChild(QWidget, "float_title_bar")
    assert strip is not None, "the toolbar has no title strip"
    return strip


def _title_rect(tb: QToolBar):
    strip = _strip(tb)
    return strip.geometry() if strip.isVisibleTo(tb) else QRect()


@pytest.fixture
def bare():
    """A window watching its toolbars, and a plain toolbar it gets after —
    the way a plugin adds one."""
    from views.floating_toolbar import watch_toolbars
    win = QMainWindow()
    win.setCentralWidget(QLabel("model"))
    win.resize(600, 400)
    watch_toolbars(win)
    tb = QToolBar("Draw")
    tb.setObjectName("draw_toolbar")
    tb.addAction("Line")
    win.addToolBar(Qt.TopToolBarArea, tb)
    win.show()
    _app.processEvents()
    yield win, tb
    win.close()


def test_docked_bar_has_no_title_strip_nor_close_button(bare):
    _win, tb = bare
    assert not tb.isFloating()
    assert _title_rect(tb).isEmpty()
    assert not _close_button(tb).isVisibleTo(tb)


def test_a_bar_already_there_before_watching_gets_it_too():
    from views.floating_toolbar import watch_toolbars
    win = QMainWindow()
    try:
        tb = QToolBar("Old", win)
        tb.setObjectName("old_toolbar")
        win.addToolBar(tb)
        watch_toolbars(win)
        _close_button(tb)
        watch_toolbars(win)            # twice: still one strip
        assert len(tb.findChildren(QWidget, "float_title_bar")) == 1
    finally:
        win.close()


def test_the_strip_shows_the_bar_name(bare):
    win, tb = bare
    _float(win, tb)
    label = _strip(tb).findChild(QLabel, "float_title_label")
    assert label.text() == "Draw"
    tb.setWindowTitle("Drawing")
    assert label.text() == "Drawing"


def test_floating_bar_has_a_title_strip_with_the_close_button_on_top(bare):
    win, tb = bare
    _float(win, tb)
    strip = _title_rect(tb)
    assert strip.height() > 0 and strip.width() == tb.width()
    btn = _close_button(tb)
    assert btn.isVisibleTo(tb)
    # top-right corner, the strip's whole height — a window's ×
    box = QRect(btn.mapTo(tb, QPoint(0, 0)), btn.size())
    assert box.top() == 0
    assert box.right() == tb.width() - 1
    assert box.bottom() == strip.bottom()
    assert btn.toolTip()


def test_the_buttons_sit_under_the_strip_even_when_tools_are_added(bare):
    win, tb = bare
    _float(win, tb)
    tb.addAction("Arc")                 # a tool added while floating
    for _ in range(3):
        _app.processEvents()
    tb.resize(tb.sizeHint())
    _app.processEvents()
    strip = _title_rect(tb)
    for act in tb.actions():
        w = tb.widgetForAction(act)
        assert w.geometry().top() > strip.bottom(), act.text()
        assert w.geometry().bottom() < tb.height()


def test_the_close_button_hides_the_bar_and_unticks_its_menu_entry(bare):
    win, tb = bare
    docked = win.saveState()
    _float(win, tb)
    assert tb.isVisible() and tb.toggleViewAction().isChecked()
    _close_button(tb).click()
    assert not tb.isVisible()
    assert not tb.toggleViewAction().isChecked()
    # …and the menu brings it back
    tb.toggleViewAction().trigger()
    assert tb.isVisible()
    win.restoreState(docked)
    _app.processEvents()
    assert not tb.isFloating()
    assert _title_rect(tb).isEmpty()
    assert not _close_button(tb).isVisibleTo(tb)


def test_a_closed_floating_bar_docked_again_loses_the_strip(bare):
    """Closed while floating, then put back in a dock — Window ▸ Restore
    default toolbars does it — the bar came back docked still wearing the
    strip: hidden, Qt docks it without saying topLevelChanged."""
    win, tb = bare
    _float(win, tb)
    _close_button(tb).click()
    win.removeToolBar(tb)
    win.addToolBar(Qt.TopToolBarArea, tb)
    tb.show()
    _app.processEvents()
    assert not tb.isFloating()
    assert _title_rect(tb).isEmpty()
    assert tb.contentsMargins().top() == 0


def _drag(target: QWidget, start: QPoint, end: QPoint, steps: int = 30):
    """Press at ``start`` (global) on ``target``, move to ``end``, release:
    each event goes to whoever has the mouse now — Qt's toolbar drag grabs
    it on the way."""
    def send(kind, at, btns):
        w = QWidget.mouseGrabber() or target
        QApplication.sendEvent(w, QMouseEvent(
            kind, QPointF(w.mapFromGlobal(at)), QPointF(at),
            Qt.LeftButton, btns, Qt.NoModifier))
        _app.processEvents()
    send(QEvent.MouseButtonPress, start, Qt.LeftButton)
    for i in range(1, steps + 1):
        send(QEvent.MouseMove, start + (end - start) * (i / steps),
             Qt.LeftButton)
    send(QEvent.MouseButtonRelease, end, Qt.NoButton)
    for _ in range(10):
        _app.processEvents()


def _grip_point(tb: QToolBar) -> QPoint:
    from PySide6.QtWidgets import QStyle, QStyleOptionToolBar
    opt = QStyleOptionToolBar()
    tb.initStyleOption(opt)
    grip = tb.style().subElementRect(QStyle.SE_ToolBarHandle, opt, tb)
    return tb.mapToGlobal(grip.center())


@pytest.fixture
def row():
    """A real row of three bars, torn off with a real drag of the middle
    one's grip (no animation: the dock lands at once)."""
    from views.floating_toolbar import watch_toolbars
    win = QMainWindow()
    win.setCentralWidget(QLabel("model"))
    win.resize(900, 500)
    win.move(0, 0)
    win.setAnimated(False)
    watch_toolbars(win)
    bars = []
    for name in ("first", "middle", "last"):
        tb = QToolBar(name)
        tb.setObjectName(name)
        for i in range(3):
            tb.addAction(f"{name} {i}")
        win.addToolBar(Qt.TopToolBarArea, tb)
        bars.append(tb)
    win.show()
    _app.processEvents()
    tb = bars[1]
    home = tb.geometry()
    g = _grip_point(tb)
    _drag(tb, g, g + QPoint(0, 220))
    assert tb.isFloating()
    yield win, tb, home
    win.close()


def test_the_strip_shows_the_move_cursor(row):
    _win, tb, _home = row
    assert _strip(tb).cursor().shape() == Qt.SizeAllCursor
    assert _close_button(tb).cursor().shape() == Qt.PointingHandCursor


def test_dragging_the_strip_moves_the_bar_without_a_jump(row):
    _win, tb, _home = row
    strip = _strip(tb)
    start_pos = tb.pos()
    grab = strip.mapToGlobal(QPoint(strip.width() // 2, strip.height() // 2))
    _drag(strip, grab, grab + QPoint(40, 30))
    assert tb.isFloating()
    assert tb.pos() == start_pos + QPoint(40, 30)


def test_dragging_the_strip_docks_the_bar(row):
    win, tb, home = row
    strip = _strip(tb)
    grab = strip.mapToGlobal(QPoint(strip.width() // 2, strip.height() // 2))
    # back where it came from, between the other two
    _drag(strip, grab, win.mapToGlobal(home.topLeft() + QPoint(4, 12)))
    assert not tb.isFloating()
    assert win.toolBarArea(tb) == Qt.TopToolBarArea
    assert tb.geometry() == home
    assert _title_rect(tb).isEmpty()


def test_the_drawn_grip_does_not_grow(row):
    """Only the press the strip passes on sees the whole bar as grip."""
    _win, tb, _home = row
    from PySide6.QtWidgets import QStyle, QStyleOptionToolBar
    opt = QStyleOptionToolBar()
    tb.initStyleOption(opt)
    grip = tb.style().subElementRect(QStyle.SE_ToolBarHandle, opt, tb)
    assert grip.width() < tb.width() // 2


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    return path


def test_every_toolbar_of_the_model_window_floats_as_a_window(settings_file):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        _app.processEvents()
        bars = [tb for tb in win.findChildren(QToolBar)
                if tb.parent() is win]
        assert bars
        for tb in bars:
            _close_button(tb)
        tb = win.toolbars["draw"] if "draw" in win.toolbars else bars[0]
        _float(win, tb)
        assert _close_button(tb).isVisibleTo(tb)
        _close_button(tb).click()
        assert not tb.isVisible()
        # A plugin's own bar, added once the window is up (as faceup does)
        plug = QToolBar("Plugin tools")
        plug.setObjectName("plugin_test_toolbar")
        plug.addAction("Do it")
        win.addToolBar(Qt.TopToolBarArea, plug)
        plug.show()
        _app.processEvents()
        _float(win, plug)
        assert _close_button(plug).isVisibleTo(plug)
        assert _title_rect(plug).height() > 0
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_every_toolbar_of_the_composer_floats_as_a_window(settings_file, monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    try:
        comp = ComposerWindow(win)
        try:
            comp.show()
            _app.processEvents()
            bars = [tb for tb in comp.findChildren(QToolBar)
                    if tb.parent() is comp and tb.isVisible()]
            assert len(bars) >= 3
            for tb in bars:
                _close_button(tb)
        finally:
            comp.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
