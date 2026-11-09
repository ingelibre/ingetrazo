# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""With an axis locked, moving the cursor sideways does not change the length.

#769 (@BastelBaus): the point on the lock line was the closest one to the
cursor's ray, and in perspective that slides along the line as the cursor
moves square to it — 2.00 m read 1.57 m with the cursor 120 px aside. The
cursor is now dropped onto the line as the screen shows it first."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from views.viewport import Viewport  # noqa: E402


def _vp(view):
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.camera.set_view(view)
    vp.camera.target = V(0, 0, 0)
    vp.camera.distance = 10
    return vp


@pytest.mark.parametrize("view", ["iso", "front", "top"])
@pytest.mark.parametrize("axis", [V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)])
def test_sideways_cursor_keeps_the_length(view, axis):
    vp = _vp(view)
    start = V(0, 0, 0)
    pa, pb = vp._world_to_pixel(start), vp._world_to_pixel(start + axis)
    ux, uy = pb[0] - pa[0], pb[1] - pa[1]
    n = math.hypot(ux, uy)
    if n < 5:
        pytest.skip("axis points at the camera in this view")
    on = vp._world_to_pixel(start + axis * 2)
    nx, ny = -uy / n, ux / n
    for off in (-120, -40, 40, 120):
        p = vp._project_to_lock_line(start, axis, on[0] + nx * off,
                                     on[1] + ny * off)
        assert (p - start).length() == pytest.approx(2.0, abs=1e-3)
