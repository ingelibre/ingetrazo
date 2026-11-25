# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A BUILT mesh baked from arrays (views.array_bake.bake_built — the mesh
open for editing is baked so on every edit) is the chunk the object walk
bakes, field for field: every bucket, pick triangles and their faces,
areas, edges, soft-edge data, box, samples — painted containers, alpha
colours, holes, hidden faces, and curved surfaces shaded round (#131).
"""
from __future__ import annotations

import math
import random
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D as V

import core._native as _native
from core import mesh as M
from tests.test_array_bake import _KINDS, _compare, _paint_up, _with_alpha
from tests.test_deferred_mesh import _meshes, _random_scene
from views import array_bake

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")


@pytest.fixture(scope="module")
def vp():
    from views.main_window import MainWindow
    win = MainWindow()
    yield win.viewport
    win._saved_version = win.viewport.scene.version
    win.close()


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 0)


def _both(vp, monkeypatch, mesh, paint):
    holder = SimpleNamespace(mesh=mesh, xform=None, material=paint)
    calls = []
    real = array_bake.bake_built
    with monkeypatch.context() as mp:
        mp.setattr(array_bake, "bake_built",
                   lambda *a: calls.append(1) or real(*a))
        vp._group_chunks, vp._fp_memo = {}, {}
        got = vp._group_chunk(holder)
    assert calls == [1], "baked from arrays"
    assert isinstance(got["faces"], list)
    with monkeypatch.context() as mp:
        mp.setattr(array_bake, "can_bake_built", lambda m: False)
        vp._group_chunks, vp._fp_memo = {}, {}
        mesh.__dict__.pop("_face_geom_memo", None)
        want = vp._group_chunk(holder)
    assert got["faces"] == want["faces"]
    _compare(got, want)
    assert got["fp"] == want["fp"]
    return got


def _cylinder(mesh, n=16, r=1.0, h=2.0, at=V(0, 0, 0), caps=True):
    ring = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p0 = at + V(r * math.cos(a0), r * math.sin(a0), 0)
        p1 = at + V(r * math.cos(a1), r * math.sin(a1), 0)
        mesh.add_face([p0, p1, p1 + V(0, 0, h), p0 + V(0, 0, h)])
        ring.append(p0)
    for e in mesh.edges:
        if abs(e.a.z() - e.b.z()) > h / 2:
            e.soft = True
    if caps:
        mesh.add_face([p + V(0, 0, h) for p in ring])


PAINTS = [None, {"color": [0.2, 0.3, 0.9]},
          {"color": [0.8, 0.8, 0.1], "opacity": 0.5}]


@pytest.mark.parametrize("seed", range(6))
def test_built_bake_from_arrays_is_the_object_bake(vp, monkeypatch, tmp_path,
                                                   seed):
    rng = random.Random(seed)
    png = tmp_path / "t.png"
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x8B5A2B)
    img.save(str(png))
    scene = _random_scene(rng)
    _paint_up(scene, rng, png)
    if seed % 2:
        _with_alpha(scene, rng)
    seen = set()
    for m in _meshes(scene):
        assert type(m) is M.Mesh
        if seed % 3 == 0:
            _cylinder(m, at=V(rng.random() * 3, 0, 1.0))
        for paint in PAINTS:
            got = _both(vp, monkeypatch, m, paint)
            seen |= {k for k in _KINDS if got[k]}
    assert "vcol" in seen


def test_curved_surfaces_bake_round_from_arrays(vp, monkeypatch):
    m = M.Mesh()
    _cylinder(m, n=24)
    for f in list(m.faces)[::3]:
        f.attrs["color"] = [0.7, 0.3, 0.2]
    list(m.faces)[1].attrs["opacity"] = 0.4
    got = _both(vp, monkeypatch, m, None)
    tones = np.frombuffer(got["vcol"], np.float32).reshape(-1, 6)[:, 3]
    assert len(np.unique(tones)) > 6            # shaded corner by corner


def test_hidden_faces_and_holes(vp, monkeypatch):
    m = M.Mesh()
    for i in range(6):
        f = m.add_face([V(i, 0, 0), V(i + 1, 0, 0), V(i + 1, 1, 0),
                        V(i, 1, 0)],
                       [[V(i + .3, .3, 0), V(i + .6, .3, 0),
                         V(i + .6, .6, 0), V(i + .3, .6, 0)]] if i % 2 else None)
        if i == 2:
            f.attrs["hidden"] = True
        if i == 4:
            f.attrs["back"] = {"color": [0.1, 0.5, 0.2]}
    m.add_edge(V(0, 2, 0), V(3, 2, 0)).hidden = True
    _both(vp, monkeypatch, m, None)
    _both(vp, monkeypatch, m, PAINTS[2])


def test_an_edit_bakes_again_the_same_way(vp, monkeypatch):
    """After edits (a face moved, one painted, one deleted) the arrays
    still bake what the walk bakes."""
    m = M.Mesh()
    _cylinder(m, n=12)
    for i in range(5):
        m.add_face([V(i, 5, 0), V(i + 1, 5, 0), V(i + 1, 6, 0), V(i, 6, 0)])
    _both(vp, monkeypatch, m, None)
    faces = list(m.faces)
    for v in faces[-1].loop:
        v.position = v.position + V(0, 0, 0.25)
    faces[-2].attrs["color"] = [0.2, 0.9, 0.4]
    m.remove_face(faces[-3])
    _both(vp, monkeypatch, m, None)


def test_a_small_mesh_keeps_the_walk(vp, monkeypatch):
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 500)
    m = M.Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    assert not array_bake.can_bake_built(m)


def test_copies_of_one_paint_on_many_sides(vp, monkeypatch, tmp_path):
    """Every face its own copy of the same attrs — what a built mesh holds
    after an import or a paint over many faces — on sides facing every
    way, textured front and back: the bake shares each content's row and
    map (night of 19-11) and still comes out as the object bake."""
    png = tmp_path / "t.png"
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x2B5A8B)
    img.save(str(png))
    m = M.Mesh()
    _cylinder(m, n=10)
    p = [V(4, 0, 0), V(5, 0, 0), V(5, 1, 0), V(4, 1, 0)]
    q = [v + V(0, 0, 1) for v in p]
    m.add_face(p[::-1])
    m.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        m.add_face([p[i], p[j], q[j], q[i]])
    tex = {"path": str(png), "sw": 0.5, "sh": 0.5}
    for i, f in enumerate(m.faces):
        if i % 3 == 0:
            f.attrs.update({"texture": dict(tex), "color": [0.5, 0.4, 0.3]})
        elif i % 3 == 1:
            f.attrs.update({"color": [0.1, 0.8, 0.2],
                            "back": {"texture": dict(tex), "opacity": 0.5}})
        else:
            f.attrs.update({"texture": dict(tex), "opacity": 0.6})
    for paint in PAINTS:
        got = _both(vp, monkeypatch, m, paint)
        assert got["by_texture"] or got["ttex"]
