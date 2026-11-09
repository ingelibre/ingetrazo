# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #177 (Lefteris Schetakis, by email): «Al copiar una arista y
moverla de manera que intersecte una cara existente, la aplicación no
actualiza la topología de la cara.» The copy was added as a bare edge;
now plain copied edges go through the Line tool's planner, so a copy laid
across a face splits it — and a face copied with its edges is not doubled."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tests.test_fuzz_engine import _draw_rect
from tools.base import ToolContext
from tools.move import MoveTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None

    def pick_group(self, x, y):
        return None


def _ctx(vp, x, y):
    return ToolContext(viewport=vp, world=V(x, y), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _copy(vp, grab, drop):
    tool = MoveTool()
    tool.on_click(_ctx(vp, *grab))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_hover(_ctx(vp, *drop))
    tool.on_click(_ctx(vp, *drop))


def _scene_with_square_and_loose_edge():
    scene = Scene()
    vp = _Vp(scene)
    _draw_rect(scene, vp.history, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    edge = scene.mesh.add_edge(V(6, 0), V(6, 4))     # beside the square
    return scene, vp, edge


def test_a_copied_edge_across_a_face_splits_it():
    scene, vp, edge = _scene_with_square_and_loose_edge()
    assert len(scene.mesh.faces) == 1
    scene.selection = {edge}
    _copy(vp, (6, 0), (2, 0))                        # lay the copy at x = 2
    assert len(scene.mesh.faces) == 2                # the square is split
    areas = sorted(round(f.area(), 6) for f in scene.mesh.faces)
    assert areas == [8.0, 8.0]
    vp.history.undo()                                # one step back
    assert len(scene.mesh.faces) == 1


def test_a_copied_edge_crossing_past_the_face_splits_it_too():
    scene = Scene()
    vp = _Vp(scene)
    _draw_rect(scene, vp.history, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    edge = scene.mesh.add_edge(V(6, -1), V(6, 5))
    scene.selection = {edge}
    _copy(vp, (6, -1), (2, -1))
    assert len(scene.mesh.faces) == 2


def test_copying_a_face_with_its_edges_does_not_double_it():
    scene = Scene()
    vp = _Vp(scene)
    _draw_rect(scene, vp.history, [V(0, 0), V(1, 0), V(1, 1), V(0, 1)], [])
    scene.selection = set(scene.mesh.faces) | set(scene.mesh.edges)
    _copy(vp, (0, 0), (5, 0))
    assert len(scene.mesh.faces) == 2                # original + ONE copy
    assert len(scene.mesh.edges) == 8


def _box_and_its_top():
    """A 1 × 0.5 × 0.8 box; the selection is its top face with its edges —
    a piece picked whole, as a triple-click does."""
    from core.edits import build_add_edges
    from tests.test_coplanar_merge import _push
    scene = Scene()
    vp = _Vp(scene)
    c = [V(0, 0), V(1, 0), V(1, 0.5), V(0, 0.5)]
    vp.history.execute(build_add_edges(
        scene, [(c[i], c[(i + 1) % 4]) for i in range(4)]))
    _push(scene, vp.history, scene.mesh.faces[0], 0.8)
    top = next(f for f in scene.mesh.faces
               if all(abs(v.z() - 0.8) < 1e-6 for v in f.vertices))
    edges = [e for e in scene.mesh.edges if top in e.faces]
    return scene, vp, top, edges


def _front(scene):
    return [f for f in scene.mesh.faces
            if all(abs(v.y()) < 1e-6 for v in f.vertices)]


def _at_height(scene, z):
    return [f for f in scene.mesh.faces
            if all(abs(v.z() - z) < 1e-6 for v in f.vertices)]


def test_a_copied_face_s_edges_split_the_faces_they_land_on():
    # #379 (ArqAi review, 37:00): the edges of a piece copied 1 cm down
    # left the box's walls whole; a line drawn there splits them.
    scene, vp, top, edges = _box_and_its_top()
    tool = MoveTool()
    tool._groups, tool._sel_faces, tool._sel_edges = [], [top], edges
    vp.history.execute(tool._make_copy_builder(scene)([V(0, 0, -0.01)]))
    assert len(_front(scene)) == 2, "the copy did not split the wall"
    assert len(_at_height(scene, 0.79)) == 1          # ONE copied face
    vp.history.undo()
    assert len(_front(scene)) == 1 and not _at_height(scene, 0.79)
    vp.history.redo()
    assert len(_front(scene)) == 2 and len(_at_height(scene, 0.79)) == 1


def test_an_array_of_copied_faces_splits_at_every_copy():
    # «4/» in the video: several copies at once, each one splits.
    scene, vp, top, edges = _box_and_its_top()
    tool = MoveTool()
    tool._groups, tool._sel_faces, tool._sel_edges = [], [top], edges
    deltas = [V(0, 0, -0.2 * k) for k in (1, 2, 3)]
    vp.history.execute(tool._make_copy_builder(scene)(deltas))
    assert len(_front(scene)) == 4
    for z in (0.6, 0.4, 0.2):
        assert len(_at_height(scene, z)) == 1
