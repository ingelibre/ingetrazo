# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser's padlock: a locked group cannot be picked in the view, so
it can be neither moved nor opened by double-click.

The pick index's group block is keyed on the placements epoch, which knew
each group's ``hidden`` but not its ``locked``: a group picked once kept
its stale «selectable» entry after the padlock, and the Move tool and a
double-click still reached it (as #53 did with the view's Hidden switches).
The order matters — a pick BEFORE locking is what leaves the stale block."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.group import Group  # noqa: E402
from core.history import History, LockCommand  # noqa: E402
from core.mesh import Mesh  # noqa: E402
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


def _boxed_group(vp):
    m = Mesh()
    m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    g = Group(m, "muro")
    xf = QMatrix4x4()
    xf.translate(1, 1, 0)
    g.xform = xf
    vp.scene.groups.append(g)
    vp.scene.version += 1
    return g


def test_the_padlock_takes_the_group_out_of_the_pick():
    vp = _vp()
    g = _boxed_group(vp)
    history = History(vp.scene)
    px = vp._world_to_pixel(V(2, 2, 0))
    assert vp.pick_group(*px) is g                    # the block is built
    history.execute(LockCommand([g], True))
    assert vp.pick_group(*px) is None                 # locked: not pickable
    history.undo()
    assert vp.pick_group(*px) is g                    # unlocked again


def test_a_locked_classic_group_is_not_picked_either():
    """A plain group (no matrix) goes through the same block."""
    vp = _vp()
    m = Mesh()
    m.add_face([V(1, 1, 0), V(3, 1, 0), V(3, 3, 0), V(1, 3, 0)])
    g = Group(m, "suelo")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    px = vp._world_to_pixel(V(2, 2, 0))
    assert vp.pick_group(*px) is g
    g.locked = True
    vp.scene.version += 1
    assert vp.pick_group(*px) is None


# --- nothing opens a locked group, whichever road asks ------------------------

def test_a_locked_component_does_not_open_for_editing():
    vp = _vp()
    g = _boxed_group(vp)
    g.locked = True
    vp.begin_group_edit(g)                 # double-click, Edit Group, Parts
    assert vp.scene.edit_group is None
    g.locked = False
    vp.begin_group_edit(g)
    assert vp.scene.edit_group is g


def test_nothing_inside_a_locked_group_opens():
    vp = _vp()
    pieza = Group(Mesh(), "pieza")
    pieza.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    muro = Group(Mesh(), "muro")
    muro.children = [pieza]
    vp.scene.groups.append(muro)
    vp.scene.version += 1
    muro.locked = True
    vp.begin_group_edit(pieza)
    assert vp.scene.edit_group is None
