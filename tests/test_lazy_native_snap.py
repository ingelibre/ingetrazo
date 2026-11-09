# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""With the experimental engine, the corner a drawing tool acquires and
whether a point is hidden are answered for the lazy placements without
baking them (#158) — and they are the answers of the pick index that holds
every placement baked: the same corner, bit for bit, at every pixel of a
few views over turned, scaled and mirrored copies that hide one another.
Skipped without the engine."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402

_app = QApplication.instance() or QApplication([])
mod = _native.native            # the engine on (INGETRAZO_RUST), not only built
pytestmark = pytest.mark.skipif(
    mod is None or not hasattr(mod, "InstanceSet")
    or not hasattr(mod.InstanceSet, "corners_near"),
    reason="native module not built")


def _cube(sx=1.0, sy=1.0, sz=1.0, at=(0.0, 0.0, 0.0)):
    from core.mesh import Mesh
    m = Mesh()
    o = V(*at)
    p = [o + V(0, 0, 0), o + V(sx, 0, 0), o + V(sx, sy, 0), o + V(0, sy, 0),
         o + V(0, 0, sz), o + V(sx, 0, sz), o + V(sx, sy, sz),
         o + V(0, sy, sz)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    return m


def _window(lazy):
    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(900, 640)
    vp.scene.guides.clear()
    rng = np.random.default_rng(7)
    protos = [_cube(), _cube(2.0, 0.5, 1.5), _cube(0.3, 0.3, 3.0)]
    for i in range(8):
        for j in range(6):
            g = Group(protos[(i + j) % 3], name=f"C{i}{j}")
            m = QMatrix4x4()
            m.translate(2.2 * i + 0.13 * j, 2.4 * j - 0.07 * i,
                        float(rng.uniform(0, 1.5)))
            m.rotate(float(rng.uniform(0, 360)), *rng.uniform(-1, 1, 3))
            s = rng.uniform(0.5, 1.4, 3)
            if (i * 6 + j) % 7 == 3:
                s[1] = -s[1]                         # mirrored
            m.scale(*s)
            g.xform = m
            vp.scene.groups.append(g)
    by = {g.name: g for g in vp.scene.groups}
    by["C23"].hidden = True             # neither hides nor snaps
    by["C51"].locked = True             # hides, but does not snap
    for k, (x, y) in enumerate(((5.1, 3.3), (11.7, 8.2), (1.4, 12.6))):
        m = _cube(1.0 + 0.4 * k, 0.8, 2.0 - 0.3 * k, (x, y, 0.4 * k))
        vp.scene.groups.append(Group(m, name=f"G{k}"))   # fixed: no matrix
    vp.scene.groups[-1].hidden = True   # a fixed one that hides nothing
    loose = _cube(3.0, 0.2, 2.5, (7.3, 6.1, 0.0))        # the loose part
    for f in loose.faces:
        vp.scene.mesh.add_face(list(f.vertices))
    # A wall of hidden loose faces: in the index, hiding nothing.
    wall = _cube(0.1, 9.0, 4.0, (9.9, 1.0, -0.5))
    for f in wall.faces:
        g = vp.scene.mesh.add_face(list(f.vertices))
        g.attrs["hidden"] = True
    vp.scene.version += 1
    vp._PICK_LAZY_MIN_FACES = 1 if lazy else 10 ** 9
    return win, vp


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


VIEWS = ((30.0, 35.0, True), (200.0, 20.0, True), (115.0, 60.0, False),
         (300.0, 10.0, True))


def _set_view(vp, view):
    yaw, pitch, persp = view
    cam = vp.camera
    cam.perspective = persp
    cam.fit_to(V(-1, -1, -1), V(18, 14, 4))
    cam.yaw, cam.pitch = math.radians(yaw), math.radians(pitch)
    vp._tick = getattr(vp, "_tick", 0) + 1


def _key(p):
    return None if p is None else (p.x(), p.y(), p.z())


@pytest.fixture
def pair():
    a, va = _window(lazy=True)
    b, vb = _window(lazy=False)
    try:
        yield va, vb
    finally:
        _close(a)
        _close(b)


def test_the_unbaked_corner_is_the_baked_one_everywhere(pair):
    va, vb = pair
    assert va._pick_lazy_table() is not None
    assert vb._pick_lazy_table() is None
    seen = 0
    for view in VIEWS:
        _set_view(va, view)
        _set_view(vb, view)
        assert va._lazy_native() is not None
        for x in np.arange(13.37, 900, 17.0):
            for y in np.arange(9.71, 640, 19.0):
                va._input_serial = vb._input_serial = (x, y)
                got = va.pick_vertex(float(x), float(y))
                want = vb.pick_vertex(float(x), float(y))
                assert _key(got) == _key(want), (view, x, y)
                seen += got is not None
    # Nothing was baked to answer.
    assert not getattr(va, "_pick_live", None)
    assert seen > 100


def test_a_point_is_hidden_unbaked_as_it_is_baked(pair):
    va, vb = pair
    rng = np.random.default_rng(3)
    hidden = 0
    for view in VIEWS:
        _set_view(va, view)
        _set_view(vb, view)
        pts = [V(*rng.uniform((-1, -1, -1), (18, 14, 4)))
               for _ in range(300)]
        # Corners of the copies too: on their own faces, never behind them.
        for g in va.scene.groups[::5]:
            if getattr(g, "xform", None) is not None:
                pts.append(g.xform.map(V(0, 0, 0)))
        got = va._occluded_many(pts)
        want = vb._occluded_many(pts)
        assert got == want, view
        assert [va._is_occluded(p) for p in pts[:40]] == want[:40]
        hidden += sum(want)
    assert 0 < hidden < 4 * 300
    assert not getattr(va, "_pick_live", None)


def _edge_key(e):
    return (_key(e.a), _key(e.b), getattr(e, "in_group", False),
            getattr(e, "context", None),
            getattr(getattr(e, "group", None), "name", None))


def test_the_edges_near_the_cursor_are_the_baked_ones(pair):
    """The group edges a snap is fed and the one the linear inferences
    hover come from the engine for the lazy copies, and they are the pick
    index's."""
    va, vb = pair
    seen = 0
    for view in VIEWS:
        _set_view(va, view)
        _set_view(vb, view)
        for x in np.arange(11.3, 900, 23.0):
            for y in np.arange(7.9, 640, 29.0):
                va._input_serial = vb._input_serial = (x, y)
                got = va._nearby_group_edges(float(x), float(y))
                want = vb._nearby_group_edges(float(x), float(y))
                # The same edges; their order is the index's, which for the
                # lazy part is the order the placements were baked in.
                assert (sorted(map(_edge_key, got))
                        == sorted(map(_edge_key, want))), (view, x, y)
                g1 = va.pick_edge_any(float(x), float(y))
                g2 = vb.pick_edge_any(float(x), float(y))
                assert ((g1 is None) == (g2 is None)
                        and (g1 is None or _edge_key(g1) == _edge_key(g2))), \
                    (view, x, y)
                seen += len(want) + (g2 is not None)
    assert not getattr(va, "_pick_live", None)
    assert seen > 200


def _face_key(face, place):
    if face is None:
        return None
    c = face.centroid()
    if place is not None and getattr(place, "xform", None) is not None:
        c = place.xform.map(c)
    return (c.x(), c.y(), c.z(), getattr(place, "name", None))


def test_the_faces_under_the_cursor_are_the_baked_ones(pair):
    """What a ray through a pixel finds — the face and the placement it
    was hit through, the group a click takes, the face of each probe, the
    crossing of two faces, the distance to what is seen — comes from the
    engine for the lazy copies, none baked, and is the pick index's."""
    va, vb = pair
    seen = crossed = edged = 0
    for view in VIEWS:
        _set_view(va, view)
        _set_view(vb, view)
        for x in np.arange(8.3, 900, 21.0):
            for y in np.arange(5.9, 640, 23.0):
                x, y = float(x), float(y)
                va._input_serial = vb._input_serial = (x, y)
                fa = va.pick_face_placement(x, y)
                fb = vb.pick_face_placement(x, y)
                assert _face_key(*fa) == _face_key(*fb), (view, x, y)
                ga, gb = va.pick_group(x, y), vb.pick_group(x, y)
                assert (getattr(ga, "name", None)
                        == getattr(gb, "name", None)), (view, x, y)
                ha, hb = va._front_face_at(x, y), vb._front_face_at(x, y)
                assert ((ha is None) == (hb is None)
                        and (ha is None or _face_key(*ha) == _face_key(*hb))
                        ), (view, x, y)
                ca = va._face_crossing_point(x, y)
                cb = vb._face_crossing_point(x, y)
                assert ((ca is None) == (cb is None)
                        and (ca is None or (_key(ca[0]), ca[1])
                             == (_key(cb[0]), cb[1]))), (view, x, y)
                o, d = va._pixel_to_ray(x, y)
                assert (va.ray_distance(o, d) == vb.ray_distance(o, d)), \
                    (view, x, y)
                assert (va.ray_distance(o, d, 9.0)
                        == vb.ray_distance(o, d, 9.0)), (view, x, y)
                seen += fb[0] is not None
                crossed += cb is not None
                edged += fb[0] is None and gb is not None
    assert not getattr(va, "_pick_live", None)
    assert seen > 200 and crossed >= 3 and edged > 3, (seen, crossed, edged)


def test_of_two_coplanar_faces_the_smaller_copy_is_picked():
    """Two copies of one cube whose tops are one plane — a 4×4 slab, then
    a small block standing in it: the ray meets both tops at the same
    depth and the smaller face wins, by its area as placed."""
    from core.group import Group
    from views.main_window import MainWindow
    out = []
    for lazy in (True, False):
        win = MainWindow()
        vp = win.viewport
        vp.resize(600, 400)
        vp.scene.guides.clear()
        proto = _cube()
        for name, (sx, sy, tx, ty) in (("big", (4.0, 4.0, 0.0, 0.0)),
                                      ("small", (1.0, 1.0, 1.5, 1.5))):
            g = Group(proto, name=name)
            m = QMatrix4x4()
            m.translate(tx, ty, 0.0)
            m.scale(sx, sy, 1.0)
            g.xform = m
            vp.scene.groups.append(g)
        vp.scene.version += 1
        vp._PICK_LAZY_MIN_FACES = 1 if lazy else 10 ** 9
        cam = vp.camera
        cam.perspective = False
        cam.fit_to(V(-1, -1, 0), V(5, 5, 1))
        cam.yaw, cam.pitch = math.radians(0.0), math.radians(89.0)
        x, y = vp._world_to_pixel(V(2.0, 2.0, 1.0))
        vp._input_serial = (x, y)
        if lazy:
            assert vp._lazy_native() is not None
        face, place = vp.pick_face_placement(x, y)
        out.append((_key(face.centroid()), place.name))
        assert not lazy or not getattr(vp, "_pick_live", None)
        win._saved_version = vp.scene.version
        win.close()
    assert out[0] == out[1] and out[0][1] == "small"



def test_the_points_near_the_cursor_are_numpys():
    """``_px_near`` (the native candidates, measured by NumPy) finds the
    same indices in the same order, with the same distances, as one
    ``np.hypot`` pass — points behind the eye, not finite, on the radius."""
    from views.viewport import _px_near
    rng = np.random.default_rng(158)
    for _ in range(40):
        n = int(rng.integers(5000, 60000))
        x = rng.uniform(-50, 950, n)
        y = rng.uniform(-50, 700, n)
        px, py = rng.uniform(0, 900), rng.uniform(0, 650)
        thr = float(rng.choice([6.0, 12.0, 0.5]))
        # Some on the radius, a hair inside and outside it.
        a = rng.uniform(0, 2 * np.pi, 300)
        rr = thr * (1.0 + rng.choice([-1e-15, 0.0, 1e-15], 300))
        x[:300], y[:300] = px + rr * np.cos(a), py + rr * np.sin(a)
        x[300:310] = np.nan
        x[310:320] = np.inf
        y[320:330] = -np.inf
        ok = rng.random(n) > 0.1
        m = int(rng.integers(4097, n))                   # a cached head
        for xs, ys, oks in ((x, y, ok), (x[:m], y[:m], ok[:m])):
            k, d = _px_near(xs, ys, oks, px, py, thr)
            with np.errstate(invalid="ignore"):
                full = np.where(oks, np.hypot(xs - px, ys - py), np.inf)
            want = np.flatnonzero(full < thr)
            assert np.array_equal(k, want)
            assert np.array_equal(d, full[want])


def test_a_face_the_static_engine_does_not_hold_is_still_hit(pair):
    """The engine's BVH over the index's own triangles holds the visible
    ones only (they are what hides): a ray asked for faces that are not
    visible (selectable while hidden geometry shows) goes over the spans
    as before, and meets them."""
    from types import SimpleNamespace
    from views.viewport import Viewport, _moller_trumbore
    va, _vb = pair
    _set_view(va, VIEWS[0])
    idx0 = va._pick_index(near="skip")
    skip = {"_static_occl", "_mask_in_vis", "_span_boxes"}
    idx = SimpleNamespace(**{k: v for k, v in vars(idx0).items()
                             if k not in skip})
    rng = np.random.default_rng(11)
    gone = rng.random(len(idx.entities)) < 0.5
    idx.ent_vis = idx0.ent_vis & ~gone
    every = np.ones(len(idx.entities), dtype=bool)
    o3, d3 = (0.0, 0.0, 9.0), (0.0, 0.0, -1.0)
    assert Viewport._static_ray_rows(va, idx, idx.ent_vis, o3, d3) is not None
    assert Viewport._static_ray_rows(va, idx, every, o3, d3) is None
    met_gone = 0
    eye = va.camera.eye()
    cen = idx.tri_v0 + (idx.tri_e1 + idx.tri_e2) / 3.0
    for c in cen.tolist():                    # a ray at every triangle
        o, d = eye, (V(*c) - eye).normalized()
        for mask in (every, idx.ent_vis):
            got = va._ray_hits(idx, o, d, mask, own=False)
            on = np.array([o.x(), o.y(), o.z()])
            dn = np.array([d.x(), d.y(), d.z()])
            t, hit = _moller_trumbore(on, dn, idx.tri_v0, idx.tri_e1,
                                      idx.tri_e2)
            hit &= mask[idx.tri_ent]
            want = np.full(len(idx.entities), np.inf)
            np.minimum.at(want, idx.tri_ent[hit], t[hit])
            assert np.array_equal(got, want)
            if mask is every:
                met_gone += int(np.isfinite(want[gone]).any())
    assert met_gone > 10


def test_rays_the_static_engine_leaves_open_are_settled_as_before(pair,
                                                                   monkeypatch):
    """The rays the engine cannot call over the index's own triangles (its
    doubts) go through the spans alone, the others skip them; forced
    doubts on a random part of the rays give the same answers, the same
    as all of them through the spans."""
    from views.viewport import Viewport
    va, vb = pair
    real = Viewport._static_occluders
    share = {"p": 0.0}
    rng = np.random.default_rng(5)

    class Doubtful:
        def __init__(self, iset):
            self._iset = iset

        def occluded(self, cand, o, D, lim):
            hid, doubt = self._iset.occluded(cand, o, D, lim)
            forced = rng.random(len(hid)) < share["p"]
            return hid & ~forced, doubt | forced

    def static(self, idx):
        st = real(self, idx)
        return None if st is None else (Doubtful(st[0]),) + tuple(st[1:])

    monkeypatch.setattr(Viewport, "_static_occluders", static)
    hidden = 0
    for view in VIEWS:
        _set_view(va, view)
        _set_view(vb, view)
        pts = [V(*rng.uniform((-1, -1, -1), (18, 14, 4)))
               for _ in range(300)]
        want = vb._occluded_many(pts)
        for p in (0.0, 0.3, 1.0):
            share["p"] = p
            assert va._occluded_many(pts) == want, (view, p)
        hidden += sum(want)
    assert 0 < hidden < 4 * 300
