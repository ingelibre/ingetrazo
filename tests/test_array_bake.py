# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A lazy mesh's drawing baked from its arrays (views.array_bake) is the
chunk the viewport bakes from the built mesh, field for field: colour,
translucent, textured and two-side buckets, the default-back tint, pick
triangles and their faces, areas, hard edges, soft-edge silhouette data,
box, samples and fingerprint — inside painted containers too. And it
builds nothing: the mesh stays deferred until a face is asked for."""
from __future__ import annotations

import random
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D as V

import core._native as _native
from core import mesh as M
from core.scene import Scene
from formats import igz
from tests.test_deferred_mesh import _meshes, _random_scene

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")

_SKIP = {"uid", "faces", "serial", "mesh", "vkey", "obb", "rev"}


@pytest.fixture(params=["binary", "json-walk", "json-bulk"])
def lazy(request, monkeypatch):
    """Lazy meshes from binary blocks, or from JSON ones read by the
    per-entity walk or by the bulk pass."""
    big = request.param == "binary"
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0 if big else 10 ** 12)
    monkeypatch.setattr(igz, "_BULK_MIN",
                        10 ** 12 if request.param == "json-walk" else 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())


@pytest.fixture(scope="module")
def vp():
    from views.main_window import MainWindow
    win = MainWindow()
    yield win.viewport
    win._saved_version = win.viewport.scene.version
    win.close()


def _paint_up(scene, rng, png):
    """Every kind of face paint, at random."""
    for m in _meshes(scene):
        for f in m.faces:
            r = rng.random()
            if r < 0.15:
                f.attrs["texture"] = {"path": str(png), "sw": 0.5,
                                      "sh": 0.7, "rot": 30}
            elif r < 0.25:
                f.attrs["opacity"] = rng.choice([0.5, 0.3])
            elif r < 0.33:
                f.attrs["back"] = {"color": [0.1, 0.6, 0.2]}
            elif r < 0.38:
                f.attrs["back"] = {"color": [0.7, 0.1, 0.2],
                                   "opacity": 0.4}
            elif r < 0.42:
                f.attrs["back"] = True
            elif r < 0.47:
                f.attrs["hidden"] = True
            elif r < 0.52:
                f.attrs["back"] = {"texture": {"path": str(png),
                                               "sw": 1.0, "sh": 1.0}}
            elif r < 0.56:
                f.attrs["texture"] = {"path": str(png), "sw": 1.0,
                                      "sh": 1.0}
                f.attrs["opacity"] = 0.6
            elif r < 0.60:
                f.attrs["back"] = {"texture": {"path": str(png),
                                               "sw": 2.0, "sh": 1.0},
                                   "opacity": 0.5}
        for e in m.edges:
            if rng.random() < 0.3:
                e.soft = True


def _compare(a, b):
    assert set(a) == set(b)
    for k in a:
        if k in _SKIP:
            continue
        x, y = a[k], b[k]
        if isinstance(x, np.ndarray) or isinstance(y, np.ndarray):
            if x is None or y is None:
                assert x is None and y is None, k
                continue
            x, y = np.asarray(x), np.asarray(y)
            assert x.dtype == y.dtype and x.shape == y.shape, k
            assert np.array_equal(x, y), k
        else:
            assert x == y, k


_KINDS = ("by_texture", "tcol", "ttex", "back_vcol", "back_tex",
          "back_tcol", "back_ttex", "fvcol", "dback", "vcol", "edges")


def _with_alpha(scene, rng):
    """Front and back colours as imported ones may come: some with their
    alpha as a fourth value, beside plain RGB ones."""
    for m in _meshes(scene):
        for f in m.faces:
            r = rng.random()
            if r < 0.5:
                f.attrs["color"] = [0.3, 0.5, 0.7, 1.0]
            elif r < 0.6:
                f.attrs["color"] = [0.9, 0.4, 0.1]
            elif r < 0.8:
                f.attrs["back"] = {"color": [0.1, 0.6, 0.2, 1.0]}
            elif r < 0.9:
                f.attrs["back"] = {"color": [0.7, 0.1, 0.2, 0.5],
                                   "opacity": 0.4}


def _check(vp, tmp_path, seed, alpha=False):
    """Bake every mesh of a random painted scene both ways and compare;
    returns the buckets that were not empty."""
    rng = random.Random(seed)
    png = tmp_path / "t.png"
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x8B5A2B)
    img.save(str(png))
    scene = _random_scene(rng)
    _paint_up(scene, rng, png)
    if alpha:
        _with_alpha(scene, rng)
    path = tmp_path / f"doc{seed}.igz"
    igz.save_scene(scene, path)
    paints = [None, {"color": [0.2, 0.3, 0.9]},
              {"color": [0.8, 0.8, 0.1], "opacity": 0.5}]
    seen = set()
    for i in range(len(list(_meshes(scene)))):
        for paint in paints:
            opened = Scene()             # deferred again, every time
            igz.load_into(opened, path)
            m = list(_meshes(opened))[i]
            assert type(m) is M.DeferredMesh
            vp._group_chunks, vp._fp_memo = {}, {}
            got = vp._group_chunk(SimpleNamespace(mesh=m, xform=None,
                                                  material=paint))
            assert type(m) is M.DeferredMesh, "baking builds nothing"
            assert len(got["faces"]) == len(got["areas"])
            faces = list(got["faces"])  # built now: bake the objects
            vp._group_chunks, vp._fp_memo = {}, {}
            want = vp._group_chunk(SimpleNamespace(mesh=m, xform=None,
                                                   material=paint))
            assert type(m) is M.Mesh
            assert faces == want["faces"]
            _compare(got, want)
            seen |= {k for k in _KINDS if got[k]}
            if got["soft_pts"] is not None:
                seen.add("soft")
    return seen


@pytest.mark.parametrize("seed", range(4))
def test_bake_from_arrays_is_the_object_bake(lazy, vp, tmp_path, seed):
    _check(vp, tmp_path, seed)


@pytest.mark.parametrize("seed", range(3))
def test_colours_with_their_alpha_bake_as_rgb(lazy, vp, tmp_path, seed):
    """pileta.igz: RGBA colours stopped every frame with the engine on."""
    seen = _check(vp, tmp_path, seed, alpha=True)
    assert {"vcol", "back_vcol", "back_tcol"} <= seen


def test_every_bucket_is_compared(lazy, vp, tmp_path):
    seen = set()
    for seed in range(4, 10):
        seen |= _check(vp, tmp_path, seed)
    assert seen == set(_KINDS) | {"soft"}, set(_KINDS) - seen


def test_a_baked_mesh_stays_valid_without_building(lazy, vp, tmp_path):
    scene = _random_scene(random.Random(1))
    path = tmp_path / "doc.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    m = opened.groups[-1].mesh
    w = SimpleNamespace(mesh=m, xform=None, material=None)
    vp._group_chunks = {}
    first = vp._group_chunk(w)
    vp.scene.version += 1                # any edit elsewhere
    assert vp._group_chunk(w) is first
    assert type(m) is M.DeferredMesh
