# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Scale of whole groups previews the way Move and Rotate preview
them (``begin_groups_preview``, 21-11): the movers' arrays drawn through
the scale, nothing mutated until the commit — a group without its own
placement matrix had every vertex set again and the group re-baked on
each frame. The commit lands exactly where a typed scale lands, in one
undo step — uniform, one axis, mirrored, the smallest factor allowed;
groups with and without a placement matrix, a component's copy, a group
open around them — and a cancel leaves everything as it was."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    if getattr(w.viewport, "_gl", None) is None or not w.viewport.isValid():
        # The preview draws from GL buffers: with no context (the
        # offscreen platform on macOS) it never starts.
        w._saved_version = w.viewport.scene.version
        w.close()
        pytest.skip("no OpenGL context on this platform")
    return w


@pytest.fixture
def win():
    w = _window()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _box(m, o, s=1.0):
    x, y, z = o.x(), o.y(), o.z()
    p = [V(x, y, z), V(x + s, y, z), V(x + s, y + s, z), V(x, y + s, z)]
    q = [a + V(0, 0, s * 0.7) for a in p]
    m.add_face(list(reversed(p)))
    m.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        m.add_face([p[i], p[j], q[j], q[i]])


def _scene(w, kind):
    """Two groups to scale: a plain one (no matrix) and ``kind`` — another
    plain one, one placed by a matrix, a component's copy, or (``nested``)
    two pieces placed inside an instance that is open."""
    from core.group import Group
    from core.mesh import Mesh
    vp = w.viewport
    sc = vp.scene
    a = Mesh()
    _box(a, V(0, 0, 0))
    _box(a, V(1.5, 0, 0), 0.5)
    ga = Group(a, "a")
    b = Mesh()
    _box(b, V(0, 0, 0), 0.8)
    gb = Group(b, "b")
    if kind in ("matrix", "component", "nested"):
        xf = QMatrix4x4()
        xf.translate(3, 1, 0.25)
        xf.rotate(30, 0, 0, 1)
        gb.xform = xf
        gb.component = kind == "component"
    else:
        for v in list(b.vertices):
            b.move_vertex(v, V(3, 1, 0))
    if kind == "nested":
        ga.xform = QMatrix4x4()
        om = Mesh()
        _box(om, V(-4, 0, 0))
        outer = Group(om, "outer")
        outer.adopt([ga, gb])
        sc.groups.append(outer)
        sc.version += 1
        _app.processEvents()
        vp.begin_group_edit(outer)
        _app.processEvents()
        pieces = list(sc.edit_group.children)
    else:
        sc.groups.extend([ga, gb])
        pieces = [ga, gb]
    sc.version += 1
    vp.repaint()
    _app.processEvents()
    return vp, pieces


def _state(groups):
    return [([v.position.toTuple() for v in g.mesh.vertices],
             None if g.xform is None else tuple(g.xform.data()))
            for g in groups]


def _grab(w, vp, groups):
    vp.scene.select(groups)
    w._tool_actions["scale"].trigger()
    tool = vp.active_tool
    tool._refresh_box(vp)
    grip = next(g for g in tool._grips if len(g.mask) == 3)
    tool._grab(vp, grip, (10.0, 10.0))
    return tool


def _scale(kind, factors, preview, frames, monkeypatch):
    w = _window()
    try:
        vp, groups = _scene(w, kind)
        if not preview:
            # The old road: no groups preview to start.
            monkeypatch.setattr(vp, "begin_groups_preview", None,
                                raising=False)
        start = _state(groups)
        tool = _grab(w, vp, groups)
        assert tool._vp_preview is preview
        undo_before = len(vp.history.undo_stack)
        if frames:
            for k in range(1, 5):
                t = k / 4.0
                tool._apply_preview(vp, tuple(1.0 + (f - 1.0) * t
                                              for f in factors))
                vp.repaint()
                if preview:
                    assert _state(groups) == start      # nothing mutated
                    assert vp._preview_matrix is not None
        tool._commit(vp, factors)
        _app.processEvents()
        assert not getattr(vp, "_preview_groups", None)
        steps = len(vp.history.undo_stack) - undo_before
        moved = _state(groups)
        vp.history.undo()
        undone = _state(groups)
        assert len(undone) == len(start)
        vp.history.redo()
        return moved, undone, _state(groups), steps
    finally:
        monkeypatch.undo()
        w._saved_version = w.viewport.scene.version
        w.close()


FACTORS = [(2.0, 2.0, 2.0), (1.5, 1.0, 1.0), (-1.0, 1.0, 1.0),
           (0.5, -2.0, 1.0), (1.0, 1.0, 1e-4), (-0.75, -0.75, -0.75)]


@pytest.mark.parametrize("kind", ["plain", "matrix", "component",
                                  "nested"])
@pytest.mark.parametrize("factors", FACTORS)
def test_a_group_scale_lands_where_a_typed_scale_does(monkeypatch, kind,
                                                      factors):
    frozen = _scale(kind, factors, True, True, monkeypatch)
    typed = _scale(kind, factors, True, False, monkeypatch)
    live = _scale(kind, factors, False, True, monkeypatch)
    assert frozen[3] == typed[3] == live[3] == 1          # one undo step
    assert frozen == typed                                # exactly
    # The live scale put a plain group's vertices back by a difference
    # each frame (``move_vertex(v, p0 - v.position)``): within a float32
    # rounding of the typed one.
    for a, b in zip(frozen[:3], live[:3]):
        for (pa, xa), (pb, xb) in zip(a, b):
            assert xa == xb
            assert all(abs(x - y) < 1e-5 for p, q in zip(pa, pb)
                       for x, y in zip(p, q))


def test_a_cancel_leaves_the_groups(win):
    vp, groups = _scene(win, "matrix")
    start = _state(groups)
    tool = _grab(win, vp, groups)
    assert tool._vp_preview
    tool._apply_preview(vp, (-1.5, 2.0, 0.5))
    vp.repaint()
    assert _state(groups) == start
    tool.on_cancel(vp)
    _app.processEvents()
    assert not getattr(vp, "_preview_groups", None)
    assert _state(groups) == start


def test_groups_with_loose_geometry_preview_with_the_engine(win):
    """Groups and loose geometry together: both previews at once when the
    engine bakes the loose part (tests/test_mixed_drag_preview.py), the
    live scale for the whole selection without it — never the groups
    previewed alone."""
    vp, groups = _scene(win, "plain")
    m = vp.scene.mesh
    f = m.add_face([V(-3, 0, 0), V(-2, 0, 0), V(-2, 1, 0), V(-3, 1, 0)])
    vp.scene.version += 1
    vp.scene.select(groups + [f])
    win._tool_actions["scale"].trigger()
    tool = vp.active_tool
    tool._refresh_box(vp)
    grip = next(g for g in tool._grips if len(g.mask) >= 2)
    tool._grab(vp, grip, (10.0, 10.0))
    from views import array_bake
    both = array_bake.can_bake_built(m, 0)
    assert tool._vp_preview is both
    assert (getattr(vp, "_verts_preview", None) is not None) is both
    assert bool(getattr(vp, "_preview_groups", None)) is both
    tool.on_cancel(vp)
    assert not getattr(vp, "_preview_groups", None)
