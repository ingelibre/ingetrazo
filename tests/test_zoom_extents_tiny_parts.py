# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#583 (@andku85, parts for 3D printing): two 10 mm lines typed with the
Line tool, Zoom Extents with the line still going — and nothing could be
drawn or pushed any more: «AddEdgeCommand: cannot convert float NaN to
integer», the length label reading «mm» with no number.

The camera ends 2 cm from the part, the perspective's near plane 0.4 mm
in front of it and the far plane kilometres away: past float32, the
projection's depth term rounds to exactly -1, the far plane goes to
infinity, and the cursor ray — unprojected through the far plane — came out
NaN. Every inference built on it (intersection, through point…) handed the
tool a NaN point."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QVector3D as V  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _finite(p) -> bool:
    return p is not None and all(math.isfinite(c) for c in (p.x(), p.y(), p.z()))


def _move(vp, w):
    px, py = vp._world_to_pixel(w)
    QTest.mouseMove(vp, QPointF(px, py).toPoint())
    vp._last_mouse_pos = QPointF(px, py)
    vp._refresh_snap()
    _app.processEvents()
    return px, py


def _click(vp, px, py):
    vp._dispatch_tool_click(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(px, py), QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    _app.processEvents()


def _type(vp, text):
    for ch in text:
        QTest.keyClick(vp, ch)
    QTest.keyClick(vp, Qt.Key_Return)
    _app.processEvents()


def _window():
    from core import units
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    _app.processEvents()
    scene = win.viewport.scene
    units.apply_units(scene, {"length": "mm", "precision": 2})
    scene.groups.clear()                        # «delete man»
    scene.version += 1
    return win


def _two_lines_then_zoom(win):
    vp = win.viewport
    win._activate_tool("line")
    _click(vp, *vp._world_to_pixel(V(0, 0, 0)))
    _move(vp, V(0, 1, 0))
    _type(vp, "10")
    _move(vp, V(1, 0.01, 0))
    _type(vp, "10")                              # the line is still going
    win._on_zoom_extents()
    vp.repaint()
    _app.processEvents()
    return vp


def test_the_cursor_ray_stays_finite_a_few_centimetres_from_a_part():
    win = _window()
    try:
        vp = _two_lines_then_zoom(win)
        assert vp.camera.distance < 0.05         # right up to the part
        for w in (V(0.02, 0.01, 0), V(0.01, 0, 0), V(-0.01, 0.02, 0)):
            origin, direction = vp._pixel_to_ray(*vp._world_to_pixel(w))
            assert _finite(origin) and _finite(direction), w
            assert abs(direction.length() - 1.0) < 1e-4
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_drawing_goes_on_after_zoom_extents_on_a_10_mm_part():
    win = _window()
    try:
        vp = _two_lines_then_zoom(win)
        tool = vp.active_tool
        edges = len(vp.scene.mesh.edges)
        for w in (V(0.02, 0.01, 0), V(0.01, 0, 0), V(0.015, 0.012, 0)):
            _move(vp, w)
            assert _finite(tool.hover_point), w
        _click(vp, *vp._world_to_pixel(V(0.015, 0.012, 0)))
        assert "NaN" not in (win.statusBar().currentMessage() or "")
        assert len(vp.scene.mesh.edges) == edges + 1
        assert all(_finite(v.position) for v in vp.scene.mesh.vertices)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
