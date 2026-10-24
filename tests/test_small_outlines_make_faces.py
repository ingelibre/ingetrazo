# SPDX-License-Identifier: GPL-3.0-or-later
"""Outlines under 1 cm² close into faces (tutorial hunt 2, B8).

The face tracer dropped every loop whose area was under ``_TOL`` — a length
tolerance (0.1 mm) read as an area, i.e. 1 cm². A circle under 5.7 mm radius
stayed loose edges, and a countersink or a bolt's cap could not be modelled
at its size. Loops thinner than the weld tolerance are still noise."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D as V

from core.arrangement import _area_floor, planar_arrangement
from core.edits import build_add_edges
from core.history import (AddFaceCommand, History, RebuildPlaneFacesCommand,
                          RebuildPlanarFacesCommand, TagCurveCommand)
from core.scene import Scene
from tools.circle import busy_plane, flat_drawing

UP = V(0, 0, 1)


def _circle(c, r, n=24):
    return [c + V(math.cos(2 * math.pi * k / n) * r,
                  math.sin(2 * math.pi * k / n) * r, 0) for k in range(n)]


def _draw_circle(sc, h, pts):
    # The Circle tool's commit, without a viewport.
    n = len(pts)
    segs = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    if flat_drawing(sc, pts):
        extra = [TagCurveCommand(list(pts), closed=True),
                 RebuildPlanarFacesCommand()]
    else:
        plane = busy_plane(sc, pts)
        assert plane is not None
        extra = [AddFaceCommand(list(pts)),
                 TagCurveCommand(list(pts), closed=True),
                 RebuildPlaneFacesCommand(*plane)]
    h.execute(build_add_edges(sc, segs, detect_faces=False, extra=extra))
    assert h.last_error is None


def test_a_3_mm_circle_on_the_ground_is_a_disc():
    sc = Scene()
    _draw_circle(sc, History(sc), _circle(V(0, 0, 0), 0.003))
    assert len(sc.mesh.faces) == 1


def test_a_3_mm_circle_on_a_box_top_cuts_a_hole_in_it():
    sc = Scene()
    p = [V(0, 0, 0), V(.2, 0, 0), V(.2, .2, 0), V(0, .2, 0),
         V(0, 0, .2), V(.2, 0, .2), V(.2, .2, .2), V(0, .2, .2)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        sc.mesh.add_face([p[i] for i in idx])
    _draw_circle(sc, History(sc), _circle(V(.1, .1, .2), 0.003))
    top = [f for f in sc.mesh.faces
           if all(abs(v.z() - .2) < 1e-6 for v in f.vertices)]
    assert len(top) == 2
    assert sum(1 for f in top if f.hole_loops) == 1


def test_a_small_square_with_a_smaller_hole_keeps_the_hole():
    sq = [V(0, 0, 0), V(.008, 0, 0), V(.008, .008, 0), V(0, .008, 0)]
    hole = [V(.003, .003, 0), V(.005, .003, 0), V(.005, .005, 0),
            V(.003, .005, 0)]
    segs = list(zip(sq, sq[1:] + sq[:1])) + list(zip(hole, hole[1:] + hole[:1]))
    faces = planar_arrangement(segs, V(0, 0, 0), UP)
    assert len(faces) == 2
    assert sum(len(h) for _o, h in faces) == 1


def test_a_loop_thinner_than_the_weld_tolerance_is_still_noise():
    # 1 m long, 0.05 mm wide: a rounding sliver, not a face.
    xy = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.00005), (0.0, 0.00005)]
    assert 1.0 * 0.00005 < _area_floor(xy)


def test_a_big_loop_needs_no_more_area_than_before():
    xy = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]
    assert _area_floor(xy) == 1e-4
