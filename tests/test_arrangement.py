# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Planar arrangement: rebuild minimal faces from an edge graph.

Covers the geometry a floor plan is made of — rooms, diagonals, crossings,
T-junctions/spurs, doubled lines, and a hole nested in its ring — plus the
``RebuildPlanarFacesCommand`` end-to-end (with undo) and the 3D no-op guard.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.arrangement import planar_arrangement
from core.history import AddEdgeCommand, History, RebuildPlanarFacesCommand
from core.scene import Scene

O = V(0, 0, 0)
N = V(0, 0, 1)


def _loop(pts):
    return [(V(*p, 0), V(*q, 0)) for p, q in zip(pts, pts[1:] + pts[:1])]


def _area(loop):
    s = 0.0
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        s += a.x() * b.y() - b.x() * a.y()
    return abs(s) * 0.5


# ---- the algorithm ---------------------------------------------------------

def test_square_is_one_face():
    faces = planar_arrangement(_loop([(0, 0), (4, 0), (4, 4), (0, 4)]), O, N)
    assert len(faces) == 1
    outer, holes = faces[0]
    assert len(outer) == 4
    assert not holes
    assert abs(_area(outer) - 16.0) < 1e-6


def test_diagonal_splits_square_into_two_triangles():
    segs = _loop([(0, 0), (4, 0), (4, 4), (0, 4)]) + [(V(0, 0, 0), V(4, 4, 0))]
    faces = planar_arrangement(segs, O, N)
    assert len(faces) == 2
    for outer, holes in faces:
        assert len(outer) == 3
        assert not holes
        assert abs(_area(outer) - 8.0) < 1e-6


def test_crossing_rectangles_make_three_faces():
    segs = _loop([(0, 0), (4, 0), (4, 3), (0, 3)]) + _loop(
        [(2, 1), (6, 1), (6, 5), (2, 5)])
    faces = planar_arrangement(segs, O, N)
    assert len(faces) == 3
    # the central overlap is a 2×2 quad; the two arms are 6-gons.
    areas = sorted(round(_area(o), 3) for o, _ in faces)
    assert areas[0] == 4.0  # overlap 2×2


def test_inner_square_nests_as_a_hole_of_the_ring():
    segs = _loop([(0, 0), (6, 0), (6, 6), (0, 6)]) + _loop(
        [(2, 2), (4, 2), (4, 4), (2, 4)])
    faces = planar_arrangement(segs, O, N)
    assert len(faces) == 2
    ring = max(faces, key=lambda f: _area(f[0]))
    inner = min(faces, key=lambda f: _area(f[0]))
    assert len(ring[1]) == 1                      # ring carries the hole
    assert abs(_area(ring[1][0]) - 4.0) < 1e-6    # hole is the 2×2
    assert not inner[1]                           # inner square is solid
    assert abs(_area(inner[0]) - 4.0) < 1e-6


def test_spur_is_pruned_from_the_face():
    # A line sticking into the square from its bottom edge borders no face.
    segs = _loop([(0, 0), (4, 0), (4, 4), (0, 4)]) + [(V(2, 0, 0), V(2, 2, 0))]
    faces = planar_arrangement(segs, O, N)
    assert len(faces) == 1
    outer, _ = faces[0]
    assert abs(_area(outer) - 16.0) < 1e-6        # full square area, spur ignored


def test_doubled_edge_collapses():
    segs = _loop([(0, 0), (4, 0), (4, 4), (0, 4)]) + [(V(0, 0, 0), V(4, 0, 0))]
    faces = planar_arrangement(segs, O, N)
    assert len(faces) == 1
    assert abs(_area(faces[0][0]) - 16.0) < 1e-6


def test_open_loop_makes_no_face():
    # Three sides of a square (not closed) bound nothing.
    segs = [(V(0, 0, 0), V(4, 0, 0)), (V(4, 0, 0), V(4, 4, 0)),
            (V(4, 4, 0), V(0, 4, 0))]
    assert planar_arrangement(segs, O, N) == []


# ---- the command -----------------------------------------------------------

def _flat_scene(segments):
    scene = Scene()
    hist = History(scene)
    for a, b in segments:
        hist.execute(AddEdgeCommand(a, b))
    return scene, hist


def test_command_rebuilds_crossing_rectangles():
    segs = _loop([(0, 0), (4, 0), (4, 3), (0, 3)]) + _loop(
        [(2, 1), (6, 1), (6, 5), (2, 5)])
    scene, hist = _flat_scene(segs)
    assert len(scene.faces) == 0
    cmd = RebuildPlanarFacesCommand()
    hist.execute(cmd)
    assert cmd.flat and cmd.rebuilt == 3
    assert len(scene.faces) == 3
    # crossings were split, so the edge count grew.
    assert len(scene.mesh.edges) > len(segs)


def test_command_undo_restores_raw_edges():
    segs = _loop([(0, 0), (4, 0), (4, 4), (0, 4)])
    scene, hist = _flat_scene(segs)
    before = len(scene.mesh.edges)
    hist.execute(RebuildPlanarFacesCommand())
    assert len(scene.faces) == 1
    hist.undo()
    assert len(scene.faces) == 0
    assert len(scene.mesh.edges) == before


def test_command_skips_non_flat_mesh():
    # A vertical edge makes the mesh non-flat → the rebuild is a no-op.
    segs = _loop([(0, 0), (4, 0), (4, 4), (0, 4)]) + [(V(0, 0, 0), V(0, 0, 3))]
    scene, hist = _flat_scene(segs)
    cmd = RebuildPlanarFacesCommand()
    hist.execute(cmd)
    assert cmd.flat is False
    assert len(scene.faces) == 0  # untouched
