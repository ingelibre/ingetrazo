# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing a line across a face with a hole must leave the hole open (#1407).

The cycle planner faced both sides of a chord across a holed plate, and
executing the first side carved the mother into exactly the second side's
region — so the second AddFace stacked a hole-less twin on the piece that
held the hole, and the plane rebuild read the twin as a redraw and capped
the opening. Chords crossing or grazing the hole fared no better: their
cycles re-faced the opening itself, in whole or in halves.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edge
from core.history import History
from core.scene import Scene
from core.topology import _point_in_face_solid

HOLE = [[V(4, 4, 0), V(4, 6, 0), V(6, 6, 0), V(6, 4, 0)]]
CENTRE = V(5, 5, 0)


def _plate():
    """A 10x10 plate with a 2x2 square hole in the middle."""
    sc = Scene()
    sc.mesh.add_face([V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)],
                     [list(h) for h in HOLE])
    return sc, History(sc)


def _hole_open(sc) -> bool:
    return not any(_point_in_face_solid(f, CENTRE) for f in sc.mesh.faces)


def _total_holes(sc) -> int:
    return sum(len(f.holes) for f in sc.mesh.faces)


def test_line_beside_the_hole_splits_the_plate_and_keeps_the_hole():
    sc, history = _plate()
    history.execute(build_add_edge(sc, V(0, 2, 0), V(10, 2, 0)))
    assert len(sc.mesh.faces) == 2
    assert _total_holes(sc) == 1
    assert _hole_open(sc)


def test_line_through_the_hole_keeps_it_open():
    sc, history = _plate()
    history.execute(build_add_edge(sc, V(0, 5, 0), V(10, 5, 0)))
    assert len(sc.mesh.faces) == 2
    assert _hole_open(sc)


def test_diagonal_through_the_hole_corners_keeps_it_open():
    sc, history = _plate()
    history.execute(build_add_edge(sc, V(0, 0, 0), V(10, 10, 0)))
    assert len(sc.mesh.faces) == 2
    assert _hole_open(sc)


def test_line_along_the_hole_rim_keeps_it_open():
    sc, history = _plate()
    history.execute(build_add_edge(sc, V(0, 4, 0), V(10, 4, 0)))
    assert len(sc.mesh.faces) == 2
    assert _hole_open(sc)


def test_undo_restores_the_holed_plate():
    sc, history = _plate()
    history.execute(build_add_edge(sc, V(0, 2, 0), V(10, 2, 0)))
    history.undo()
    assert len(sc.mesh.faces) == 1
    assert _total_holes(sc) == 1
    history.redo()
    assert len(sc.mesh.faces) == 2
    assert _total_holes(sc) == 1
    assert _hole_open(sc)
