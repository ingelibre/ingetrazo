# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A drag of vertices of a big open group previews from frozen arrays
(``Viewport.begin_verts_preview``, night of 18-11): nothing is mutated
until the commit, the open mesh is baked once in two parts — what stays
and what rides the drag — and the faces the drag stretches are drawn
moved by the tool. The two parts hold every face and edge of the mesh
exactly once, the commit lands where the old live drag landed, a cancel
leaves the mesh as it was, and a mesh drawn twice keeps the old drag."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
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


def _grid_group(win, n=8, copies=False):
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh
    vp = win.viewport
    m = Mesh()
    for i in range(n):
        for j in range(n):
            f = m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                            V(i, j + 1, 0)])
            if (i + j) % 3 == 0:
                f.attrs["color"] = [0.8, 0.2, 0.1]
    m.add_edge(V(0, -2, 0), V(3, -2, 0))
    g = Group(m, "big")
    vp.scene.groups.append(g)
    if copies:
        g.component = True
        b = Group(m, "big")
        b.component = True
        xf = QMatrix4x4()
        xf.translate(30, 0, 0)
        b.xform = xf
        vp.scene.groups.append(b)
    vp.scene.version += 1
    vp.begin_group_edit(g)
    _app.processEvents()
    return vp


def _block(mesh, i0, i1):
    """The faces of the grid with i0 <= x < i1: a block to move."""
    return [f for f in mesh.faces
            if all(i0 - 1e-6 <= v.position.x() <= i1 + 1e-6 for v in f.loop)
            and abs(f.centroid().z()) < 1e-6]


def _positions(mesh):
    return sorted((round(v.position.x(), 5), round(v.position.y(), 5),
                   round(v.position.z(), 5)) for v in mesh.vertices)


def test_the_two_parts_hold_the_mesh_once(win):
    vp = _grid_group(win)
    mesh = vp.scene.mesh
    block = _block(mesh, 2, 4)
    verts = list({id(v): v for f in block for v in f.loop}.values())
    got = vp.begin_verts_preview(verts)
    assert got is not None
    bent, bent_e, _paint = got
    vpv = vp._verts_preview
    stay = vpv["stay"]
    ride = {id(f) for f in block}
    assert vpv["hide"] == ride | {id(f) for f in bent}
    assert {id(f) for f in stay["faces"]}.isdisjoint(vpv["hide"])
    assert ({id(f) for f in stay["faces"]} | vpv["hide"]
            == {id(f) for f in mesh.faces})
    # Every stretched face has a corner on each side.
    moving = {id(v) for v in verts}
    for f in bent:
        ids = [id(v) in moving for v in f.loop]
        assert any(ids) and not all(ids)
    for e in bent_e:
        assert (id(e.v0) in moving) != (id(e.v1) in moving)
    # The open group draws what stays; the cached bake of the whole mesh
    # is not touched.
    assert vp._group_chunk(vp.scene.edit_group) is stay
    vp.end_verts_preview()
    assert vp._verts_preview is None
    assert vp._group_chunk(vp.scene.edit_group) is not stay


def _ctx(vp, world, x=10):
    from PySide6.QtCore import QPointF
    from tools.base import ToolContext
    return ToolContext(viewport=vp, world=world, screen=QPointF(x, 10),
                       modifiers=Qt.NoModifier, snap=None)


def _drag(win, vp, faces):
    """Select ``faces`` and grab them with Move at the first's centre."""
    vp.scene.select(faces)
    win._tool_actions["move"].trigger()
    tool = vp.active_tool
    ctx = _ctx(vp, faces[0].centroid())
    tool.on_click(ctx)
    return tool, ctx


def test_a_drag_commits_where_the_live_drag_did(win, monkeypatch):
    results = []
    for preview in (True, False):
        vp = _grid_group(win)
        if not preview:
            monkeypatch.setattr(type(vp), "begin_verts_preview",
                                lambda self, verts: None)
        mesh = vp.scene.mesh
        block = _block(mesh, 2, 4)
        tool, ctx = _drag(win, vp, block)
        assert tool._vp_preview is preview
        before = _positions(mesh)
        for k in range(1, 4):
            tool.on_hover(_ctx(vp, ctx.world + V(0.1 * k, 0, 0.25 * k),
                               10 + k))
            _app.processEvents()
            if preview:
                assert _positions(mesh) == before      # nothing mutated
                assert tool.preview_faces()            # the stretched faces
        tool._commit(vp, V(0.3, 0, 0.75))
        _app.processEvents()
        assert vp._verts_preview is None
        results.append(_positions(mesh))
        vp.end_group_edit()
        vp.scene.groups.clear()
        vp.scene.version += 1
        monkeypatch.undo()
    assert results[0] == results[1]


def test_a_cancel_leaves_the_mesh_as_it_was(win):
    vp = _grid_group(win)
    mesh = vp.scene.mesh
    before = _positions(mesh)
    block = _block(mesh, 0, 3)
    tool, ctx = _drag(win, vp, block)
    assert tool._vp_preview
    tool.on_hover(_ctx(vp, ctx.world + V(0, 0, 2), 30))
    tool.on_cancel(vp)
    _app.processEvents()
    assert vp._verts_preview is None
    assert _positions(mesh) == before


def test_a_mesh_drawn_twice_keeps_the_live_drag(win):
    vp = _grid_group(win, copies=True)
    mesh = vp.scene.mesh
    block = _block(mesh, 2, 4)
    verts = list({id(v): v for f in block for v in f.loop}.values())
    assert vp.begin_verts_preview(verts) is None
    assert getattr(vp, "_verts_preview", None) is None


def test_the_stretched_faces_are_drawn_moved(win):
    vp = _grid_group(win)
    mesh = vp.scene.mesh
    block = _block(mesh, 2, 4)
    tool, ctx = _drag(win, vp, block)
    d = V(0.0, 0.0, 0.5)
    tool.on_hover(_ctx(vp, ctx.world + d, 30))
    moving = {id(v) for f in block for v in f.loop}
    shown = tool.preview_faces()
    assert len(shown) == len(tool._bent_faces)
    delta = tool._preview_delta
    for pf, f in zip(shown, [f for f in tool._bent_faces
                             if not f.attrs.get("hidden")]):
        for p, v in zip(pf.vertices, f.loop):
            want = v.position + delta if id(v) in moving else v.position
            assert (p - want).length() < 1e-9
    # Painted faces keep their colour in the preview.
    assert any((pf.attrs or {}).get("color") for pf in shown)
    tool.on_cancel(vp)
    assert np.isfinite(delta.length())
