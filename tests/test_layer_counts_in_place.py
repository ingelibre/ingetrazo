# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Layers panel's counts read a plain mesh's face and edge layers in
place instead of calling ``layer_of`` on each (night of 19-11): the same
counts, in the same order, unlabelled and default-named folded alike."""
from __future__ import annotations

import random

import pytest
from PySide6.QtGui import QVector3D as V

from core import purge
from core.layers import DEFAULT_LAYER, layer_of
from core.mesh import Mesh
from core.scene import Scene


def _scene(seed):
    rng = random.Random(seed)
    sc = Scene()
    names = [None, "", DEFAULT_LAYER, "Muros", "Losa"]
    for i in range(rng.randint(2, 30)):
        x = i * 2
        f = sc.mesh.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0)])
        nm = rng.choice(names)
        if nm is not None:
            f.attrs["layer"] = nm
    for e in sc.mesh.edges:
        e.layer = rng.choice(names)
    return sc


def _before(scene, monkeypatch):
    from core import mesh as M

    class NotFace:
        pass
    # Every entity through layer_of: the walk as it was.
    with monkeypatch.context() as mp:
        mp.setattr(M, "Face", NotFace)
        mp.setattr(M, "Edge", NotFace)
        return purge.layer_counts(scene)


@pytest.mark.parametrize("seed", range(30))
def test_the_same_counts(seed, monkeypatch):
    sc = _scene(seed)
    got = purge.layer_counts(sc)
    want = _before(sc, monkeypatch)
    assert list(got.items()) == list(want.items())
    total = len(sc.mesh.faces) + len(sc.mesh.edges)
    assert sum(got.values()) >= total
    assert sum(1 for f in sc.mesh.faces if layer_of(f) == "Muros") <= \
        got.get("Muros", 0)
