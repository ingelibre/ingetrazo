# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A group's points for its selection box are read from a lazy mesh's
document data: the same points as from the built mesh, and the mesh stays
unbuilt. A box drawn over the 590 groups of a 5-million-face model built
every one of them and went past 12 GB."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

import core._native as _native
from core import mesh as M
from core.group import Group, iter_placements, placement_points
from core.scene import Scene
from formats import igz
from views.viewport import Viewport


@pytest.fixture
def lazy(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)


def _box(m, x0, y0, z0, s):
    P = V
    x1, y1, z1 = x0 + s, y0 + s, z0 + s
    for loop in ([P(x0, y0, z0), P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0)],
                 [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)],
                 [P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)],
                 [P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1)],
                 [P(x0, y1, z0), P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1)],
                 [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)]):
        m.add_face(loop)


def _opened(tmp_path):
    scene = Scene()
    plain = Group(name="Caja")
    _box(plain.mesh, 0, 0, 0, 1)
    turned = Group(name="Girada")
    _box(turned.mesh, 3, 0, 0, 0.5)
    turned.mesh.add_face([V(3, 2, 0), V(4, 2, 0), V(4, 2.5, 0.3)])
    xf = QMatrix4x4()
    xf.translate(10, 2, 1)
    xf.rotate(30, 0, 0, 1)
    turned.xform = xf
    scene.groups.extend([plain, turned])
    path = tmp_path / "cajas.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    return opened


def _rows(a):
    return np.unique(np.round(a, 9), axis=0)


def test_lazy_points_are_the_built_ones(lazy, tmp_path):
    scene = _opened(tmp_path)
    assert all(type(g.mesh) is M.DeferredMesh for g in scene.groups)
    got = [placement_points(g) for g in scene.groups]
    assert all(type(g.mesh) is M.DeferredMesh for g in scene.groups), \
        "reading the points built the mesh"
    for g in scene.groups:
        for pg, _m in iter_placements(g):
            _ = pg.mesh.faces                    # build it
    want = [placement_points(g) for g in scene.groups]
    for a, b in zip(got, want):
        assert len(a) and np.array_equal(_rows(a), _rows(b))


def test_the_selection_box_of_a_lazy_group_builds_nothing(lazy, tmp_path):
    scene = _opened(tmp_path)
    boxes = [Viewport._compute_obb(g) for g in scene.groups]
    assert all(type(g.mesh) is M.DeferredMesh for g in scene.groups)
    for g in scene.groups:
        _ = g.mesh.faces
    again = [Viewport._compute_obb(g) for g in scene.groups]
    for (_f, lo, hi), (_f2, lo2, hi2) in zip(boxes, again):
        assert lo == pytest.approx(lo2, abs=1e-9)
        assert hi == pytest.approx(hi2, abs=1e-9)
