# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A face a hair off an axis gave a ZeroDivisionError on hover.

``QVector3D.normalized()`` returns the null vector below 1e-5, so a normal
that close to a world axis passed the «parallel» guard and then divided by
zero, with the cursor over the face and a point encouraged.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.snap import _in_plane_with_point_snap


def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)


def test_a_normal_a_hair_off_the_axis_is_treated_as_parallel():
    n = V(3e-6, 0.0, 1.0)
    cand = V(1.0, 1.0, 0.0)
    x, y = _w2p(cand)
    _in_plane_with_point_snap(V(0, 0, 2), cand, n, x, y, _w2p, 9.0, None)
