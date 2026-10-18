# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Arc Midpoint snap of a lazy mesh is read from its plan: the same
points, in the same order, as from the built mesh — and the mesh stays
unbuilt (moving anything near a plant of 2 500 meshes built them all)."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QVector3D as V

import core._native as _native
from core import mesh as M
from core.group import Group
from core.scene import Scene
from formats import igz
from views.viewport import Viewport


@pytest.fixture
def lazy(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)


def _arcs(m, cid, cx, r, n, sweep):
    pts = [V(cx + r * math.cos(sweep * k / n), r * math.sin(sweep * k / n),
             0.3 * cid) for k in range(n + 1)]
    if sweep >= 2 * math.pi - 1e-9:
        pts[-1] = pts[0]                         # a circle: closed
    for a, b in zip(pts, pts[1:]):
        try:
            m.add_edge(a, b).curve = cid
        except ValueError:
            pass


def test_lazy_arc_midpoints_are_the_built_ones(lazy, tmp_path):
    scene = Scene()
    g = Group(name="Arcos")
    for cid, (cx, r, n, sweep) in enumerate(((0, 1, 8, 1.5), (5, 2, 13, 3.0),
                                             (12, 1, 16, 2 * math.pi),
                                             (20, 3, 5, 0.7))):
        _arcs(g.mesh, 100 + cid, cx, r, n, sweep)
    g.mesh.add_face([V(30, 0, 0), V(31, 0, 0), V(31, 1, 0)])
    scene.groups.append(g)
    path = tmp_path / "arcs.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    m = opened.groups[0].mesh
    assert type(m) is M.DeferredMesh
    got = [p.toTuple() for p in Viewport._mesh_arc_midpoints(m)]
    assert type(m) is M.DeferredMesh, "the snap built the mesh"
    _ = m.faces                                  # build it
    want = [p.toTuple() for p in Viewport._mesh_arc_midpoints(m)]
    assert got == want and len(want) == 3        # three open arcs
