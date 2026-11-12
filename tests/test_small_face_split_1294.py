# SPDX-License-Identifier: GPL-3.0-or-later
"""A line across a 1 mm face splits it, it does not delete it (#1294).

``is_planar`` read "every vertex in one line" off an absolute floor on the
cross product, 1e-6. The cross product is an area: half of a 1 mm square,
0.5 mm x 1 mm, has 5e-7, so drawing a line from the middle of one side to
the middle of the other deleted the mother face and refused both halves.
A loop below that floor is now read against its own size, as the distance
of its farthest corner from the line; what passed before passes as before
and points in one line are still refused."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D

from core.edits import build_add_edge, build_add_edges
from core.history import AddFaceCommand, History
from core.scene import Scene
from core.topology import is_planar
from tools.pushpull import PushPullTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(x, y, z)


def _square(side, with_lines=False):
    scene = Scene()
    hist = History(scene)
    c = [V(0, 0), V(side, 0), V(side, side), V(0, side)]
    if with_lines:
        for i in range(4):
            hist.execute(build_add_edge(scene, c[i], c[(i + 1) % 4]))
    else:
        segs = [(c[i], c[(i + 1) % 4]) for i in range(4)]
        hist.execute(build_add_edges(scene, segs, detect_faces=False,
                                     extra=[AddFaceCommand(list(c))]))
    return scene, hist


def _sizes(scene):
    return sorted(len(f.vertices) for f in scene.faces)


@pytest.mark.parametrize("side", [1.0, 0.001, 0.0005])
@pytest.mark.parametrize("with_lines", [False, True])
def test_a_line_between_two_midpoints_splits_the_square(side, with_lines):
    scene, hist = _square(side, with_lines)
    assert _sizes(scene) == [4]
    hist.execute(build_add_edge(scene, V(side / 2, 0), V(side / 2, side)))
    assert _sizes(scene) == [4, 4]
    assert len(scene.edges) == 7
    hist.undo()
    assert _sizes(scene) == [4]
    assert len(scene.edges) == 4


@pytest.mark.parametrize("side", [0.001, 0.0005])
def test_a_diagonal_splits_a_millimetre_square_into_triangles(side):
    scene, hist = _square(side)
    hist.execute(build_add_edge(scene, V(0, 0), V(side, side)))
    assert _sizes(scene) == [3, 3]


def test_a_corner_to_a_midpoint_splits_a_millimetre_square():
    scene, hist = _square(0.001)
    hist.execute(build_add_edge(scene, V(0, 0), V(0.0005, 0.001)))
    assert _sizes(scene) == [3, 4]


class _StubViewport:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def set_hover(self, entity):
        pass

    def set_suppressed_faces(self, faces):
        pass


def test_half_of_a_millimetre_square_is_pushed_up():
    scene, hist = _square(0.001)
    hist.execute(build_add_edge(scene, V(0.0005, 0), V(0.0005, 0.001)))
    half = min(scene.faces, key=lambda f: f.centroid().x())
    tool = PushPullTool()
    tool.base_face = half
    tool.extrusion = 0.001
    tool.dragging = True
    tool._commit(_StubViewport(scene))
    tops = [f for f in scene.faces
            if all(abs(v.z() - 0.001) < 1e-7 for v in f.vertices)]
    assert len(tops) == 1
    assert max(v.x() for v in tops[0].vertices) == pytest.approx(0.0005,
                                                                 abs=1e-7)


def test_points_in_one_line_are_still_not_a_face():
    for s in (1.0, 0.001, 0.0001):
        assert not is_planar([V(0, 0), V(s, 0), V(2 * s, 0)])
        assert not is_planar([V(0, 0), V(s, 0), V(2 * s, 0), V(3 * s, 0)])
    # a corner well under the weld tolerance off a 1 mm line
    assert not is_planar([V(0, 0), V(0.0005, 1e-9), V(0.001, 0)])


def test_what_was_planar_is_planar_as_before():
    assert is_planar([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    assert is_planar([V(0, 0), V(1, 0), V(0, 1)])
    # a 2 cm sliver 1e-7 m off its line stays a line, as it was
    assert not is_planar([V(0, 0), V(0.01, 1e-7), V(0.02, 0)])
