# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Field of View (tools/field_of_view.py): drag down to widen the
perspective's angle, up to narrow it, or type it; 1° … 120°, to a
hundredth of a degree, and only in perspective."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core import units  # noqa: E402
from core.camera import MAX_FOV_DEG, MIN_FOV_DEG, OrbitCamera  # noqa: E402
from core.scene import Scene  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from tools.field_of_view import FieldOfViewTool  # noqa: E402


class _Viewport:
    """Just what the tool touches: a camera, a height, a status bar."""

    def __init__(self, h=700):
        self.camera = OrbitCamera()
        self._h = h
        self.flashed = []

    def height(self):
        return self._h

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.flashed.append(text)


def _ctx(vp, y):
    return ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(300, y),
                       modifiers=Qt.NoModifier, snap=None)


def _armed(vp):
    tool = FieldOfViewTool()
    tool.on_activate(vp)
    return tool


# ---- The camera ----------------------------------------------------------------

def test_set_fov_keeps_the_range_and_a_hundredth_of_a_degree():
    cam = OrbitCamera()
    assert (MIN_FOV_DEG, MAX_FOV_DEG) == (1.0, 120.0)
    assert cam.set_fov(35.123456) == pytest.approx(35.12, abs=1e-9)
    assert cam.set_fov(0.2) == 1.0
    assert cam.set_fov(170.0) == 120.0
    assert cam.fov_deg == 120.0


def test_the_eye_stays_put_when_the_angle_changes():
    cam = OrbitCamera()
    eye, target = cam.eye(), QVector3D(cam.target)
    cam.set_fov(80.0)
    assert (cam.eye() - eye).length() < 1e-9
    assert (cam.target - target).length() < 1e-9


# ---- The drag ------------------------------------------------------------------

def test_drag_down_widens_and_drag_up_narrows():
    vp = _Viewport()
    tool = _armed(vp)
    start = vp.camera.fov_deg
    tool.on_click(_ctx(vp, 300))
    tool.on_hover(_ctx(vp, 400))                 # down
    wider = vp.camera.fov_deg
    assert wider > start
    tool.on_hover(_ctx(vp, 200))                 # up, past the press
    assert vp.camera.fov_deg < start
    tool.on_release(vp)
    narrowed = vp.camera.fov_deg
    tool.on_hover(_ctx(vp, 600))                 # no button: nothing moves
    assert vp.camera.fov_deg == narrowed


def test_a_full_drag_is_held_within_one_and_a_hundred_and_twenty():
    vp = _Viewport()
    tool = _armed(vp)
    tool.on_click(_ctx(vp, 0))
    tool.on_hover(_ctx(vp, 10 * vp.height()))
    assert vp.camera.fov_deg == MAX_FOV_DEG
    tool.on_hover(_ctx(vp, -10 * vp.height()))
    assert vp.camera.fov_deg == MIN_FOV_DEG


def test_a_slow_drag_at_one_degree_still_moves():
    """Rounding each pixel's step to 0.01° would leave 1° stuck: the angle
    is worked out from the press, not from the previous move."""
    vp = _Viewport()
    vp.camera.set_fov(1.0)
    tool = _armed(vp)
    tool.on_click(_ctx(vp, 300))
    for y in range(301, 341):
        tool.on_hover(_ctx(vp, y))
    assert vp.camera.fov_deg > 1.05


def test_esc_mid_drag_puts_the_angle_back():
    vp = _Viewport()
    tool = _armed(vp)
    tool.on_click(_ctx(vp, 300))
    tool.on_hover(_ctx(vp, 500))
    tool.on_cancel(vp)
    assert vp.camera.fov_deg == 45.0


# ---- The Measurements box ------------------------------------------------------

def test_the_box_shows_the_angle_to_a_hundredth():
    vp = _Viewport()
    vp.camera.set_fov(35.5)
    tool = _armed(vp)
    assert tool.vcb_label == "Field of View"
    assert tool.value_label() == ("35.50°", None)
    assert tool.value_is_unitless()


def test_a_typed_angle_is_set_and_kept_in_range():
    vp = _Viewport()
    tool = _armed(vp)
    assert tool.on_value(vp, 62.375) is True
    assert vp.camera.fov_deg == pytest.approx(62.38, abs=1e-9)
    assert tool.on_value(vp, 500.0) is True
    assert vp.camera.fov_deg == MAX_FOV_DEG
    assert tool.on_value(vp, (2.0, 3.0)) is False
    assert tool.on_value(vp, 0.0) is False


class _Ev:
    def __init__(self, text, key=0):
        self._t, self._k = text, key

    def text(self):
        return self._t

    def key(self):
        return self._k


@pytest.mark.parametrize("unit", ["mm", "in"])
def test_a_typed_angle_is_degrees_in_any_document_unit(unit):
    """«35» is 35°, not 35 mm read as 0.035."""
    from views.viewport import Viewport
    scene = Scene()
    units.bind_scene(scene)
    try:
        scene.units = {"length": unit, "precision": 0}
        vp = Viewport.__new__(Viewport)
        vp.camera = OrbitCamera()
        vp.active_tool = FieldOfViewTool()
        vp._value_buffer = "35"
        vp.valueBufferChanged = type("S", (), {"emit": lambda s, t: None})()
        vp.update = lambda: None
        vp._release_axis_lock_after_operation = lambda *a, **k: None
        vp.flash_status = lambda *a, **k: None
        vp._handle_value_key(_Ev("", Qt.Key_Return))
        assert vp.camera.fov_deg == pytest.approx(35.0)
    finally:
        units.bind_scene(None)


# ---- Perspective only ----------------------------------------------------------

def test_in_parallel_the_tool_says_so_and_leaves_the_camera_alone():
    vp = _Viewport()
    vp.camera.perspective = False
    tool = _armed(vp)
    assert vp.flashed                            # said on arrival
    tool.on_click(_ctx(vp, 300))
    tool.on_hover(_ctx(vp, 600))
    assert tool.on_value(vp, 90.0) is False
    assert vp.camera.fov_deg == 45.0
    assert tool.value_label() is None


def test_switching_to_parallel_mid_drag_ends_the_drag():
    vp = _Viewport()
    tool = _armed(vp)
    tool.on_click(_ctx(vp, 300))
    tool.on_hover(_ctx(vp, 400))
    vp.camera.perspective = False                # Shift+P
    tool.on_hover(_ctx(vp, 600))
    assert vp.camera.fov_deg == 45.0             # back where it started
    vp.camera.perspective = True
    tool.on_hover(_ctx(vp, 700))
    assert vp.camera.fov_deg == 45.0             # the drag is over


# ---- The menu ------------------------------------------------------------------

def test_camera_menu_has_it_between_zoom_and_zoom_window():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        act = win._tool_actions["field_of_view"]
        camera_menu = next(a.menu() for a in win.menuBar().actions()
                           if a.menu() is not None and a.text() == "Camera")
        acts = [a for a in camera_menu.actions() if not a.isSeparator()]
        i = acts.index(act)
        assert acts[i - 1] is win._nav_actions["zoom"]
        assert acts[i + 1] is win._nav_actions["zoom_window"]
        # The Zoom's magnifier, on the menu entry and as the pointer.
        assert win._tools["field_of_view"].icon == "zoom"
        assert (act, "zoom") in win._icon_actions
        # A menu entry only: no toolbar carries it.
        assert all(act not in tb.actions() for tb in win.toolbars.values())
        # Picking it arms the tool; the menu greys it out in parallel.
        act.trigger()
        assert win.viewport.active_tool is win._tools["field_of_view"]
        win.viewport.camera.perspective = False
        camera_menu.aboutToShow.emit()
        assert not act.isEnabled()
        win.viewport.camera.perspective = True
        camera_menu.aboutToShow.emit()
        assert act.isEnabled()
    finally:
        win.close()
        win.deleteLater()
