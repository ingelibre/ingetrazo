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
    for k in range(0, len(pts), 40):          # the batch size snaps ask
        assert vp._occluded_many(pts[k:k + 40]) == one[k:k + 40]


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
