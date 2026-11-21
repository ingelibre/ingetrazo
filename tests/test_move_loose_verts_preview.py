# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Move of vertices of the loose model (no group open) previews from
frozen arrays, as one inside an open group does (``begin_verts_preview``,
21-11): the sync that starts the drag leaves out of the loose buffers what
rides and what bends, and no frame after it walks the loose model again
(each frame re-walked the whole of it, ~0.33 s on a 6 400-face floor).
Nothing is mutated until the commit, which lands on the same model with
the same undo step the live drag made; a cancel leaves it as it was; a
soft edge riding keeps the live drag."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402

_app = QApplication.instance() or QApplication([])

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")


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


def _floor(win, n=10):
    vp = win.viewport
    m = vp.scene.mesh
    for i in range(n):
        for j in range(n):
            f = m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                            V(i, j + 1, 0)])
            if (i + j) % 4 == 0:
                f.attrs["color"] = [0.2, 0.5, 0.8]
    m.add_edge(V(0, -2, 0), V(4, -2, 0))
    vp.scene.version += 1
    vp.repaint()
    _app.processEvents()
    return vp


def _block(mesh, i0, i1):
    return [f for f in mesh.faces
            if all(i0 - 1e-6 <= v.position.x() <= i1 + 1e-6 for v in f.loop)]


def _ctx(vp, world, x=10):
    from tools.base import ToolContext
    return ToolContext(viewport=vp, world=world, screen=QPointF(x, 10),
                       modifiers=Qt.NoModifier, snap=None)


def _grab(win, vp, faces):
    vp.scene.select(faces)
    win._tool_actions["move"].trigger()
    tool = vp.active_tool
    ctx = _ctx(vp, faces[0].centroid())
    tool.on_click(ctx)
    return tool, ctx


def _model(mesh):
    """The model exactly: every vertex, and every face's corners and look,
    in mesh order."""
    return ([v.position.toTuple() for v in mesh.vertices],
            [([v.position.toTuple() for v in f.loop],
              [[v.position.toTuple() for v in h] for h in f.hole_loops],
              repr(sorted(f.attrs.items()))) for f in mesh.faces],
            sorted((e.v0.position.toTuple(), e.v1.position.toTuple())
                   for e in mesh.edges))


def _fresh_window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    return w


def _close(a, b, tol=1e-5):
    """Two ``_model``s alike to ``tol``: same vertices, faces, rings and
    looks, positions within a float32 rounding."""
    pa, fa, ea = a
    pb, fb, eb = b
    assert len(pa) == len(pb) and len(fa) == len(fb) and len(ea) == len(eb)
    assert all(abs(x - y) < tol for p, q in zip(pa, pb)
               for x, y in zip(p, q))
    for (la, ha, ta), (lb, hb, tb) in zip(fa, fb):
        assert len(la) == len(lb) and ta == tb
        assert [len(h) for h in ha] == [len(h) for h in hb]


def _drag_and_drop(w, delta, preview, hover):
    """``(model moved, model undone, model redone, undo steps)`` of a Move
    of a block of the loose floor by ``delta``."""
    vp = _floor(w)
    mesh = vp.scene.mesh
    start = _model(mesh)
    tool, ctx = _grab(w, vp, _block(mesh, 3, 6))
    assert tool._vp_preview is preview
    if preview:
        assert vp._verts_preview["loose"]
    undo_before = len(vp.history.undo_stack)
    if hover:
        for k in range(1, 4):
            tool.on_hover(_ctx(vp, ctx.world + delta * (k / 3.0), 10 + k))
            vp.repaint()
            if preview:
                assert _model(mesh) == start           # nothing mutated
    tool._commit(vp, delta)
    _app.processEvents()
    assert getattr(vp, "_verts_preview", None) is None
    steps = len(vp.history.undo_stack) - undo_before
    moved = _model(mesh)
    vp.history.undo()
    undone = _model(mesh)
    _close(undone, start)
    vp.history.redo()
    return moved, undone, _model(mesh), steps


@pytest.mark.parametrize("delta", [V(0.3, 0, 0.75), V(0, 0, 2.0),
                                   V(-0.25, 0.5, 0)])
def test_a_loose_drag_commits_and_undoes_as_the_live_drag(win, monkeypatch,
                                                         delta):
    frozen = _drag_and_drop(win, delta, preview=True, hover=True)
    monkeypatch.setattr(type(win.viewport), "begin_verts_preview",
                        lambda self, verts: None)
    out = []
    for hover in (False, True):
        w = _fresh_window()
        try:
            out.append(_drag_and_drop(w, delta, preview=False, hover=hover))
        finally:
            w._saved_version = w.viewport.scene.version
            w.close()
    typed, live = out
    assert frozen[3] == typed[3] == live[3] == 1       # one undo step
    # The frozen drag lands exactly where a move with no hover lands (the
    # mesh is moved once, by the offset) ...
    assert frozen[:3] == typed[:3]
    assert frozen[0] == frozen[2]
    # ... and where the live drag lands but for the float32 rounding its
    # per-frame steps and their revert left behind.
    for a, b in zip(frozen[:3], live[:3]):
        _close(a, b)


def test_the_loose_buffers_leave_out_what_moves(win):
    vp = _floor(win)
    mesh = vp.scene.mesh
    faces0, edges0 = vp._faces_count, vp._edges_count
    assert faces0 == 6 * len(mesh.faces)
    tool, ctx = _grab(win, vp, _block(mesh, 3, 6))
    vpv = vp._verts_preview
    assert vpv is not None and vpv["loose"] and vpv["stay"] is None
    vp.repaint()
    assert vp._faces_count == faces0 - 6 * len(vpv["hide"])
    assert vp._edges_count == edges0 - 2 * len(vpv["hide_e"])
    # No frame after it walks the loose model.
    walked = []
    real = vp._tris_of
    vp._tris_of = lambda f: walked.append(f) or real(f)
    for k in range(1, 5):
        tool.on_hover(_ctx(vp, ctx.world + V(0, 0, 0.2 * k), 20 + k))
        vp.repaint()
    assert not walked
    assert tool.preview_faces()                  # the stretched faces drawn
    del vp._tris_of
    tool.on_cancel(vp)
    vp.repaint()
    assert vp._verts_preview is None
    assert vp._faces_count == faces0 and vp._edges_count == edges0


def test_a_cancel_leaves_the_loose_model(win):
    vp = _floor(win)
    mesh = vp.scene.mesh
    start = _model(mesh)
    tool, ctx = _grab(win, vp, _block(mesh, 0, 4))
    assert tool._vp_preview
    tool.on_hover(_ctx(vp, ctx.world + V(1, 1, 1), 30))
    vp.repaint()
    tool.on_cancel(vp)
    _app.processEvents()
    assert vp._verts_preview is None
    assert _model(mesh) == start


def test_a_soft_edge_riding_keeps_the_live_drag(win):
    vp = _floor(win)
    mesh = vp.scene.mesh
    block = _block(mesh, 3, 6)
    e = next(e for f in block for e in f.loop[0].edges)
    e.soft = True
    vp.scene.version += 1
    tool, _ctx0 = _grab(win, vp, block)
    assert not tool._vp_preview
    assert getattr(vp, "_verts_preview", None) is None
    tool.on_cancel(vp)


def test_an_open_group_still_draws_its_static_part(win):
    """The open-group drag keeps its own static chunk (the loose path
    takes none)."""
    from core.group import Group
    from core.mesh import Mesh
    vp = win.viewport
    m = Mesh()
    for i in range(6):
        for j in range(6):
            m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                        V(i, j + 1, 0)])
    g = Group(m, "g")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    vp.begin_group_edit(g)
    _app.processEvents()
    tool, _c = _grab(win, vp, _block(vp.scene.mesh, 2, 4))
    vpv = vp._verts_preview
    assert vpv is not None and not vpv["loose"] and vpv["stay"] is not None
    assert vp._group_chunk(vp.scene.edit_group) is vpv["stay"]
    tool.on_cancel(vp)
