# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tools ▸ Guide Point (issue #616): one click leaves a guide point.

The point is the same :class:`core.guide.Guide` the Tape leaves in its
«guide points» mode, so it must behave like every other guide: snapped
to by the drawing tools, undone, saved, swept by Edit ▸ Delete Guides.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

from core.guide import Guide, guide_from_dict
from tools.guide_point import GuidePointTool

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    w.resize(1600, 900)
    _app.processEvents()
    vp = w.viewport
    cam = vp.camera
    cam.target = QVector3D(2, 2, 0)
    cam.distance = 14.0
    cam.pitch = math.radians(30.0)
    cam.yaw = math.radians(-50.0)
    vp.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(4, 0, 0),
                            QVector3D(4, 4, 0), QVector3D(0, 4, 0)])
    vp.scene.version += 1
    vp.update()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _hover(vp, px, py):
    vp._last_mouse_pos = QPointF(px, py)
    vp._process_hover(QPointF(px, py), Qt.NoModifier)


def _click(vp, px, py):
    vp._last_mouse_pos = QPointF(px, py)
    vp._dispatch_tool_click(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def _points(scene):
    return [g for g in scene.guides
            if isinstance(g, Guide) and g.direction is None]


def _close(a, b, tol=1e-6):
    return (a - b).length() < tol


def test_the_tool_is_on_the_annotate_bar_and_in_the_tools_menu(win):
    action = win._tool_actions["guide_point"]
    assert action in win.toolbars["annotate"].actions()
    tools_menu = next(a.menu() for a in win.menuBar().actions()
                      if a.menu() is not None
                      and action in a.menu().actions())
    assert tools_menu is not None


def test_one_click_on_a_corner_leaves_a_guide_point_there(win):
    vp = win.viewport
    win._activate_tool("guide_point")
    assert isinstance(vp.active_tool, GuidePointTool)
    x, y = vp._world_to_pixel(QVector3D(4, 0, 0))
    _hover(vp, x + 2, y + 1)                     # a hair off: the snap pulls
    _click(vp, x + 2, y + 1)
    pts = _points(vp.scene)
    assert len(pts) == 1
    assert _close(pts[0].point, QVector3D(4, 0, 0))
    assert pts[0].origin is None                 # a bare point, no segment


def test_each_click_leaves_its_own_point_and_undo_takes_them_back(win):
    vp = win.viewport
    win._activate_tool("guide_point")
    for corner in (QVector3D(0, 0, 0), QVector3D(4, 4, 0)):
        x, y = vp._world_to_pixel(corner)
        _hover(vp, x, y)
        _click(vp, x, y)
    assert len(_points(vp.scene)) == 2
    vp.history.undo()
    assert len(_points(vp.scene)) == 1
    vp.history.undo()
    assert _points(vp.scene) == []
    vp.history.redo()
    assert len(_points(vp.scene)) == 1


def test_typed_coordinates_place_it_exactly(win):
    vp = win.viewport
    win._activate_tool("guide_point")
    x, y = vp._world_to_pixel(QVector3D(2, 2, 0))
    _hover(vp, x, y)
    vp._set_value_buffer("1,5;2;0,75")
    vp._handle_value_key(QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                                   Qt.NoModifier, "\r"))
    pts = _points(vp.scene)
    assert len(pts) == 1
    assert _close(pts[0].point, QVector3D(1.5, 2.0, 0.75))


def test_a_lone_number_places_nothing(win):
    vp = win.viewport
    tool = GuidePointTool()
    assert tool.on_value(vp, 2.0) is False
    assert _points(vp.scene) == []


def test_a_point_at_nan_is_never_left(win):
    vp = win.viewport
    tool = GuidePointTool()
    assert tool.place(vp, QVector3D(float("nan"), 0, 0)) is False
    assert vp.scene.guides == []


def test_the_line_tool_snaps_to_it_like_to_a_tape_guide_point(win):
    vp = win.viewport
    GuidePointTool().place(vp, QVector3D(2, 2, 1.5))   # in mid-air
    win._activate_tool("line")
    x, y = vp._world_to_pixel(QVector3D(2, 2, 1.5))
    _hover(vp, x + 2, y + 1)
    # The only thing 1.5 m up in the air is the point: the cursor lands on
    # it (the Line names it an end, as it does a Tape guide point).
    assert vp.last_snap is not None
    assert vp.last_snap.kind in ("guide_point", "endpoint")
    assert _close(vp.last_snap.point, QVector3D(2, 2, 1.5))


def test_edit_delete_guides_sweeps_it(win):
    vp = win.viewport
    GuidePointTool().place(vp, QVector3D(1, 1, 0))
    win._on_delete_guides()
    assert vp.scene.guides == []


def test_it_saves_as_the_tapes_guide_point_does():
    g = Guide(QVector3D(1, 2, 3))
    back = guide_from_dict(json.loads(json.dumps(g.to_dict())))
    assert back.direction is None and back.origin is None
    assert _close(back.point, QVector3D(1, 2, 3))


_I18N = Path(__file__).resolve().parent.parent / "i18n"
_NEW = ("Guide Point", GuidePointTool.description,
        "Click to leave a guide point, or type x;y;z and Enter.",
        "Guide point at ({x}; {y}; {z})")


@pytest.mark.parametrize("path", sorted(p for p in _I18N.glob("*.json")
                                        if p.stem != "en"),
                         ids=lambda p: p.stem)
def test_its_texts_are_translated_everywhere(path):
    table = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in _NEW if not table.get(k)]
    assert not missing, missing
    assert "{x}" in table["Guide point at ({x}; {y}; {z})"]
