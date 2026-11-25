# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Rotate of vertices — of the loose model, or inside an open group —
previews the way Move's vertex drag does (``begin_verts_preview``, 21-11):
nothing is mutated until the commit, what rides is drawn through the
rotation and the faces it bends are drawn turned by the tool. The commit
lands exactly where a typed rotation (and the old live one) lands, in one
undo step; a cancel leaves the model as it was. The engine bakes the
turned faces to the very floats and colours the Python bake makes of
them, from the places Qt's ``map`` gives the riding vertices."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402
import random  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core.history import rotation_matrix  # noqa: E402
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
    if getattr(w.viewport, "_gl", None) is None or not w.viewport.isValid():
        # The preview draws from GL buffers: with no context (the
        # offscreen platform on macOS) it never starts.
        w._saved_version = w.viewport.scene.version
        w.close()
        pytest.skip("no OpenGL context on this platform")
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _fresh_window():
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


def _grid(m, n=10):
    for i in range(n):
        for j in range(n):
            f = m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                            V(i, j + 1, 0)])
            if (i + j) % 4 == 0:
                f.attrs["color"] = [0.2, 0.5, 0.8]
    m.add_edge(V(0, -2, 0), V(4, -2, 0))


def _scene(w, where):
    vp = w.viewport
    if where == "loose":
        _grid(vp.scene.mesh)
        vp.scene.version += 1
    else:
        from core.group import Group
        m = Mesh()
        _grid(m)
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


def _ctx(vp, world, x=10):
    from tools.base import ToolContext
    return ToolContext(viewport=vp, world=world, screen=QPointF(x, 10),
                       modifiers=Qt.NoModifier, snap=None)


def _model(mesh):
    return ([v.position.toTuple() for v in mesh.vertices],
            [([v.position.toTuple() for v in f.loop],
              [[v.position.toTuple() for v in h] for h in f.hole_loops],
              repr(sorted(f.attrs.items()))) for f in mesh.faces],
            sorted((e.v0.position.toTuple(), e.v1.position.toTuple())
                   for e in mesh.edges))


CENTRE = V(4.5, 4.5, 0)


def _grab(w, vp):
    vp.scene.select(_block(vp.scene.mesh))
    w._tool_actions["rotate"].trigger()
    tool = vp.active_tool
    tool.on_click(_ctx(vp, CENTRE, 10))
    tool.on_click(_ctx(vp, CENTRE + V(1, 0, 0), 11))
    return tool


def _turn(w, where, deg, preview, hover):
    vp = _scene(w, where)
    mesh = vp.scene.mesh
    start = _model(mesh)
    tool = _grab(w, vp)
    assert tool._vp_preview is preview
    undo_before = len(vp.history.undo_stack)
    if hover:
        for k in range(1, 5):
            a = math.radians(deg * k / 4.0)
            tool.on_hover(_ctx(vp, CENTRE + V(math.cos(a), math.sin(a), 0),
                               20 + k))
            vp.repaint()
            if preview:
                assert _model(mesh) == start            # nothing mutated
                assert len(tool.preview_faces()) == len(tool._bent_faces)
    tool._commit(vp, deg)
    _app.processEvents()
    assert getattr(vp, "_verts_preview", None) is None
    steps = len(vp.history.undo_stack) - undo_before
    moved = _model(mesh)
    vp.history.undo()
    undone = _model(mesh)
    vp.history.redo()
    return moved, undone, _model(mesh), steps


@pytest.mark.parametrize("where", ["loose", "group"])
@pytest.mark.parametrize("deg", [30.0, -112.5, 90.0])
def test_a_turn_lands_where_a_typed_turn_does(win, monkeypatch, where, deg):
    frozen = _turn(win, where, deg, preview=True, hover=True)
    out = []
    for preview, hover in ((True, False), (False, True)):
        w = _fresh_window()
        try:
            if not preview:
                monkeypatch.setattr(type(w.viewport), "begin_verts_preview",
                                    lambda self, verts: None)
            out.append(_turn(w, where, deg, preview=preview, hover=hover))
        finally:
            w._saved_version = w.viewport.scene.version
            w.close()
    typed, live = out
    assert frozen[3] == typed[3] == live[3] == 1          # one undo step
    assert frozen == typed == live                        # exactly


@pytest.mark.parametrize("where", ["loose", "group"])
def test_a_cancel_leaves_the_model(win, where):
    vp = _scene(win, where)
    mesh = vp.scene.mesh
    start = _model(mesh)
    tool = _grab(win, vp)
    assert tool._vp_preview
    tool.on_hover(_ctx(vp, CENTRE + V(0, 1, 0), 30))
    vp.repaint()
    tool.on_cancel(vp)
    _app.processEvents()
    assert getattr(vp, "_verts_preview", None) is None
    assert _model(mesh) == start


def test_the_bent_faces_and_edges_are_drawn_turned(win):
    vp = _scene(win, "loose")
    tool = _grab(win, vp)
    # Before the turn: exactly where they are.
    for pf, f in zip(tool.preview_faces(), tool._bent_faces):
        assert pf.vertices == [v.position for v in f.loop]
    tool.on_hover(_ctx(vp, CENTRE + V(0, 1, 0), 30))
    deg = tool._preview_deg
    assert abs(deg) > 1
    m = rotation_matrix(tool.start_point, tool._axis(), deg)
    moving = {id(v) for v in tool._verts}
    shown = tool.preview_faces()
    for pf, f in zip(shown, tool._bent_faces):
        assert pf.vertices == [m.map(v.position) if id(v) in moving
                               else v.position for v in f.loop]
    # The stretched edges: the riding end turned, the other in place.
    vpv = vp._verts_preview
    ends, rides = vpv["bent_ends"], vpv["bent_rides"]
    a = np.array(vp._preview_matrix.data(), dtype=np.float64).reshape(4, 4)
    want = np.array([m.map(V(*p)).toTuple() if r else tuple(p)
                     for p, r in zip(ends.tolist(), rides.tolist())])
    turned = np.where(rides[:, None] > 0,
                      (ends.astype(np.float64) @ a[:3, :3] + a[3, :3]), ends)
    assert np.allclose(turned, want, atol=1e-5)
    tool.on_cancel(vp)


def test_copy_mode_draws_the_bent_faces_at_rest(win):
    """The original stays put in copy mode: the faces it bends are drawn
    where they are (they are left out of the static buffers, so drawing
    none left a hole in the model)."""
    vp = _scene(win, "loose")
    tool = _grab(win, vp)
    tool._toggle_copy(vp, say=False)
    tool.on_hover(_ctx(vp, CENTRE + V(0, 1, 0), 30))
    faces = tool.preview_faces()
    shown = [f for f in tool._bent_faces if not f.attrs.get("hidden")]
    assert len(faces) == len(shown) > 0
    for moved, f in zip(faces, shown):
        assert ([p.toTuple() for p in moved.vertices]
                == [p.toTuple() for p in f.vertices])
    tool.on_cancel(vp)


# ---- the engine's bake of turned faces -------------------------------------

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
@pytest.mark.parametrize("seed", range(8))
def test_turned_faces_bake_alike(win, seed):
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
    moving = frozenset(id(v) for v in m.vertices if rng.random() < 0.4)
    paint = rng.choice([None, {"color": (0.1, 0.6, 0.3)}])
    vp._moved_pack_memo = None
    for _ in range(10):
        c = V(rng.uniform(-50, 50), rng.uniform(-50, 50), rng.uniform(-5, 5))
        ax = V(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        if rng.random() < 0.3:
            ax = rng.choice([V(0, 0, 1), V(1, 0, 0), V(0, -1, 0)])
        mat = rotation_matrix(c, ax, rng.uniform(-360, 360))
        moved = _MovedFaces(faces, moving, paint, V(0, 0, 0), mat)
        want = vp._bake_preview_faces_py(list(moved))
        got = vp._bake_preview_moved_native(moved.moved_parts)
        assert _per_vertex(got) == _per_vertex(want)


def test_an_engine_without_placed_bakes_in_python(win, monkeypatch):
    vp = win.viewport
    m = Mesh()
    f = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    moved = _MovedFaces([f], frozenset([id(f.loop[0])]), None, V(0, 0, 0),
                        rotation_matrix(V(0, 0, 0), V(0, 0, 1), 30.0))

    class _Pack:                     # MovePreview of an engine before it
        pass

    class _Old:
        MovePreview = _Pack
    monkeypatch.setattr(_native, "native", _Old())
    assert vp._bake_preview_moved_native(moved.moved_parts) is None
