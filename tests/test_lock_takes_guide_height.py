# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A line locked to the blue axis takes a guide's height (issue #166).

@pacaeiro: with Shift held on the blue axis (or the up arrow), hovering a
guide line that the vertical does not touch should offer its height, the
way hovering any edge does. It never did for guides: the point of the
hovered edge was found by lerping the SCREEN parameter in 3D, which under
perspective is metres off on a long edge — and a guide clipped to the view
is tens of metres long — so the «hovered» point landed off screen and the
lock stayed free. Now it goes through the cursor ray, as the on-edge snap.
"""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

ALTURA = 0.825


@pytest.fixture
def vp():
    from core.guide import Guide
    from views.main_window import MainWindow
    win = MainWindow()
    v = win.viewport
    v.resize(1200, 800)
    # A horizontal guide 3 m behind the start, at the height to fetch.
    v.scene.guides.append(Guide(QVector3D(0, 3.0, ALTURA), QVector3D(1, 0, 0)))
    v.camera.target = QVector3D(0, 1, 0.5)
    win._activate_tool("line")
    v.active_tool.start_point = QVector3D(0.5, 0, 0)
    try:
        yield v
    finally:
        win._saved_version = v.scene.version
        win.close()


def _hover_guide(v, x, mods=Qt.NoModifier):
    px = v._world_to_pixel(QVector3D(x, 3.0, ALTURA))
    ev = QMouseEvent(QEvent.MouseMove, QPointF(*px), QPointF(*px),
                     Qt.NoButton, Qt.NoButton, mods)
    return v._build_ctx(ev).snap


@pytest.mark.parametrize("x", [-1.0, 0.2, 0.5, 2.0])
def test_shift_on_the_blue_axis_takes_the_guides_height(vp, x):
    vp._shift_lock = (QVector3D(0, 0, 1), (0.2, 0.3, 0.9))
    s = _hover_guide(vp, x, Qt.ShiftModifier)
    assert s.kind == "from_point"
    assert s.point.z() == pytest.approx(ALTURA, abs=1e-4)
    assert (s.point.x(), s.point.y()) == pytest.approx((0.5, 0.0), abs=1e-6)


def test_so_does_the_up_arrow(vp):
    vp.axis_lock = "z"
    s = _hover_guide(vp, 1.5)
    assert s.point.z() == pytest.approx(ALTURA, abs=1e-4)
    assert (s.point.x(), s.point.y()) == pytest.approx((0.5, 0.0), abs=1e-6)
