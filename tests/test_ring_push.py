# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Concentric-rings push (the 'eye' model): three concentric circles on a slab,
pushed ring by ring. Documents the known deep class — pushing a HOLED ring
whose neighbours already sit at different levels either cracks (guard restores)
or is digested back to the original by the per-plane rebuild — and pins the
BIM-grade behaviour: the mesh stays watertight and untouched, and the user is
TOLD (status message). The desired outcome (the ring actually moving) is the
strict xfail, to flip when the region-identity rebuild lands."""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import (
    AddFaceCommand,
    History,
    RebuildPlanarFacesCommand,
    TagCurveCommand,
)
from core.orient import is_closed
from core.scene import Scene
from tools.base import ToolContext
from tools.pushpull import PushPullTool


class _Vp:
    """Just enough viewport for a scripted push (no Qt widgets)."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.messages = []

    def set_hover(self, *_):
        pass

    def set_suppressed_faces(self, *_):
        pass

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.messages.append(text)


def _circle(r):
    return [QVector3D(r * math.cos(2 * math.pi * i / 24),
                      r * math.sin(2 * math.pi * i / 24), 0) for i in range(24)]


def _setup():
    scene = Scene()
    vp = _Vp(scene)

    def V(x, y):
        return QVector3D(x, y, 0)

    sq = [V(-8, -8), V(8, -8), V(8, 8), V(-8, 8)]
    vp.history.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)],
        detect_faces=True, extra=[AddFaceCommand(sq)]))
    for r in (5, 3, 1.5):
        pts = _circle(r)
        segs = [(pts[i], pts[(i + 1) % 24]) for i in range(24)]
        vp.history.execute(build_add_edges(
            scene, segs, detect_faces=False,
            extra=[TagCurveCommand(list(pts), closed=True),
                   RebuildPlanarFacesCommand()]))
    return vp, scene


def _push(vp, face, dist):
    pp = PushPullTool()
    pp.hovered_face = face
    pp._hover_group = None
    pp.on_click(ToolContext(viewport=vp, world=QVector3D(0, 0, 0),
                            screen=QPointF(500, 350),
                            modifiers=Qt.NoModifier, snap=None))
    pp.extrusion = dist
    pp._commit(vp)


def _at0(f):
    return all(abs(v.position.z()) < 1e-6 for v in f.loop)


def _rings(scene):
    ext = [f for f in scene.mesh.faces if _at0(f) and len(f.loop) == 4
           and f.hole_loops][0]
    return ext


def test_ring_push_refusal_is_failsafe_and_announced():
    vp, sc = _setup()
    _push(vp, _rings(sc), 2.0)
    ring1 = [f for f in sc.mesh.faces if _at0(f)
             and abs(f.area() - 77.65) < 2 and f.hole_loops][0]
    _push(vp, ring1, 1.0)
    assert is_closed(sc.mesh)
    faces_before = len(sc.mesh.faces)
    ring2 = [f for f in sc.mesh.faces if _at0(f)
             and abs(f.area() - 27.95) < 2 and f.hole_loops][0]
    _push(vp, ring2, 0.5)
    assert is_closed(sc.mesh)                       # never commits a crack
    assert len(sc.mesh.faces) == faces_before       # untouched
    ring2_z = {round(v.position.z(), 3) for v in ring2.loop}
    assert ring2_z == {0.0}                         # really did not move
    assert any("refused" in m.lower() for m in vp.messages)  # user is told


@pytest.mark.xfail(reason="holed-ring push between mixed neighbour levels "
                          "needs the region-identity rebuild (A.3)",
                   strict=True)
def test_ring_push_between_levels_actually_moves():
    vp, sc = _setup()
    _push(vp, _rings(sc), 2.0)
    ring1 = [f for f in sc.mesh.faces if _at0(f)
             and abs(f.area() - 77.65) < 2 and f.hole_loops][0]
    _push(vp, ring1, 1.0)
    ring2 = [f for f in sc.mesh.faces if _at0(f)
             and abs(f.area() - 27.95) < 2 and f.hole_loops][0]
    _push(vp, ring2, 0.5)
    ring2_z = {round(v.position.z(), 3) for v in ring2.loop}
    assert ring2_z == {-0.5}                        # desired: it just works
    assert is_closed(sc.mesh)
