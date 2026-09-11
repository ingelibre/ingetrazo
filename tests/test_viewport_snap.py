# SPDX-License-Identifier: GPL-3.0-or-later
"""Viewport contextual Shift-lock tests."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.snap import COLOR_AXIS_X, SnapResult
from views.viewport import Viewport


class _Tool:
    def __init__(self):
        self.start_point = QVector3D(2.0, 3.0, 4.0)


class _ViewportStub:
    _SHIFT_LOCKABLE = Viewport._SHIFT_LOCKABLE

    def __init__(self, snap_point):
        self.last_snap = SnapResult(
            snap_point, "axis_inference", COLOR_AXIS_X, axis="x"
        )
        self.active_tool = _Tool()
        self._shift_lock = None


def _capture(stub):
    Viewport._capture_shift_lock.__get__(stub)()
    return stub._shift_lock[0]


def test_shift_lock_uses_exact_positive_inferred_axis():
    stub = _ViewportStub(QVector3D(5.0, 3.01, 4.0))

    direction = _capture(stub)

    assert direction == QVector3D(1.0, 0.0, 0.0)


def test_shift_lock_preserves_negative_inferred_axis_direction():
    stub = _ViewportStub(QVector3D(-1.0, 3.01, 4.0))

    direction = _capture(stub)

    assert direction == QVector3D(-1.0, 0.0, 0.0)
