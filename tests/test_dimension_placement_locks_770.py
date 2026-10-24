# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Arrow and Shift locks steer the Dimension tool's placement step.

#770 (@BastelBaus): with the X axis locked, the dimension still switched
between parallel and orthogonal as the cursor crossed to one side of the
line — the cursor alone chose the kind. With @pacaeiro's #810 an arrow pins
the placement direction, as in Line, and Shift keeps the kind the preview
was showing when it went down."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D as V

from tools.dimension import DimensionTool


def _tool(lock=None):
    t = DimensionTool()
    t.a, t.b = V(0, 0, 0), V(2, 1, 0)
    t._vp = SimpleNamespace(axis_lock=lock)
    return t


@pytest.mark.parametrize("cursor", [
    V(3, 0.5, 0), V(-1, 0.5, 0), V(4, 2, 0), V(-2, -1, 0),
    V(1, 3, 0), V(1, -2, 0)])
def test_x_locked_slides_along_x_and_measures_y_on_every_side(cursor):
    d = _tool("x")._proposed(cursor)
    assert d.axis == "y"
    assert d.value() == pytest.approx(1.0)
    assert abs(d.offset.y()) < 1e-9 and abs(d.offset.z()) < 1e-9


def test_shift_keeps_the_kind_the_preview_showed(monkeypatch):
    t = _tool()
    monkeypatch.setattr(DimensionTool, "_shift_held", staticmethod(lambda: False))
    free = t._proposed(V(1, 3, 0))
    t._free = (free.offset, free.axis)
    monkeypatch.setattr(DimensionTool, "_shift_held", staticmethod(lambda: True))
    for c in (V(5, 3, 0), V(-3, 4, 0), V(1, 6, 0)):
        assert t._proposed(c).axis == free.axis
