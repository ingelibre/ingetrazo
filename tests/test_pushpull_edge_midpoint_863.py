# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull pushes level with an edge's midpoint (#863, #964).

The drawing tools snap to the middle of an edge; Push/Pull reads its own
distance inference and only knew corners, guides and the projection onto an
edge or a face, so "push up to half that wall" had nothing to catch. The
midpoint now comes right after a corner: an exact distance, and the cyan
Midpoint cue — also for an edge running along the push, whose arbitrary
points are no reference but whose middle is.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from tools.pushpull import PushPullTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402

from types import SimpleNamespace


def _vp():
    """Looking from the front, so a push along Z runs up the screen."""
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("front")
    vp.camera.target = V(4, 0, 2)
    vp.camera.distance = 14
    return vp


def _scene(vp):
    """A face to push at x 4..8 on the ground, and beside it a vertical
    reference edge (1, -1, 0)→(1, -1, 4): its midpoint is at height 2."""
    sc = vp.scene
    sc.mesh.add_edge(V(1, -1, 0), V(1, -1, 4))
    base = sc.mesh.add_face([V(4, 0, 0), V(8, 0, 0), V(8, 4, 0), V(4, 4, 0)])
    sc.version += 1
    tool = PushPullTool()
    tool.base_face = base
    tool.dragging = True
    tool._anchor = base.centroid()
    tool._normal = V(0, 0, 1)
    tool._cap_positions = tool._cap_loop_positions(base)
    return tool


def _hover_at(tool, vp, world):
    px, py = vp._world_to_pixel(world)
    return tool._infer_reference_distance(
        SimpleNamespace(viewport=vp, screen=QPointF(px, py)))


def test_the_push_stops_level_with_an_edge_midpoint():
    vp = _vp()
    tool = _scene(vp)
    d = _hover_at(tool, vp, V(1, -1, 2))
    assert tool._inference_kind == "midpoint"
    assert abs(d - 2.0) < 1e-6
    point, kind = tool.inference_marker()
    assert kind == "midpoint" and abs(point.z() - 2.0) < 1e-6


def test_a_few_pixels_off_the_midpoint_still_reads_it():
    vp = _vp()
    tool = _scene(vp)
    px, py = vp._world_to_pixel(V(1, -1, 2))
    d = tool._infer_reference_distance(
        SimpleNamespace(viewport=vp, screen=QPointF(px + 3, py - 3)))
    assert tool._inference_kind == "midpoint" and abs(d - 2.0) < 1e-6


def test_a_corner_still_wins_and_a_quarter_point_is_no_midpoint():
    vp = _vp()
    tool = _scene(vp)
    assert abs(_hover_at(tool, vp, V(1, -1, 4)) - 4.0) < 1e-6
    assert tool._inference_kind == "vertex"
    _hover_at(tool, vp, V(1, -1, 1))
    assert tool._inference_kind != "midpoint"
