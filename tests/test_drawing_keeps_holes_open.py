# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing on the plane of a through hole leaves the hole open (tutorial
hunt 2, A15).

The plane rebuild gives a face to every region an existing face covers. A
rectangle or a circle drawn AROUND the mouth of a hole is such a face, so the
hole was filled; and on a centimetre part a circle drawn anywhere on the
plane capped the hole, because the probe for the hole region was the
centroid of its first fan triangle -- a sliver at the rim -- which read as
covered by the face around it. A face traced exactly along the hole still
caps it: that is how a hole is closed on purpose.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D as V

from core.history import History, _point_in_tri
from core.scene import Scene
from core.topology import _point_in_face_solid
from tools.circle import CircleTool
from tools.rectangle import RectangleTool


class _Viewport:
    def __init__(self, scene, history):
        self.scene, self.history = scene, history

    def update(self):
        pass


def _ring(cx, cy, r, z, n=24):
    return [V(cx + r * math.cos(2 * math.pi * k / n),
              cy + r * math.sin(2 * math.pi * k / n), z) for k in range(n)]


def _holed_box(side, height, r, n=24):
    """A ``side`` square block ``height`` tall with a round hole through."""
    sc = Scene()
    m = sc.mesh
    c = side / 2

    def square(z):
        return [V(0, 0, z), V(side, 0, z), V(side, side, z), V(0, side, z)]

    m.add_face(list(reversed(square(0))), [_ring(c, c, r, 0, n)])
    m.add_face(square(height), [list(reversed(_ring(c, c, r, height, n)))])
    b, t = square(0), square(height)
    for i in range(4):
        j = (i + 1) % 4
        m.add_face([b[i], b[j], t[j], t[i]])
    rb, rt = _ring(c, c, r, 0, n), _ring(c, c, r, height, n)
    for i in range(n):
        j = (i + 1) % n
        m.add_face([rb[j], rb[i], rt[i], rt[j]])
    return sc, History(sc), c


def _capped(sc, c, z):
    return any(_point_in_face_solid(f, V(c, c, z)) for f in sc.mesh.faces
               if all(abs(v.z() - z) < 1e-6 for v in f.vertices))


def _nonmanifold(sc):
    return sum(1 for e in sc.mesh.edges if len(e.faces) > 2)


def test_a_rectangle_around_the_hole_leaves_it_open():
    sc, h, c = _holed_box(1, 0.5, 0.1)
    RectangleTool()._commit_rect(_Viewport(sc, h), [
        V(.3, .3, .5), V(.7, .3, .5), V(.7, .7, .5), V(.3, .7, .5)])
    assert not _capped(sc, c, 0.5)
    assert _nonmanifold(sc) == 0


def test_a_circle_around_the_hole_leaves_it_open():
    sc, h, c = _holed_box(1, 0.5, 0.1)
    CircleTool()._commit(_Viewport(sc, h), _ring(.5, .5, .2, .5))
    assert not _capped(sc, c, 0.5)
    assert _nonmanifold(sc) == 0


def test_a_circle_elsewhere_on_a_centimetre_part_leaves_the_hole_open():
    sc, h, c = _holed_box(0.1, 0.06, 0.008)
    CircleTool()._commit(_Viewport(sc, h), _ring(.8, 0, .016, 0))
    assert not _capped(sc, c, 0.0)
    assert _nonmanifold(sc) == 0


def test_a_circle_traced_on_the_hole_still_caps_it():
    sc, h, c = _holed_box(1, 0.5, 0.1)
    CircleTool()._commit(_Viewport(sc, h), _ring(.5, .5, .1, .5))
    assert _capped(sc, c, 0.5)


def test_a_sliver_triangle_contains_nothing():
    # Three nearly collinear corners: the raw cross-product test let any
    # point through, 8 m away included.
    a, b, s = V(0, 0, 0), V(0.003, 0, 0), V(0.0015, 1e-9, 0)
    assert not _point_in_tri(V(4, 6, 0), a, b, s)
    assert _point_in_tri(V(0.3, 0.2, 0), V(0, 0, 0), V(1, 0, 0), V(0, 1, 0))


def test_redrawing_the_whole_top_fills_the_hole_as_in_538():
    sc, h, c = _holed_box(1, 0.5, 0.1)
    RectangleTool()._commit_rect(_Viewport(sc, h), [
        V(0, 0, .5), V(1, 0, .5), V(1, 1, .5), V(0, 1, .5)])
    assert _capped(sc, c, 0.5)
