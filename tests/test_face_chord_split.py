"""Chord split + multi-cycle detection — Phase 1, sub-step 4.

The reported case: draw a rectangle (a face), then a diagonal between opposite
corners. It must become two independent triangles — the mother face gone, both
halves present — so push/pull grabs a triangle, not the whole rectangle.

Covers:
- ``split_face_by_chord`` (corner-to-corner, corner-to-edge-midpoint, the
  non-chord / concave / holed rejections, no inverted halves);
- ``find_cycles_through`` (a diagonal bounds a triangle on each side);
- end to end via ``build_add_edge`` + ``History`` (mother removed, two faces,
  undo/redo).

Headless: ``QVector3D`` value types only.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edge, build_add_edges
from core.geometry import Face
from core.history import AddEdgeCommand, AddFaceCommand, History
from core.scene import Scene
from core.topology import (
    find_chord_split,
    find_cycles_through,
    split_face_by_chord,
)


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(x, y, z)


A, B, C, D = V(0, 0), V(2, 0), V(2, 2), V(0, 2)
SQUARE = [A, B, C, D]


def _vcount(scene) -> list[int]:
    return sorted(len(f.vertices) for f in scene.faces)


# ---- split_face_by_chord ----------------------------------------------------

def test_chord_diagonal_splits_into_two_triangles():
    res = split_face_by_chord(Face(list(SQUARE)), A, C)
    assert res is not None
    loop_a, loop_b = res
    assert len(loop_a) == 3 and len(loop_b) == 3


def test_chord_halves_not_inverted():
    mother = Face(list(SQUARE))
    n0 = mother.normal()
    loop_a, loop_b = split_face_by_chord(mother, A, C)
    for loop in (loop_a, loop_b):
        assert QVector3D.dotProduct(Face(loop).normal(), n0) > 0.0


def test_adjacent_vertices_is_not_a_chord():
    # A and B are an existing boundary edge, not a chord.
    assert split_face_by_chord(Face(list(SQUARE)), A, B) is None


def test_chord_corner_to_edge_midpoint():
    # A → midpoint of the far edge CD splits into a triangle and a quad,
    # inserting the midpoint as a new boundary vertex.
    mid = V(1, 2)
    res = split_face_by_chord(Face(list(SQUARE)), A, mid)
    assert res is not None
    sizes = sorted(len(loop) for loop in res)
    assert sizes == [3, 4]


def test_chord_on_holed_face_is_skipped():
    f = Face(list(SQUARE), [[V(0.5, 0.5), V(1.5, 0.5), V(1.5, 1.5), V(0.5, 1.5)]])
    assert split_face_by_chord(f, A, C) is None


def test_find_chord_split_picks_the_face():
    faces = [Face([V(10, 10), V(11, 10), V(11, 11)]), Face(list(SQUARE))]
    found = find_chord_split(faces, A, C)
    assert found is not None and found[0] is faces[1]


# ---- find_cycles_through ----------------------------------------------------

def _square_edges():
    return [Edge_(A, B), Edge_(B, C), Edge_(C, D), Edge_(D, A)]


def Edge_(a, b):
    from core.geometry import Edge
    return Edge(a, b)


def test_diagonal_bounds_two_cycles():
    cycles = find_cycles_through(_square_edges(), A, C)
    assert len(cycles) == 2


def test_closing_edge_is_single_cycle():
    # The square's own boundary closes only one face (the other side is open).
    edges = [Edge_(A, B), Edge_(B, C), Edge_(C, D)]
    cycles = find_cycles_through(edges, D, A)
    assert len(cycles) == 1


# ---- end to end -------------------------------------------------------------

def _rectangle(scene, hist, corners):
    segments = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    hist.execute(
        build_add_edges(scene, segments, detect_faces=False,
                        extra=[AddFaceCommand(list(corners))])
    )


def test_rectangle_then_diagonal_makes_two_triangles():
    scene = Scene()
    hist = History(scene)
    _rectangle(scene, hist, SQUARE)
    assert _vcount(scene) == [4]  # one rectangle face

    hist.execute(build_add_edge(scene, A, C))  # draw the diagonal
    # Mother gone, two triangles in its place.
    assert _vcount(scene) == [3, 3]
    assert len(scene.edges) == 5  # 4 sides + diagonal


def test_diagonal_split_undo_restores_rectangle():
    scene = Scene()
    hist = History(scene)
    _rectangle(scene, hist, SQUARE)
    hist.execute(build_add_edge(scene, A, C))
    assert hist.undo() is True
    assert _vcount(scene) == [4]      # rectangle face back
    assert len(scene.edges) == 4      # diagonal gone


def test_diagonal_split_redo():
    scene = Scene()
    hist = History(scene)
    _rectangle(scene, hist, SQUARE)
    hist.execute(build_add_edge(scene, A, C))
    hist.undo()
    assert hist.redo() is True
    assert _vcount(scene) == [3, 3]


def test_corner_to_edge_midpoint_end_to_end():
    scene = Scene()
    hist = History(scene)
    _rectangle(scene, hist, SQUARE)
    hist.execute(build_add_edge(scene, A, V(1, 2)))  # A → midpoint of edge CD
    assert _vcount(scene) == [3, 4]   # triangle + quad
    assert len(scene.edges) == 6      # CD split + new chord
