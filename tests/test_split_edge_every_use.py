# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Splitting an edge reaches every use of it in a face.

A face can walk one edge twice: a slit (a line drawn from a wall's outline
to its opening turns the wall into one loop that goes up the line and back
down it), or a jamb two openings of one face share. ``Mesh.split_edge``
put the new point into the first use only, and the halves listed the face
once. Divided in three, the slit kept a segment with no edge (save and
reopen gave a different model); divided in two, erasing one piece took
the whole wall, because the piece no longer read as a line inside it."""
from __future__ import annotations

from collections import Counter

import pytest
from PySide6.QtGui import QVector3D

from core.edits import build_add_edge, divide_edges
from core.history import EraseSelectionCommand, History, SnapshotMutation
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _segments(face):
    for lp in (face.loop, *face.hole_loops):
        n = len(lp)
        for i in range(n):
            yield lp[i], lp[(i + 1) % n]


def _check_incidence(m):
    """Every segment of every face has an edge, and the edge lists the face
    once per segment — as ``add_face`` lists a slit or a shared jamb."""
    for f in m.faces:
        uses = Counter()
        for a, b in _segments(f):
            e = m.find_edge(a, b)
            assert e is not None, "a face segment with no edge"
            uses[id(e)] += 1
        for e in {id(e): e for e in m.edges}.values():
            assert sum(1 for g in e.faces if g is f) == uses[id(e)]


def _shape(m):
    """What a save keeps: the edges and every face's loop sizes."""
    return (len(m.edges),
            sorted((len(f.loop), tuple(sorted(len(h) for h in f.hole_loops)))
                   for f in m.faces))


def _reopened(scene, tmp_path):
    path = tmp_path / "model.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    return back.mesh


def _draw(scene, history, pts, closed=True):
    n = len(pts)
    for i in range(n if closed else n - 1):
        history.execute(build_add_edge(scene, pts[i], pts[(i + 1) % n]))
        assert history.last_error is None


def _slit_wall():
    """A 4 × 3 m wall with a 1 × 1 m opening, and a line drawn from the
    bottom of the wall to the bottom of the opening: the slit."""
    scene = Scene()
    history = History(scene)
    _draw(scene, history, [V(0, 0), V(4, 0), V(4, 3), V(0, 3)])
    _draw(scene, history, [V(1.5, 1), V(2.5, 1), V(2.5, 2), V(1.5, 2)])
    _draw(scene, history, [V(2, 0), V(2, 1)], closed=False)
    m = scene.mesh
    slit = m.find_edge(m.vertex_at(V(2, 0)), m.vertex_at(V(2, 1)))
    wall = next(f for f in m.faces if abs(f.area() - 11.0) < 1e-6)
    assert sum(1 for a, b in _segments(wall)
               if {a, b} == {slit.v0, slit.v1}) == 2  # walked up and back
    return scene, history, wall, slit


def _divide(history, edge, n):
    history.execute(SnapshotMutation(
        lambda sc: divide_edges(sc.mesh, [edge], n)))
    assert history.last_error is None


@pytest.mark.parametrize("n", [2, 3, 4])
def test_a_divided_slit_line_is_divided_on_both_sides(n, tmp_path):
    scene, history, wall, slit = _slit_wall()
    _divide(history, slit, n)
    m = scene.mesh
    _check_incidence(m)
    points = [v for v in m.vertices
              if abs(v.position.x() - 2) < 1e-6 and 0 < v.position.y() < 1]
    assert len(points) == n - 1
    for v in points:                                # up the slit and back down
        assert sum(1 for w in wall.loop if w is v) == 2
    back = _reopened(scene, tmp_path)
    _check_incidence(back)
    assert _shape(back) == _shape(m)


@pytest.mark.parametrize("n", [2, 3])
def test_erasing_a_piece_of_a_divided_slit_keeps_the_wall(n):
    scene, history, wall, slit = _slit_wall()
    _divide(history, slit, n)
    m = scene.mesh
    bottom = m.vertex_at(V(2, 0))
    piece = next(e for e in bottom.edges
                 if abs(e.other(bottom).position.x() - 2) < 1e-6)
    history.execute(EraseSelectionCommand([piece]))
    assert history.last_error is None
    # As when the whole slit is erased: the wall is whole again, with its
    # opening; the rest of the slit stays as a line.
    walls = [f for f in m.faces if abs(f.area() - 12.0) < 1e-6]
    assert len(walls) == 1 and len(m.faces) == 2
    assert len(walls[0].hole_loops) == 1
    _check_incidence(m)


def _two_openings(m, punched):
    """A 6 × 3 m wall with two 2 × 1 m openings side by side, sharing the
    jamb x = 3 — as a file builds it (``add_face`` with both holes) or as
    two punches (``add_hole``) leave it."""
    outline = [V(0, 0), V(6, 0), V(6, 3), V(0, 3)]
    left = [V(1, 1), V(1, 2), V(3, 2), V(3, 1)]
    right = [V(3, 1), V(3, 2), V(5, 2), V(5, 1)]
    if punched:
        wall = m.add_face(outline)
        m.add_hole(wall, left)
        m.add_hole(wall, right)
    else:
        wall = m.add_face(outline, [left, right])
    jamb = m.find_edge(m.vertex_at(V(3, 1)), m.vertex_at(V(3, 2)))
    return wall, jamb


@pytest.mark.parametrize("punched", [False, True])
@pytest.mark.parametrize("n", [2, 3])
def test_a_jamb_two_openings_share_is_divided_in_both(punched, n, tmp_path):
    scene = Scene()
    m = scene.mesh
    wall, jamb = _two_openings(m, punched)
    assert divide_edges(m, [jamb], n) == n - 1
    points = [v for v in m.vertices
              if abs(v.position.x() - 3) < 1e-6 and 1 < v.position.y() < 2]
    assert len(points) == n - 1
    for hole in wall.hole_loops:
        assert all(any(w is v for w in hole) for v in points)
    _check_incidence(m)
    back = _reopened(scene, tmp_path)
    _check_incidence(back)
    assert _shape(back) == _shape(m)


def test_a_split_shared_by_two_faces_lists_each_once():
    """The ordinary case is unchanged: an edge between two faces."""
    m = Mesh()
    a = m.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    b = m.add_face([V(2, 0), V(4, 0), V(4, 2), V(2, 2)])
    shared = m.find_edge(m.vertex_at(V(2, 0)), m.vertex_at(V(2, 2)))
    e0, e1 = m.split_edge(shared, V(2, 1))
    for half in (e0, e1):
        assert sorted(map(id, half.faces)) == sorted([id(a), id(b)])
    assert len(a.loop) == 5 and len(b.loop) == 5
    _check_incidence(m)
