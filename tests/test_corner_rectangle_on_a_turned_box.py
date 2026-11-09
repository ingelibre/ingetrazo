# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A rectangle drawn in the corner of a wall carves that wall only.

A window drawn on a box wall against its corner edge (two corners on the
edge the wall shares with the side wall) is AddFaceCommand's "direction C":
the faces it lands against are carved around it. Every face was asked, and
``find_subdividing_chain`` judged a corner "inside" by its 2-D projection
alone. Seen from the side wall, at right angles, the window's far corners
are 3 m off its plane but project onto its edge; on a box turned in plan,
float noise put that projection a hair inside, so the side wall was carved
into a warped face reaching 2.9 m off its plane, and saved that way.

Headless: ``QVector3D`` value types only.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.edits import build_add_edge, build_add_edges
from core.geometry import Face
from core.history import AddFaceCommand, History
from core.scene import Scene
from core.topology import find_subdividing_chain


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


W, D, H = 6.0, 4.0, 3.0


def _turned_box(angle: float):
    """A closed 6 x 4 x 3 m box turned ``angle`` degrees in plan."""
    turn = QMatrix4x4()
    turn.rotate(float(angle), QVector3D(0, 0, 1))

    def at(x, y, z):
        return turn.map(V(x, y, z))

    scene = Scene()
    hist = History(scene)
    for quad in (
        [(0, 0, 0), (W, 0, 0), (W, 0, H), (0, 0, H)],     # front
        [(W, 0, 0), (W, D, 0), (W, D, H), (W, 0, H)],     # side, x = W
        [(W, D, 0), (0, D, 0), (0, D, H), (W, D, H)],     # back
        [(0, D, 0), (0, 0, 0), (0, 0, H), (0, D, H)],     # other side
        [(0, 0, H), (W, 0, H), (W, D, H), (0, D, H)],     # top
        [(0, 0, 0), (0, D, 0), (W, D, 0), (W, 0, 0)],     # bottom
    ):
        scene.mesh.add_face([at(*p) for p in quad])
    hist.clear()
    return scene, hist, at, turn


def _rectangle(scene, hist, corners):
    segs = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    hist.execute(build_add_edges(scene, segs, detect_faces=False,
                                 extra=[AddFaceCommand(list(corners))],
                                 plane_rebuild=True))      # the tool's way


def _off_plane(face) -> float:
    """How far the farthest corner of ``face`` is from its plane."""
    normal, origin = face.normal(), face.vertices[0]
    return max(abs(QVector3D.dotProduct(v - origin, normal))
               for loop in (face.vertices, *face.holes) for v in loop)


def _area_on_plane(scene, origin, normal) -> float:
    return sum(f.area() for f in scene.faces
               if all(abs(QVector3D.dotProduct(v - origin, normal)) < 1e-3
                      for v in f.vertices))


@pytest.mark.parametrize("angle", range(0, 360, 5))
def test_a_window_against_the_corner_of_a_turned_box_carves_only_its_wall(angle):
    scene, hist, at, turn = _turned_box(angle)
    # A line across the front wall, then a window resting on that line and
    # against the corner edge the front shares with the side wall.
    hist.execute(build_add_edge(scene, at(0, 0, 1), at(W, 0, 1)))
    _rectangle(scene, hist, [at(3, 0, 1), at(W, 0, 1), at(W, 0, 2), at(3, 0, 2)])

    assert max(_off_plane(f) for f in scene.faces) < 1e-3   # 2.91 m before

    side_n = turn.mapVector(V(1, 0, 0)).normalized()
    front_n = turn.mapVector(V(0, 1, 0)).normalized()
    assert abs(_area_on_plane(scene, at(W, 0, 0), side_n) - D * H) < 1e-4
    assert abs(_area_on_plane(scene, at(0, 0, 0), front_n) - W * H) < 1e-4
    # The front wall above the line was carved around the window.
    front = sorted(round(f.area(), 4) for f in scene.faces
                   if all(abs(QVector3D.dotProduct(v - at(0, 0, 0), front_n)) < 1e-3
                          for v in f.vertices))
    assert front == [3.0, 6.0, 9.0]

    hist.undo()
    assert abs(_area_on_plane(scene, at(W, 0, 0), side_n) - D * H) < 1e-4
    assert max(_off_plane(f) for f in scene.faces) < 1e-3


def test_a_loop_off_the_face_s_plane_does_not_subdivide_it():
    """Two corners on the side wall's edge, two 3 m away in front of it whose
    projection lands just inside it: not a corner rectangle of that wall."""
    side = Face([V(W, 0, 0), V(W, D, 0), V(W, D, H), V(W, 0, H)])
    window = [V(3, 0.001, 1), V(W, 0, 1), V(W, 0, 2), V(3, 0.001, 2)]
    assert find_subdividing_chain(side, window) is None


def test_a_loop_in_the_face_s_plane_still_subdivides_it():
    side = Face([V(W, 0, 0), V(W, D, 0), V(W, D, H), V(W, 0, H)])
    corner = [V(W, 0, 1), V(W, 1, 1), V(W, 1, 2), V(W, 0, 2)]
    chain = find_subdividing_chain(side, corner)
    assert chain is not None and len(chain) == 4
