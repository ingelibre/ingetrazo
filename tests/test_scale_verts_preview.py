# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Scale of vertices — of the loose model, or inside an open group —
previews the way Move's vertex drag does (``begin_verts_preview``, 21-11):
nothing is mutated until the commit, what rides is drawn through the scale
and the faces it bends are drawn scaled by the tool. The commit lands
exactly where a typed scale lands (the old live one landed there but for
the float32 rounding its frames left), in one undo step — uniform, one axis, mirrored (a negative factor), down to the
smallest factor allowed; a cancel leaves the model as it was. The engine
bakes the scaled faces to the floats and colours the Python bake makes."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402
import random  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core.history import scale_matrix  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from tools.move import _MovedFaces  # noqa: E402

_app = QApplication.instance() or QApplication([])

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")

_has_placed = hasattr(getattr(_native.available(), "MovePreview", None),
                      "bake_placed")


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())
    from views import array_bake
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 0)
    from views.viewport import Viewport
    monkeypatch.setattr(Viewport, "_preview_native_state", True)
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _fresh_window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    return w


def _z(i, j):
    return 0.3 * math.sin(i * 0.9) * math.cos(j * 0.7)


def _terrain(m, n=10):
    """Triangles over a bumpy grid: every axis has extent to scale."""
    for i in range(n):
        for j in range(n):
            a, b = V(i, j, _z(i, j)), V(i + 1, j, _z(i + 1, j))
            c, d = V(i + 1, j + 1, _z(i + 1, j + 1)), V(i, j + 1, _z(i, j + 1))
            f = m.add_face([a, b, c])
            m.add_face([a, c, d])
            if (i + j) % 4 == 0:
                f.attrs["color"] = [0.2, 0.5, 0.8]


def _scene(w, where):
    vp = w.viewport
    if where == "loose":
        _terrain(vp.scene.mesh)
        vp.scene.version += 1
    else:
        from core.group import Group
        m = Mesh()
        _terrain(m)
        g = Group(m, "big")
        vp.scene.groups.append(g)
        vp.scene.version += 1
        vp.begin_group_edit(g)
    vp.repaint()
    _app.processEvents()
    return vp


def _block(mesh):
    return [f for f in mesh.faces
            if all(3 - 1e-6 <= v.position.x() <= 6 + 1e-6
                   and 3 - 1e-6 <= v.position.y() <= 6 + 1e-6
                   for v in f.loop)]


def _model(mesh):
    return ([v.position.toTuple() for v in mesh.vertices],
            [([v.position.toTuple() for v in f.loop],
              [[v.position.toTuple() for v in h] for h in f.hole_loops],
              repr(sorted(f.attrs.items()))) for f in mesh.faces],
            sorted((e.v0.position.toTuple(), e.v1.position.toTuple())
                   for e in mesh.edges))


def _grab(w, vp):
    vp.scene.select(_block(vp.scene.mesh))
    w._tool_actions["scale"].trigger()
    tool = vp.active_tool
    tool._refresh_box(vp)
    grip = next(g for g in tool._grips if len(g.mask) == 3)   # a corner
    tool._grab(vp, grip, (10.0, 10.0))
    return tool


def _scale(w, where, factors, preview, frames):
    vp = _scene(w, where)
    mesh = vp.scene.mesh
    start = _model(mesh)
    tool = _grab(w, vp)
    assert tool._vp_preview is preview
    undo_before = len(vp.history.undo_stack)
    if frames:
        for k in range(1, 5):
            t = k / 4.0
            tool._apply_preview(vp, tuple(1.0 + (f - 1.0) * t
                                          for f in factors))
            vp.repaint()
            if preview:
                assert _model(mesh) == start            # nothing mutated
                assert len(tool.preview_faces()) == len(
                    [f for f in tool._bent_faces
                     if not f.attrs.get("hidden")])
    tool._commit(vp, factors)
    _app.processEvents()
    assert getattr(vp, "_verts_preview", None) is None
    steps = len(vp.history.undo_stack) - undo_before
    moved = _model(mesh)
    vp.history.undo()
    undone = _model(mesh)
    vp.history.redo()
    return moved, undone, _model(mesh), steps


def _close(a, b, tol=1e-5):
    pa, fa, ea = a
    pb, fb, eb = b
    assert len(pa) == len(pb) and len(fa) == len(fb) and len(ea) == len(eb)
    assert all(abs(x - y) < tol for p, q in zip(pa, pb)
               for x, y in zip(p, q))
    for (la, ha, ta), (lb, hb, tb) in zip(fa, fb):
        assert len(la) == len(lb) and ta == tb
        assert [len(h) for h in ha] == [len(h) for h in hb]


FACTORS = [(2.0, 2.0, 2.0), (1.5, 1.0, 1.0), (-1.0, 1.0, 1.0),
           (0.5, -2.0, 1.0), (1.0, 1.0, 1e-4), (-0.75, -0.75, -0.75)]


@pytest.mark.parametrize("where", ["loose", "group"])
@pytest.mark.parametrize("factors", FACTORS)
def test_a_scale_lands_where_a_typed_scale_does(win, monkeypatch, where,
                                                factors):
    frozen = _scale(win, where, factors, preview=True, frames=True)
    out = []
    for preview, frames in ((True, False), (False, True)):
        w = _fresh_window()
        try:
            if not preview:
                monkeypatch.setattr(type(w.viewport), "begin_verts_preview",
                                    lambda self, verts: None)
            out.append(_scale(w, where, factors, preview=preview,
                              frames=frames))
        finally:
            w._saved_version = w.viewport.scene.version
            w.close()
    typed, live = out
    assert frozen[3] == typed[3] == live[3] == 1          # one undo step
    # The frozen scale lands exactly where a typed one lands, the undo
    # and redo too ...
    assert frozen == typed
    # ... and where the live one landed, give or take the float32 rounding
    # its frames left behind (each put the vertices back by a difference,
    # ``move_vertex(v, p0 - v.position)``, which needs not be exact).
    for a, b in zip(frozen[:3], live[:3]):
        _close(a, b)


@pytest.mark.parametrize("where", ["loose", "group"])
def test_a_cancel_leaves_the_model(win, where):
    vp = _scene(win, where)
    mesh = vp.scene.mesh
    start = _model(mesh)
    tool = _grab(win, vp)
    assert tool._vp_preview
    tool._apply_preview(vp, (-1.5, 2.0, 0.5))
    vp.repaint()
    tool.on_cancel(vp)
    _app.processEvents()
    assert getattr(vp, "_verts_preview", None) is None
    assert _model(mesh) == start


def test_the_bent_faces_are_drawn_scaled(win):
    vp = _scene(win, "loose")
    tool = _grab(win, vp)
    for pf, f in zip(tool.preview_faces(), tool._bent_faces):
        assert pf.vertices == [v.position for v in f.loop]   # 1:1: in place
    factors = (-1.25, 0.5, 2.0)
    tool._apply_preview(vp, factors)
    m = scale_matrix(tool._anchor, factors, tool._axes)
    moving = {id(v) for v in tool._verts}
    for pf, f in zip(tool.preview_faces(), tool._bent_faces):
        assert pf.vertices == [m.map(v.position) if id(v) in moving
                               else v.position for v in f.loop]
    assert vp._preview_matrix == m
    tool.on_cancel(vp)


def _per_vertex(baked):
    assert baked is not None, "the engine refused faces Python bakes"
    data, runs, by_texture = baked
    cols, at = [], 0
    for rgb, start, count in runs:
        assert start == at
        cols.extend([tuple(rgb)] * count)
        at += count
    assert at == len(data) // 3
    return (data.tobytes(), cols,
            [(k, v.tobytes()) for k, v in by_texture.items()])


@pytest.mark.skipif(not _has_placed, reason="no MovePreview.bake_placed")
@pytest.mark.parametrize("seed", range(6))
def test_scaled_faces_bake_alike(win, seed):
    """Mirrors and near-flat scales among them: a flipped face's winding
    and shade come out as Python's."""
    from core.preview_probe import probe_faces
    vp = win.viewport
    rng = random.Random(seed)
    m = Mesh()
    pos, sizes, counts, attrs = [], [], [], []
    for f in probe_faces(seed=seed, count=80):
        if len(f.vertices) < 3:
            continue
        rings = [f.vertices] + [h for h in f.holes if len(h) >= 3]
        counts.append(len(rings))
        for r in rings:
            sizes.append(len(r))
            pos.extend(p.toTuple() for p in r)
        attrs.append(dict(f.attrs) if f.attrs else None)
    faces = m.add_faces_bulk(np.array(pos, dtype=np.float32), sizes, counts,
                             attrs)
    moving = frozenset(id(v) for v in m.vertices if rng.random() < 0.5)
    vp._moved_pack_memo = None
    for _ in range(10):
        c = V(rng.uniform(-50, 50), rng.uniform(-50, 50), rng.uniform(-5, 5))
        fs = tuple(rng.choice([-1, 1]) * 10 ** rng.uniform(-4, 1)
                   for _ in range(3))
        if rng.random() < 0.3:
            fs = (fs[0],) * 3
        mat = scale_matrix(c, fs)
        moved = _MovedFaces(faces, moving, None, V(0, 0, 0), mat)
        want = vp._bake_preview_faces_py(list(moved))
        got = vp._bake_preview_moved_native(moved.moved_parts)
        assert _per_vertex(got) == _per_vertex(want)
