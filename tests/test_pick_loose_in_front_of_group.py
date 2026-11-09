# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A loose face in front of a group takes the click (#276, @mrmonkington;
#363; #378 from the ArqAi review).

The pick asked «is there a group under the cursor?» before anything else,
and a group anywhere along the ray answered yes — so a loose box sitting
in front of a component (or inside a concave one) could not be selected,
and a right-click over selected loose faces with a group behind them
dropped the selection for the group, taking «Make Group» with it.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from tools.select import SelectTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _vp():
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("top")
    vp.camera.target = V(3, 3, 0)
    vp.camera.distance = 12
    return vp


def _floor_group(vp):
    """A group lying at z = 0 under the whole scene."""
    m = Mesh()
    m.add_face([V(0, 0, 0), V(6, 0, 0), V(6, 6, 0), V(0, 6, 0)])
    g = Group(m, "piso")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    return g


def _loose_lid(vp, z=1.0):
    f = vp.scene.mesh.add_face([V(2, 2, z), V(4, 2, z), V(4, 4, z),
                                V(2, 4, z)])
    vp.scene.version += 1
    return f


def test_a_loose_face_in_front_of_a_group_is_what_gets_picked():
    vp = _vp()
    g = _floor_group(vp)
    lid = _loose_lid(vp)
    px = vp._world_to_pixel(V(3, 3, 1))
    assert vp.pick_group(*px) is None, "the group behind the face won"
    assert SelectTool()._pick(vp, *px) is lid
    # beside the lid nothing hides the group: it still takes the click
    beside = vp._world_to_pixel(V(5, 5, 0))
    assert vp.pick_group(*beside) is g
    assert SelectTool()._pick(vp, *beside) is g


def test_a_group_in_front_of_a_loose_face_still_wins():
    vp = _vp()
    _loose_lid(vp, z=0.0)
    m = Mesh()
    m.add_face([V(2, 2, 1), V(4, 2, 1), V(4, 4, 1), V(2, 4, 1)])
    g = Group(m, "tapa")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    px = vp._world_to_pixel(V(3, 3, 1))
    assert vp.pick_group(*px) is g
    assert SelectTool()._pick(vp, *px) is g


def test_right_click_keeps_a_selection_with_a_group_behind_it():
    vp = _vp()
    _floor_group(vp)
    lid = _loose_lid(vp)
    edges = [e for e in vp.scene.mesh.edges if lid in e.faces]
    vp.scene.select([lid, *edges])
    px = vp._world_to_pixel(V(3, 3, 1))
    vp._context_pick(*px)
    assert set(vp.scene.selection) == {lid, *edges}, \
        "right-click replaced the selection with the group behind it"


def test_a_loose_face_drawn_on_a_group_face_takes_the_click():
    """#982: a circle drawn ON a wall group's face (coplanar, outside the
    group) could not be clicked — every click went to the wall behind it,
    so the new face could neither be grouped nor pushed. The user had to
    hide the wall to reach it."""
    vp = _vp()
    g = _floor_group(vp)
    disc = _loose_lid(vp, z=0.0)        # drawn on the group's face
    px = vp._world_to_pixel(V(3, 3, 0))
    assert vp.pick_group(*px) is None, "the group under the face won"
    assert SelectTool()._pick(vp, *px) is disc
    # off the drawn face the wall is still the pick
    beside = vp._world_to_pixel(V(5, 5, 0))
    assert vp.pick_group(*beside) is g
    assert SelectTool()._pick(vp, *beside) is g
