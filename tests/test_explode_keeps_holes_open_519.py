# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A local edit after exploding must not fill a hole it never touched
(#519, @jb-dev-github: «closed contours that previously represented holes
can be filled with new faces»).

A plate with two square openings, grouped; outside the group, a rectangle
on the same plane straddling one opening; explode; draw a line across the
far end of the rectangle. The line split the rectangle and both halves were
punched into the plate as holes — the lower half wraps the opening's top
edge without a corner inside it, so it passed as «inside the plate». Two
crossing holes triangulate over the opening, and the plane rebuild read the
uncovered half of the opening as covered and filled it."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import (EraseSelectionCommand, ExplodeGroupCommand,
                          MakeGroupCommand)
from core.scene import Scene
from core.topology import loop_inside_face
from tests.test_line_restarts_after_cutting_a_face import _Vp, _click
from tools.line import LineTool


def _sq(x0, y0, x1, y1):
    p = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    return [(p[i], p[(i + 1) % 4]) for i in range(4)]


def _plate_with_rectangle():
    scene = Scene()
    vp = _Vp(scene)
    h = vp.history
    h.execute(build_add_edges(scene, _sq(0, 0, 6, 4)))
    for x in (1, 3):
        h.execute(build_add_edges(scene, _sq(x, 1, x + 1, 2)))
    h.execute(EraseSelectionCommand(
        [], [f for f in scene.mesh.faces if abs(f.area() - 1) < 1e-6]))
    h.execute(MakeGroupCommand(list(scene.mesh.faces),
                               list(scene.mesh.edges)))
    h.execute(build_add_edges(scene, _sq(0.5, 1.5, 2.5, 3.5)))
    h.execute(ExplodeGroupCommand(scene.groups[0]))
    return scene, vp


def _covered(scene, x, y):
    """Whether a face covers the point (x, y) on the plate's plane."""
    p = V(x, y, 0)
    return any(any(_inside(p, t) for t in f.triangulate())
               for f in scene.mesh.faces)


def _inside(p, tri):
    a, b, c = tri

    def s(u, v, w):
        return (v.x() - u.x()) * (w.y() - u.y()) - (v.y() - u.y()) * (w.x() - u.x())
    d = (s(a, b, p), s(b, c, p), s(c, a, p))
    return all(x > 0 for x in d) or all(x < 0 for x in d)


def test_a_line_far_from_the_opening_leaves_it_open():
    scene, vp = _plate_with_rectangle()
    assert not _covered(scene, 1.5, 1.2)
    tool = LineTool()
    _click(tool, vp, (0.5, 3, 0))
    _click(tool, vp, (2.5, 3, 0))
    assert not _covered(scene, 1.5, 1.2)        # the opening's free half
    assert not _covered(scene, 3.5, 1.5)        # the other opening
    assert _covered(scene, 1.5, 1.8)            # the rectangle still covers
    assert _covered(scene, 1.5, 3.2)


def test_a_loop_wrapping_a_hole_is_not_inside_the_face():
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(6, 0, 0), V(6, 4, 0), V(0, 4, 0)],
                        [[V(1, 1, 0), V(1, 2, 0), V(2, 2, 0), V(2, 1, 0)]])
    plate = scene.mesh.faces[0]
    wraps_top = [V(0.5, 1.5, 0), V(2.5, 1.5, 0), V(2.5, 3, 0), V(0.5, 3, 0)]
    around = [V(0.5, 0.5, 0), V(2.5, 0.5, 0), V(2.5, 2.5, 0), V(0.5, 2.5, 0)]
    strip = [V(1.2, 0.5, 0), V(1.8, 0.5, 0), V(1.8, 2.5, 0), V(1.2, 2.5, 0)]
    clear = [V(3, 1, 0), V(4, 1, 0), V(4, 3, 0), V(3, 3, 0)]
    assert not loop_inside_face(plate, wraps_top, outside_holes=True)
    assert not loop_inside_face(plate, around, outside_holes=True)
    assert not loop_inside_face(plate, strip, outside_holes=True)
    assert loop_inside_face(plate, clear, outside_holes=True)
