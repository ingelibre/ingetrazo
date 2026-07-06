# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rectangle tool — on-screen dimensions and typed exact size (VCB).

Drawing a rectangle shows a live ``width × height`` readout, and typing
``W;H`` + Enter lays the rectangle at that exact size, in the quadrant the
cursor is heading toward.

Headless: ``QVector3D`` values + a stub viewport.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.rectangle import RectangleTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _Stub:
    def __init__(self) -> None:
        self.scene = Scene()
        self.history = History(self.scene)

    def update(self) -> None:
        pass


def _corner_keys(face):
    return {(round(v.x(), 3), round(v.y(), 3), round(v.z(), 3)) for v in face.vertices}


def test_dimension_label_tracks_drag():
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)
    text, _ = t.value_label()
    assert text == "5.00 × 4.00 m"


def test_label_none_before_drag():
    t = RectangleTool()
    assert t.value_label() is None


def test_typed_dimensions_build_exact_rectangle():
    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)            # heading +X, +Y
    assert t.on_value(vp, (3.0, 2.0)) is True
    assert len(vp.scene.faces) == 1
    assert _corner_keys(vp.scene.faces[0]) == {
        (0, 0, 0), (3, 0, 0), (3, 2, 0), (0, 2, 0)
    }


def test_typed_dimensions_follow_drag_quadrant():
    # Cursor heading into the -X, -Y quadrant → the exact rectangle lays there.
    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(-1, -1)
    assert t.on_value(vp, (3.0, 2.0)) is True
    assert _corner_keys(vp.scene.faces[0]) == {
        (0, 0, 0), (-3, 0, 0), (-3, -2, 0), (0, -2, 0)
    }


def test_typed_dimensions_rejects_non_pair():
    vp = _Stub()
    t = RectangleTool()
    t.start_point = V(0, 0)
    t.hover_point = V(5, 4)
    assert t.on_value(vp, 3.0) is False          # a bare length isn't a W×H
    assert t.on_value(vp, (1.0, 2.0, 3.0)) is False  # a 3D delta isn't either
    assert len(vp.scene.faces) == 0
