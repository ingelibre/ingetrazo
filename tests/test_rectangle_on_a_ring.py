# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A rectangle drawn over a ring-shaped top, on walls, fills the hole (#538).

Drawn exactly over the ring's outline, it stacked a full face on top of the
ring: on a flat drawing the plane is rebuilt after the rectangle, but in a
3D model only the Line rebuilt the plane it drew on. The Rectangle now does
too, with the same rebuild (regions keep a face only where one already
covered them)."""
from __future__ import annotations

from collections import Counter

from PySide6.QtGui import QVector3D as V

from core.history import History
from core.scene import Scene
from core.topology import offset_loop
from tests import test_pushpull_ux as T
from tools.rectangle import RectangleTool


class _Vp:
    def __init__(self, scene, hist):
        self.scene = scene
        self.history = hist

    def update(self):
        pass


def _rect(scene, hist, x0, y0, x1, y1, z):
    corners = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    RectangleTool()._commit_rect(_Vp(scene, hist), corners)


def _on(scene, z):
    return [f for f in scene.faces
            if all(abs(v.z() - z) < 1e-9 for v in f.vertices)]


def _shape(scene, z):
    def ext(loop):
        xs = [p.x() for p in loop]
        return round(max(xs) - min(xs), 6)
    return sorted((ext(f.vertices), sorted(ext(h) for h in f.holes))
                  for f in _on(scene, z))


def _ring_on_walls():
    """#538's steps: a 2×2 square, offset 0.5 in, the ring pushed 1 up."""
    scene = Scene()
    hist = History(scene)
    m = scene.mesh
    outer = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]
    inner = offset_loop([V(p) for p in outer], V(0, 0, 1), 0.5)
    m.add_face([V(p) for p in inner])
    ring = m.add_face(list(outer), [list(inner)])
    T._push(scene, ring, 1.0)
    return scene, hist


def test_a_rectangle_over_the_ring_fills_its_hole():
    scene, hist = _ring_on_walls()
    assert _shape(scene, 1.0) == [(2.0, [1.0])]
    _rect(scene, hist, 0, 0, 2, 2, 1.0)
    # The ring stays and the hole gets its 1×1 face: no full 2×2 on top.
    assert _shape(scene, 1.0) == [(1.0, []), (2.0, [1.0])]
    assert hist.undo() is True
    assert _shape(scene, 1.0) == [(2.0, [1.0])]


def test_a_rectangle_inside_the_hole_only_fills_that_part():
    scene, hist = _ring_on_walls()
    _rect(scene, hist, 0.5, 0.5, 1.5, 1.5, 1.0)      # exactly the hole
    assert _shape(scene, 1.0) == [(1.0, []), (2.0, [1.0])]


def test_a_rectangle_on_a_box_top_still_splits_it():
    """What already worked keeps working: a rectangle inside a box's top
    cuts it into the rectangle and a holed rest, nothing stacked."""
    scene = Scene()
    hist = History(scene)
    T._cube(scene, hist, size=4.0, height=3.0)
    _rect(scene, hist, 1, 1, 3, 3, 3.0)
    assert _shape(scene, 3.0) == [(2.0, []), (4.0, [2.0])]
    assert Counter(len(e.faces) for e in scene.mesh.edges) == {
        2: len(scene.mesh.edges)}


def test_a_rectangle_across_a_box_top_splits_it_in_two():
    scene = Scene()
    hist = History(scene)
    T._cube(scene, hist, size=4.0, height=3.0)
    _rect(scene, hist, 0, 0, 4, 2, 3.0)               # half the top
    assert sorted(round(f.area(), 6) for f in _on(scene, 3.0)) == [8.0, 8.0]
    assert Counter(len(e.faces) for e in scene.mesh.edges) == {
        2: len(scene.mesh.edges)}


def test_a_loose_rectangle_off_the_model_is_just_a_face():
    scene = Scene()
    hist = History(scene)
    T._cube(scene, hist, size=4.0, height=3.0)
    _rect(scene, hist, 10, 10, 12, 13, 0.0)
    loose = [f for f in scene.faces if min(v.x() for v in f.vertices) >= 10]
    assert len(loose) == 1 and abs(loose[0].area() - 6.0) < 1e-9
