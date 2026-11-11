# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The first section cut reads the layers of what it crosses without
building a single lazy mesh.

The cut fills each chord with the layer of the face it comes from, and
asked the pick index for that face. In a placement still unbuilt (a big
document opens its components lazily), asking for one face built the
whole mesh: 140 of the 153 s of a first cut on a 590-object model, and the
five-second freeze placing a section in a user's video. The layer is in
the document already; it is read from there."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

import core._native as _native
from core import mesh as M
from core.group import Group
from core.layers import DEFAULT_LAYER
from core.scene import Scene
from formats import igz

pytestmark = pytest.mark.skipif(
    _native.available() is None or _native.qt_hypot() is None,
    reason="native module or hypot unknown")


@pytest.fixture
def lazy(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(_native, "wanted", lambda: True)
    monkeypatch.setattr(_native, "native", _native.available())


def _layered_group(tmp_path):
    """A group of six faces: two on «Muros», one on «Losa», three on none,
    one of those hidden (not drawn, so not in the pick index). Saved and
    opened again: its mesh is lazy."""
    scene = Scene()
    m = M.Mesh()
    layers = ["Muros", None, "Losa", None, "Muros", None]
    for k, ly in enumerate(layers):
        x = 2.0 * k
        f = m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 0, 3),
                        V(x, 0, 3)])
        if ly:
            f.attrs["layer"] = ly
        if k == 5:
            f.attrs["hidden"] = True
    g = Group(m, "piezas")
    scene.groups.append(g)
    path = tmp_path / "doc.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    group = opened.groups[-1]
    assert type(group.mesh) is M.DeferredMesh
    return group


def test_a_lazy_faces_layer_is_read_without_building_it(lazy, tmp_path):
    from views.array_bake import DeferredFaces, LazyPairs, PickEntities
    group = _layered_group(tmp_path)
    drawn = np.array([0, 1, 2, 3, 4])               # the hidden one is not
    ents = PickEntities([("loose face", None)])
    ents.extend(LazyPairs(DeferredFaces(group.mesh, drawn), group))
    got = [ents.layer_at(i) for i in range(1, len(ents))]
    assert type(group.mesh) is M.DeferredMesh, "reading built the mesh"
    assert [own for own, _owner in got] == ["Muros", None, "Losa", None,
                                            "Muros"]
    assert all(owner is group for _own, owner in got)
    # Once built, the faces themselves say the same.
    built = [(ents[i][0].attrs or {}).get("layer") for i in range(1, 6)]
    assert type(group.mesh) is M.Mesh
    assert built == [own for own, _owner in got]
    assert [ents.layer_at(i)[0] for i in range(1, 6)] == built


def test_the_cut_tags_its_chords_from_the_document(lazy, tmp_path):
    from types import SimpleNamespace

    from views.array_bake import DeferredFaces, LazyPairs, PickEntities
    from views.viewport import Viewport
    group = _layered_group(tmp_path)
    group.layer = "Mobiliario"                       # the object's own
    ents = PickEntities()
    ents.extend(LazyPairs(DeferredFaces(group.mesh, np.arange(5)), group))
    idx = SimpleNamespace(entities=ents)
    tags = Viewport._cut_layer_tags(idx, np.array([0, 1, 2, 3, 4, 0, 2]))
    assert type(group.mesh) is M.DeferredMesh
    # A face of no layer of its own is filled as its object's.
    assert list(tags) == ["Muros", "Mobiliario", "Losa", "Mobiliario",
                          "Muros", "Muros", "Losa"]
    group.layer = None
    tags = Viewport._cut_layer_tags(idx, np.array([1]))
    assert list(tags) == [DEFAULT_LAYER]
