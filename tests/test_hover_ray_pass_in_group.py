# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Inside an open group a Line hover casts the cursor's ray ONCE (#1392).

The snap engine reads the faces it may infer from — the group's own and the
rest of the model drawn around it (#1327) — and the «Face center» inference
(#736) and the tools' planes read the faces a click could pick. Both are the
same ray: each used to run its own Möller–Trumbore pass over the model, 13–21 %
of a hover inside a group. One pass over the union now answers both, each
masked after, and the answers are the same as two separate passes.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from views.viewport import Viewport

_app = QApplication.instance() or QApplication([])


def _box(mesh, s=1.0):
    pts = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
           V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)]
    return [mesh.add_face([pts[i] for i in q]) for q in quads]


def _window():
    """A plain group, a second group in front of part of it and a loose
    floor under both: the cursor meets the open group's faces, the other
    group's (a reference, not a pick) and the floor."""
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(900, 600)
    sc = vp.scene
    sc.clear()
    sc.mesh.add_face([V(-3, -3, 0), V(7, -3, 0), V(7, 4, 0), V(-3, 4, 0)])
    ma, mb = Mesh(), Mesh()
    _box(ma, 2.0)
    _box(mb, 1.0)
    a, b = Group(ma, name="A"), Group(mb, name="B")
    a.xform = QMatrix4x4()
    a.xform.translate(0.0, 0.0, 0.01)
    b.xform = QMatrix4x4()
    b.xform.translate(1.5, -1.5, 0.01)
    sc.groups += [a, b]
    sc.version += 1
    cam = vp.camera
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(35.0), math.radians(35.0)
    cam.target = V(1.5, 0.5, 0.5)
    cam.distance = 12.0
    win._activate_tool("line")
    return win, vp, a, b


def _count_cursor_passes(monkeypatch, vp, px, py):
    """How many per-face ray passes the cursor's own rays pay for in one
    hover — through the event's position and through its whole pixel
    (probe rays at other pixels and the single-t readings of the visible
    faces are not counted)."""
    want = set()
    for x, y in ((px, py), (float(round(px)), float(round(py)))):
        o, d = vp._pixel_to_ray(x, y)
        want.add((o.x(), o.y(), o.z(), d.x(), d.y(), d.z()))
    calls = []
    real = Viewport._ray_hits

    def spy(self, idx, origin, direction, ent_mask, reduce_global=False,
            reach=None, own=True):
        ray = (origin.x(), origin.y(), origin.z(),
               direction.x(), direction.y(), direction.z())
        if ray in want and not reduce_global and ent_mask is not idx.ent_vis:
            calls.append(ent_mask)
        return real(self, idx, origin, direction, ent_mask,
                    reduce_global=reduce_global, reach=reach, own=own)

    monkeypatch.setattr(Viewport, "_ray_hits", spy)
    # A fresh pointer: nothing kept from the hover before.
    vp._ray_union_memo = vp._ray_union_prev = None
    vp._hover_hits_cache = vp._infer_hits_cache = None
    vp._face_any_memo = vp._face_infer_memo = None
    vp._process_hover(QPointF(px, py), Qt.NoModifier)
    monkeypatch.setattr(Viewport, "_ray_hits", real)
    return len(calls)


def test_a_line_hover_inside_a_group_casts_the_cursor_ray_once(monkeypatch):
    from georef.datum import SceneDatum
    win, vp, a, _b = _window()
    try:
        vp.scene.georef = SceneDatum(-12.0464, -77.0428)
        vp.begin_group_edit(a)
        # Over the open group's top, over the other group, over the floor.
        for world in (V(0.5, 1.0, 2.01), V(2.0, -1.0, 1.01),
                      V(5.0, 2.0, 0.0)):
            px = vp._world_to_pixel(world)
            assert px is not None
            # A whole pixel, as a mouse gives it: the snap reads the
            # cursor at whole pixels, the reference pass before it at the
            # event's own position — here the same ray.
            n = _count_cursor_passes(monkeypatch, vp, float(round(px[0])),
                                     float(round(px[1])))
            assert n == 1, (world, n)
            # Between whole pixels (a fractional pointer): the references
            # read the event's position, the snap and the coordinate
            # readout (a georeferenced model) the whole pixel — one pass
            # each, not one more when they interleave.
            n = _count_cursor_passes(monkeypatch, vp, round(px[0]) + 0.4,
                                     round(px[1]) + 0.3)
            assert n == 2, (world, n)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_shared_pass_answers_as_two_separate_passes(monkeypatch):
    """Over a grid of cursor positions, each reading of the shared pass is
    the one its own pass gives: the same faces at the same t, in the same
    order, the same winner of each pick."""
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        idx = vp._pick_index(near="skip")
        assert Viewport._sel_infer_union(idx) is not None
        W, H = vp.width(), vp.height()
        met = {"sel": 0, "infer": 0}
        for j in range(12):
            for i in range(18):
                x, y = W * (0.05 + 0.9 * i / 17), H * (0.05 + 0.9 * j / 11)
                o, d = vp._pixel_to_ray(x, y)
                if o is None or d is None:
                    continue
                vp._ray_union_memo = vp._ray_union_prev = None
                shared = {w: Viewport._face_hits(vp, idx, o, d, w)
                          for w in ("infer", "sel")}
                with monkeypatch.context() as m:
                    m.setattr(Viewport, "_sel_infer_union",
                              staticmethod(lambda _idx: None))
                    alone = {w: Viewport._face_hits(vp, idx, o, d, w)
                             for w in ("sel", "infer")}
                for w in ("sel", "infer"):
                    s, t = shared[w], alone[w]
                    assert (s is None) == (t is None)
                    if s is None:
                        continue
                    assert np.array_equal(s.t, t.t)
                    assert np.array_equal(s.area, t.area)
                    for k in range(len(s.t)):
                        assert s.ent(k)[0] is t.ent(k)[0]
                        assert s.place(k) is t.place(k)
                    if len(s.t) and np.isfinite(s.t).any():
                        met[w] += 1
        # The grid really met both kinds of face.
        assert met["sel"] > 10 and met["infer"] > met["sel"]
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_the_shared_pass_follows_an_edit(monkeypatch):
    """The memo is per scene version: after an edit the same ray is cast
    again, not answered from before."""
    win, vp, a, _b = _window()
    try:
        vp.begin_group_edit(a)
        px = vp._world_to_pixel(V(0.5, 1.0, 2.01))
        o, d = vp._pixel_to_ray(px[0], px[1])
        idx = vp._pick_index(near="skip")
        Viewport._face_hits(vp, idx, o, d, "infer")
        memo = getattr(vp, "_ray_union_memo", None)
        assert memo is not None and memo[1] is not None
        vp.scene.version += 1
        idx = vp._pick_index(near="skip")
        Viewport._face_hits(vp, idx, o, d, "sel")
        assert getattr(vp, "_ray_union_memo", None) is not memo
    finally:
        win._saved_version = vp.scene.version
        win.close()


def _big_group_window():
    """An open group of ~10 000 faces (a grid of small squares on a wavy
    sheet, two triangles each): more triangles than the span grid's
    threshold, all of them loose while the group is open."""
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(900, 600)
    sc = vp.scene
    sc.clear()
    m = Mesh()
    n = 70
    for i in range(n):
        for j in range(n):
            z0 = 0.3 * math.sin(i * 0.3) * math.cos(j * 0.2)
            m.add_face([V(i, j, z0), V(i + 1, j, z0), V(i + 1, j + 1, z0),
                        V(i, j + 1, z0)])
    g = Group(m, name="Sheet")
    g.xform = QMatrix4x4()
    sc.groups.append(g)
    sc.version += 1
    cam = vp.camera
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(30.0), math.radians(40.0)
    cam.target = V(35.0, 35.0, 0.0)
    cam.distance = 90.0
    win._activate_tool("line")
    return win, vp, g


def test_an_open_big_groups_faces_are_on_the_span_grid(monkeypatch):
    """The open group's own faces are the loose part of the pick index: on
    the span grid, as a closed group's chunk is, a ray tests the cells it
    crosses — and answers as over one span, per entity and nearest."""
    import views.viewport as vv
    win, vp, g = _big_group_window()
    try:
        vp.begin_group_edit(g)
        idx = vp._pick_index(near="skip")
        n_loose = len(idx.entities)
        spans = idx.tri_spans
        assert spans is not None and len(spans) > 1
        assert all(bb is not None for bb, _s, _n in spans)
        assert sum(c for _bb, _s, c in spans) == len(idx.tri_v0)
        W, H = vp.width(), vp.height()
        rays = [vp._pixel_to_ray(W * (0.1 + 0.8 * i / 9),
                                 H * (0.1 + 0.8 * j / 6))
                for i in range(10) for j in range(7)]
        grid = [(Viewport._ray_hits(vp, idx, o, d, idx.ent_vis),
                 Viewport._ray_hits(vp, idx, o, d, idx.ent_vis,
                                    reduce_global=True)) for o, d in rays]
        # The same model without the grid: one span for the loose part.
        monkeypatch.setattr(vv, "_NO_SPAN_GRID", True)
        vp._pick_loose_memo = None
        vp._pick_index_cache = None
        flat = vp._pick_index(near="skip")
        assert len(flat.entities) == n_loose
        assert flat.tri_spans[0][0] is None
        met = 0
        for (o, d), (per, near) in zip(rays, grid):
            per1 = Viewport._ray_hits(vp, flat, o, d, flat.ent_vis)
            near1 = Viewport._ray_hits(vp, flat, o, d, flat.ent_vis,
                                       reduce_global=True)
            assert np.array_equal(per, per1)
            assert near == near1
            met += bool(np.isfinite(near))
        assert met > 30
    finally:
        win._saved_version = vp.scene.version
        win.close()
