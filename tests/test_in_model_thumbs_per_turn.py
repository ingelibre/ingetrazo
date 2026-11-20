# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The «In model» pictures are drawn a couple per turn of the event loop.

A selection scrolls its row into view and the rows around it need their
pictures: twelve of them on Marco's plaza, ~25 ms each. Drawn in one go
once the view was still, the 0.3 s landed inside the next thing the hand
did — the first Ctrl+Z after a Rotate took ~0.55 s instead of ~0.25 s
(20-11). Every row on screen still gets its picture, a few turns later."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import Mesh
from views import component_thumbs

_app = QApplication.instance() or QApplication([])


def _component(i):
    m = Mesh()
    s = 1.0 + i * 0.01
    m.add_face([V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0)])
    g = Group(m, name=f"C{i:03d}")
    xf = QMatrix4x4()
    xf.translate(i * 2.0, 0.0, 0.0)
    g.xform = xf
    return g


def _visible_rows(lst):
    area = lst.viewport().rect()
    return [lst.item(i) for i in range(lst.count())
            if lst.visualItemRect(lst.item(i)).intersects(area)]


def test_one_turn_draws_at_most_a_couple_of_pictures(monkeypatch):
    from views.main_window import MainWindow
    from views.tray import ComponentsPanel
    drawn = []
    real = component_thumbs._draw

    def spy(definition, size):
        drawn.append(definition.name)
        return real(definition, size)
    monkeypatch.setattr(component_thumbs, "_draw", spy)
    component_thumbs._cache.clear()
    win = MainWindow()
    try:
        win.show()
        monkeypatch.setattr(win.viewport, "view_busy", lambda: False)
        win.viewport.scene.groups.extend(_component(i) for i in range(60))
        panel = win.tray.components
        panel.refresh_in_model()
        panel._thumbs_timer.stop()
        drawn.clear()
        component_thumbs._cache.clear()
        lst = panel._in_model
        for i in range(lst.count()):
            lst.item(i).setData(Qt.UserRole + 2, None)
        rows = _visible_rows(lst)
        per_turn = getattr(ComponentsPanel, "THUMBS_PER_TURN", 2)
        assert len(rows) > per_turn + 2, len(rows)
        panel._draw_visible_thumbs()                 # one turn
        assert 0 < len(drawn) <= per_turn, (len(drawn), len(rows))
        assert panel._thumbs_timer.isActive(), "the rest is scheduled"
        end = time.monotonic() + 5.0
        while (any(not r.data(Qt.UserRole + 2) for r in rows)
               and time.monotonic() < end):
            QTest.qWait(10)
        assert all(r.data(Qt.UserRole + 2) for r in rows)
        assert len(drawn) == len(set(drawn)), "each picture drawn once"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
        # Keyed on id(mesh): left behind, a later test's meshes born at
        # the same addresses would find these pictures.
        component_thumbs._cache.clear()
