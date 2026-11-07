# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Erasing the line under a window took the whole wall front with it (#356).

A wall base cut by the two lines of a window, its ends pushed up 2 m and the
window part 1 m: the window block's side faces stand against the taller
blocks, so the vertical line under the window bounds four faces — the two
fronts and two inner partitions. Erasing it must reunite the fronts, the
way it does when the line has only them."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.edits import build_add_edges  # noqa: E402
from core.history import (AddFaceCommand, EraseSelectionCommand,  # noqa: E402
                          History)
from core.orient import is_closed  # noqa: E402
from core.scene import Scene  # noqa: E402
from tests.test_pushpull_ux import V, _push  # noqa: E402

_W, _D, _X0, _X1 = 2.0, 0.3, 0.8, 1.2


def _ground_face(scene, xa, xb):
    for f in scene.mesh.faces:
        xs = [v.x() for v in f.vertices]
        if (all(abs(v.z()) < 1e-6 for v in f.vertices)
                and abs(min(xs) - xa) < 1e-6 and abs(max(xs) - xb) < 1e-6):
            return f
    raise AssertionError("no ground face")


def _wall_with_window():
    scene = Scene()
    hist = History(scene)
    g = [V(0, 0), V(_W, 0), V(_W, _D), V(0, _D)]
    hist.execute(build_add_edges(
        scene, [(g[i], g[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(g))]))
    hist.execute(build_add_edges(
        scene, [(V(_X0, 0), V(_X0, _D)), (V(_X1, 0), V(_X1, _D))],
        detect_faces=True))
    for xa, xb, h in ((0, _X0, 2.0), (_X1, _W, 2.0), (_X0, _X1, 1.0)):
        f = _ground_face(scene, xa, xb)
        _push(scene, f, h if f.normal().z() > 0 else -h)
    return scene, hist


def _edge(scene, a, b):
    m = scene.mesh
    return m.find_edge(m.vertex_at(a), m.vertex_at(b))


def _fronts(scene):
    return [f for f in scene.mesh.faces if f.normal().y() < -0.99]


def test_the_line_under_the_window_really_bounds_four_faces():
    scene, _ = _wall_with_window()
    assert len(_edge(scene, V(_X0, 0, 0), V(_X0, 0, 1)).faces) == 4


def test_erasing_it_reunites_the_front_and_keeps_the_jamb():
    scene, hist = _wall_with_window()
    area = sum(f.area() for f in _fronts(scene))
    before = len(scene.mesh.faces)
    hist.execute(EraseSelectionCommand(
        [_edge(scene, V(_X0, 0, 0), V(_X0, 0, 1))]))
    assert abs(sum(f.area() for f in _fronts(scene)) - area) < 1e-6
    assert len(_fronts(scene)) == 2                      # was 3
    assert _edge(scene, V(_X0, 0, 0), V(_X0, 0, 1)) is None
    side = [f for f in scene.mesh.faces
            if all(abs(v.x() - _X0) < 1e-6 for v in f.vertices)]
    # The jamb above the sill stays; the inner partitions below it go.
    assert len(side) == 1
    assert min(v.z() for v in side[0].vertices) > 1 - 1e-6
    assert is_closed(scene.mesh)
    hist.undo()
    assert len(scene.mesh.faces) == before
    assert len(_edge(scene, V(_X0, 0, 0), V(_X0, 0, 1)).faces) == 4


def _floor_with_fin():
    """A floor split by a line with a wall fin standing on that line."""
    scene = Scene()
    hist = History(scene)
    for x0, x1 in ((0, 1), (1, 2)):
        hist.execute(AddFaceCommand(
            [V(x0, 0), V(x1, 0), V(x1, 1), V(x0, 1)]))
    hist.execute(AddFaceCommand(
        [V(1, 0, 0), V(1, 1, 0), V(1, 1, 1), V(1, 0, 1)]))
    return scene, hist


def test_erasing_the_line_under_a_fin_reunites_the_floor():
    scene, hist = _floor_with_fin()
    edge = _edge(scene, V(1, 0, 0), V(1, 1, 0))
    assert len(edge.faces) == 3
    hist.execute(EraseSelectionCommand([edge]))
    floors = [f for f in scene.mesh.faces if abs(f.normal().z()) > 0.99]
    assert len(floors) == 1 and abs(floors[0].area() - 2.0) < 1e-6
    # The fin lost its foot: it no longer closes, so it goes, like SketchUp.
    assert len(scene.mesh.faces) == 1


def test_a_line_with_no_coplanar_pair_still_takes_its_faces():
    scene = Scene()
    hist = History(scene)
    hist.execute(AddFaceCommand([V(0, 0), V(1, 0), V(1, 1), V(0, 1)]))
    hist.execute(AddFaceCommand(
        [V(1, 0, 0), V(1, 1, 0), V(1, 1, 1), V(1, 0, 1)]))
    hist.execute(AddFaceCommand(
        [V(1, 0, 0), V(1, 1, 0), V(2, 1, -1), V(2, 0, -1)]))
    edge = _edge(scene, V(1, 0, 0), V(1, 1, 0))
    assert len(edge.faces) == 3
    hist.execute(EraseSelectionCommand([edge]))
    assert not scene.mesh.faces


def test_only_the_faces_across_the_line_are_rebuilt():
    """The plane across the line is rebuilt from ITS faces only: a face
    elsewhere on that plane, crossed by a loose line, stays one face (the
    whole-plane rebuild split such faces on small LED-bar models)."""
    scene, hist = _wall_with_window()
    sq = [V(_X0, 2, 0), V(_X0, 3, 0), V(_X0, 3, 1), V(_X0, 2, 1)]
    hist.execute(AddFaceCommand(sq))
    scene.mesh.add_edge(V(_X0, 2.5, -0.5), V(_X0, 2.5, 1.5))
    far = lambda: [f for f in scene.mesh.faces
                   if min(v.y() for v in f.vertices) > 1.5]
    assert len(far()) == 1
    hist.execute(EraseSelectionCommand(
        [_edge(scene, V(_X0, 0, 0), V(_X0, 0, 1))]))
    assert len(far()) == 1
    assert len(_fronts(scene)) == 2
