# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rotation grips on Move (issue #115), the usual ones: hovering a group with
Move shows red «+» grips on the faces of its box that look at you; taking
one turns the object in that face's plane about its centre — the protractor,
the 15° ticks and a typed angle all as in Rotate.

Asked for over WhatsApp by a user from Brazil (25-09): «uma coisa que senti
falta é ferramenta de giro rápido como esta».
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.group import Group, oriented_bounds
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext
from tools.move import MoveTool, rotation_grips


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _box(scene, sx=4.0, sy=1.0, sz=1.0):
    """A closed box as a group: 4 × 1 × 1, a bench lying along X."""
    m = Mesh()
    p = [V(0, 0, 0), V(sx, 0, 0), V(sx, sy, 0), V(0, sy, 0),
         V(0, 0, sz), V(sx, 0, sz), V(sx, sy, sz), V(0, sy, sz)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    g = Group(m, name="Banca")
    scene.groups.append(g)
    return g


def _obb(g):
    return oriented_bounds(g.mesh)


def test_grips_sit_on_the_faces_that_look_at_the_eye():
    scene = Scene()
    g = _box(scene)
    eye = V(10, -10, 10)                  # front (−Y), right (+X) and top
    grips = rotation_grips(_obb(g), eye)
    normals = {(round(n.x()), round(n.y()), round(n.z())) for _p, _c, n in grips}
    assert normals == {(1, 0, 0), (0, -1, 0), (0, 0, 1)}
    assert len(grips) == 12               # four per visible face
    for pos, centre, n in grips:
        # every grip lies on its face's plane, inside the face
        assert QVector3D.dotProduct(pos - centre, n) == pytest.approx(0, abs=1e-6)
        assert -1e-6 <= pos.x() <= 4 + 1e-6 and -1e-6 <= pos.y() <= 1 + 1e-6


def test_a_flat_group_gets_grips_only_on_its_face():
    scene = Scene()
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 1), V(0, 1)])
    g = Group(m)
    scene.groups.append(g)
    grips = rotation_grips(oriented_bounds(m), V(1, 0.5, 5))
    assert grips and all(abs(n.z()) == pytest.approx(1.0) for _p, _c, n in grips)


# ---- the tool --------------------------------------------------------------

class _Cam:
    def __init__(self, eye):
        self._eye = eye

    def eye(self):
        return self._eye


class _Vp:
    """Just enough viewport: a top-down orthographic projection (1 m = 100 px,
    y flipped) so pixels and metres are easy to reason about."""

    def __init__(self, scene, group):
        self.scene = scene
        self.history = History(scene)
        self.camera = _Cam(V(2, 0.5, 50))
        self.group = group
        self.flashed = []

    def update(self):
        pass

    def flash_status(self, msg, *a, **k):
        self.flashed.append(msg)

    def pick_group(self, x, y):
        wx, wy = x / 100.0, -y / 100.0
        return self.group if (0 <= wx <= 4 and 0 <= wy <= 1) else None

    def _group_obb(self, g):
        return _obb(g)

    def _world_to_pixel(self, p):
        return (p.x() * 100.0, -p.y() * 100.0)

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None


def _ctx(vp, wx, wy, wz=1.0, mods=Qt.NoModifier):
    return ToolContext(viewport=vp, world=V(wx, wy, wz),
                       screen=QPointF(wx * 100.0, -wy * 100.0),
                       modifiers=mods, snap=None)


def _corners(g):
    return sorted((round(v.position.x(), 4), round(v.position.y(), 4))
                  for v in g.mesh.vertices if abs(v.position.z()) < 1e-6)


def _setup():
    scene = Scene()
    g = _box(scene)
    vp = _Vp(scene, g)
    tool = MoveTool()
    tool.on_activate(vp)
    return scene, g, vp, tool


def test_hovering_a_group_shows_its_grips_and_one_lights_up():
    scene, g, vp, tool = _setup()
    tool.on_hover(_ctx(vp, 2.0, 0.5))
    assert len(tool._grips) == 4          # top view: only the top face
    assert tool._hot_grip is None
    gx = 2.0 + 0.3 * 4.0                  # the grip toward +X on the top
    tool.on_hover(_ctx(vp, gx + 0.03, 0.5))
    assert tool._hot_grip is not None
    tool.on_hover(_ctx(vp, 8.0, 8.0))     # far off: grips go
    assert tool._grips == []


def test_taking_a_grip_turns_the_group_about_its_centre_by_a_typed_angle():
    scene, g, vp, tool = _setup()
    gx = 2.0 + 0.3 * 4.0
    tool.on_hover(_ctx(vp, gx, 0.5))
    tool.on_click(_ctx(vp, gx, 0.5))      # take the grip
    assert tool._grip_rot is not None
    assert tool.start_point is None       # not a move
    assert vp.scene.groups == [g]
    tool.on_hover(_ctx(vp, 2.0, 1.4))     # swing it anticlockwise a bit
    assert tool.on_value(vp, 90.0)        # exact: a quarter turn
    assert tool._grip_rot is None
    # the 4 × 1 bench now lies along Y, still centred on (2, 0.5)
    xs = [c[0] for c in _corners(g)]
    ys = [c[1] for c in _corners(g)]
    assert (min(xs), max(xs)) == pytest.approx((1.5, 2.5))
    assert (min(ys), max(ys)) == pytest.approx((-1.5, 2.5))
    vp.history.undo()                     # one undo step
    assert _corners(g) == [(0.0, 0.0), (0.0, 1.0), (4.0, 0.0), (4.0, 1.0)]


def test_the_click_commits_the_live_angle_and_esc_puts_it_back():
    scene, g, vp, tool = _setup()
    gx = 2.0 + 0.3 * 4.0
    tool.on_hover(_ctx(vp, gx, 0.5))
    tool.on_click(_ctx(vp, gx, 0.5))
    tool.on_hover(_ctx(vp, 2.0, 3.0))     # straight up from the centre: +90°
    tool.on_cancel(vp)                    # Esc
    assert tool._grip_rot is None
    assert _corners(g) == [(0.0, 0.0), (0.0, 1.0), (4.0, 0.0), (4.0, 1.0)]
    # again, and this time click
    tool.on_hover(_ctx(vp, gx, 0.5))
    tool.on_click(_ctx(vp, gx, 0.5))
    tool.on_hover(_ctx(vp, 2.0, 3.0))
    tool.on_click(_ctx(vp, 2.0, 3.0))
    xs = [c[0] for c in _corners(g)]
    assert (min(xs), max(xs)) == pytest.approx((1.5, 2.5))


def test_a_tool_change_mid_turn_leaves_no_rotate_helper_behind():
    # #480: a tool change while a grip was held cancelled the turn but kept
    # the Rotate helper, so the next Move showed the Rotate widget and did
    # not respond.
    scene, g, vp, tool = _setup()
    gx = 2.0 + 0.3 * 4.0
    tool.on_hover(_ctx(vp, gx, 0.5))
    tool.on_click(_ctx(vp, gx, 0.5))      # take the grip
    tool.on_hover(_ctx(vp, 2.0, 3.0))
    tool.on_deactivate(vp)                # e.g. R for Rectangle
    assert _corners(g) == [(0.0, 0.0), (0.0, 1.0), (4.0, 0.0), (4.0, 1.0)]
    tool.on_activate(vp)                  # back to Move
    assert tool._grip_rot is None and tool._drag is None
    assert not tool.value_is_unitless()   # a distance again, not an angle
    assert tool._grips == [] and tool._hot_grip is None
    scene.selection.add(g)                # a plain move works
    tool.on_hover(_ctx(vp, 0.5, 0.5))
    tool.on_click(_ctx(vp, 0.5, 0.5))
    tool.on_click(_ctx(vp, 0.5, 2.5))
    assert min(c[1] for c in _corners(g)) == pytest.approx(2.0)


def test_a_typed_angle_after_a_tool_change_does_not_turn_the_last_group():
    scene, g, vp, tool = _setup()
    gx = 2.0 + 0.3 * 4.0
    tool.on_hover(_ctx(vp, gx, 0.5))
    tool.on_click(_ctx(vp, gx, 0.5))
    tool.on_hover(_ctx(vp, 2.0, 1.4))
    assert tool.on_value(vp, 90.0)        # committed; its retype stays hot
    turned = _corners(g)
    tool.on_deactivate(vp)
    tool.on_activate(vp)
    assert not tool.on_value(vp, 45.0)    # no Move started: nothing to do
    assert _corners(g) == turned


def test_with_something_else_selected_move_shows_no_grips():
    scene, g, vp, tool = _setup()
    other = scene.mesh.add_face([V(9, 9), V(10, 9), V(10, 10), V(9, 10)])
    scene.selection.add(other)
    tool.on_hover(_ctx(vp, 2.0, 0.5))
    assert tool._grips == []


def test_a_plain_move_still_moves():
    scene, g, vp, tool = _setup()
    tool.on_hover(_ctx(vp, 0.5, 0.5))     # on the group, away from grips
    assert tool._hot_grip is None
    scene.selection.add(g)
    tool.on_click(_ctx(vp, 0.5, 0.5))
    tool.on_click(_ctx(vp, 0.5, 2.5))
    ys = [c[1] for c in _corners(g)]
    assert min(ys) == pytest.approx(2.0)
