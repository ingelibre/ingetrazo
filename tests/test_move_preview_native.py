# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Move of vertices inside an open group draws the faces it stretches
from arrays the engine packed at the grab (``MovePreview``, Bloque 6d):
each frame's bake is the very floats and per-vertex colours the Python
bake makes of the moved faces — random meshes of every kind and map,
random subsets riding, offsets from zero to far, one axis locked, faces
touched by a single corner, a container's paint, -0.0 corners — and with
the engine off (or the symbol missing) Python bakes as it always did.
The runs the engine hands back join neighbouring faces of one colour and
shade, so the comparison is per vertex, not per run."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.preview_probe import MATERIALS, probe_faces  # noqa: E402
from tools.move import _MovedFaces  # noqa: E402

_app = QApplication.instance() or QApplication([])

needs_engine = pytest.mark.skipif(
    _native.native is None or _native.qt_hypot() is None
    or not hasattr(_native.native, "MovePreview"),
    reason="the Rust engine is off")

PAINTS = (None, {"color": (0.1, 0.6, 0.3)},
          {"texture": {"path": "/probe/p.png", "sw": 2.0, "sh": 0.5}})


@pytest.fixture(scope="module")
def vp():
    from views.main_window import MainWindow
    win = MainWindow()
    yield win.viewport
    win._saved_version = win.viewport.scene.version
    win.close()


def _per_vertex(baked):
    """A bake as ``(colour floats, one colour per colour vertex, textured
    runs)`` — the runs checked to tile the colour floats in order."""
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


def _mesh_of(seed):
    """Mesh faces shaped as the probe's preview faces (quads, stars, holed,
    thin, tiny, n-gons; slanted, hair-vertical; every material), welded so
    neighbours share corners."""
    m = Mesh()
    pos, sizes, counts, attrs = [], [], [], []
    for f in probe_faces(seed=seed, count=90):
        if len(f.vertices) < 3:
            continue
        rings = [f.vertices] + [h for h in f.holes if len(h) >= 3]
        counts.append(len(rings))
        for r in rings:
            sizes.append(len(r))
            pos.extend((p.x(), p.y(), p.z()) for p in r)
        attrs.append(dict(f.attrs) if f.attrs else None)
    faces = m.add_faces_bulk(np.array(pos, dtype=np.float32), sizes, counts,
                             attrs)
    return m, faces


def _check(vp, shown, moving, paint, d):
    moved = _MovedFaces(shown, moving, paint, d)
    want = vp._bake_preview_faces_py(list(moved))
    got = vp._bake_preview_moved_native(moved.moved_parts)
    assert _per_vertex(got) == _per_vertex(want)


@needs_engine
@pytest.mark.parametrize("seed", range(10))
def test_random_drags_bake_alike(vp, seed):
    rng = random.Random(seed)
    m, faces = _mesh_of(seed)
    verts = list(m.vertices)
    for f in faces[::7]:
        f.attrs["hidden"] = True      # the tool drops these before
    shown = [f for f in faces if not f.attrs.get("hidden")]
    moving = frozenset(id(v) for v in verts if rng.random() < 0.4)
    paint = rng.choice(PAINTS)
    vp._moved_pack_memo = None
    for _ in range(12):               # one pack, many frames
        s = 10 ** rng.uniform(-6, 3)
        d = V(rng.uniform(-s, s), rng.uniform(-s, s), rng.uniform(-s, s))
        _check(vp, shown, moving, paint, d)


@needs_engine
def test_edge_offsets_and_corners(vp):
    m = Mesh()
    # Corners at -0.0 that stay; a triangle the drag touches by ONE
    # corner; a holed face; a painted and a textured face.
    tri = m.add_face([V(-0.0, -0.0, 0), V(2, 0, -0.0), V(0, 2, 0)])
    quad = m.add_face([V(2, 0, 0), V(5, 0, 0), V(5, 3, 0), V(2, 3, 0)])
    quad.attrs["color"] = [0.2, 0.4, 0.9]
    big = m.add_face([V(10, 0, 0), V(20, 0, 0), V(20, 10, 0), V(10, 10, 0)])
    m.add_face([V(12, 2, 0), V(14, 2, 0), V(14, 4, 0), V(12, 4, 0)])
    big.attrs["texture"] = dict(MATERIALS[4]["texture"])
    shown = list(m.faces)
    corner = m.vertex_at(V(2, 0, 0))
    assert corner is not None
    one = frozenset([id(corner)])
    every = frozenset(id(v) for v in m.vertices)
    for paint in PAINTS:
        for moving in (one, every, frozenset()):
            vp._moved_pack_memo = None
            for d in (V(0, 0, 0), V(-0.0, 0, 0), V(0.25, 0, 0),
                      V(0, -3.5, 0), V(0, 0, 1e-7), V(1e4, -1e4, 7.5)):
                _check(vp, shown, moving, paint, d)


@needs_engine
def test_resting_minus_zero_stays_in_the_floats(vp):
    """A corner at -0.0 that does not ride keeps its sign — ``v.position``,
    not ``v.position + 0`` — and one that rides turns to +0.0 as Qt's add
    makes it."""
    m = Mesh()
    f = m.add_face([V(-0.0, -0.0, -0.0), V(1, 0, -0.0), V(0, 1, -0.0)])
    vp._moved_pack_memo = None
    got = vp._bake_preview_moved_native(
        ([f], frozenset(), None, V(0, 0, 0)))
    raw = np.frombuffer(got[0].tobytes(), dtype=np.float32)
    assert np.signbit(raw).any()
    _check(vp, [f], frozenset(), None, V(0, 0, 0))
    _check(vp, [f], frozenset(id(v) for v in f.loop), None, V(0, 0, 0))


@needs_engine
def test_neighbours_of_one_look_draw_once(vp):
    """The flat floor a drag stretches: one draw for every face of it."""
    m = Mesh()
    for i in range(30):
        m.add_face([V(i, 0, 0), V(i + 1, 0, 0), V(i + 1, 1, 0), V(i, 1, 0)])
    moving = frozenset(id(v) for v in m.vertices if v.position.y() > 0.5)
    vp._moved_pack_memo = None
    got = vp._bake_preview_moved_native(
        (list(m.faces), moving, None, V(0, 0.5, 0)))
    assert len(got[1]) == 1
    _check(vp, list(m.faces), moving, None, V(0, 0.5, 0))


def test_without_the_engine_python_bakes(vp, monkeypatch):
    m, faces = _mesh_of(3)
    moving = frozenset(id(v) for v in list(m.vertices)[::3])
    moved = _MovedFaces(faces, moving, None, V(0.5, 0, 1))
    want = vp._bake_preview_faces_py(list(moved))
    monkeypatch.setattr(_native, "native", None)
    assert vp._bake_preview_moved_native(moved.moved_parts) is None
    assert _per_vertex(vp._bake_preview_faces(moved)) == _per_vertex(want)

    class _Old:                              # an engine built before 6d
        pass
    monkeypatch.setattr(_native, "native", _Old())
    assert vp._bake_preview_moved_native(moved.moved_parts) is None


def test_moved_faces_are_the_faces_the_tool_built(vp):
    """The sequence walks to the faces ``preview_faces`` always built."""
    from core.geometry import Face as GeomFace
    from core.materials import effective_attrs
    m, faces = _mesh_of(5)
    moving = frozenset(id(v) for v in list(m.vertices)[::2])
    paint = PAINTS[1]
    d = V(0.3, -0.2, 0.9)
    moved = _MovedFaces(faces, moving, paint, d)
    assert len(moved) == len(faces) and bool(moved)
    assert not _MovedFaces([], moving, paint, d)
    for pf, f in zip(moved, faces):
        want = GeomFace(
            [v.position + d if id(v) in moving else v.position
             for v in f.loop],
            [[v.position + d if id(v) in moving else v.position for v in h]
             for h in f.hole_loops],
            attrs=effective_attrs(f.attrs, paint) or None)
        assert pf.vertices == want.vertices and pf.holes == want.holes
        assert pf.attrs == want.attrs
    assert moved[0] is list(moved)[0]


# ---- the tool's drag, end to end -------------------------------------------

@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())
    from views import array_bake
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 0)
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


def _ctx(vp, world, x=10):
    from tools.base import ToolContext
    return ToolContext(viewport=vp, world=world, screen=QPointF(x, 10),
                       modifiers=Qt.NoModifier, snap=None)


def _open_grid(win, n=14):
    from core.group import Group
    vp = win.viewport
    m = Mesh()
    for i in range(n):
        for j in range(n):
            f = m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                            V(i, j + 1, 0)])
            if (i * j) % 5 == 0:
                f.attrs["color"] = [0.8, 0.2, 0.1]
    g = Group(m, "big")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    vp.begin_group_edit(g)
    _app.processEvents()
    return vp


@pytest.mark.skipif(_native.available() is None or _native.qt_hypot() is None
                    or not hasattr(_native.available() or object(),
                                   "MovePreview"),
                    reason="no engine with MovePreview")
@pytest.mark.parametrize("axis", [None, "x", "z"])
def test_a_drag_frame_bakes_as_python(win, monkeypatch, axis):
    from views.viewport import Viewport
    monkeypatch.setattr(Viewport, "_preview_native_state", True)
    vp = _open_grid(win)
    mesh = vp.scene.mesh
    block = [f for f in mesh.faces
             if all(3 <= v.position.x() <= 9 and 3 <= v.position.y() <= 9
                    for v in f.loop)]
    vp.scene.select(block)
    win._tool_actions["move"].trigger()
    tool = vp.active_tool
    c0 = block[0].centroid()
    tool.on_click(_ctx(vp, c0))
    assert tool._vp_preview
    called = []
    real = vp._bake_preview_moved_native
    monkeypatch.setattr(vp, "_bake_preview_moved_native",
                        lambda parts: called.append(1) or real(parts))
    for k in range(1, 5):
        step = {None: V(0.1 * k, -0.05 * k, 0.3 * k), "x": V(0.37 * k, 0, 0),
                "z": V(0, 0, -0.41 * k)}[axis]
        tool.on_hover(_ctx(vp, c0 + step, 10 + k))
        faces = tool.preview_faces()
        assert len(faces) >= vp.MOVED_NATIVE_MIN_FACES
        assert tool.preview_faces() is faces           # one per offset
        got = vp._bake_preview_faces(faces, tool)
        assert _per_vertex(got) == _per_vertex(
            vp._bake_preview_faces_py(list(faces)))
        vp.repaint()
    assert called
    tool.on_cancel(vp)
    _app.processEvents()
    assert vp._moved_pack_memo is None      # let go with the preview


def test_a_group_drag_bakes_no_stretched_faces(win):
    """A group grabbed whole moves by the drawing offset alone: nothing
    stretches, nothing is packed."""
    from core.group import Group
    vp = win.viewport
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "box")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    _app.processEvents()
    vp.scene.select([g])
    win._tool_actions["move"].trigger()
    tool = vp.active_tool
    tool.on_click(_ctx(vp, V(0.5, 0.5, 0)))
    tool.on_hover(_ctx(vp, V(2.5, 0.5, 0), 30))
    assert tool.preview_faces() == []
    assert getattr(vp, "_moved_pack_memo", None) is None
    tool.on_cancel(vp)
