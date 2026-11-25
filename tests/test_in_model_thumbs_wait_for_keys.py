# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The «In model» pictures wait for the keys to rest too, not only the
mouse and the camera.

After a Rotate the hand goes to Ctrl+Z without moving the mouse: the
pictures of the rows the selection had scrolled into view were drawn at
that moment, inside the undo — the first Ctrl+Z after a Rotate on
Marco's plaza took ~0.33 s against ~0.22 s in 0.6.2.1 (20-11). A key over
the view (a menu shortcut reaches it as a ShortcutOverride) now holds
them back like a mouse move; every row on screen still gets its picture
once the hand rests. And a turn that has spent its budget leaves the
next picture for the next turn."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from views import component_thumbs
from views.viewport import _support

_app = QApplication.instance() or QApplication([])


def _component(i):
    m = Mesh()
    s = 1.0 + i * 0.01
    m.add_face([V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0)])
    g = Group(m, name=f"K{i:03d}")
    xf = QMatrix4x4()
    xf.translate(i * 2.0, 0.0, 0.0)
    g.xform = xf
    return g


def _visible_rows(lst):
    area = lst.viewport().rect()
    return [lst.item(i) for i in range(lst.count())
            if lst.visualItemRect(lst.item(i)).intersects(area)]


def _window(monkeypatch, drawn):
    from views.main_window import MainWindow
    real = component_thumbs._draw

    def spy(definition, size):
        drawn.append(definition.name)
        return real(definition, size)
    monkeypatch.setattr(component_thumbs, "_draw", spy)
    component_thumbs._cache.clear()
    win = MainWindow()
    win.show()
    monkeypatch.setattr(win.viewport, "view_busy", lambda: False)
    win.viewport.scene.groups.extend(_component(i) for i in range(40))
    panel = win.tray.components
    panel.refresh_in_model()
    timer = getattr(panel, "_in_model_timer", None)
    if timer is not None:
        timer.stop()
    panel._thumbs_timer.stop()
    drawn.clear()
    component_thumbs._cache.clear()
    lst = panel._in_model
    for i in range(lst.count()):
        lst.item(i).setData(Qt.UserRole + 2, None)
    return win, panel


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()
    component_thumbs._cache.clear()


def test_a_key_over_the_view_holds_the_pictures_back(monkeypatch):
    drawn = []
    win, panel = _window(monkeypatch, drawn)
    try:
        vp = win.viewport
        # Ctrl+Z, as a menu shortcut reaches the view.
        ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z,
                       Qt.ControlModifier, "z")
        QApplication.sendEvent(vp, ev)
        panel._thumbs_when_still()          # the timer's turn, right after
        assert drawn == [], "a picture landed inside the key's work"
        assert panel._thumbs_timer.isActive(), "they wait, not give up"
        panel._thumbs_timer.stop()
        # The hand rests: they come.
        _support.LAST_KEY[0] -= 10.0
        turns = 0
        while any(not r.data(Qt.UserRole + 2) for r in _visible_rows(
                panel._in_model)):
            assert turns < 200, "the pictures never all came"
            panel._thumbs_timer.stop()
            panel._thumbs_when_still()
            turns += 1
        assert drawn
    finally:
        _support.LAST_KEY[0] = 0.0
        _close(win)


def test_a_turn_past_its_budget_leaves_the_next_picture(monkeypatch):
    from views.tray import ComponentsPanel
    drawn = []
    win, panel = _window(monkeypatch, drawn)
    try:
        monkeypatch.setattr(ComponentsPanel, "THUMBS_BUDGET_S", 0.0)
        assert len(_visible_rows(panel._in_model)) > 2
        panel._draw_visible_thumbs()
        assert len(drawn) == 1, drawn
        assert panel._thumbs_timer.isActive(), "the rest is scheduled"
    finally:
        _close(win)
