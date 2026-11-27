# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Move, Rotate or Scale of a MIXED selection — objects and loose
geometry grabbed together — previews with both viewport previews at once
(``begin_verts_preview`` with ``groups``, 21-11): the objects leave the
buffers as in a groups preview, what rides the drag is baked once beside
them, and the faces it bends are drawn by the tool. Nothing is mutated
until the commit, which lands exactly where a typed operation lands, in
one undo step; a cancel leaves everything as it was. Where the vertex
part cannot preview (a soft edge riding, no engine, a group open around
it: a group holding objects is always placed by a matrix, and the vertex
preview leaves those to the live drag), the whole drag stays live — never
half of it. Each frame of a mixed drag re-walked the whole
loose model and re-placed the objects before."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402

_app = QApplication.instance() or QApplication([])

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")


@pytest.fixture(params=["engine", "python"])
def bake(request, monkeypatch):
    """Who bakes the bent faces each frame: the engine, or Python's bake
    (the engine refused at start-up)."""
    from views.viewport import Viewport
    monkeypatch.setattr(Viewport, "_preview_native_state",
                        request.param == "engine")
    return request.param


@pytest.fixture(autouse=True)
def _engine(monkeypatch):
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())
    from views import array_bake
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 0)
    from views.viewport import Viewport
    if Viewport._preview_native_state is None:
        monkeypatch.setattr(Viewport, "_preview_native_state", True)


def _window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    # Exposed before the first frame: after another test's window, the
    # offscreen platform may otherwise never paint this one.
    from PySide6.QtTest import QTest
    QTest.qWaitForWindowExposed(w)
    _app.processEvents()
    if getattr(w.viewport, "_gl", None) is None or not w.viewport.isValid():
        # The preview draws from GL buffers: with no context (the
        # offscreen platform on macOS) it never starts.
        w._saved_version = w.viewport.scene.version
        w.close()
        pytest.skip("no OpenGL context on this platform")
    return w


def _close_window(w):
    w._saved_version = w.viewport.scene.version
    w.close()


@pytest.fixture
def win():
    w = _window()
    yield w
    _close_window(w)


def _grid(m, n=10):
    for i in range(n):
        for j in range(n):
            f = m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                            V(i, j + 1, 0)])
            if (i + j) % 4 == 0:
                f.attrs["color"] = [0.2, 0.5, 0.8]
    m.add_edge(V(0, -2, 0), V(4, -2, 0))


def _box(m, o, s=1.0):
    x, y, z = o.x(), o.y(), o.z()
    p = [V(x, y, z), V(x + s, y, z), V(x + s, y + s, z), V(x, y + s, z)]
    q = [a + V(0, 0, s * 0.7) for a in p]
    m.add_face(list(reversed(p)))
    m.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        m.add_face([p[i], p[j], q[j], q[i]])


def _objects():
    """Two objects to grab with the loose block: a plain group (its own
    vertices) and one placed by a matrix."""
    from core.group import Group
    from core.mesh import Mesh
    a = Mesh()
    _box(a, V(4, 4, 0.5))
    ga = Group(a, "plain")
    b = Mesh()
    _box(b, V(0, 0, 0), 0.8)
    gb = Group(b, "placed")
    xf = QMatrix4x4()
    xf.translate(5, 3, 0.25)
    xf.rotate(30, 0, 0, 1)
    gb.xform = xf
    return [ga, gb]


def _scene(w, where):
    """The loose floor with two objects on it (``loose``), or (``group``)
    the floor inside a group that is open, the two objects placed in it."""
    from core.group import Group
    from core.mesh import Mesh
    vp = w.viewport
    sc = vp.scene
    objs = _objects()
    if where == "loose":
        _grid(sc.mesh)
        # And one holding a piece of its own: its placements ride too.
        inner = Mesh()
        _box(inner, V(7, 6, 0), 0.5)
        own = Mesh()
        _box(own, V(7, 7, 0), 0.6)
        nest = Group(own, "nest")
        nest.adopt([Group(inner, "piece")])
        objs.append(nest)
        sc.groups.extend(objs)
    else:
        m = Mesh()
        _grid(m)
        outer = Group(m, "outer")
        objs[0].xform = QMatrix4x4()     # a child keeps a placement
        outer.adopt(objs)
        sc.groups.append(outer)
        sc.version += 1
        _app.processEvents()
        vp.begin_group_edit(outer)
        _app.processEvents()
        objs = list(sc.edit_group.children)
    sc.version += 1
    vp.repaint()
    _app.processEvents()
    return vp, objs


def _block(mesh):
    return [f for f in mesh.faces
            if all(3 - 1e-6 <= v.position.x() <= 6 + 1e-6
                   and 3 - 1e-6 <= v.position.y() <= 6 + 1e-6
                   for v in f.loop)]


def _ctx(vp, world, x=10):
    from tools.base import ToolContext
    return ToolContext(viewport=vp, world=world, screen=QPointF(x, 10),
                       modifiers=Qt.NoModifier, snap=None)


def _model(vp, objs):
    """The mesh exactly (every vertex, every face's corners and look, the
    edges), and every object's vertices and placement."""
    mesh = vp.scene.mesh
    return ([v.position.toTuple() for v in mesh.vertices],
            [([v.position.toTuple() for v in f.loop],
              [[v.position.toTuple() for v in h] for h in f.hole_loops],
              repr(sorted(f.attrs.items()))) for f in mesh.faces],
            sorted((e.v0.position.toTuple(), e.v1.position.toTuple())
                   for e in mesh.edges),
            [([v.position.toTuple() for v in g.mesh.vertices],
              None if g.xform is None else tuple(g.xform.data()))
             for g in objs])


def _close(a, b, tol=1e-4):
    """Two ``_model``s alike to ``tol`` (the live drag's float32 steps)."""
    def flat(x):
        if isinstance(x, (int, float)):
            yield float(x)
        elif x is None or isinstance(x, str):
            yield x
        else:
            for y in x:
                yield from flat(y)
    fa, fb = list(flat(a)), list(flat(b))
    assert len(fa) == len(fb)
    for x, y in zip(fa, fb):
        if isinstance(x, float) and isinstance(y, float):
            assert abs(x - y) < tol
        else:
            assert x == y


def _no_preview_state(vp):
    assert getattr(vp, "_verts_preview", None) is None
    assert not getattr(vp, "_preview_groups", None)
    assert getattr(vp, "_frozen_cache_version", None) is None


# ---- the three tools, driven the same way ----------------------------------

CENTRE = V(4.5, 4.5, 0)


def _grab(w, vp, objs, tool_name):
    vp.scene.select(_block(vp.scene.mesh) + list(objs))
    w._tool_actions[tool_name].trigger()
    tool = vp.active_tool
    if tool_name == "move":
        tool.on_click(_ctx(vp, CENTRE))
    elif tool_name == "rotate":
        tool.on_click(_ctx(vp, CENTRE, 10))
        tool.on_click(_ctx(vp, CENTRE + V(1, 0, 0), 11))
    else:
        tool._refresh_box(vp)
        grip = next(g for g in tool._grips if len(g.mask) == 3)
        tool._grab(vp, grip, (10.0, 10.0))
    return tool


AMOUNT = {"move": V(0.3, -0.5, 0.75), "rotate": -67.5,
          "scale": (1.4, 0.8, 1.25)}


def _hover(vp, tool, tool_name, t, x=20):
    """The drag a fraction ``t`` of the way to ``AMOUNT``."""
    if tool_name == "move":
        tool.on_hover(_ctx(vp, CENTRE + AMOUNT["move"] * t, x))
    elif tool_name == "rotate":
        a = math.radians(AMOUNT["rotate"] * t)
        tool.on_hover(_ctx(vp, CENTRE + V(math.cos(a), math.sin(a), 0), x))
    else:
        tool._apply_preview(vp, tuple(1.0 + (f - 1.0) * t
                                      for f in AMOUNT["scale"]))


def _commit(vp, tool, tool_name):
    tool._commit(vp, AMOUNT[tool_name])


#: Whether a mixed drag previews there: not inside an open group (see the
#: module's note).
PREVIEWS = {"loose": True, "group": False}


def _operate(w, where, tool_name, preview, hover):
    """``(moved, undone, redone, undo steps, start)`` of one mixed drag."""
    vp, objs = _scene(w, where)
    start = _model(vp, objs)
    tool = _grab(w, vp, objs, tool_name)
    assert tool._vp_preview is preview
    if preview:
        assert vp._verts_preview is not None
        assert vp._verts_preview["loose"] is (where == "loose")
        assert vp._preview_groups >= {id(g) for g in objs}
    else:
        _no_preview_state(vp)
    undo_before = len(vp.history.undo_stack)
    version = vp.scene.version
    if hover:
        for k in range(1, 5):
            _hover(vp, tool, tool_name, k / 4.0, 20 + k)
            vp.repaint()
            if preview:
                assert _model(vp, objs) == start         # nothing mutated
                assert vp.scene.version == version
                assert len(tool.preview_faces()) == len(
                    [f for f in tool._bent_faces
                     if not f.attrs.get("hidden")])
    _commit(vp, tool, tool_name)
    _app.processEvents()
    _no_preview_state(vp)
    steps = len(vp.history.undo_stack) - undo_before
    moved = _model(vp, objs)
    vp.history.undo()
    undone = _model(vp, objs)
    vp.history.redo()
    return moved, undone, _model(vp, objs), steps, start


def _live(monkeypatch):
    """The old road: the vertex preview refuses, so the whole drag is
    live."""
    from views.viewport import Viewport
    monkeypatch.setattr(Viewport, "begin_verts_preview",
                        lambda self, verts, groups=(): None)


@pytest.mark.parametrize("where", ["loose", "group"])
@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_a_mixed_drag_lands_where_a_typed_one_does(monkeypatch, bake, where,
                                                  tool_name):
    out = []
    for hover in (True, False):
        w = _window()
        try:
            out.append(_operate(w, where, tool_name, PREVIEWS[where], hover))
        finally:
            _close_window(w)
    _live(monkeypatch)
    w = _window()
    try:
        live = _operate(w, where, tool_name, False, True)
    finally:
        _close_window(w)
    frozen, typed = out
    assert frozen[3] == typed[3] == live[3] == 1       # one undo step
    # The preview drag lands exactly where a typed operation lands, and
    # undo / redo go through the very same states.
    assert frozen[:3] == typed[:3]
    # (A plain group's own vertices turned by the command again on redo
    # land within a float32 rounding — the typed turn does the same.)
    _close(frozen[0], frozen[2])
    assert frozen[0] != frozen[4]                      # it did move
    _close(frozen[1], frozen[4])
    # The live drag lands there too, but for the float32 rounding its
    # per-frame steps left behind.
    for a, b in zip(frozen[:3], live[:3]):
        _close(a, b)


@pytest.mark.parametrize("where", ["loose", "group"])
@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_a_cancel_leaves_everything_as_it_was(win, where, tool_name):
    vp, objs = _scene(win, where)
    start = _model(vp, objs)
    faces0, edges0 = vp._faces_count, vp._edges_count
    tool = _grab(win, vp, objs, tool_name)
    assert tool._vp_preview is PREVIEWS[where]
    assert bool(getattr(vp, "_preview_groups", None)) is PREVIEWS[where]
    _hover(vp, tool, tool_name, 0.5)
    vp.repaint()
    tool.on_cancel(vp)
    _app.processEvents()
    vp.repaint()
    _no_preview_state(vp)
    if PREVIEWS[where]:
        assert _model(vp, objs) == start
    else:
        _close(_model(vp, objs), start)
    assert vp._faces_count == faces0 and vp._edges_count == edges0


@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_the_buffers_leave_out_what_moves(win, tool_name):
    """The sync that starts the drag leaves the objects and what rides out
    of the buffers; the scratch copy holds both; no frame after it walks
    the loose model."""
    vp, objs = _scene(win, "loose")
    mesh = vp.scene.mesh
    faces0 = vp._faces_count
    tool = _grab(win, vp, objs, tool_name)
    vpv = vp._verts_preview
    vp.repaint()
    assert vp._faces_count == faces0 - 6 * len(vpv["hide"])
    # The scratch copy: what rides AND both objects' faces.
    ride = sum(1 for f in mesh.faces if id(f) in vpv["hide"]
               and f not in tool._bent_faces)
    obj_faces = sum(len(g.mesh.faces) for g in objs) + sum(
        len(c.mesh.faces) for g in objs for c in g.children)
    assert vp._pv_vcol_count == 6 * (ride + obj_faces)
    walked = []
    real = vp._tris_of
    vp._tris_of = lambda f: walked.append(f) or real(f)
    for k in range(1, 5):
        _hover(vp, tool, tool_name, k / 4.0, 20 + k)
        vp.repaint()
    assert not walked
    assert tool.preview_faces()                  # the bent faces drawn
    del vp._tris_of
    tool.on_cancel(vp)


@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_a_soft_edge_riding_keeps_the_whole_drag_live(win, tool_name):
    """The vertex part refuses: the objects do not preview alone — the
    whole selection drags live, and lands where it always did."""
    vp, objs = _scene(win, "loose")
    mesh = vp.scene.mesh
    block = _block(mesh)
    e = next(e for f in block for e in f.loop[0].edges)
    e.soft = True
    vp.scene.version += 1
    start = _model(vp, objs)
    tool = _grab(win, vp, objs, tool_name)
    assert not tool._vp_preview
    _no_preview_state(vp)
    _hover(vp, tool, tool_name, 1.0)
    vp.repaint()
    assert _model(vp, objs) != start             # the live drag moves it
    tool.on_cancel(vp)
    _close(_model(vp, objs), start)


@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_no_engine_keeps_the_whole_drag_live(win, monkeypatch, tool_name):
    """Without the engine (Python only) nothing previews: the live drag,
    for the whole selection."""
    monkeypatch.setattr(_native, "native", None)
    vp, objs = _scene(win, "loose")
    tool = _grab(win, vp, objs, tool_name)
    assert not tool._vp_preview
    _no_preview_state(vp)
    tool.on_cancel(vp)


@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_a_group_open_keeps_the_whole_drag_live(win, tool_name):
    """Objects inside an open group make it an instance: the vertex
    preview refuses, and the objects do not preview alone either."""
    vp, objs = _scene(win, "group")
    assert vp.scene.edit_group.xform is not None
    tool = _grab(win, vp, objs, tool_name)
    assert not tool._vp_preview
    _no_preview_state(vp)
    tool.on_cancel(vp)
    _no_preview_state(vp)


def test_objects_alone_or_vertices_alone_keep_their_previews(win):
    """The two previews a mixed drag puts together still start alone."""
    vp, objs = _scene(win, "loose")
    vp.scene.select(list(objs))
    win._tool_actions["move"].trigger()
    tool = vp.active_tool
    tool.on_click(_ctx(vp, CENTRE))
    assert tool._vp_preview and vp._preview_groups
    assert getattr(vp, "_verts_preview", None) is None
    tool.on_cancel(vp)
    _no_preview_state(vp)
    vp.scene.select(_block(vp.scene.mesh))
    tool.on_click(_ctx(vp, CENTRE))
    assert tool._vp_preview and vp._verts_preview is not None
    assert not vp._preview_groups
    tool.on_cancel(vp)
    _no_preview_state(vp)


# ---- copy mode ---------------------------------------------------------------

def _copy_drop(w, preview):
    """A mixed Move with Ctrl pressed mid-drag: what it leaves."""
    vp, objs = _scene(w, "loose")
    tool = _grab(w, vp, objs, "move")
    assert tool._vp_preview is preview
    _hover(vp, tool, "move", 0.5)
    tool._toggle_copy(vp, say=False)
    vp.repaint()
    if preview:
        # The original stays: everything drawn at rest, the bent faces
        # too (they are out of the static buffers).
        assert vp._preview_offset.toTuple() == (0.0, 0.0, 0.0)
        faces = tool.preview_faces()
        shown = [f for f in tool._bent_faces if not f.attrs.get("hidden")]
        assert len(faces) == len(shown) > 0
        for moved, f in zip(faces, shown):
            assert ([p.toTuple() for p in moved.vertices]
                    == [p.toTuple() for p in f.vertices])
    _hover(vp, tool, "move", 1.0, 40)
    _commit(vp, tool, "move")
    _app.processEvents()
    _no_preview_state(vp)
    sc = vp.scene
    return (_model(vp, objs), len(sc.groups), len(sc.mesh.faces),
            len(vp.history.undo_stack))


def test_a_mixed_copy_leaves_what_the_live_copy_leaves(monkeypatch):
    w = _window()
    try:
        frozen = _copy_drop(w, True)
    finally:
        _close_window(w)
    _live(monkeypatch)
    w = _window()
    try:
        live = _copy_drop(w, False)
    finally:
        _close_window(w)
    # The same copies and the same single step. The copies come in the
    # selection's order, a set's: compared in no order.
    assert frozen[1:] == live[1:]

    def canon(m):
        verts, faces, edges, objects = m
        return (sorted(verts), sorted(repr(f) for f in faces),
                sorted(tuple(sorted(e)) for e in edges),
                objects)
    assert canon(frozen[0]) == canon(live[0])


# ---- the cursor and the faces in motion -------------------------------------

@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_the_faces_in_motion_are_no_snap_target(win, tool_name):
    """Rotate and Scale leave the faces they bend or carry out of the
    snap (their centres, the plane under the cursor), as Move does: the
    preview draws them elsewhere, and the live drag shook on them."""
    vp, objs = _scene(win, "loose")
    mesh = vp.scene.mesh
    block = _block(mesh)
    tool = _grab(win, vp, objs, tool_name)
    want = {id(f) for f in mesh.faces
            if any(abs(v.position.x() - 4.5) <= 1.5 + 1e-6
                   and abs(v.position.y() - 4.5) <= 1.5 + 1e-6
                   for v in f.loop)}
    assert tool.moving_face_ids() == want
    assert {id(f) for f in block} <= want
    # No selected face's centre is offered or drawn while it moves.
    assert vp._selected_face_centers() == []
    tool.on_cancel(vp)
    assert tool.moving_face_ids() == set()
    assert len(vp._selected_face_centers()) == len(block)


# ---- what rides keeps its look ----------------------------------------------

def test_what_rides_keeps_the_selection_look(win):
    """The riding part keeps the look the live drag gives it: the selected
    faces their dots (as many as the static pass leaves out), the selected
    edges the selection colour, the others the edge colour."""
    vp, objs = _scene(win, "loose")
    mesh = vp.scene.mesh
    block = _block(mesh)
    inside = {id(f) for f in block}
    edges = [e for e in mesh.edges
             if e.faces and all(id(f) in inside for f in e.faces)]
    picked = [edges[0], edges[3]]
    vp.scene.select(block + picked + list(objs))
    vp.repaint()
    dots0 = vp._sel_faces_count
    win._tool_actions["move"].trigger()
    tool = vp.active_tool
    tool.on_click(_ctx(vp, CENTRE))
    vpv = vp._verts_preview
    vp.repaint()
    assert vp._sel_faces_count == 0               # all of them ride
    assert len(vpv["dots"]) // 12 == dots0
    assert sum(n for _f, _b, _s, n in vpv["dot_spans"]) == dots0
    ride_e = [e for e in mesh.edges
              if all(id(f) in vpv["hide"] for f in e.faces)
              and id(e) in vpv["hide_e"]
              and e.v0 in tool._verts and e.v1 in tool._verts]
    assert len(vpv["sel_edges"]) // 24 == len(
        [e for e in ride_e if e in picked]) == 2
    assert len(vpv["plain_edges"]) // 24 == len(ride_e) - 2
    # The orange scratch edges are the objects' alone.
    movers = [g for g in vp._placements() if id(g) in vp._preview_groups]
    assert vp._pv_edges_count == sum(
        len(vp._preview_chunk(g)["edges"]) // 12 for g in movers)
    tool.on_cancel(vp)


def _frame(vp):
    import numpy as np
    img = vp.grabFramebuffer().convertToFormat(
        vp.grabFramebuffer().Format.Format_RGB888)
    h, w = img.height(), img.width()
    a = np.frombuffer(img.constBits(), dtype=np.uint8)
    return a.reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3).copy()


def _shot(live, monkeypatch):
    """A frame mid-way through a mixed Move."""
    from views.viewport import Viewport
    if live:
        monkeypatch.setattr(Viewport, "begin_verts_preview",
                            lambda self, verts, groups=(): None)
    w = _window()
    try:
        w.resize(900, 700)
        _app.processEvents()
        vp, objs = _scene(w, "loose")
        tool = _grab(w, vp, objs, "move")
        assert tool._vp_preview is not live
        _hover(vp, tool, "move", 0.6)
        vp.repaint()
        _app.processEvents()
        out = _frame(vp)
        tool.on_cancel(vp)
    finally:
        _close_window(w)
        monkeypatch.undo()
    return out


def test_a_mixed_move_frame_looks_as_the_live_one(monkeypatch):
    """The frame a mixed Move draws from the previews and the one the live
    drag draws: alike but for the rasterised lines a pixel away (the
    riding edges drawn through a matrix, not from moved vertices). The
    selection's dots — none at all before — count the same."""
    import numpy as np
    a = _shot(False, monkeypatch)
    b = _shot(True, monkeypatch)
    if not (a != a[0, 0]).any():
        pytest.skip("this platform renders nothing offscreen")
    d = np.abs(a.astype(int) - b.astype(int)).max(axis=2)
    # A handful of pixels on lines, not whole faces.
    assert (d > 40).sum() < 0.01 * d.size

    def orange(x):
        r, g, bb = (x[..., i].astype(int) for i in range(3))
        return int(((r > 200) & (g > 70) & (g < 160) & (bb < 90)).sum())
    oa, ob = orange(a), orange(b)
    assert ob > 0 and abs(oa - ob) <= 0.15 * ob


# ---- a few loose faces beside the objects ---------------------------------

@pytest.mark.parametrize("tool_name", ["move", "rotate", "scale"])
def test_a_few_loose_faces_with_objects_preview_too(monkeypatch, tool_name):
    """Below the size a vertex drag alone previews from (BUILT_MIN_FACES),
    a mixed one still does: the live drag's cost is the objects. It lands
    where the typed operation lands. Vertices alone keep the live drag."""
    from views import array_bake
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 500)
    out = []
    for hover in (True, False):
        w = _window()
        try:
            out.append(_operate(w, "loose", tool_name, True, hover))
        finally:
            _close_window(w)
    assert out[0][:4] == out[1][:4]
    assert out[0][3] == 1
    w = _window()
    try:
        vp, objs = _scene(w, "loose")
        vp.scene.select(_block(vp.scene.mesh))
        w._tool_actions["move"].trigger()
        tool = vp.active_tool
        tool.on_click(_ctx(vp, CENTRE))
        assert not tool._vp_preview
        _no_preview_state(vp)
        tool.on_cancel(vp)
    finally:
        _close_window(w)
