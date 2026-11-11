# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The engine's geometry of a view's faces is the Python walk's.

Before a face of the plaza reached the visible-parts pass, the walk took
its rings to the world through its placement, found its normal, cut it to
the section, drew it and fitted its nearness plane — 12 s of Python over
85 000 faces, a least-squares fit each. The engine does the same steps in
the same order, face by face in parallel; this holds it to the walk: the
same faces kept and skipped, the same casters, the same world and drawn
rings, normals, sides, nearness planes and depths — in parallel and in
perspective, mirrored placements, a section cut, holes."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core import _native
from core import vista_caras as VC
from core.camera import OrbitCamera
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene

native = _native.available()
pytestmark = pytest.mark.skipif(
    native is None or not hasattr(native, "faces_view"),
    reason="Rust engine without faces_view")


def _box(mesh, x0, y0, z0, s=1.0):
    x1, y1, z1 = x0 + s, y0 + s, z0 + s
    for loop in (
            [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
            [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
            [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]):
        mesh.add_face([V(*p) for p in loop])


def _scene():
    """Loose faces with a hole, a box, a mirrored placement, a turned and
    moved one, a sliver seen edge on, a face with two corners."""
    scene = Scene()
    lm = scene.loose_mesh
    lm.add_face([V(0, 0, 0), V(6, 0, 0), V(6, 6, 0), V(0, 6, 0)],
                [[V(2, 2, 0), V(2, 4, 0), V(4, 4, 0), V(4, 2, 0)]])
    lm.add_face([V(0, 0, 0.001), V(6, 0, 0.001), V(6, 0, 0.0011),
                 V(0, 0, 0.0011)])                      # all but edge on
    m = Mesh()
    _box(m, 1, 1, 0, 1.0)
    scene.groups.append(Group(m, "box"))
    mirror = QMatrix4x4()
    mirror.scale(-1.0, 1.0, 1.0)
    mirror.translate(-8.0, 0.0, 0.0)
    g2 = Group(Mesh(), "mirrored")
    _box(g2.mesh, 0, 0, 0, 1.0)
    g2.xform = mirror
    scene.groups.append(g2)
    turned = QMatrix4x4()
    turned.translate(3.0, 7.0, 0.5)
    turned.rotate(37.0, 0.3, 0.2, 1.0)
    g3 = Group(Mesh(), "turned")
    _box(g3.mesh, 0, 0, 0, 1.5)
    g3.xform = turned
    scene.groups.append(g3)
    scene.version += 1
    return scene


def _camera(scene, perspective, view="iso"):
    cam = OrbitCamera()
    cam.set_aspect(800, 600)
    cam.perspective = perspective
    cam.set_view(view)
    lo, hi = scene.bounds()
    cam.fit_to(lo, hi, 1.2)
    return cam


def _same_rings(a, b, tol):
    assert len(a) == len(b)
    for ra, rb in zip(a, b):
        ra, rb = np.asarray(ra, float), np.asarray(rb, float)
        assert ra.shape == rb.shape, (ra.shape, rb.shape)
        assert np.allclose(ra, rb, atol=tol, rtol=0), (ra, rb)


def _compare(scene, cam, sp=None):
    proj = (VC._Perspective(cam) if cam.perspective else VC._Parallel(cam))
    items = list(VC._faces_of(scene))
    py = VC._face_geometry_py(items, cam, proj, sp)
    rust = VC._face_geometry_native(items, cam, proj, sp, native)
    assert len(py) == len(rust) == len(items)
    kept = 0
    for gp, gr in zip(py, rust):
        if gp is None:
            assert gr is None
            continue
        assert gr is not None
        wp, rp, dp, npy, bp, nearp = gp
        wr, rr, dr, nr, br, nearr = gr
        # The placement's map is Qt's in single precision; the engine's is
        # double: a few 1e-7 of the drawing's size apart, no more.
        _same_rings(wp, wr, 1e-5)
        assert np.allclose(npy, nr, atol=1e-6)
        assert bp == br
        if nearp is None:
            assert nearr is None and rr == [] and dr == []
            continue
        assert nearr is not None
        _same_rings(rp, rr, 1e-5)
        _same_rings(dp, dr, 1e-5)
        # The plane itself, where it is used: at the drawn corners. Its
        # coefficients may differ more on a face seen at a grazing angle —
        # the fit amplifies the placement's single-precision map — while
        # what it says at every corner stays within rounding.
        xy = np.concatenate([np.asarray(r, float) for r in rp])
        qp = xy @ nearp[:2] + nearp[2]
        qr = xy @ nearr[:2] + nearr[2]
        assert np.allclose(qp, qr, atol=1e-6 * max(1.0, np.abs(qp).max()),
                           rtol=0), (nearp, nearr)
        kept += 1
    return kept


@pytest.mark.parametrize("perspective", [False, True])
def test_the_same_geometry_face_by_face(perspective):
    scene = _scene()
    kept = _compare(scene, _camera(scene, perspective))
    assert kept >= 15                       # most of the box faces


@pytest.mark.parametrize("perspective", [False, True])
def test_with_a_section_cut(perspective):
    from core.section import SectionPlane
    scene = _scene()
    sp = SectionPlane(V(3, 3, 0.7), V(0, 0, 1))
    kept = _compare(scene, _camera(scene, perspective), sp)
    assert kept >= 10


def test_a_face_the_camera_cannot_draw_still_casts():
    """In perspective, a face wholly behind the eye draws nothing and the
    walk skipped it after listing it as a caster: the engine says so."""
    front = Scene()
    front.loose_mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0),
                               V(0, 2, 0)])
    front.version += 1
    cam = OrbitCamera()
    cam.set_aspect(800, 600)
    cam.perspective = True
    cam.set_view("iso")
    lo, hi = front.bounds()
    cam.fit_to(lo, hi, 1.2)
    # The same face, moved to five times its distance behind the eye.
    eye, fwd = cam.eye(), (cam.target - cam.eye()).normalized()
    at = eye - fwd * 5.0 * (cam.target - cam.eye()).length()
    scene = Scene()
    scene.loose_mesh.add_face([at + V(0, 0, 0), at + V(2, 0, 0),
                               at + V(2, 2, 0), at + V(0, 2, 0)])
    scene.version += 1
    proj = VC._Perspective(cam)
    items = list(VC._faces_of(scene))
    py = VC._face_geometry_py(items, cam, proj, None)
    rust = VC._face_geometry_native(items, cam, proj, None, native)
    assert py[0] is not None and py[0][5] is None
    assert rust[0] is not None and rust[0][5] is None
    _same_rings(py[0][0], rust[0][0], 1e-9)


def test_view_faces_goes_through_the_engine_when_it_is_on(monkeypatch):
    scene = _scene()
    cam = _camera(scene, False)
    called = []
    real = VC._face_geometry_native

    def spy(items, *a):
        called.append(len(items))
        return real(items, *a)

    monkeypatch.setattr(VC, "_face_geometry_native", spy)
    # The visible-parts pass pinned to one engine: only the geometry
    # changes between the two runs.
    monkeypatch.setattr(VC, "_visible_parts", VC._visible_parts_py)
    monkeypatch.setattr(_native, "native", native)
    on = VC.view_faces(scene, cam)
    assert called and called[0] == 20
    monkeypatch.setattr(_native, "native", None)
    off = VC.view_faces(scene, cam)
    assert len(called) == 1
    # The placement's map is Qt's, in single precision: between two faces
    # of a turned box that share an edge it leaves hairline slivers the
    # engine's double precision closes exactly. Below a square micrometre
    # of the drawing, those are no face.
    net = lambda f: abs(sum(VC._area(r) for r in f.rings))     # noqa: E731
    on_ = [f for f in on if net(f) > 1e-6]
    off_ = [f for f in off if net(f) > 1e-6]
    assert [f.depth for f in on_] == pytest.approx([f.depth for f in off_],
                                                   abs=1e-6)
    assert [f.layer for f in on_] == [f.layer for f in off_]
    assert [net(f) for f in on_] == pytest.approx([net(f) for f in off_],
                                                  abs=1e-6)
    assert len(on_) >= 10
