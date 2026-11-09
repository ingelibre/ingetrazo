# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Snap occlusion in one batch answers like one ray at a time.

``Viewport._occluded_many`` casts the snap engine's candidates together
(they share the eye) instead of one ``_is_occluded`` ray each, and
``compute_snap`` asks it for the rest of its candidates once the nearest
turns out hidden. Neither may change which point is snapped to:

- on a scene of walls, groups and component copies, from several views,
  the batch says "hidden" exactly where ``_is_occluded`` does — points
  behind, in front, ON faces (vertices, centroids: the epsilon cases);
- X-ray hides nothing, in batch as one by one;
- ``compute_snap`` picks the same candidate with and without the batch,
  and never calls it while the nearest candidate is visible.

Rays ask the pick index (NumPy), so this runs headless, GL or not.
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _box(mesh, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in idx])


def _scene_points(sc, rng, n):
    pts = []
    groups = [g for g in sc.groups if g.mesh.faces]
    while len(pts) < n:
        g = rng.choice(groups)
        f = rng.choice(g.mesh.faces)
        for p in [f.centroid()] + [v.position for v in f.loop]:
            pts.append(g.xform.map(p) if g.xform is not None else p)
        pts.append(V(rng.uniform(-6, 6), rng.uniform(-6, 6), rng.uniform(0, 4)))
    return pts


@pytest.fixture(params=[4, 80], ids=["few-spans", "many-spans"])
def viewport(request):
    # 4 blocks: the pick index's spans stay under 64 (``_ray_aabb`` per
    # span); 80: past it (the vectorised slab) — both prefilters covered.
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    for _ in range(10):
        _app.processEvents()
    vp = win.viewport          # rays ask the pick index: no GL needed
    sc = vp.scene
    _box(sc.mesh, -4, -0.1, 0, 4, 0.1, 3)                 # a loose wall
    for k in range(request.param):                         # group blocks
        m = Mesh()
        x = -3 + 2 * (k % 4) + 0.1 * (k // 4)
        _box(m, x, 1 + 0.2 * (k // 4), 0, x + 1, 2 + 0.2 * (k // 4),
             1 + k % 4)
        sc.groups.append(Group(m, name=f"block {k}"))
    proto = Mesh()                                         # component copies
    _box(proto, -0.3, -0.3, 0, 0.3, 0.3, 2.5)
    for k in range(5):
        g = Group(proto, name="post")
        xf = QMatrix4x4()
        xf.translate(-4 + 2 * k, -2, 0)
        g.xform = xf
        sc.groups.append(g)
    sc.version += 1
    spans = len(getattr(vp._pick_index(), "tri_spans", None) or ())
    assert (spans > 64) == (request.param > 64), spans   # the regime asked
    yield vp
    win._saved_version = sc.version          # no «save changes?» on close
    win.close()


@pytest.mark.parametrize("view", ["iso", "front", "back", "top", "left"])
def test_the_batch_hides_exactly_what_the_rays_hide(viewport, view):
    vp = viewport
    vp.camera.set_view(view)
    vp.camera.fit_to(V(-5, -3, 0), V(5, 3, 4))
    _app.processEvents()
    pts = _scene_points(vp.scene, random.Random(view), 400)
    one = [vp._is_occluded(p) for p in pts]
    assert any(one) and not all(one)          # the views do hide something
    import numpy as np
    xyz = np.array([(p.x(), p.y(), p.z()) for p in pts])
    for k in range(0, len(pts), 40):          # the batch size snaps ask
        assert vp._occluded_many(pts[k:k + 40]) == one[k:k + 40]
        # The same points as an array (pick_vertex's corners, #158).
        assert vp._occluded_many(xyz[k:k + 40]) == one[k:k + 40]


def test_without_the_array_rays_the_batch_still_matches(viewport,
                                                        monkeypatch):
    # A C++ library whose QVector3D length rounds otherwise: the rays are
    # built point by point, with the same answer.
    import numpy as np
    import views.viewport as V_
    monkeypatch.setattr(V_, "_QV_HYPOT3", False)
    vp = viewport
    vp.camera.set_view("iso")
    vp.camera.fit_to(V(-5, -3, 0), V(5, 3, 4))
    pts = _scene_points(vp.scene, random.Random(7), 120)
    one = [vp._is_occluded(p) for p in pts]
    assert any(one) and not all(one)
    xyz = np.array([(p.x(), p.y(), p.z()) for p in pts])
    assert vp._occluded_many(pts) == one
    assert vp._occluded_many(xyz) == one


def test_the_rays_are_built_as_qvector3d_builds_them():
    import numpy as np
    import views.viewport as V_
    rng = np.random.default_rng(3)
    pts = np.concatenate([
        rng.normal(size=(3000, 3)) * 10.0 ** rng.uniform(-3, 4, (3000, 1)),
        np.array([[1.5, -2.0, 3.25], [1.5, -2.0, 3.25 + 1e-7],
                  [0.0, 0.0, 9.0], [7.0, 0.0, 0.0]])])
    eye = V(1.5, -2.0, 3.25)
    rays = V_._unit_rays(eye, pts)
    if not V_._qv_hypot3():
        assert rays is None               # then built point by point
        return
    rows, D, dist = rays
    want_rows, want_d, want_l = [], [], []
    for i, p in enumerate(pts.tolist()):
        delta = V(*p) - eye
        L = delta.length()
        if L < 1e-9:
            continue
        d = delta / L
        want_rows.append(i)
        want_d.append((d.x(), d.y(), d.z()))
        want_l.append(L)
    assert rows.tolist() == want_rows
    assert len(rows) < len(pts)           # the eye itself is left out
    assert (D == np.array(want_d)).all()
    assert (dist == np.array(want_l)).all()


def test_xray_hides_nothing_in_batch(viewport, monkeypatch):
    vp = viewport
    vp.camera.set_view("front")
    vp.camera.fit_to(V(-5, -3, 0), V(5, 3, 4))
    behind = V(0, 2.5, 1)
    assert vp._is_occluded(behind)
    from types import SimpleNamespace
    xray = SimpleNamespace(face_mode="xray")
    monkeypatch.setattr(vp, "_effective_style", lambda: xray)
    assert not vp._is_occluded(behind)
    assert vp._occluded_many([behind, V(0, -2.5, 1)]) == [False, False]


def test_empty_batch():
    from views.viewport import Viewport
    assert Viewport._occluded_many(object(), []) == []


# ---- compute_snap ------------------------------------------------------------

def _snap_scene():
    from core.scene import Scene
    s = Scene()
    for x in range(6):
        s.mesh.add_face([V(x * 0.05, 0, 0), V(x * 0.05 + 0.02, 0, 0),
                         V(x * 0.05 + 0.02, 0.02, 0), V(x * 0.05, 0.02, 0)])
    return s


@pytest.mark.parametrize("hidden_below", [-1.0, 0.06, 0.13, 0.3])
def test_compute_snap_picks_the_same_candidate_with_the_batch(hidden_below):
    from core.snap import compute_snap
    s = _snap_scene()
    w2p = lambda p: (p.x() * 400.0, p.y() * 400.0)  # noqa: E731
    hidden = lambda p: p.x() < hidden_below          # noqa: E731
    batches = []

    def many(points):
        batches.append(len(points))
        return [hidden(p) for p in points]

    args = dict(candidate_world=V(0.0, 0.0, 0), candidate_pixel=(0.5, 0.5),
                scene=s, world_to_pixel=w2p, threshold_px=60.0)
    one = compute_snap(**args, is_occluded=hidden)
    both = compute_snap(**args, is_occluded=hidden, are_occluded=many)
    assert (one.kind, tuple(round(c, 9) for c in (one.point.x(),
            one.point.y(), one.point.z()))) == \
           (both.kind, tuple(round(c, 9) for c in (both.point.x(),
            both.point.y(), both.point.z())))
    if hidden_below < 0:                     # nearest visible: no batch
        assert batches == []
    else:
        assert batches                       # the rest went in one call


def test_the_kill_switch_keeps_the_rays_one_by_one(monkeypatch):
    # INGETRAZO_NO_SNAP_FAST=1: compute_snap gets no batch to ask.
    import views.viewport as vv
    monkeypatch.setattr(vv, "_NO_SNAP_FAST", True)
    import core.snap as cs
    seen = {}
    real = cs.compute_snap

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(cs, "compute_snap", spy)
    if getattr(vv, "compute_snap", None) is real:
        monkeypatch.setattr(vv, "compute_snap", spy)
    # The snap search lives in the inference engine since the refactor.
    import core.inference as ci
    if getattr(ci, "compute_snap", None) is real:
        monkeypatch.setattr(ci, "compute_snap", spy)
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
        vp.scene.version += 1
        win._activate_tool("line")
        from PySide6.QtCore import QPointF, Qt
        vp._process_hover(QPointF(vp.width() / 2, vp.height() / 2), Qt.NoModifier)
        assert "are_occluded" in seen and seen["are_occluded"] is None
    finally:
        win._saved_version = vp.scene.version
        win.close()


@pytest.mark.parametrize("view", ["iso", "front", "back", "top"])
def test_pick_vertex_batches_like_one_ray_at_a_time(viewport, view,
                                                    monkeypatch):
    """pick_vertex asks its candidates' occlusion in batches past the
    nearest (one ray each, in turn, took minutes over a dense mesh): the
    corner it returns is the one-at-a-time loop's, pixel for pixel."""
    vp = viewport
    vp.camera.set_view(view)
    vp.camera.fit_to(V(-5, -3, 0), V(5, 3, 4))
    _app.processEvents()
    rng = random.Random(view)
    pixels = []
    pts = _scene_points(vp.scene, rng, 400)
    # Mostly at HIDDEN corners: there the nearest candidate is hidden and
    # the answer, if any, comes out of the batches.
    hidden = [p for p in pts if vp._is_occluded(p)]
    for p in hidden[:120] + pts[:60]:
        px = vp._world_to_pixel(p)
        if px is not None:
            pixels.append((px[0] + rng.uniform(-2, 2),
                           px[1] + rng.uniform(-2, 2)))

    def picks():
        out = []
        for x, y in pixels:
            r = vp.pick_vertex(x, y)
            out.append(None if r is None else r.toTuple())
        return out
    got = picks()
    monkeypatch.setattr(type(vp), "_occluded_many", None, raising=False)
    want = picks()
    assert got == want
    assert sum(g is not None for g in got) > 10


def test_pick_vertex_dense_hidden_corners(monkeypatch):
    """Two grids of short edges seen through and around a wall, offset by
    less than the pick radius: at most pixels the nearest corner is hidden
    behind the wall and a visible one lies a few pixels away — the batches
    must answer the one-at-a-time loop's corner every time."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        for _ in range(10):
            _app.processEvents()
        vp = win.viewport
        sc = vp.scene
        _box(sc.mesh, -3, -0.1, -1, 3, 0.1, 1)            # the wall, y≈0
        import numpy as np
        xs, zs = np.meshgrid(np.arange(-0.6, 0.6, 0.006),
                             np.arange(-0.4, 0.4, 0.006))   # dense, behind
        for x, z in zip(xs.ravel().tolist(), zs.ravel().tolist()):
            sc.mesh.add_edge(V(x, 1.0, z), V(x + 0.002, 1.0, z))
        for k in range(12):                              # sparse, in front
            for j in range(8):
                x, z = -0.59 + 0.1 * k, -0.39 + 0.1 * j
                sc.mesh.add_edge(V(x, -0.5, z), V(x + 0.004, -0.5, z))
        sc.version += 1
        vp.camera.set_view("front")
        vp.camera.fit_to(V(-0.7, -1, -0.5), V(0.7, 1, 0.5))
        _app.processEvents()
        rng = random.Random(1)
        pixels = []
        for k in range(12):                 # around each front corner
            for j in range(8):
                p = vp._world_to_pixel(V(-0.59 + 0.1 * k, -0.5,
                                         -0.39 + 0.1 * j))
                if p is not None:
                    pixels.append((p[0] + rng.uniform(-4, 4),
                                   p[1] + rng.uniform(-4, 4)))

        def picks():
            out = []
            for x, y in pixels:
                r = vp.pick_vertex(x, y)
                out.append(None if r is None else r.toTuple())
            return out
        got = picks()
        monkeypatch.setattr(type(vp), "_occluded_many", None, raising=False)
        want = picks()
        assert got == want
        front = sum(1 for g in got if g is not None and abs(g[1] + 0.5) < 1e-6)
        assert front > 20, front                        # the batches answered
        assert vp._is_occluded(V(0.0, 1.0, 0.0))        # the dense grid hides
        # The rule itself, from an independent projection of every corner:
        # the answer is visible and every corner nearer to the cursor than
        # it (within the pick radius) is hidden.
        ends = []
        for e in sc.mesh.edges:
            ends += [e.a, e.b]
        px = [vp._world_to_pixel(p) for p in ends]
        thr = vp.pick_threshold_px
        hidden_memo: dict = {}

        def hidden(p):
            k = p.toTuple()
            if k not in hidden_memo:
                hidden_memo[k] = vp._is_occluded(p)
            return hidden_memo[k]
        for (x, y), r in zip(pixels, got):
            d = [((q[0] - x) ** 2 + (q[1] - y) ** 2) ** 0.5
                 if q is not None else float("inf") for q in px]
            if r is None:
                assert all(hidden(p) for p, dd in zip(ends, d) if dd < thr - 1e-6)
                continue
            dr = min(dd for p, dd in zip(ends, d) if p.toTuple() == r)
            assert not hidden(V(*r))
            assert all(hidden(p) for p, dd in zip(ends, d)
                       if dd < dr - 1e-6 and p.toTuple() != r)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


@pytest.mark.parametrize("view", ["iso", "front", "back", "top", "left"])
def test_the_native_rays_hide_exactly_what_numpy_hides(viewport, view,
                                                       monkeypatch):
    """With the experimental engine on, ``_occluded_many``'s Möller–Trumbore
    block runs in core/occlusion.rs; a ray it cannot call bit for bit comes
    back to NumPy. Either way the answer is NumPy's, point for point —
    points on faces and at their corners included (the threshold cases)."""
    import views.viewport as vv
    if vv._occlusion_native() is None:
        pytest.skip("the native engine is off or not built")
    vp = viewport
    vp.camera.set_view(view)
    vp.camera.fit_to(V(-5, -3, 0), V(5, 3, 4))
    _app.processEvents()
    pts = _scene_points(vp.scene, random.Random("native" + view), 600)
    calls = []
    real = vv._occlusion_native()

    class Spy:
        def occlusion_span(self, *a):
            out = real.occlusion_span(*a)
            calls.append(int(out[1].sum()))
            return out
    monkeypatch.setattr(vv, "_occlusion_native", lambda: Spy())
    native = [h for k in range(0, len(pts), 40)
              for h in vp._occluded_many(pts[k:k + 40])]
    monkeypatch.setattr(vv, "_occlusion_native", lambda: None)
    numpy_ = [h for k in range(0, len(pts), 40)
              for h in vp._occluded_many(pts[k:k + 40])]
    assert native == numpy_
    assert calls                              # the kernel did answer


@pytest.mark.parametrize("view", ["iso", "front", "back", "left"])
def test_a_narrow_cone_of_rays_hides_what_the_rays_hide(viewport, view,
                                                        monkeypatch):
    """Rays crowded onto a few blocks seen from afar (zoomed out over the
    plant of #158, ~65 000 corners under the cursor): the spans outside
    their cone are left out of the box test — the answer stays the rays'
    one by one, and some spans were left out."""
    import numpy as np
    vp = viewport
    vp.camera.set_view(view)
    vp.camera.fit_to(V(-60, -40, -20), V(60, 40, 40))
    _app.processEvents()
    rng = random.Random(view)
    sc = vp.scene
    near = [g for g in sc.groups if g.name in ("block 0", "block 4",
                                               "block 8", "post")]
    pts = []
    for g in near:
        for f in g.mesh.faces:
            for p in [f.centroid()] + [v.position for v in f.loop]:
                pts.append(g.xform.map(p) if g.xform is not None else p)
    pts += [V(rng.uniform(-3.5, -1.5), rng.uniform(0.5, 3), rng.uniform(0, 3))
            for _ in range(200)]
    one = [vp._is_occluded(p) for p in pts]
    assert any(one) and not all(one)
    widths = []
    real = np.flatnonzero

    def spy(a):
        r = real(a)
        if a.dtype == bool and a.ndim == 1 and len(a) > 64:
            widths.append((len(r), len(a)))
        return r
    monkeypatch.setattr(np, "flatnonzero", spy)
    got = vp._occluded_many(pts)
    monkeypatch.setattr(np, "flatnonzero", real)
    assert got == one
    assert any(k < n for k, n in widths), widths     # the cone left some out


def test_pick_vertex_asks_a_shared_corner_once(viewport, monkeypatch):
    """A corner shared by several edges is one point: asked once."""
    vp = viewport
    vp.camera.set_view("iso")
    vp.camera.fit_to(V(-60, -40, -20), V(60, 40, 40))
    _app.processEvents()
    asked = []
    real_many, real_one = vp._occluded_many, vp._is_occluded
    monkeypatch.setattr(vp, "_is_occluded",
                        lambda w: asked.append(w) or True)
    monkeypatch.setattr(vp, "_occluded_many",
                        lambda ws: asked.extend(ws) or [True] * len(ws))
    cx, cy = vp._world_to_pixel(V(-2.5, 1.5, 1.0))
    vp.pick_threshold_px = 40
    assert vp.pick_vertex(cx, cy) is None             # all hidden
    keys = [(p.x(), p.y(), p.z()) for p in asked]
    assert len(keys) > 8
    assert len(keys) == len(set(keys))
    monkeypatch.setattr(vp, "_is_occluded", real_one)
    monkeypatch.setattr(vp, "_occluded_many", real_many)
