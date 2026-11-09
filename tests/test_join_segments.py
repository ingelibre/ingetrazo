# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Join Segments, the inverse of Divide: collinear pieces of a line back
to one line, the needless points between them gone."""
from __future__ import annotations

import math
import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.edits import divide_edges, join_edges, join_preview
from core.history import AddEdgeCommand, History, SnapshotMutation
from core.mesh import Mesh
from core.scene import Scene

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _polyline(m, pts):
    return [m.add_edge(a, b) for a, b in zip(pts, pts[1:])]


def _ends(e):
    return sorted((round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
                  for p in (e.a, e.b))


def test_a_line_drawn_in_pieces_becomes_one_line():
    m = Mesh()
    edges = _polyline(m, [V(0, 0), V(1, 0), V(2.5, 0), V(4, 0)])
    out = join_edges(m, edges)
    assert len(m.edges) == 1 and out == m.edges
    assert len(m.vertices) == 2
    assert _ends(m.edges[0]) == [(0, 0, 0), (4, 0, 0)]


def test_join_undoes_a_divide():
    m = Mesh()
    e = m.add_edge(V(0, 0, 0), V(3, 6, 9))
    divide_edges(m, [e], 7)
    assert len(m.edges) == 7
    join_edges(m, list(m.edges))
    assert len(m.edges) == 1
    assert _ends(m.edges[0]) == [(0, 0, 0), (3, 6, 9)]


def test_divide_after_join_still_works():
    m = Mesh()
    join_edges(m, _polyline(m, [V(0, 0), V(1, 0), V(4, 0)]))
    assert divide_edges(m, list(m.edges), 4) == 3
    xs = sorted(round(v.position.x(), 6) for v in m.vertices)
    assert xs == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_only_the_selected_pieces_join():
    m = Mesh()
    a, b, c = _polyline(m, [V(0, 0), V(1, 0), V(2, 0), V(3, 0)])
    out = join_edges(m, [a, b])
    assert len(m.edges) == 2
    assert len(out) == 1 and c not in out
    assert sorted(_ends(e) for e in m.edges) == [
        [(0, 0, 0), (2, 0, 0)], [(2, 0, 0), (3, 0, 0)]]


def test_a_corner_is_kept():
    m = Mesh()
    edges = _polyline(m, [V(0, 0), V(2, 0), V(2, 2)])
    join_edges(m, edges)
    assert len(m.edges) == 2


def test_a_nearly_straight_kink_is_kept():
    # 0.1° off straight: a real angle, not a stray point.
    m = Mesh()
    t = math.radians(0.1)
    edges = _polyline(m, [V(0, 0), V(10, 0), V(10 + 10 * math.cos(t), 10 * math.sin(t))])
    join_edges(m, edges)
    assert len(m.edges) == 2


def test_a_short_piece_far_out_still_joins():
    # 2 cm pieces 300 m away on a slant: the weld's rounding tilts them a
    # hundredth of a degree, yet each point is on the line within 0.1 mm.
    m = Mesh()
    a, d = V(300, 120, 7), V(3, 1.7, 0.4)
    edges = _polyline(m, [a, a + d * 0.004, a + d * 0.008, a + d])
    join_edges(m, edges)
    assert len(m.edges) == 1


def _line_into_fillet(r, segs):
    # A 20 mm line, then a 90° fillet of radius r in ``segs`` facets,
    # NOT tagged as a curve (an imported or exploded arc).
    m = Mesh()
    pts = [V(-0.02, 0), V(0, 0)]
    pts += [V(r * math.sin(a), r - r * math.cos(a))
            for a in (math.pi / 2 * k / segs for k in range(1, segs + 1))]
    return m, _polyline(m, pts)


def test_a_small_fillet_keeps_its_first_facet():
    # Review of the PR: in mm work a 2-3 mm fillet on sheet metal is
    # everyday, and its first facet sits a few thousandths of a mm off the
    # line it leaves. Near the origin that is a thousand float32 steps:
    # a corner, not a stray point.
    for r in (0.002, 0.003, 0.010):
        for segs in (6, 12, 24):         # facets the 0.1 mm weld can hold
            m, edges = _line_into_fillet(r, segs)
            join_edges(m, edges)
            assert len(m.edges) == segs + 1, (r, segs)


def test_mm_pieces_near_the_origin_still_join():
    m = Mesh()
    a, d = V(0.012, -0.004, 0.0015), V(0.0031, 0.0017, -0.0009)
    edges = _polyline(m, [a + d * t for t in (0.0, 0.13, 0.5, 0.77, 1.0)])
    join_edges(m, edges)
    assert len(m.edges) == 1


def test_a_t_junction_is_kept():
    m = Mesh()
    edges = _polyline(m, [V(0, 0), V(1, 0), V(2, 0)])
    stem = m.add_edge(V(1, 0), V(1, 1))
    join_edges(m, edges + [stem])
    assert len(m.edges) == 3


def test_segments_with_different_flags_are_kept_apart():
    m = Mesh()
    a, b = _polyline(m, [V(0, 0), V(1, 0), V(2, 0)])
    b.soft = True
    join_edges(m, [a, b])
    assert len(m.edges) == 2
    b.soft = False
    a.layer = b.layer = "Walls"
    out = join_edges(m, [a, b])
    assert len(m.edges) == 1 and out[0].layer == "Walls"


def test_the_facets_of_a_fine_circle_are_not_joined():
    m = Mesh()
    pts = [V(math.cos(2 * math.pi * i / 360), math.sin(2 * math.pi * i / 360))
           for i in range(360)]
    for i in range(360):
        m.add_edge(pts[i], pts[(i + 1) % 360])
    m.tag_curve(pts, closed=True)
    join_edges(m, list(m.edges))
    assert len(m.edges) == 360


def test_a_face_loses_the_needless_corner_and_stays_whole():
    m = Mesh()
    f = m.add_face([V(0, 0), V(4, 0), V(4, 2), V(0, 2)])
    bottom = next(e for e in m.edges if abs(e.a.y()) < 1e-9 and abs(e.b.y()) < 1e-9)
    divide_edges(m, [bottom], 3)
    assert len(f.vertices) == 6
    join_edges(m, list(m.edges))
    assert len(m.faces) == 1 and len(f.vertices) == 4
    assert len(m.edges) == 4
    assert all(f in e.faces for e in m.edges)
    assert sorted((round(p.x(), 6), round(p.y(), 6)) for p in f.vertices) == [
        (0, 0), (0, 2), (4, 0), (4, 2)]


def test_an_existing_full_line_beside_its_pieces_is_left_alone():
    m = Mesh()
    pieces = _polyline(m, [V(0, 0), V(1, 0), V(2, 0)])
    whole = m.add_edge(V(0, 0), V(2, 0))
    join_edges(m, pieces + [whole])
    assert len(m.edges) == 3


def test_random_lines_in_pieces_each_come_back_as_one():
    # Synthetic: lines in every direction, each cut at random points into
    # 2..8 pieces, all handed in at once (the whole-model clean-up).
    rnd = random.Random(1234)
    m = Mesh()
    lines = []
    for i in range(40):
        a = V(rnd.uniform(-50, 50), rnd.uniform(-50, 50), rnd.uniform(0, 20))
        d = V(rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))
        d = d * (rnd.uniform(1, 30) / max(d.length(), 1e-3))
        ts = sorted(rnd.uniform(0.05, 0.95) for _ in range(rnd.randint(1, 7)))
        ts = [t for k, t in enumerate(ts) if k == 0 or t - ts[k - 1] > 0.02]
        _polyline(m, [a + d * t for t in [0.0, *ts, 1.0]])
        lines.append((a, a + d))
    assert len(m.edges) > len(lines)
    join_edges(m, list(m.edges))
    assert len(m.edges) == len(lines)
    got = sorted(_ends(e) for e in m.edges)
    want = sorted(sorted((round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
                         for p in ends) for ends in lines)
    for g, w in zip(got, want):
        for pg, pw in zip(g, w):
            assert all(abs(x - y) < 1e-3 for x, y in zip(pg, pw))


def test_join_is_one_undo_step():
    scene = Scene()
    hist = History(scene)
    for x in range(3):
        hist.execute(AddEdgeCommand(V(x, 0), V(x + 1, 0)))
    edges = list(scene.mesh.edges)
    hist.execute(SnapshotMutation(lambda sc: join_edges(sc.mesh, edges)))
    assert len(scene.mesh.edges) == 1
    hist.undo()
    assert len(scene.mesh.edges) == 3
    hist.redo()
    assert len(scene.mesh.edges) == 1


def test_the_menu_command_joins_the_selection_and_reselects_the_line():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        hist = win.viewport.history
        for x in range(4):
            hist.execute(AddEdgeCommand(V(x, 0), V(x + 1, 0)))
        hist.execute(AddEdgeCommand(V(0, 5), V(1, 5)))
        scene.selection.update(e for e in scene.mesh.edges if abs(e.a.y()) < 1e-9)
        win._on_join_segments()
        assert len(scene.mesh.edges) == 5          # only the preview so far
        win._join_preview.apply_button.click()
        assert len(scene.mesh.edges) == 2
        assert len(scene.selection) == 1
        (line,) = scene.selection
        assert _ends(line) == [(0, 0, 0), (4, 0, 0)]
        hist.undo()
        assert len(scene.mesh.edges) == 5
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_menu_command_with_nothing_selected_cleans_the_whole_model():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        hist = win.viewport.history
        for x in range(3):
            hist.execute(AddEdgeCommand(V(x, 0), V(x + 1, 0)))
            hist.execute(AddEdgeCommand(V(0, x), V(0, x + 1)))
        scene.selection.clear()
        win._on_join_segments()
        win._join_preview.accept()
        assert len(scene.mesh.edges) == 2
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- The preview: what goes and what stays, before anything changes ----

def _reasons(verdicts):
    out: dict = {}
    for v, r in verdicts.items():
        out.setdefault(r, []).append((round(v.position.x(), 6),
                                      round(v.position.y(), 6)))
    return {r: sorted(p) for r, p in out.items()}


def test_the_preview_changes_nothing_and_agrees_with_the_command():
    m = Mesh()
    edges = _polyline(m, [V(x, 0) for x in range(5)])
    state = (list(m.vertices), list(m.edges))
    verdicts = join_preview(m, edges)
    assert (list(m.vertices), list(m.edges)) == state
    assert all(len(v.edges) == 2 for v in verdicts)
    assert _reasons(verdicts) == {"join": [(1, 0), (2, 0), (3, 0)]}
    join_edges(m, edges)
    assert len(m.edges) == 1


def test_the_preview_tells_why_a_point_on_the_line_stays():
    m = Mesh()
    line = _polyline(m, [V(x, 0) for x in range(6)])
    stem = m.add_edge(V(1, 0), V(1, 1))
    line[3].soft = True                        # (3,0)-(4,0) soft
    verdicts = join_preview(m, line + [stem])
    assert _reasons(verdicts) == {"branch": [(1, 0)],
                                  "flags": [(3, 0), (4, 0)],
                                  "join": [(2, 0)]}


def test_the_preview_points_out_a_kink_but_not_a_plain_corner():
    m = Mesh()
    t = math.radians(0.3)
    kinked = _polyline(m, [V(0, 0), V(10, 0),
                           V(10 + 10 * math.cos(t), 10 * math.sin(t))])
    corner = _polyline(m, [V(0, 5), V(2, 5), V(2, 7)])
    assert _reasons(join_preview(m, kinked + corner)) == {"kink": [(10, 0)]}


def test_the_preview_marks_the_facets_of_a_curve():
    m = Mesh()
    pts = [V(x, 0) for x in range(3)]
    arc = _polyline(m, pts)
    m.tag_curve(pts, closed=False)
    assert _reasons(join_preview(m, arc)) == {"curve": [(1, 0)]}


def test_the_preview_panel_paints_and_cancel_leaves_the_model_alone():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        hist = win.viewport.history
        for x in range(3):
            hist.execute(AddEdgeCommand(V(x, 0), V(x + 1, 0)))
        scene.selection.update(scene.mesh.edges)
        win._on_join_segments()
        panel = win._join_preview
        assert panel.counts == {"join": 2}
        assert panel._paint in win.viewport._ext_overlays
        assert panel.parent() is win.viewport          # floats in the view
        vp = win.viewport
        assert panel.geometry().right() <= vp.width()
        assert panel.geometry().bottom() <= vp.height()
        assert panel.x() > vp.width() // 2 or vp.width() < 2 * panel.width()
        panel.reject()
        assert panel._paint not in win.viewport._ext_overlays
        assert len(scene.mesh.edges) == 3
        assert win._join_preview is None
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_nothing_to_show_skips_the_panel():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        win.viewport.history.execute(AddEdgeCommand(V(0, 0), V(1, 0)))
        scene.selection.update(scene.mesh.edges)
        win._on_join_segments()
        assert getattr(win, "_join_preview", None) is None
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_enter_on_the_view_joins_and_esc_cancels():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        hist = win.viewport.history
        for x in range(3):
            hist.execute(AddEdgeCommand(V(x, 0), V(x + 1, 0)))

        def press(key):
            QApplication.sendEvent(win.viewport, QKeyEvent(
                QEvent.KeyPress, key, Qt.NoModifier))

        scene.selection.update(scene.mesh.edges)
        win._on_join_segments()
        press(Qt.Key_Escape)
        assert win._join_preview is None and len(scene.mesh.edges) == 3
        win._on_join_segments()
        press(Qt.Key_Return)
        assert win._join_preview is None and len(scene.mesh.edges) == 1
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
