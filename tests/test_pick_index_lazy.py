# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pick index takes component placements lazily on a big model (issue
#158): only those near the query are baked, under a cap. Here the threshold
is lowered so a small scene runs in that mode, and every answer is compared
with the ordinary index."""
from __future__ import annotations

import math
import sys

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _cube():
    from core.mesh import Mesh
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    return m


@pytest.fixture
def vp():
    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    v = win.viewport
    v.resize(1000, 700)
    v.scene.guides.clear()
    proto = _cube()
    for i in range(6):
        for j in range(4):
            g = Group(proto, name=f"C{i}{j}")
            m = QMatrix4x4()
            m.translate(3.0 * i, 3.0 * j, 0.0)
            if (i + j) % 3 == 0:
                m.scale(-1.0, 1.0, 1.0)              # some mirrored
            g.xform = m
            v.scene.groups.append(g)
    v.scene.version += 1
    v.camera.set_view("top")
    v.camera.perspective = False
    v.camera.fit_to(V(-2, -2, 0), V(18, 12, 1))
    try:
        yield v
    finally:
        win._saved_version = v.scene.version
        win.close()


def _lazy(v, on, cap=None):
    v._PICK_LAZY_MIN_FACES = 1 if on else 10 ** 12
    if cap is not None:
        v._PICK_LIVE_MAX_FACES = cap
    v._pick_index_cache = None
    v._pick_block = None
    v._pick_lazy_memo = None
    v._pick_near_memo = None
    v._pick_live = None
    v._pick_foot_keep = None
    getattr(v, "_inst_chunks", {}).clear()
    v._hover_hits_cache = None


def _centre(v, name):
    g = next(g for g in v.scene.groups if g.name == name)
    c = g.xform.map(V(0.5, 0.5, 1.0))
    return V(c.x(), c.y(), 1.0)


def _answers(v, pts):
    out = []
    for p in pts:
        x, y = v._world_to_pixel(p)
        f, pl = v.pick_face_placement(x, y)
        g = v.pick_group(x, y)
        where = None
        if f is not None:
            c = f.centroid()
            if pl is not None and getattr(pl, "xform", None) is not None:
                c = pl.xform.map(c)
            where = (round(c.x(), 4), round(c.y(), 4), round(c.z(), 4))
        out.append((where, g.name if g is not None else None))
    return out


def test_lazy_answers_equal_the_full_index(vp):
    pts = [_centre(vp, f"C{i}{j}") for i in range(6) for j in range(4)]
    pts += [V(1.5, 1.5, 0.0), V(-1.0, -1.0, 0.0)]           # gaps
    _lazy(vp, False)
    full = _answers(vp, pts)
    _lazy(vp, True)
    lazy = _answers(vp, pts)
    assert lazy == full


def _baking(monkeypatch):
    # What the index bakes for a ray: with the experimental engine a ray
    # bakes nothing (it answers for the lazy placements itself), so these
    # watch the path that runs without it.
    import views.viewport as vpm
    monkeypatch.setattr(vpm, "_LAZY_NATIVE", False)


def test_only_the_placements_near_the_cursor_are_baked(vp, monkeypatch):
    _baking(monkeypatch)
    _lazy(vp, True)
    x, y = vp._world_to_pixel(_centre(vp, "C10"))
    vp.pick_face_any(x, y)
    live = vp._pick_live
    assert 0 < len(live) < 24
    baked = [k for k in getattr(vp, "_inst_chunks", {})]
    assert len(baked) <= len(live)


def test_the_cap_lets_old_ones_go(vp):
    _lazy(vp, True, cap=12)                   # two cubes' worth of faces
    for i in range(6):
        x, y = vp._world_to_pixel(_centre(vp, f"C{i}0"))
        assert vp.pick_group(x, y).name == f"C{i}0"
    assert sum(n for _g, n in vp._pick_live.values()) <= 12 + 6


def test_everything_when_the_whole_model_is_asked_for(vp):
    _lazy(vp, True)
    vp._pick_index(near="all")
    assert len(vp._pick_live) == 24


def test_a_ray_bakes_what_it_crosses(vp):
    _lazy(vp, True)
    c = _centre(vp, "C21")
    d = vp.ray_distance(V(c.x(), c.y(), 10.0), V(0, 0, -1))
    assert d == pytest.approx(9.0, abs=1e-5)                 # top of C21


def test_a_bounded_ray_bakes_only_what_it_can_reach(vp, monkeypatch):
    _baking(monkeypatch)
    # Along the row j = 0 at mid-height: C00 (mirrored, x in [-1, 0]) is
    # 2 m from the origin, C10 6 m, … C50 18 m. The walkthrough's wall
    # feelers ask half a metre ahead; an unbounded ray baked every one of
    # them, and turning the head brought in new ones (index rebuilt).
    o, d = V(-3.0, 0.5, 0.5), V(1.0, 0.0, 0.0)
    _lazy(vp, True)
    assert vp.ray_distance(o, d, 2.5) == pytest.approx(2.0, abs=1e-5)
    assert set(vp._pick_live) == {id(next(g for g in vp.scene.groups
                                          if g.name == "C00"))}
    assert vp.ray_distance(o, d, 1.5) is None              # out of reach
    _lazy(vp, True)
    assert vp.ray_distance(o, d) == pytest.approx(2.0, abs=1e-5)
    assert len(vp._pick_live) == 6                          # the whole row


def _near_edges(v, x, y):
    got = v._nearby_group_edges(x, y) or []
    return sorted((round(e.a.x(), 4), round(e.a.y(), 4), round(e.a.z(), 4),
                   round(e.b.x(), 4), round(e.b.y(), 4), round(e.b.z(), 4))
                  for e in got)


def test_the_edges_near_the_cursor_for_the_snap_are_the_same(vp):
    probes = [_centre(vp, n) for n in ("C00", "C21", "C53")]
    probes = [V(p.x() + 0.45, p.y(), 1.0) for p in probes]  # near an edge
    _lazy(vp, False)
    full = [_near_edges(vp, *vp._world_to_pixel(p)) for p in probes]
    _lazy(vp, True)
    lazy = [_near_edges(vp, *vp._world_to_pixel(p)) for p in probes]
    assert lazy == full and all(full)


def test_occlusion_is_the_same(vp):
    vp.camera.set_view("iso") if hasattr(vp.camera, "set_view") else None
    vp.camera.fit_to(V(-2, -2, 0), V(18, 12, 1))
    probes = []
    for n in ("C10", "C32", "C43"):
        c = _centre(vp, n)
        probes += [V(c.x(), c.y(), 0.0), V(c.x(), c.y(), 1.0),
                   V(c.x() + 0.5, c.y() + 0.5, 0.5)]
    def run():
        out = []
        for p in probes:
            vp._last_mouse_pos = None
            from PySide6.QtCore import QPointF
            vp._last_mouse_pos = QPointF(*vp._world_to_pixel(p))
            out.append(vp._is_occluded(p))
        return out
    _lazy(vp, False)
    full = run()
    _lazy(vp, True)
    assert run() == full


def test_with_a_frame_on_screen_the_depth_cull_changes_no_answer(vp):
    """With a painted frame the lazy mode also leaves out placements wholly
    behind what the screen shows; picks and snap edges stay the same."""
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.platformName() == "offscreen":
        # The offscreen platform opens a compatibility-profile context whose
        # instanced draw of many placements crashes in the driver (it did
        # before 0.5.7 too; xcb, hardware or llvmpipe, draws them fine).
        pytest.skip("instanced draw needs a real window platform")
    win = vp.window()
    win.show()
    for _ in range(10):
        QApplication.processEvents()
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    vp.camera.set_view("iso") if hasattr(vp.camera, "set_view") else None
    vp.camera.fit_to(V(-2, -2, 0), V(18, 12, 1))
    vp.grabFramebuffer()
    if vp._depth_world_at(10, 10) is None:
        pytest.skip("this GL context gives no depth read-back")
    pts = [_centre(vp, f"C{i}{j}") for i in range(6) for j in range(4)]
    _lazy(vp, False)
    full = _answers(vp, pts)
    full_e = [_near_edges(vp, *vp._world_to_pixel(p)) for p in pts[:6]]
    _lazy(vp, True)
    assert _answers(vp, pts) == full
    assert [_near_edges(vp, *vp._world_to_pixel(p)) for p in pts[:6]] == full_e


def _owner_holds(e):
    """Whether a group pseudo-edge lies on the cube its owner places."""
    inv, ok = e.group.xform.inverted()
    assert ok
    return all(-1e-4 <= c <= 1 + 1e-4
               for p in (inv.map(e.a), inv.map(e.b))
               for c in (p.x(), p.y(), p.z()))


#: Where four cubes meet around the cursor (and one beside a single cube):
#: each query bakes one more and the cap lets an earlier one go, so the
#: lazy part of the index changes order between two queries.
_GAPS = [V(1.6, 1.6, 1.0), V(7.6, 4.6, 1.0), V(1.6, 7.6, 1.0),
         V(13.6, 4.6, 1.0), V(4.6, 1.6, 1.0), V(10.6, 7.6, 1.0),
         V(1.45, 0.5, 1.0)]


def test_the_snap_edges_come_from_the_index_they_were_measured_on(vp):
    # The SPR of #158, hovering with Line: the candidates were measured on
    # the index as it stood and then read from the one a second query
    # baked — under the cap that one had let others go, so an edge came
    # with another group's owner, or past the end ("index 1281112 is out
    # of bounds for axis 0 with size 1247456").
    _lazy(vp, True, cap=12)                             # two cubes at most
    vp._PICK_NEW_PER_QUERY = 1                          # one more per query
    for p in _GAPS:
        x, y = vp._world_to_pixel(p)
        for e in vp._nearby_group_edges(x, y):
            assert _owner_holds(e)
            pa, pb = vp._world_to_pixel(e.a), vp._world_to_pixel(e.b)
            from core.snap import _closest_on_segment_2d
            assert _closest_on_segment_2d((x, y), pa, pb)[0] < 48.0 + 1e-6


def test_the_hovered_group_edge_comes_from_the_index_it_was_measured_on(vp):
    _lazy(vp, True, cap=12)
    vp._PICK_NEW_PER_QUERY = 1
    for p in _GAPS:
        x, y = vp._world_to_pixel(p)
        e = vp.pick_edge_any(x, y)
        if e is not None and getattr(e, "group", None) is not None:
            assert _owner_holds(e)
        vp.pick_group(x, y)                             # must not raise



def _live(v):
    return set(getattr(v, "_pick_live", None) or ())


def _far(v):
    """Zoomed out: the cursor's footprint takes in several cubes."""
    v.camera.fit_to(V(-60, -60, 0), V(80, 70, 1))
    return v._world_to_pixel(V(7.5, 4.5, 1.0))


def test_the_footprint_queries_of_one_event_share_the_cap(vp):
    # The snap and the cursor's own query of one pointer move each brought
    # in their own lot over the same spot (#158): now the lot is the
    # event's, and the next event brings the next one.
    _lazy(vp, True)
    x, y = _far(vp)
    vp._input_serial = None
    vp._pick_materialize(("snap", x, y))
    assert len(_live(vp)) >= 4               # what the spot takes in
    _lazy(vp, True)
    vp._PICK_NEW_PER_QUERY = 2
    vp._input_serial = 1
    vp._pick_materialize(("snap", x, y))
    first = _live(vp)
    assert len(first) == 2
    vp._pick_materialize(("snap", x, y))
    assert _live(vp) == first
    vp._input_serial = 2
    vp._pick_materialize(("snap", x, y))
    assert len(_live(vp)) == 4 and first <= _live(vp)


def test_without_an_input_event_each_query_has_its_own_cap(vp):
    _lazy(vp, True)
    vp._PICK_NEW_PER_QUERY = 2
    vp._input_serial = None
    x, y = _far(vp)
    vp._pick_materialize(("snap", x, y))
    vp._pick_materialize(("snap", x, y))
    assert len(_live(vp)) == 4


def test_a_ray_pick_is_not_held_back_by_the_footprint_lot(vp):
    _lazy(vp, True)
    vp._PICK_NEW_PER_QUERY = 1
    vp._input_serial = 7
    x, y = _far(vp)
    vp._pick_materialize(("snap", x, y))           # the lot is spent
    before = _live(vp)
    assert len(before) == 1
    g = next(g for g in vp.scene.groups if g.name == "C52")
    cx, cy = vp._world_to_pixel(_centre(vp, "C52"))
    vp._pick_materialize(("px", cx, cy))
    assert id(g) in _live(vp) and len(_live(vp)) == 2


def test_room_is_made_once_per_event(vp):
    # The ray picks after the snap let go of what it had just brought in,
    # and each change rebuilt the index: one clean-up per event (up to
    # twice the cap meanwhile).
    _lazy(vp, True, cap=12)                              # two cubes
    vp._input_serial = 1
    pts = [vp._world_to_pixel(_centre(vp, n)) for n in ("C00", "C11", "C22",
                                                         "C33", "C52")]
    for x, y in pts[:3]:
        vp._pick_materialize(("px", x, y))
    assert len(_live(vp)) == 2           # the first over the cap made room
    vp._pick_materialize(("px", *pts[3]))
    assert len(_live(vp)) == 3           # not again in the same event
    vp._pick_materialize(("px", *pts[4]))
    assert len(_live(vp)) == 4           # nor while within twice the cap
    vp._input_serial = 2
    vp._pick_materialize(("px", *pts[4]))
    assert len(_live(vp)) == 2           # the next event makes room


def test_the_kept_edge_projection_is_the_full_one(vp):
    # Each lazy chunk's screen projection is kept while the view stays:
    # the index rebuilt with new placements must read the same pixels
    # as projecting every edge again.
    import numpy as np
    _lazy(vp, True, cap=6 * 12)
    for name in ("C00", "C31", "C52", "C13", "C00", "C43"):
        x, y = vp._world_to_pixel(_centre(vp, name))[:2]
        vp._pick_index(near=("snap", x, y))
        idx = vp._pick_index(near="skip")
        got = vp._gedge_screen()
        ax, ay, oka = vp._project_px(idx.gedge_a)
        bx, by, okb = vp._project_px(idx.gedge_b)
        for g, w in zip(got, (ax, ay, bx, by, oka & okb)):
            assert np.array_equal(g, w)


def test_a_footprint_that_cannot_all_fit_keeps_its_nearest_and_stops_changing(vp):
    # Zoomed out over the plant of #158 the footprint met far more than the
    # cap holds: each pointer move the first ray let go of what the last
    # footprint brought in, and the footprint brought it in again — two
    # rebuilds a move for the same set. Now it takes the nearest that fit
    # in most of the cap, and those stay.
    _lazy(vp, True, cap=18)                  # three cubes; the spot meets more
    x, y = _far(vp)
    vp._input_serial = 1
    vp._pick_materialize(("snap", x, y))
    foot = _live(vp)
    assert 0 < len(foot) <= 2                # 0.8 of the cap: two cubes
    import numpy as np
    groups, lo, hi = vp._pick_lazy_table()[:3]
    e = vp.camera.eye()
    e = np.array([e.x(), e.y(), e.z()])
    dist = {id(groups[int(i)]): float(np.linalg.norm(
        np.clip(e, lo[int(i)], hi[int(i)]) - e))
        for i in vp._pick_near_memo[1]}
    assert len(dist) > len(foot)              # more than fit...
    assert max(dist[k] for k in foot) <= min(
        d for k, d in dist.items() if k not in foot)   # ...the nearest kept
    others = [g for g in vp.scene.groups if id(g) not in foot]
    for serial in range(2, 8):
        vp._input_serial = serial
        before = _live(vp)
        vp._pick_materialize(("snap", x, y))
        assert _live(vp) <= before, serial        # nothing brought in again
        assert foot <= _live(vp)
        for g in others[2 * serial:2 * serial + 2]:      # rays elsewhere
            cx, cy = vp._world_to_pixel(_centre(vp, g.name))
            vp._pick_materialize(("px", cx, cy))
            assert id(g) in _live(vp)
        assert foot <= _live(vp)


def test_a_change_of_the_lazy_set_keeps_the_static_triangles_and_the_loose_part(vp):
    # Each change of the lazy set rebuilds the index (#158): it joined the
    # static triangles again (~100 MB on the plant) and walked the loose
    # faces again. Kept while they are the same; the answers do not move.
    from core.group import Group
    vp.scene.mesh.add_face([V(-1, -1, 0), V(-0.5, -1, 0), V(-0.5, -0.5, 0),
                            V(-1, -0.5, 0)])
    big = Group(_cube(), name="fijo")                 # a group: static
    vp.scene.groups.append(big)
    vp.scene.version += 1
    pts = [_centre(vp, f"C{i}{j}") for i in range(6) for j in range(4)]
    pts += [V(-0.75, -0.75, 0.0), V(0.5, 0.5, 1.0)]
    _lazy(vp, False)
    full = _answers(vp, pts)
    _lazy(vp, True)
    x, y = vp._world_to_pixel(_centre(vp, "C00"))
    a = vp._pick_index(near=("px", x, y))
    x, y = vp._world_to_pixel(_centre(vp, "C53"))
    b = vp._pick_index(near=("px", x, y))
    assert a is not b and b.own_spans != a.own_spans  # the lazy set changed
    assert b.tri_v0 is a.tri_v0 and b.tri_ent is a.tri_ent
    assert b.entities[:1] == a.entities[:1]
    assert _answers(vp, pts) == full
    vp.scene.mesh.add_face([V(-3, -3, 0), V(-2.5, -3, 0), V(-2.5, -2.5, 0)])
    vp.scene.version += 1                              # the loose part changed
    c = vp._pick_index(near=("px", x, y))
    assert c.tri_v0 is not b.tri_v0
    assert len(c.tri_v0) == len(b.tri_v0) + 1
    lazy_after = _answers(vp, pts)
    _lazy(vp, False)
    assert lazy_after == _answers(vp, pts)            # offsets moved along
