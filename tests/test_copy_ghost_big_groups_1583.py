# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Ctrl-copy ghost of a huge group stays paintable (#1583); a normal
group's ghost is every edge of it, as always."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import DeferredMesh, Mesh
from tests.test_light_faces import big_enough, binary
from tools import move, rotate

__all__ = ["big_enough", "binary"]


def _strip(n, soft=False):
    mesh = Mesh()
    for k in range(n):
        e = mesh.add_edge(V(k, 0, 0), V(k, 0, 1 + k % 2))
        e.soft = soft
    return mesh


def _placed(mesh):
    g = Group(mesh)
    g.xform = QMatrix4x4()
    g.xform.translate(5, 6, 7)
    g.xform.rotate(90, 0, 0, 1)
    return g


def _tuples(segments):
    return {frozenset(tuple(round(c, 3) for c in p.toTuple()) for p in s)
            for s in segments}


def test_a_normal_group_keeps_every_edge(monkeypatch):
    monkeypatch.setattr(move, "GHOST_EDGES", 20)
    g = _placed(_strip(20, soft=True))
    got = move.groups_ghost_segments([g])
    assert _tuples(got) == _tuples(
        (g.xform.map(e.a), g.xform.map(e.b)) for e in g.mesh.edges)
    assert len(got) == 20


@pytest.mark.parametrize("flag", ["soft", "hidden"])
def test_past_the_limit_smooth_and_hidden_edges_go(monkeypatch, flag):
    monkeypatch.setattr(move, "GHOST_EDGES", 20)
    g = _placed(_strip(30))
    for e in g.mesh.edges[5:]:
        setattr(e, flag, True)
    assert _tuples(move.groups_ghost_segments([g])) == _tuples(
        (g.xform.map(e.a), g.xform.map(e.b)) for e in g.mesh.edges[:5])


@pytest.mark.parametrize("soft", [True, False])
def test_a_huge_group_is_its_turned_box(monkeypatch, soft):
    monkeypatch.setattr(move, "GHOST_EDGES", 20)
    g = _placed(_strip(30, soft))
    child = _placed(_strip(1))
    child.xform.setToIdentity()
    child.xform.translate(0, 9, 0)
    g.children = [child]
    got = move.groups_ghost_segments([g])
    assert len(got) == 12
    corners = {tuple(round(c, 3) for c in p.toTuple()) for s in got for p in s}
    assert corners == {tuple(round(c, 3) for c in g.xform.map(V(x, y, z)).toTuple())
                       for x in (0, 29) for y in (0, 9) for z in (0, 2)}


def test_hundreds_of_huge_groups_are_one_box(monkeypatch):
    monkeypatch.setattr(move, "GHOST_EDGES", 20)
    assert len(move.groups_ghost_segments(
        [_placed(_strip(30)) for _ in range(5)])) == 12


def test_an_empty_group_among_them(monkeypatch):
    monkeypatch.setattr(move, "GHOST_EDGES", 20)
    assert len(move.groups_ghost_segments(
        [Group(Mesh()), _placed(_strip(30))])) == 12
    assert move.groups_ghost_segments([Group(Mesh())]) == []


def test_rotate_draws_the_same_ghost():
    assert rotate.groups_ghost_segments is move.groups_ghost_segments


def test_a_lazy_group_is_boxed_unbuilt(monkeypatch, tmp_path, big_enough):
    import core._native as _native
    if _native.native is None:
        pytest.skip("engine off")
    from tests.test_tools_keep_lazy import _boxed_scene
    monkeypatch.setattr(move, "GHOST_EDGES", 11)
    g = _boxed_scene(tmp_path, True, True)
    got = move.groups_ghost_segments([g])
    assert type(g.mesh) is DeferredMesh and len(got) == 12
    g.mesh.faces
    assert _tuples(got) == _tuples(move.groups_ghost_segments([g]))
    monkeypatch.setattr(move, "GHOST_EDGES", 12)
    assert _tuples(got) == _tuples(move.groups_ghost_segments([g]))
