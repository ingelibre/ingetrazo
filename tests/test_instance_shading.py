# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A rotated component instance is lit by its world normals (#482).

The prototype chunk bakes each face's colour from its LOCAL normal, and
``Viewport._instance_chunk`` transformed the positions (and the soft-edge
normals) but carried the baked colours — and the texture runs' shade
keys — over unchanged. A copy rotated 40° kept its definition's light:
the front face stayed light and the bottom dark, while the same geometry
as a plain group shaded the other way round.
"""
from __future__ import annotations

import types

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage, QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from views.viewport import Viewport

BASE = (0.55, 0.45, 0.35)


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _VP:
    def __init__(self, scene):
        self.scene = scene

    def width(self):
        return 100

    def height(self):
        return 100


def _stub(scene):
    """A Viewport with no GL: every plain method bound, no chunk disk cache."""
    vp = _VP(scene)
    for name in dir(Viewport):
        if name.startswith("__") or hasattr(vp, name):
            continue
        attr = Viewport.__dict__.get(name)
        if isinstance(attr, types.FunctionType):
            setattr(vp, name, attr.__get__(vp))
        elif isinstance(attr, staticmethod):
            setattr(vp, name, attr.__func__)
        elif not callable(attr) and attr is not None:
            setattr(vp, name, attr)
    vp.active_tool = None
    vp._chunk_cache_load = None
    vp._chunk_cache_store = None
    return vp


def _box_mesh():
    """A 1 x 1 x 1 box, every face painted BASE."""
    m = Mesh()
    quads = [
        [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)],   # bottom (-Z)
        [V(0, 0, 1), V(0, 1, 1), V(1, 1, 1), V(1, 0, 1)],   # top (+Z)
        [V(0, 0, 0), V(0, 1, 0), V(0, 1, 1), V(0, 0, 1)],   # -X
        [V(1, 0, 0), V(1, 0, 1), V(1, 1, 1), V(1, 1, 0)],   # +X
        [V(0, 0, 0), V(0, 0, 1), V(1, 0, 1), V(1, 0, 0)],   # front (-Y)
        [V(0, 1, 0), V(1, 1, 0), V(1, 1, 1), V(0, 1, 1)],   # +Y
    ]
    for q in quads:
        f = m.add_face(q)
        f.attrs["color"] = BASE
    return m


def _instance(mesh, matrix):
    g = Group(mesh, name="copy")
    g.xform = matrix
    g.component = True
    return g


def _rot_x(deg):
    m = QMatrix4x4()
    m.rotate(deg, 1.0, 0.0, 0.0)
    return m


def _unique_rgbs(chunk):
    a = np.frombuffer(chunk["vcol"], np.float32).reshape(-1, 6)
    return np.unique(a[:, 3:6], axis=0)


def _assert_same_colours(chunk_a, chunk_b, tol):
    ua, ub = _unique_rgbs(chunk_a), _unique_rgbs(chunk_b)
    assert len(ua) == len(ub), (ua, ub)
    for rgb in ua:
        assert np.min(np.abs(ub - rgb).max(axis=1)) < tol, (rgb, ub)
    for rgb in ub:
        assert np.min(np.abs(ua - rgb).max(axis=1)) < tol, (rgb, ua)


def test_a_rotated_instance_shades_like_the_same_geometry_uninstanced():
    scene = Scene()
    mesh = _box_mesh()
    rot = _rot_x(40.0)
    plain_mesh = Mesh()
    for f in mesh.faces:
        nf = plain_mesh.add_face([rot.map(v) for v in f.vertices])
        nf.attrs["color"] = BASE
    plain = Group(plain_mesh, name="plain")
    turned = _instance(mesh, rot)
    straight = _instance(mesh, QMatrix4x4())
    scene.groups.extend([plain, turned, straight])
    vp = _stub(scene)

    _assert_same_colours(vp._group_chunk(turned), vp._group_chunk(plain),
                         tol=0.03)
    # …and the rotation really moved the light: the unrotated instance
    # (the old behaviour for every instance) shades differently.
    with pytest.raises(AssertionError):
        _assert_same_colours(vp._group_chunk(turned),
                             vp._group_chunk(straight), tol=0.03)


def test_a_translated_instance_keeps_the_prototype_colours():
    scene = Scene()
    mesh = _box_mesh()
    move = QMatrix4x4()
    move.translate(V(5.0, 3.0, 2.0))
    moved = _instance(mesh, move)
    straight = _instance(mesh, QMatrix4x4())
    scene.groups.extend([moved, straight])
    vp = _stub(scene)
    ua = _unique_rgbs(vp._group_chunk(straight))
    ub = _unique_rgbs(vp._group_chunk(moved))
    assert len(ua) == len(ub)
    assert np.allclose(np.sort(ua, axis=0), np.sort(ub, axis=0), atol=1e-6)


def test_a_rotated_instance_texture_run_carries_the_world_shade(tmp_path):
    img = QImage(8, 8, QImage.Format.Format_RGBA8888)
    img.fill(QColor(180, 120, 60))
    path = str(tmp_path / "wood.png")
    img.save(path)

    scene = Scene()
    mesh = Mesh()
    f = mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    f.attrs["texture"] = {"path": path, "sw": 1.0, "sh": 1.0}
    turned = _instance(mesh, _rot_x(90.0))
    straight = _instance(mesh, QMatrix4x4())
    scene.groups.extend([turned, straight])
    vp = _stub(scene)

    (key_flat,) = vp._group_chunk(straight)["by_texture"].keys()
    (key_turned,) = vp._group_chunk(turned)["by_texture"].keys()
    assert key_flat[0] == key_turned[0] == path
    assert key_flat[1] == pytest.approx(vp._shade_factor(V(0, 0, 1)))
    # Rotated 90° about X, the face's plane faces -Y: its run must carry
    # that plane's shade, not the prototype's.
    assert key_turned[1] == pytest.approx(vp._shade_factor(V(0, -1, 0)))
    assert key_turned[1] != key_flat[1]
