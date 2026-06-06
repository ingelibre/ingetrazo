"""Face subdivision by a loop drawn against the boundary (corner/edge rect).

A rectangle drawn in the corner of a face — sharing part of one or two of its
edges — neither sits strictly inside (a hole) nor is a single chord. It carves
a connected sub-region: the rectangle plus an L-shaped remainder. Both must
become real faces so push/pull recognises each.

Covers the geometry helpers, the AddFaceCommand "direction C" replacement, and
that strictly-inside still punches a hole (not a subdivision).

Headless: ``QVector3D`` value types only.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.geometry import Face
from core.history import AddFaceCommand, History
from core.scene import Scene
from core.topology import find_subdividing_chain, subtract_loop_from_face


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _tri_area(a, b, c) -> float:
    return QVector3D.crossProduct(b - a, c - a).length() * 0.5


def _area(face) -> float:
    return sum(_tri_area(*t) for t in face.triangulate())


MOTHER = [V(0, 0), V(10, 0), V(10, 10), V(0, 10)]          # 10×10, area 100
CORNER = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]              # shares two edges
PARTIAL = [V(2, 0), V(6, 0), V(6, 4), V(2, 4)]            # shares part of one edge
INSIDE = [V(2, 2), V(4, 2), V(4, 4), V(2, 4)]            # strictly inside

# Note: a rectangle covering a *whole* edge (all four corners on the boundary,
# far side a pure chord) is the collinear-overlap case, handled elsewhere — not
# a chain subdivision — so it is intentionally out of scope here.


def _rectangle(scene, hist, corners):
    segs = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    hist.execute(build_add_edges(scene, segs, detect_faces=False,
                                 extra=[AddFaceCommand(list(corners))]))


# ---- helpers ----------------------------------------------------------------

def test_subdividing_chain_corner():
    chain = find_subdividing_chain(Face(list(MOTHER)), CORNER)
    assert chain is not None
    # P, the interior vertex (4,4), Q.
    assert len(chain) == 3
    assert any(abs(v.x() - 4) < 1e-9 and abs(v.y() - 4) < 1e-9 for v in chain)


def test_subdividing_chain_strictly_inside_is_none():
    assert find_subdividing_chain(Face(list(MOTHER)), INSIDE) is None


def test_subtract_corner_gives_hexagon():
    remainder = subtract_loop_from_face(Face(list(MOTHER)), CORNER)
    assert remainder is not None
    assert len(remainder) == 6
    assert abs(_tri_area(remainder[0], remainder[1], remainder[2])) >= 0  # sane


def test_subtract_partial_edge_gives_octagon():
    # Sharing part of one edge (two interior corners) leaves an 8-vertex
    # remainder wrapping around the notch.
    remainder = subtract_loop_from_face(Face(list(MOTHER)), PARTIAL)
    assert remainder is not None
    assert len(remainder) == 8


def test_subtract_inside_is_none():
    assert subtract_loop_from_face(Face(list(MOTHER)), INSIDE) is None


# ---- end to end -------------------------------------------------------------

def test_corner_rect_subdivides_mother():
    scene = Scene()
    hist = History(scene)
    hist.execute(AddFaceCommand(MOTHER))
    _rectangle(scene, hist, CORNER)
    assert sorted(len(f.vertices) for f in scene.faces) == [4, 6]
    assert abs(sum(_area(f) for f in scene.faces) - 100.0) < 1e-6  # tile the mother
    # The drawn rectangle is now a real, separate face (so push/pull sees it).
    assert any(len(f.vertices) == 4 for f in scene.faces)


def test_corner_rect_undo_restores_mother():
    scene = Scene()
    hist = History(scene)
    hist.execute(AddFaceCommand(MOTHER))
    _rectangle(scene, hist, CORNER)
    assert hist.undo() is True
    assert sorted(len(f.vertices) for f in scene.faces) == [4]
    assert abs(_area(scene.faces[0]) - 100.0) < 1e-6


def test_partial_edge_rect_subdivides():
    scene = Scene()
    hist = History(scene)
    hist.execute(AddFaceCommand(MOTHER))
    _rectangle(scene, hist, PARTIAL)
    assert sorted(len(f.vertices) for f in scene.faces) == [4, 8]
    areas = sorted(_area(f) for f in scene.faces)
    assert abs(areas[0] - 16.0) < 1e-6 and abs(areas[1] - 84.0) < 1e-6


def test_strictly_inside_still_punches_hole():
    # Direction C must not steal the strictly-inside (hole) case.
    scene = Scene()
    hist = History(scene)
    hist.execute(AddFaceCommand(MOTHER))
    _rectangle(scene, hist, INSIDE)
    mother = scene.faces[0]
    assert len(mother.holes) == 1
    assert len(scene.faces) == 2  # mother (holed) + inner, not subdivided
