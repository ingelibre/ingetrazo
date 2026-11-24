# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Weld Edges, the inverse of Explode Curve: loose segments in a row
become one curve, picked whole like a circle, every point kept where it
is. Undo gives each edge back the curve it had."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.history import ExplodeCurvesCommand, History, WeldEdgesCommand
from core.scene import Scene

_app = QApplication.instance() or QApplication([])


def _polyline(mesh, pts):
    return [mesh.add_edge(a, b) for a, b in zip(pts, pts[1:])]


def _arc(mesh, c, r=1.0, n=8, start=0.0, sweep=math.pi):
    pts = [c + V(r * math.cos(start + sweep * k / n),
                 r * math.sin(start + sweep * k / n), 0) for k in range(n + 1)]
    _polyline(mesh, pts)
    mesh.tag_curve(pts, closed=False)
    return pts


def _points(mesh):
    return sorted((round(v.position.x(), 6), round(v.position.y(), 6),
                   round(v.position.z(), 6)) for v in mesh.vertices)


def test_a_zigzag_becomes_one_curve_and_undo_takes_it_apart():
    sc = Scene()
    h = History(sc)
    mesh = sc.mesh
    edges = _polyline(mesh, [V(0, 0, 0), V(1, 1, 0), V(2, 0, 0),
                             V(3, 1, 0), V(4, 0, 0)])
    before = _points(mesh)
    cmd = WeldEdgesCommand(edges)
    assert h.execute(cmd)
    assert cmd.curves == 1
    assert set(mesh.curve_edges(edges[0])) == set(edges)
    assert _points(mesh) == before            # nothing moved, no point lost
    assert len(mesh.edges) == 4
    h.undo()
    assert all(e.curve is None for e in edges)
    h.redo()
    assert set(mesh.curve_edges(edges[2])) == set(edges)


def test_two_separate_runs_weld_into_two_curves():
    sc = Scene()
    h = History(sc)
    mesh = sc.mesh
    a = _polyline(mesh, [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    b = _polyline(mesh, [V(5, 0, 0), V(6, 0, 0), V(6, 1, 0)])
    cmd = WeldEdgesCommand(a + b)
    assert h.execute(cmd)
    assert cmd.curves == 2
    assert set(mesh.curve_edges(a[0])) == set(a)
    assert set(mesh.curve_edges(b[0])) == set(b)


def test_a_fork_splits_the_weld_where_the_branches_meet():
    sc = Scene()
    h = History(sc)
    mesh = sc.mesh
    left = _polyline(mesh, [V(-2, 0, 0), V(-1, 0.5, 0), V(0, 0, 0)])
    right = _polyline(mesh, [V(0, 0, 0), V(1, 0.5, 0), V(2, 0, 0)])
    up = _polyline(mesh, [V(0, 0, 0), V(0.3, 1, 0), V(0, 2, 0)])
    cmd = WeldEdgesCommand(left + right + up)
    assert h.execute(cmd)
    assert cmd.curves == 3                    # one curve per branch
    for run in (left, right, up):
        assert set(mesh.curve_edges(run[0])) == set(run)


def test_an_arc_and_the_line_after_it_weld_into_one_curve():
    sc = Scene()
    h = History(sc)
    mesh = sc.mesh
    pts = _arc(mesh, V(0, 0, 0))
    arc = [e for e in mesh.edges if e.curve is not None]
    arc_id = arc[0].curve
    tail = mesh.add_edge(pts[-1], pts[-1] + V(0, -2, 0))
    cmd = WeldEdgesCommand(arc + [tail])
    assert h.execute(cmd)
    assert set(mesh.curve_edges(tail)) == set(arc + [tail])
    h.undo()
    assert tail.curve is None
    assert all(e.curve == arc_id for e in arc)


def test_lone_edges_are_refused_and_leave_no_undo_step():
    sc = Scene()
    h = History(sc)
    mesh = sc.mesh
    a = mesh.add_edge(V(0, 0, 0), V(1, 0, 0))
    b = mesh.add_edge(V(3, 0, 0), V(4, 0, 0))
    assert not h.execute(WeldEdgesCommand([a, b]))
    assert not h.execute(WeldEdgesCommand([a]))
    assert a.curve is None and b.curve is None
    assert not h.undo_stack


def test_a_3d_path_stays_one_curve_after_a_resplit():
    # A path for Follow Me climbs out of any one plane: other edits
    # re-cut every curve, and the weld must survive that.
    sc = Scene()
    h = History(sc)
    mesh = sc.mesh
    edges = _polyline(mesh, [V(0, 0, 0), V(2, 0, 0), V(2, 2, 1),
                             V(0, 2, 2), V(0, 0, 3)])
    assert h.execute(WeldEdgesCommand(edges))
    mesh.resplit_curves()
    assert set(mesh.curve_edges(edges[0])) == set(edges)


def test_explode_after_weld_gives_the_segments_back():
    sc = Scene()
    h = History(sc)
    mesh = sc.mesh
    edges = _polyline(mesh, [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(2, 1, 0)])
    h.execute(WeldEdgesCommand(edges))
    h.execute(ExplodeCurvesCommand([edges[1]]))
    assert all(mesh.curve_edges(e) == [e] for e in edges)


def test_the_weld_is_saved_with_the_model(tmp_path):
    from formats.igz import load_into, save_scene
    sc = Scene()
    h = History(sc)
    edges = _polyline(sc.mesh, [V(0, 0, 0), V(1, 1, 0), V(2, 0, 0)])
    h.execute(WeldEdgesCommand(edges))
    path = tmp_path / "weld.igz"
    save_scene(sc, path)
    back = Scene()
    load_into(back, path)
    ids = {e.curve for e in back.mesh.edges}
    assert len(ids) == 1 and None not in ids


def _menu_window(monkeypatch):
    from PySide6.QtWidgets import QMenu
    import views.main_window as mw

    class _Menu(QMenu):
        opened: list = []

        def exec(self, *a, **k):
            _Menu.opened.append(self)
            return None

    monkeypatch.setattr(mw, "QMenu", _Menu)
    return mw.MainWindow(), _Menu


def test_right_click_offers_it_on_loose_segments_not_on_one_curve(
        monkeypatch):
    from PySide6.QtCore import QPoint
    win, menu = _menu_window(monkeypatch)
    try:
        sc = win.viewport.scene
        run = _polyline(sc.mesh, [V(0, 0, 0), V(1, 1, 0), V(2, 0, 0)])
        _arc(sc.mesh, V(5, 0, 0))
        arc = [e for e in sc.mesh.edges if e.curve is not None]

        def entries(sel):
            menu.opened.clear()
            sc.select(sel)
            win.show_viewport_context_menu(QPoint(0, 0))
            return [a.text() for a in menu.opened[0].actions()]
        assert "Weld Edges" in entries(run)
        assert "Weld Edges" not in entries(arc)     # already one curve
        assert "Weld Edges" not in entries(run[:1])
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_command_welds_the_selection_and_repeat_names_it():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        sc = win.viewport.scene
        run = _polyline(sc.mesh, [V(0, 0, 0), V(1, 1, 0), V(2, 0, 0)])
        win._on_weld_edges()                   # nothing selected: no-op
        assert all(e.curve is None for e in run)
        sc.select(run)
        win._on_weld_edges()
        assert set(sc.mesh.curve_edges(run[0])) == set(run)
        assert win._last_command[0] == "Weld Edges"
        win._on_explode_curve()
        assert win._last_command[0] == "Explode Curve"
        win._on_undo()
        win._on_undo()
        assert all(e.curve is None for e in run)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
