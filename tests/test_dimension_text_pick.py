# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1039: a click on a dimension's value text picks the dimension.

Only the dimension's lines took a click, so a click on its value («4.00 m»)
took the face behind it, and the text of a vertical dimension, which sits
beside its line, could not be clicked at all. The text overdraws the model
like a leader text's block, so it now outranks the 3D picks the same way."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.dimension import Dimension
from core.layers import Layer
from tools.eraser import EraserTool
from tools.select import SelectTool
from views.viewport.picking import _point_to_segment_distance_2d


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    # A floor under everything, so a miss lands on a face.
    vp.scene.mesh.add_face([V(-4, -4), V(4, -4), V(4, 4), V(-4, 4)])
    flat = Dimension(V(-2, 0), V(2, 0), V(0, -1))          # along X, on the floor
    upright = Dimension(V(3, 2), V(3, 2, 2), V(0.5, 0))    # vertical, beside it
    vp.scene.dimensions.extend([flat, upright])
    vp.scene.version += 1
    vp.resize(900, 650)
    cam = vp.camera
    cam.perspective = True
    cam.yaw, cam.pitch = math.radians(-90.0), math.radians(35.0)
    cam.target = V(0.5, 0, 0.5)
    cam.distance = 9.0
    return win, vp, flat, upright


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _on_text(vp, dim, dx=12.0):
    """A point on the dimension's value text, ``dx`` px right of where the
    text starts' reference (the dimension line's midpoint)."""
    mid = vp._world_to_pixel(dim.midpoint())
    assert mid is not None
    return mid[0] + dx, mid[1] - 9.0


def test_a_click_on_the_value_picks_the_dimension_not_the_face_behind():
    win, vp, flat, _upright = _window()
    try:
        x, y = _on_text(vp, flat)
        assert vp.pick_dimension_text(x, y) is flat
        assert SelectTool()._pick(vp, x, y) is flat
        # Away from the text and the lines, the floor is still the pick.
        mid = vp._world_to_pixel(flat.midpoint())
        assert vp.pick_dimension_text(mid[0] + 12, mid[1] + 60) is None
    finally:
        _close(win)


def test_the_text_of_a_vertical_dimension_can_be_clicked():
    # The text starts 4 px right of the line's midpoint and runs on, so
    # most of it lies further from the line than the pick threshold.
    win, vp, _flat, upright = _window()
    try:
        x, y = _on_text(vp, upright, dx=4.0 + 2.5 * vp.pick_threshold_px)
        ap, bp = upright.line_points()
        a, b = vp._world_to_pixel(ap), vp._world_to_pixel(bp)
        # Too far from the dimension line for the line to take the click…
        assert _point_to_segment_distance_2d((x, y), a, b) \
            > vp.pick_threshold_px
        # …but on the text.
        assert SelectTool()._pick(vp, x, y) is upright
    finally:
        _close(win)


def test_a_hidden_dimension_is_not_picked_by_its_text():
    win, vp, flat, _upright = _window()
    try:
        layer = Layer("Hidden dims", visible=False)
        vp.scene.layers.append(layer)
        flat.layer = layer.name
        x, y = _on_text(vp, flat)
        assert vp.pick_dimension_text(x, y) is None
        assert SelectTool()._pick(vp, x, y) is not flat
    finally:
        _close(win)


def test_the_eraser_takes_a_dimension_by_its_text():
    win, vp, flat, _upright = _window()
    try:
        x, y = _on_text(vp, flat)
        eraser = EraserTool()
        eraser._mark(vp, x, y)
        assert flat in eraser.marked
    finally:
        _close(win)
