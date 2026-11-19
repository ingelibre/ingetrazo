# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A push/pull preview hides the face being pushed; inside a big open
group the rest is baked from arrays without it (night of 19-11) instead
of bucketing every face one by one. That part draws what the object walk
draws for the mesh with the hidden faces deleted — every face bucket,
pick triangle and area — and it is kept until the model or the hidden
set changes."""
from __future__ import annotations

import random
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D as V

import core._native as _native
from core import mesh as M
from tests.test_array_bake import _KINDS, _paint_up, _with_alpha
from tests.test_array_bake_built import PAINTS, _cylinder
from tests.test_deferred_mesh import _meshes, _random_scene
from views import array_bake

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")

FIELDS = tuple(k for k in _KINDS if k != "edges") + (
    "areas", "v0", "e1", "e2", "tri_ent")


@pytest.fixture(scope="module")
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())
    monkeypatch.setattr(array_bake, "BUILT_MIN_FACES", 0)


def _same(got, want):
    assert [id(f) for f in got["faces"]] == [id(f) for f in want["faces"]]
    for k in FIELDS:
        x, y = got[k], want[k]
        if isinstance(x, dict):
            assert x.keys() == y.keys(), k
            for kk in x:
                assert bytes(x[kk]) == bytes(y[kk]), (k, kk)
        elif isinstance(x, np.ndarray) or isinstance(y, np.ndarray):
            assert np.array_equal(np.asarray(x), np.asarray(y)), k
        else:
            assert bytes(x or b"") == bytes(y or b""), k


def _walk_without(vp, monkeypatch, mesh, paint, hidden):
    """The object walk's chunk of ``mesh`` with ``hidden`` deleted (and
    put back after)."""
    holder = SimpleNamespace(mesh=mesh, xform=None, material=paint)
    order = list(mesh.faces)
    for f in hidden:
        mesh.remove_face(f)
    try:
        with monkeypatch.context() as mp:
            mp.setattr(array_bake, "can_bake_built", lambda m: False)
            vp._group_chunks, vp._fp_memo = {}, {}
            mesh.__dict__.pop("_face_geom_memo", None)
            return vp._group_chunk(holder)
    finally:
        for f in hidden:
            for lp in (f.loop, *f.hole_loops):
                n = len(lp)
                for i in range(n):
                    e = mesh.find_edge(lp[i], lp[(i + 1) % n])
                    if f not in e.faces:
                        e.faces.append(f)
        mesh.faces[:] = order


def _beside_soft(f):
    return any(getattr(e, "soft", False) for lp in (f.loop, *f.hole_loops)
               for v in lp for e in v.edges)


@pytest.mark.parametrize("seed", range(6))
def test_the_part_is_the_walk_without_the_hidden_faces(win, monkeypatch,
                                                       tmp_path, seed):
    from core.materials import material_sig
    vp = win.viewport
    rng = random.Random(seed)
    png = tmp_path / "t.png"
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x8B5A2B)
    img.save(str(png))
    scene = _random_scene(rng)
    _paint_up(scene, rng, png)
    if seed % 2:
        _with_alpha(scene, rng)
    for m in _meshes(scene):
        if seed % 3 == 0:
            _cylinder(m, at=V(rng.random() * 3, 0, 1.0))
        faces = list(m.faces)
        if len(faces) < 2:
            continue
        hidden = set(rng.sample(faces, rng.randint(1, min(3, len(faces) - 1))))
        # (Beside a soft edge the faces are bucketed one by one: see below.)
        hidden = {f for f in hidden if not _beside_soft(f)}
        if not hidden:
            continue
        for paint in PAINTS:
            got = array_bake.bake_built(
                vp, m, paint, material_sig(paint), None,
                [f for f in m.faces if f not in hidden], list(m.edges))
            assert got is not None
            want = _walk_without(vp, monkeypatch, m, paint, hidden)
            _same(got, want)


def test_the_open_group_part_is_kept_until_something_changes(win):
    from core.group import Group
    from core.history import SetFaceColorCommand
    vp = win.viewport
    m = M.Mesh()
    for i in range(10):
        for j in range(10):
            m.add_face([V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                        V(i, j + 1, 0)])
    g = Group(m, "big")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    vp.begin_group_edit(g)
    E = vp.scene.edit_group
    face = next(iter(E.mesh.faces))
    a = vp._chunk_without(E, {face})
    assert a is not None and face not in a["faces"]
    assert len(a["faces"]) == len(E.mesh.faces) - 1
    assert vp._chunk_without(E, {face}) is a                 # kept
    other = list(E.mesh.faces)[5]
    assert vp._chunk_without(E, {other}) is not a            # another face
    vp.history.execute(SetFaceColorCommand([other], (0.9, 0.1, 0.1)))
    b = vp._chunk_without(E, {face})
    assert b is not a                                        # an edit
    vp.set_suppressed_faces({face})
    vp.set_suppressed_faces(set())
    assert vp._chunk_without_memo is None
    vp.end_group_edit()
    vp.scene.groups.clear()
    vp.scene.version += 1


def test_beside_a_curved_surface_the_faces_are_bucketed(win):
    from core.group import Group
    vp = win.viewport
    m = M.Mesh()
    _cylinder(m, n=12)
    g = Group(m, "round")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    vp.begin_group_edit(g)
    E = vp.scene.edit_group
    side = next(f for f in E.mesh.faces if _beside_soft(f))
    assert vp._chunk_without(E, {side}) is None
    vp.end_group_edit()
    vp.scene.groups.clear()
    vp.scene.version += 1
