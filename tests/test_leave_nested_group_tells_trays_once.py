# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Leaving every open level tells the trays once, at the end.

Since #1148 leaving goes level by level (a part shares back before the
component around it). Each level told the trays on its own, and the Parts
tray measured the parts of every container passed on the way out: leaving
the flag of Marco's plaza (three levels deep, 60 parts in «Group 333»)
went from ~1.1 s in 0.6.2.1 to ~3 s, two of them measuring parts for a
list no frame ever showed (20-11)."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh

_app = QApplication.instance() or QApplication([])


def _square(x0=0.0):
    m = Mesh()
    m.add_face([V(x0, 0, 0), V(x0 + 1, 0, 0), V(x0 + 1, 1, 0), V(x0, 1, 0)])
    return m


def _three_levels():
    """outer (5 parts) ▸ middle (3 parts) ▸ inner (1 part)."""
    inner = Group(_square(), name="inner")
    inner.adopt([Group(_square(9.0), name="leaf")])
    middle = Group(Mesh(), name="middle")
    middle.adopt([inner] + [Group(_square(2.0 * k), name=f"m{k}")
                            for k in range(2)])
    outer = Group(Mesh(), name="outer")
    outer.adopt([middle] + [Group(_square(3.0 * k), name=f"o{k}")
                            for k in range(4)])
    return outer, middle, inner


def _window(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    win.viewport.scene.groups.extend(groups)
    win.viewport.scene.version += 1
    return win, win.viewport, win.viewport.scene


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _count_part_rows(monkeypatch):
    import core.parts as parts
    calls = []
    real = parts.part_row

    def spy(part, cache=None):
        calls.append(part.name)
        return real(part, cache)
    monkeypatch.setattr(parts, "part_row", spy)
    return calls


def test_leaving_three_levels_tells_the_trays_once(monkeypatch):
    outer, middle, inner = _three_levels()
    win, vp, scene = _window(outer)
    try:
        for g in (outer, middle, inner):
            vp.begin_group_edit(g)
        told = []
        vp.sceneVersionChanged.connect(lambda v: told.append(v))
        rows = _count_part_rows(monkeypatch)
        vp.end_group_edit()
        assert scene.edit_group is None
        assert len(told) == 1, told
        # Back at the model, nothing selected: no container to list, so
        # no part is measured on the way out.
        assert rows == []
    finally:
        _close(win)


def test_esc_still_tells_the_trays_at_each_level(monkeypatch):
    """One level at a time (Esc) is a stop the user sees: the trays follow
    the container now open, as they always did."""
    outer, middle, inner = _three_levels()
    win, vp, scene = _window(outer)
    try:
        for g in (outer, middle, inner):
            vp.begin_group_edit(g)
        told = []
        vp.sceneVersionChanged.connect(lambda v: told.append(v))
        vp.end_one_group_edit()
        assert scene.edit_group is middle
        assert len(told) == 1
        assert win.tray.parts.container() is middle
        vp.end_one_group_edit()
        assert len(told) == 2
        assert win.tray.parts.container() is outer
    finally:
        _close(win)


def test_an_edit_inside_still_shares_back_every_level():
    """The level-by-level share-back of #1148 is untouched: a line drawn
    in the innermost group survives leaving all levels at once, and one
    undo takes it back."""
    from core.edits import build_add_edge
    outer, middle, inner = _three_levels()
    win, vp, scene = _window(outer)
    try:
        for g in (outer, middle, inner):
            vp.begin_group_edit(g)
        n0 = len(inner.mesh.edges)
        vp.history.execute(build_add_edge(scene, V(0, 0, 5), V(1, 0, 5)))
        vp.end_group_edit()
        assert scene.edit_group is None
        assert len(inner.mesh.edges) == n0 + 1
        vp.history.undo()
        assert len(inner.mesh.edges) == n0
    finally:
        _close(win)
