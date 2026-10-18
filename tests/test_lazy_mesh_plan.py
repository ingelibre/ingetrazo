# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A deferred mesh's plan (core.lazy_mesh) is the mesh building it makes,
index for index: vertex positions in list order, edges in list order with
their direction and flags, face corners, and each edge's incident faces in
order — on scenes whose corners sit a hair apart, so the weld's boundary
probes run, with duplicate and welded-shut edges."""
from __future__ import annotations

import random

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

import core._native as _native
from core import lazy_mesh
from core import mesh as M
from core.scene import Scene
from formats import igz
from tests.test_deferred_mesh import _meshes, _random_scene


@pytest.fixture
def binary(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)


def _compare(plan, m):
    vid = {id(v): i for i, v in enumerate(m.vertices)}
    assert plan.pos.tolist() == [list(v.position.toTuple())
                                 for v in m.vertices]
    assert plan.edges.tolist() == [[vid[id(e.v0)], vid[id(e.v1)]]
                                   for e in m.edges]
    assert plan.soft.tolist() == [bool(e.soft) for e in m.edges]
    assert plan.hidden.tolist() == [bool(getattr(e, "hidden", False))
                                    for e in m.edges]
    assert plan.curve == [e.curve for e in m.edges]
    assert plan.layer == [e.layer for e in m.edges]
    fid = {id(f): i for i, f in enumerate(m.faces)}
    corners = [vid[id(v)] for f in m.faces
               for ring in [f.loop] + f.hole_loops for v in ring]
    assert plan.corners.tolist() == corners
    assert plan.ring_counts.tolist() == [1 + len(f.hole_loops)
                                         for f in m.faces]
    ef = [[fid[id(f)] for f in e.faces] for e in m.edges]
    got = [plan.ef_face[plan.ef_start[i]:plan.ef_start[i + 1]].tolist()
           for i in range(len(plan.edges))]
    assert got == ef


@pytest.mark.parametrize("seed", range(10))
def test_plan_is_the_built_mesh(binary, tmp_path, seed):
    path = tmp_path / "doc.igz"
    igz.save_scene(_random_scene(random.Random(seed)), path)
    scene = Scene()
    igz.load_into(scene, path)
    n = 0
    for m in _meshes(scene):
        plan = lazy_mesh.plan_of(m)
        assert plan is not None
        assert type(m) is M.DeferredMesh     # planning builds nothing
        _compare(plan, m)                    # this touch builds it
        n += 1
    assert n >= 3


@pytest.mark.parametrize("engine", ["numpy", "rust"])
def test_weld_is_bulk_weld(monkeypatch, engine):
    """The weld alone, on raw points crowded at cell borders — the NumPy
    replay and the Rust one."""
    mod = _native.available()
    if engine == "rust" and mod is None:
        pytest.skip("native module not built")
    monkeypatch.setattr(_native, "native", mod if engine == "rust" else None)
    rng = random.Random(5)
    for _ in range(30):
        pts = []
        for _ in range(rng.randrange(1, 400)):
            c = [rng.randrange(-3, 3) * 0.5 + rng.choice(
                [0, 4.9e-5, 5.1e-5, -5e-5, 1e-6, 9.9e-5]) for _ in range(3)]
            pts.append(c)
        pts = np.array(pts)
        m = M.Mesh()
        vobjs, ids = m.bulk_weld(pts)
        vpos, pid = lazy_mesh.weld(pts)
        assert vpos.tolist() == [list(v.position.toTuple())
                                 for v in m.vertices]
        assert [id(vobjs[i]) for i in ids.tolist()] == \
            [id(m.vertices[i]) for i in pid.tolist()]


def test_duplicate_and_shut_edges(binary, tmp_path):
    scene = Scene()
    m = scene.mesh
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    e = m.add_edge(V(5, 0, 0), V(6, 0, 0))
    e.soft, e.curve, e.layer = True, 3, "Guias"
    m.add_edge(V(6, 0, 0), V(6, 1, 0)).hidden = True
    # Saved apart, welded shut on reading: the ends of an edge and the
    # corner of a face moved a hair from their neighbours.
    shut = m.add_edge(V(7, 0, 0), V(7.5, 0, 0))
    shut.v1.position = V(7 + 2e-6, 0, 0)
    tri = m.add_face([V(9, 0, 0), V(10, 0, 0), V(10, 1, 0), V(9.5, 1, 0)])
    tri.loop[3].position = V(10 + 3e-6, 1, 0)
    m.add_edge(V(5, 0, 0), V(6, 0, 0))            # a duplicate
    path = tmp_path / "doc.igz"
    igz.save_scene(scene, path)
    s2 = Scene()
    igz.load_into(s2, path)
    _compare(lazy_mesh.plan_of(s2.mesh), s2.mesh)


@pytest.mark.parametrize("engine", ["numpy", "rust"])
def test_sequential_weld_is_vertex_by_vertex(monkeypatch, engine):
    """weld(sequential=True): the vertices Mesh.vertex makes point by point
    — the per-entity reader's order — on points crowded at cell borders."""
    mod = _native.available()
    if engine == "rust" and mod is None:
        pytest.skip("native module not built")
    monkeypatch.setattr(_native, "native", mod if engine == "rust" else None)
    rng = random.Random(8)
    for _ in range(30):
        pts = np.array([[rng.randrange(-3, 3) * 0.5 + rng.choice(
            [0, 4.9e-5, 5.1e-5, -5e-5, 1e-6, 9.9e-5]) for _ in range(3)]
            for _ in range(rng.randrange(1, 300))])
        m = M.Mesh()
        vs = [m.vertex(V(*p)) for p in pts.tolist()]
        vpos, pid = lazy_mesh.weld(pts, sequential=True)
        assert vpos.tolist() == [list(v.position.toTuple())
                                 for v in m.vertices]
        assert [id(m.vertices[i]) for i in pid.tolist()] == \
            [id(v) for v in vs]


def test_planned_vertices_read_like_the_vertex_list(binary, tmp_path):
    """What position-only readers (push/pull's level inference) get from a
    lazy mesh: the built vertex list's positions, in order, nothing built."""
    path = tmp_path / "doc.igz"
    igz.save_scene(_random_scene(random.Random(6)), path)
    scene = Scene()
    igz.load_into(scene, path)
    for m in _meshes(scene):
        pv = lazy_mesh.PlannedVertices(lazy_mesh.plan_of(m).pos)
        got = [pv[i].position.toTuple() for i in range(len(pv))]
        assert type(m) is M.DeferredMesh
        assert got == [v.position.toTuple() for v in m.vertices]
