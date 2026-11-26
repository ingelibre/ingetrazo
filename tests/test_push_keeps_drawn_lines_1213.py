# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pushing the end face of a box keeps the lines drawn on its other faces
(#1213). The slide stretches the walls and hands every face it touched to
the plane rebuild, whose union took those lines for the push's own seams
and dissolved them: a top split in strips came out as one face."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edge
from core.history import History
from core.orient import is_closed
from core.scene import Scene
from tools.base import ToolContext
from tools.pushpull import PushPullTool

X, Y, Z = 2.0, 1.0, 0.6


class _VP:
    def __init__(self, scene, pick=None):
        self.scene, self.history, self._pick = scene, History(scene), pick

    last_status = last_hover = suppressed = None

    def update(self):
        pass

    def flash_status(self, text, msec=0):
        self.last_status = text

    def set_hover(self, entity):
        pass

    def set_suppressed_faces(self, faces):
        pass

    def pick_face(self, x, y):
        return self._pick

    def pick_face_any(self, x, y):
        return self._pick, None


def _ctx(vp, mods=Qt.NoModifier):
    return ToolContext(viewport=vp, world=V(), screen=QPointF(0, 0),
                       modifiers=mods, snap=None)


def _push(scene, face, d, mods=Qt.NoModifier):
    vp = _VP(scene, face)
    tool = PushPullTool()
    tool.on_activate(vp)
    tool.on_hover(_ctx(vp))
    tool.on_click(_ctx(vp, mods))
    tool.extrusion = d
    tool.on_click(_ctx(vp, mods))
    return vp


def _box(scene):
    p = [V(0, 0, 0), V(X, 0, 0), V(X, Y, 0), V(0, Y, 0),
         V(0, 0, Z), V(X, 0, Z), V(X, Y, Z), V(0, Y, Z)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        scene.mesh.add_face([p[i] for i in idx])
    scene.version += 1


LINES = {
    "along the top": (V(0, 0.3, Z), V(X, 0.3, Z)),
    "across the top": (V(0.4, 0, Z), V(0.4, Y, Z)),
    "diagonal on the side": (V(0.3, 0, Z), V(0.7, 0, 0)),
}


def _covered(scene, a, b):
    """Some edge runs along a–b through its middle."""
    m = (a + b) * 0.5
    for e in scene.mesh.edges:
        p, q = e.v0.position, e.v1.position
        d = q - p
        ll = V.dotProduct(d, d)
        if ll < 1e-18:
            continue
        t = V.dotProduct(m - p, d) / ll
        if (0 < t < 1 and (p + d * t - m).length() < 1e-6
                and V.crossProduct(d, b - a).length() < 1e-6):
            return True
    return False


@pytest.mark.parametrize("d", [0.5, -0.5])
@pytest.mark.parametrize("names", [[n] for n in LINES] + [list(LINES)])
def test_the_drawn_lines_stay(names, d):
    scene = Scene()
    _box(scene)
    for n in names:
        History(scene).execute(build_add_edge(scene, *LINES[n]))
    faces = len(scene.mesh.faces)
    end = next(f for f in scene.mesh.faces
               if all(abs(v.x() - X) < 1e-9 for v in f.vertices))
    vp = _push(scene, end, d)
    assert vp.last_status is None or "refused" not in vp.last_status
    assert len(scene.mesh.faces) == faces
    assert is_closed(scene.mesh)
    for n in names:
        a, b = LINES[n]
        if n == "along the top":
            b = V(X + d, b.y(), b.z())      # it runs to the face that moved
        assert _covered(scene, a, b), n
    # One undo brings the box back as it was drawn.
    assert vp.history.undo() is True
    assert len(scene.mesh.faces) == faces
    assert all(_covered(scene, *LINES[n]) for n in names)
