# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A face of 1 mm (or 0.3 mm) inside lazy placements is found and hides
what is behind it, with either engine (#1294).

The ray/triangle tests refused |det| < 1e-6, but det is (e1 × e2)·d and
shrinks with the triangle's area: a 1 mm square met head-on has det ≈ 6e-7.
The pick's test reads a small det against the triangle's own size since
#1294; the snap engine's occlusion rays (``Viewport._occluded_many``, its
NumPy block and core/occlusion.rs, which the lazy placements of a big model
and the pick index's own triangles go through) read it the same way, so a
point behind a 1 mm face is hidden by it."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

SIDES = (0.001, 0.0003)


def _proto(s):
    """A cube of 1 m with a square of side ``s`` floating 2 m off it."""
    from core.mesh import Mesh
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    sq = m.add_face([V(3, 3, 0), V(3 + s, 3, 0), V(3 + s, 3 + s, 0),
                     V(3, 3 + s, 0)])
    return m, sq


def _window(s, lazy):
    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(1400, 850)
    vp.camera.set_aspect(1400, 850)
    vp.flash_status = lambda *a, **k: None
    vp.scene.guides.clear()
    mesh, sq = _proto(s)
    first = None
    for i in range(6):
        for j in range(5):
            g = Group(mesh, name=f"C{i}{j}")
            m = QMatrix4x4()
            m.translate(7.0 * i, 7.0 * j, 0.0)
            g.xform = m
            vp.scene.groups.append(g)
            first = first or g
    vp.scene.version += 1
    vp._PICK_LAZY_MIN_FACES = 1 if lazy else 10 ** 9
    cam = vp.camera
    c = V(3 + s / 2, 3 + s / 2, 0)
    cam.target = c
    cam.distance = 20 * s
    cam.pitch = math.radians(35)
    cam.yaw = math.radians(-40)
    vp._tick = getattr(vp, "_tick", 0) + 1
    return win, vp, sq, first, c


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


@pytest.mark.parametrize("lazy", (True, False))
@pytest.mark.parametrize("s", SIDES)
def test_a_tiny_face_in_a_placement_is_picked(s, lazy):
    win, vp, sq, first, c = _window(s, lazy)
    try:
        assert (vp._pick_lazy_table() is not None) is lazy
        x, y = vp._world_to_pixel(c)
        face, place = vp.pick_face_any(x, y)
        assert face is sq and place is first, (face, place)
    finally:
        _close(win)


@pytest.mark.parametrize("lazy", (True, False))
@pytest.mark.parametrize("s", SIDES)
def test_a_tiny_face_in_a_placement_hides_what_is_behind_it(s, lazy):
    import core._native as _native
    if lazy and _native.native is None:
        # On Python the lazy placements hide only what is baked of them
        # around the cursor; the engine asks every one (#158).
        pytest.skip("lazy placements occlude through the native engine")
    win, vp, _sq, _first, c = _window(s, lazy)
    try:
        assert (vp._pick_lazy_table() is not None) is lazy
        eye = vp.camera.eye()
        d = (c - eye).normalized()
        behind = c + d * 0.05             # 5 cm past the square, on the ray
        aside = behind + V(0.01, 0.0, 0.0)  # off it: seen
        assert vp._occluded_many([behind, aside]) == [True, False]
        assert vp._is_occluded(behind) and not vp._is_occluded(aside)
    finally:
        _close(win)


def _block():
    from views.viewport import _occlusion_block
    return _occlusion_block


def test_the_occlusion_block_takes_a_tiny_triangle_and_refuses_grazing():
    blk = _block()
    for s in SIDES:
        v0 = np.array([[0.0, 0.0, 0.0]])
        e1 = np.array([[s, 0.0, 0.0]])
        e2 = np.array([[0.0, s, 0.0]])
        d = np.array([[0.1, -0.2, -1.0]])
        d = d / np.linalg.norm(d)
        o = np.array([s / 3, s / 3, 0.0]) - d[0] * 0.02
        assert abs(blk(o, d, v0, e1, e2)[0] - 0.02) < 1e-9, s
    # A ray along the plane of a big triangle is still refused.
    o = np.array([-1.0, 0.25, 1e-9])
    d = np.array([[1.0, 0.0, 0.0]])
    v0 = np.array([[0.0, 0.0, 0.0]])
    e1 = np.array([[1.0, 0.0, 0.0]])
    e2 = np.array([[0.0, 1.0, 0.0]])
    assert not np.isfinite(blk(o, d, v0, e1, e2)[0])


def test_the_native_span_is_the_numpy_block_on_tiny_triangles():
    import core._native as _native
    mod = _native.native
    if mod is None or not hasattr(mod, "occlusion_span"):
        pytest.skip("native module not built")
    blk = _block()
    rng = np.random.default_rng(1294)
    for s in (1.0, 0.01, 0.001, 0.0003, 0.0001):
        n = 300
        v0 = rng.uniform(-s, s, (n, 3))
        e1 = rng.uniform(-s, s, (n, 3))
        e2 = rng.uniform(-s, s, (n, 3))
        o = np.array([0.0, 0.0, 0.0]) + rng.uniform(-1, 1, 3) * 3 * s
        d = rng.normal(size=(200, 3))
        d /= np.linalg.norm(d, axis=1)[:, None]
        best = np.full(len(d), np.inf)
        limit = np.full(len(d), 10.0 * s)
        nb, doubt = mod.occlusion_span(tuple(o.tolist()), d, best, limit,
                                       v0, e1, e2)
        want = blk(o, d, v0, e1, e2)
        ok = ~np.asarray(doubt)
        assert ok.mean() > 0.9, s
        # The same hits; a t may differ in its last bit (BLAS sums in an
        # order of its own), which only a point at the limit could feel —
        # and that ray comes back doubtful.
        nb = np.asarray(nb)
        assert np.array_equal(np.isfinite(nb[ok]), np.isfinite(want[ok])), s
        assert np.allclose(nb[ok], want[ok], rtol=1e-12, atol=0.0), s
        assert np.isfinite(want).any(), s
