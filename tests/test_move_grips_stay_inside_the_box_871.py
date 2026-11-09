# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #871: Move's rotation grips vanished on the way out to them.

The grips sit on the group's BOX, but they only stayed while the cursor
was over the group's MESH (or already over a grip). On a thin, long
object — a pipe, an elbow — a grip can sit far off the mesh, and the
crossing from the mesh to the grip left both behind: the grips went away
before any could be taken. They now stay while the cursor is inside the
box as projected on screen (GRIP_PX of margin around it), as in
SketchUp — retention only: appearing still takes the pick."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.group import Group
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext
from tools.move import MoveTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Cam:
    def eye(self):
        return V(2, 2, 50)                 # straight down at the box


class _Vp:
    """A top-down viewport (1 m = 100 px, y flipped) whose PICKED mesh is
    a thin diagonal bar, while the group's box is the full 4 × 4 square
    the bar runs corner to corner in — the pipe-in-its-box shape of the
    report: most of the box's face is empty air the pick cannot find."""

    def __init__(self, scene, group):
        self.scene = scene
        self.history = History(scene)
        self.camera = _Cam()
        self.group = group
        self.flashed = []

    def update(self):
        pass

    def flash_status(self, msg, *a, **k):
        self.flashed.append(msg)

    def pick_group(self, x, y):
        wx, wy = x / 100.0, -y / 100.0
        on_bar = abs(wx - wy) <= 0.15 and 0 <= wx <= 4 and 0 <= wy <= 4
        return self.group if on_bar else None

    def _group_obb(self, g):
        frame = (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1))
        return (frame, (0.0, 0.0, 0.0), (4.0, 4.0, 1.0))

    def _world_to_pixel(self, p):
        return (p.x() * 100.0, -p.y() * 100.0)

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None


def _ctx(vp, wx, wy, wz=1.0):
    return ToolContext(viewport=vp, world=V(wx, wy, wz),
                       screen=QPointF(wx * 100.0, -wy * 100.0),
                       modifiers=Qt.NoModifier, snap=None)


def _setup():
    scene = Scene()
    m = Mesh()          # filler geometry; the stub owns pick and box
    m.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)])
    g = Group(m, name="Tubo")
    scene.groups.append(g)
    vp = _Vp(scene, g)
    tool = MoveTool()
    tool.on_activate(vp)
    return scene, g, vp, tool


def test_the_journey_out_to_a_grip_keeps_the_grips():
    scene, g, vp, tool = _setup()
    tool.on_hover(_ctx(vp, 2.0, 2.0))          # on the bar: grips appear
    assert tool._grip_group is g
    assert len(tool._grips) == 4               # the top face's four
    # Half-way to the +X grip at (3.2, 2.0): off the bar (the pick finds
    # nothing), 60 px short of the grip — the stretch that used to clear.
    tool.on_hover(_ctx(vp, 2.6, 2.0))
    assert tool._grip_group is g
    assert len(tool._grips) == 4
    assert tool._hot_grip is None
    tool.on_hover(_ctx(vp, 3.2, 2.0))          # arrived: the grip lights
    assert tool._hot_grip is not None
    # Just past the box's edge is still the journey (GRIP_PX of margin)…
    tool.on_hover(_ctx(vp, 4.05, 2.0))
    assert len(tool._grips) == 4
    # …but well past it the grips go, as they always did.
    tool.on_hover(_ctx(vp, 4.3, 2.0))
    assert tool._grips == []
    assert tool._grip_group is None


def test_the_box_alone_never_acquires_grips():
    scene, g, vp, tool = _setup()
    # Straight into the box's empty corner, without touching the mesh
    # first: retention is not acquisition.
    tool.on_hover(_ctx(vp, 2.6, 2.0))
    assert tool._grips == []
    assert tool._grip_group is None


def test_leaving_the_box_clears_and_the_mesh_reacquires():
    scene, g, vp, tool = _setup()
    tool.on_hover(_ctx(vp, 2.0, 2.0))
    assert len(tool._grips) == 4
    tool.on_hover(_ctx(vp, 8.0, 8.0))          # far off: gone
    assert tool._grips == []
    tool.on_hover(_ctx(vp, 1.0, 1.0))          # back on the bar: back
    assert tool._grip_group is g
    assert len(tool._grips) == 4
