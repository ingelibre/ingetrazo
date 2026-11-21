# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A prism push previews by sliding the cap in the model and slides it back
before each distance inference (Block 6 of 0.6.3). The cap is put back AT
its starting bits, not by arithmetic: after any number of frames it holds
them exactly, and releasing the drag gives the very model a typed push of
the same distance gives. Back at rest, the pick index made for the first
frame answers again instead of a rebuild per pointer move — and it is, array
for array, the index a rebuild makes, on a loose mesh and inside an open
group, with the engine and without."""
from __future__ import annotations

import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.base import ToolContext  # noqa: E402

_app = QApplication.instance() or QApplication([])

RINGS = [
    [(-1, -1, 0), (-1, 1, 0), (1, 1, 0), (1, -1, 0)],
    [(-1, -1, 2), (1, -1, 2), (1, 1, 2), (-1, 1, 2)],
    [(-1, -1, 0), (1, -1, 0), (1, -1, 2), (-1, -1, 2)],
    [(1, -1, 0), (1, 1, 0), (1, 1, 2), (1, -1, 2)],
    [(1, 1, 0), (-1, 1, 0), (-1, 1, 2), (1, 1, 2)],
    [(-1, 1, 0), (-1, -1, 0), (-1, -1, 2), (-1, 1, 2)],
]


def _bits(p):
    return struct.pack("<3f", p.x(), p.y(), p.z())


def _drag(where):
    """A box (its top a prism cap, at awkward coordinates so float32 sums
    round) beside a tiled floor, loose or in an open group; Push/Pull has
    clicked the top."""
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(900, 640)
    vp.flash_status = lambda *a, **k: None
    sc = vp.scene
    sc.guides.clear()
    mesh = Mesh() if where == "group" else sc.mesh
    # The cap near z = 0, on fine float32 bits of its own: pushed metres
    # out, each sum rounds on a coarser grid than the cap stands on, and an
    # arithmetic slide back would drift.
    def at(x, y, z):
        return V(0.1234567 + 1.37 * x, -0.7654321 + 1.37 * y,
                 0.0117 if z else -1.3)
    faces = [mesh.add_face([at(*p) for p in ring]) for ring in RINGS]
    s = 0.31
    for i in range(14):
        for j in range(14):
            x0, y0 = 3.1 + i * s, -2.9 + j * s
            mesh.add_face([V(x0, y0, 0.1), V(x0 + s, y0, 0.1),
                           V(x0 + s, y0 + s, 0.1), V(x0, y0 + s, 0.1)])
    if where == "group":
        g = Group(mesh, name="host")
        sc.groups.append(g)
    sc.version += 1
    if where == "group":
        vp.begin_group_edit(g)
    vp.camera.target = V(2.0, 0.0, 1.0)
    vp.camera.distance = 14.0
    win._activate_tool("pushpull")
    tool = vp.active_tool
    top = faces[1]
    at = top.centroid()
    px = vp._world_to_pixel(at)
    vp._process_hover(QPointF(*px), Qt.NoModifier)
    tool.hovered_face = top
    tool.on_click(ToolContext(vp, at, QPointF(*px), Qt.NoModifier, None))
    assert tool._prism_cap and tool.dragging
    start = [_bits(v.position) for v in tool._prism_verts]
    return win, vp, tool, px, start


@pytest.fixture(params=["loose", "group"])
def drag(request):
    win, vp, tool, px, start = _drag(request.param)
    try:
        yield vp, tool, px, start
    finally:
        if tool.dragging:
            tool.on_cancel(vp)
        win._saved_version = vp.scene.version
        win.close()


def _hover(vp, px, k):
    # Up and back down, so the cap goes out, in and out again.
    dy = 7.0 * (k if k < 25 else 50 - k)
    vp._process_hover(QPointF(px[0] + 0.37 * k, px[1] - 3.0 - dy),
                      Qt.NoModifier)


def _arrays(idx):
    names = ("tri_v0", "tri_e1", "tri_e2", "tri_ent", "ent_area", "ent_vis",
             "ent_sel", "ent_infer", "ent_loose", "edge_a", "edge_b",
             "edge_sel", "edge_snap", "edge_soft", "gedge_a", "gedge_b")
    out = []
    for n in names:
        a = getattr(idx, n, None)
        out.append(None if a is None else np.asarray(a).tobytes())
    out.append(tuple((sp[1], sp[2]) for sp in (idx.tri_spans or ())))
    out.append([id(e[0]) for e in idx.entities])
    out.append([id(e) for e in idx.edges])
    return out


def _rebuilt(vp):
    """The pick index made from scratch for the model as it is now."""
    saved = {k: getattr(vp, k, None) for k in (
        "_pick_index_cache", "_pick_index_prev", "_pick_loose_memo",
        "_pick_geom_alias", "_pick_rest")}
    for k in saved:
        setattr(vp, k, None)
    try:
        return vp._pick_index(near="skip")
    finally:
        for k, v in saved.items():
            setattr(vp, k, v)


def test_the_cap_slides_back_to_its_very_starting_bits(drag):
    vp, tool, px, start = drag
    for k in range(40):
        _hover(vp, px, k)
        assert tool._prism_applied != 0.0
    tool._revert_prism_preview(vp)
    assert [_bits(v.position) for v in tool._prism_verts] == start


def test_at_rest_the_pick_index_is_the_one_a_rebuild_makes(drag):
    vp, tool, px, _start = drag
    _hover(vp, px, 0)
    first = vp._pick_index(near="skip")      # the moved cap's index
    rest = None
    served = 0
    for k in range(1, 30):
        _hover(vp, px, k)
        # The moved cap: its own index, a rebuild's.
        moved = vp._pick_index(near="skip")
        assert moved is not first
        assert _arrays(moved) == _arrays(_rebuilt(vp))
        # Back at rest, as the distance inference reads it.
        tool._revert_prism_preview(vp)
        tool._note_prism_rest(vp)
        idx = vp._pick_index(near="skip")
        if rest is None:
            rest = idx
        served += idx is rest
        assert _arrays(idx) == _arrays(_rebuilt(vp))
        # Back out where the frame had it.
        tool._show_prism_preview(vp)
    assert served >= 28                      # kept, not made again


def test_the_drag_infers_what_rebuilding_the_index_infers(monkeypatch):
    """The same pointer path with the rest index kept and with a rebuild per
    move: the same distance on every frame, the same snap shown."""
    from views.viewport import Viewport
    runs = []
    for keep in (True, False):
        with monkeypatch.context() as m:
            if not keep:
                m.setattr(Viewport, "note_same_geometry",
                          lambda self, same_as: None)
            win, vp, tool, px, _start = _drag("group")
            try:
                got = []
                for k in range(40):
                    _hover(vp, px, k)
                    snap = vp.last_snap
                    got.append((struct.pack("<d", tool.extrusion),
                                getattr(snap, "kind", None),
                                None if snap is None or snap.point is None
                                else _bits(snap.point)))
                runs.append(got)
            finally:
                tool.on_cancel(vp)
                win._saved_version = vp.scene.version
                win.close()
    assert runs[0] == runs[1]


def _model(vp):
    mesh = vp.scene.edit_group.mesh if vp.scene.edit_group else vp.scene.mesh
    return (sorted(_bits(v.position) for v in mesh.vertices),
            len(mesh.edges), len(mesh.faces))


@pytest.mark.parametrize("where", ["loose", "group"])
def test_releasing_the_drag_gives_the_typed_push(where):
    win, vp, tool, px, _start = _drag(where)
    try:
        for k in range(37):
            _hover(vp, px, k)
        e = tool.extrusion
        assert e != 0.0
        tool._commit(vp)
        assert not tool.dragging
        dragged = _model(vp)
    finally:
        win._saved_version = vp.scene.version
        win.close()
    win, vp, tool, px, _start = _drag(where)
    try:
        assert tool.on_value(vp, e)
        assert _model(vp) == dragged
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_an_edit_during_the_drag_ends_the_kept_index(drag):
    vp, tool, px, _start = drag
    for k in range(3):
        _hover(vp, px, k)
    vp.scene.version += 1                    # someone else's edit
    for k in range(3, 6):
        _hover(vp, px, k)
    assert tool._prism_rest_ver is False
    tool._revert_prism_preview(vp)
    tool._note_prism_rest(vp)
    assert getattr(vp, "_pick_geom_alias", (None,))[0] != vp.scene.geometry_version
