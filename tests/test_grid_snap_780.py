# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The drawing grid with its snap (#780).

Off by default; spacing, major lines and colour per document (they travel
in the .igz); a free point on the ground goes to the nearest crossing
while every named inference keeps winning; and the status bar's switches
for the grid, its snap and the point inferences.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication, QToolButton

from core import grid as gridmod
from core.scene import Scene
from core.snap import (SNAP_TOGGLES, SnapResult, disabled_snap_toggles,
                       set_disabled_snap_toggles, set_snap_toggle_enabled)
from tests.test_edge_rendering import cube_viewport  # noqa: F401 - native fixture

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture(autouse=True)
def _all_inferences_on():
    set_disabled_snap_toggles(())
    yield
    set_disabled_snap_toggles(())


# ---- Settings -------------------------------------------------------------------

def test_a_new_document_has_no_grid_and_no_snap():
    scene = Scene()
    grid = gridmod.grid_of(scene)
    assert grid["visible"] is False and grid["snap"] is False
    assert scene.grid is None
    assert not gridmod.snap_active(scene)
    assert gridmod.snap_point(scene, V(0.4, 0.6)) is None


@pytest.mark.parametrize("unit, spacing", [
    ("m", 1.0), ("cm", 0.1), ("mm", 0.1), ("in", 0.3048), ("ft-in", 0.3048)])
def test_the_first_spacing_follows_the_units(unit, spacing):
    scene = Scene()
    scene.units = {"length": unit, "precision": 2}
    assert gridmod.grid_of(scene)["spacing"] == pytest.approx(spacing)


@pytest.mark.parametrize("raw, spacing, major", [
    ({"spacing": 0.25, "major": 4}, 0.25, 4),
    ({"spacing": -1, "major": 0}, 1.0, 1),
    ({"spacing": "abc", "major": "x"}, 1.0, 10),
    ({"spacing": float("nan"), "major": 500}, 1.0, 100),
    ({"spacing": 1e9}, gridmod.MAX_SPACING, 10),
    ({"spacing": 1e-9}, gridmod.MIN_SPACING, 10),
])
def test_broken_settings_fall_back(raw, spacing, major):
    grid = gridmod.normalized(raw)
    assert grid["spacing"] == pytest.approx(spacing)
    assert grid["major"] == major


def test_color_is_automatic_unless_chosen():
    assert gridmod.normalized({"color": "red"})["color"] is None
    assert gridmod.normalized({"color": [2, 0.5, -1]})["color"] == (1.0, 0.5, 0.0)
    light, dark = gridmod.auto_color((0.9, 0.9, 0.9)), gridmod.auto_color((0.1, 0.1, 0.1))
    assert sum(light) < sum((0.9, 0.9, 0.9)) and sum(dark) > sum((0.1, 0.1, 0.1))
    scene = Scene()
    gridmod.set_grid(scene, color=(1, 0, 0))
    assert gridmod.line_color(scene, (0.9, 0.9, 0.9)) == (1.0, 0.0, 0.0)


# ---- Rounding ----------------------------------------------------------------------

def test_a_point_on_the_ground_goes_to_the_nearest_crossing():
    p = gridmod.round_to_grid(V(1.26, -0.74), 0.5)
    assert (p.x(), p.y(), p.z()) == pytest.approx((1.5, -0.5, 0.0))
    p = gridmod.round_to_grid(V(12.4, 7.6), 1.0)
    assert (p.x(), p.y()) == pytest.approx((12.0, 8.0))


def test_a_point_off_the_ground_is_left_alone():
    assert gridmod.round_to_grid(V(1.2, 1.2, 0.3), 1.0) is None


def test_snap_acts_only_with_the_grid_shown():
    scene = Scene()
    gridmod.set_grid(scene, snap=True)
    assert gridmod.snap_point(scene, V(0.4, 0.6)) is None    # grid hidden
    gridmod.set_grid(scene, visible=True)
    p = gridmod.snap_point(scene, V(0.4, 0.6))
    assert (p.x(), p.y()) == pytest.approx((0.0, 1.0))
    gridmod.set_grid(scene, snap=False)
    assert gridmod.snap_point(scene, V(0.4, 0.6)) is None


# ---- The document ---------------------------------------------------------------------

def test_the_grid_travels_in_the_igz(tmp_path):
    from formats.igz import load_into, save_scene
    scene = Scene()
    scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    gridmod.set_grid(scene, visible=True, snap=True, spacing=0.25, major=4,
                     color=(0.2, 0.4, 0.6))
    path = tmp_path / "grid.igz"
    save_scene(scene, path)
    back = Scene()
    load_into(back, path)
    assert gridmod.grid_of(back) == gridmod.grid_of(scene)


def test_an_untouched_document_stores_no_grid_and_opens_without_one(tmp_path):
    from formats.igz import load_into, save_scene
    scene = Scene()
    scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    assert gridmod.to_payload(scene) is None
    path = tmp_path / "plain.igz"
    save_scene(scene, path)
    other = Scene()
    gridmod.set_grid(other, visible=True)
    load_into(other, path)                 # the old grid does not leak in
    assert other.grid is None
    assert gridmod.grid_of(other)["visible"] is False


def test_a_new_document_forgets_the_grid():
    scene = Scene()
    gridmod.set_grid(scene, visible=True, snap=True)
    scene.clear()
    assert scene.grid is None


# ---- In the viewport ------------------------------------------------------------------

def _line_vp():
    """Seen from above, Line tool on, a 1 × 1 square at (5, 5)."""
    from tools.line import LineTool
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("top")
    vp.camera.target = V(3, 3, 0)
    vp.camera.distance = 14
    vp.scene.mesh.add_face([V(5, 5), V(6, 5), V(6, 6), V(5, 6)])
    vp.scene.version += 1
    vp.set_active_tool(LineTool())
    return vp


def _hover(vp, world):
    px = vp._world_to_pixel(world)
    vp._process_hover(QPointF(*px), Qt.NoModifier)
    return vp.last_snap


def test_without_the_grid_nothing_changes():
    vp = _line_vp()
    snap = _hover(vp, V(1.3, 2.2))
    assert snap.kind != "grid"
    assert snap.point.x() == pytest.approx(1.3, abs=0.02)


def test_with_grid_snap_a_free_point_goes_to_a_crossing():
    vp = _line_vp()
    gridmod.set_grid(vp.scene, visible=True, snap=True, spacing=0.5)
    snap = _hover(vp, V(1.3, 2.2))
    assert snap.kind == "grid"
    assert (snap.point.x(), snap.point.y(), snap.point.z()) == pytest.approx(
        (1.5, 2.0, 0.0))


def test_a_corner_of_the_model_still_wins_over_the_grid():
    vp = _line_vp()
    gridmod.set_grid(vp.scene, visible=True, snap=True, spacing=0.3)
    snap = _hover(vp, V(5.01, 5.01))
    assert snap.kind == "endpoint"
    assert (snap.point.x(), snap.point.y()) == pytest.approx((5.0, 5.0))


def test_a_floor_at_ground_level_takes_the_grid_too():
    vp = _line_vp()
    gridmod.set_grid(vp.scene, visible=True, snap=True, spacing=0.25)
    vp.camera.target = V(5.5, 5.5, 0)          # close up: the edges far off
    vp.camera.distance = 3
    # Inside the square, away from its centre («Face center» still wins
    # there, as every named inference does).
    snap = _hover(vp, V(5.22, 5.77))
    assert snap.kind == "grid"
    assert (snap.point.x(), snap.point.y()) == pytest.approx((5.25, 5.75))
    assert _hover(vp, V(5.5, 5.5)).kind == "face_center"


def test_grid_snap_is_not_a_named_point_of_the_model():
    from core.snap import POINT_SNAP_KINDS
    assert "grid" not in POINT_SNAP_KINDS


def _engine_with(scene, normal=V(0, 0, 1)):
    from types import SimpleNamespace
    from core.inference import InferenceEngine
    vp = SimpleNamespace(scene=scene, _work_plane_normal=lambda: normal)
    engine = InferenceEngine.__new__(InferenceEngine)
    engine.viewport = vp
    return engine


def test_a_vertical_face_keeps_its_own_point():
    scene = Scene()
    gridmod.set_grid(scene, visible=True, snap=True)
    engine = _engine_with(scene, normal=V(1, 0, 0))
    on_wall = SnapResult(V(2.3, 0.0, 0.0), "on_face")
    assert engine._grid_snap(on_wall).kind == "on_face"
    flat = _engine_with(scene)
    assert flat._grid_snap(SnapResult(V(2.3, 0.4, 0.0), "on_face")).kind == "grid"


def test_the_axis_cue_keeps_its_colour_on_a_crossing_along_it():
    scene = Scene()
    gridmod.set_grid(scene, visible=True, snap=True, spacing=1.0)
    engine = _engine_with(scene)
    cue = SnapResult(V(3.2, 0.02, 0.0), "axis_inference", (1, 0, 0), axis="x")
    out = engine._grid_snap(cue, start_pt=V(0, 0, 0))
    assert out.kind == "axis_inference" and out.axis == "x"
    assert (out.point.x(), out.point.y()) == pytest.approx((3.0, 0.0))
    # Started off the grid: the crossing is not on the cue's line.
    out = engine._grid_snap(cue, start_pt=V(0, 0.3, 0))
    assert out.kind == "grid"


def test_named_snaps_are_never_moved():
    scene = Scene()
    gridmod.set_grid(scene, visible=True, snap=True)
    engine = _engine_with(scene)
    for kind in ("endpoint", "midpoint", "on_edge", "axis", "intersection"):
        snap = SnapResult(V(0.3, 0.3, 0.0), kind)
        assert engine._grid_snap(snap) is snap


# ---- Drawing ------------------------------------------------------------------------------

def test_the_shader_reads_its_uniforms():
    from views.viewport._support import SHADER_DIR
    text = (SHADER_DIR / "grid.frag").read_text(encoding="utf-8")
    for name in ("u_inverse_mvp", "u_mvp", "u_color", "u_spacing", "u_major",
                 "u_alpha"):
        assert name in text


def test_the_kept_frame_knows_the_grid():
    """Showing the grid with the camera still must redraw: the frame cache
    key reads the document's grid."""
    import inspect
    from views.viewport import render
    src = inspect.getsource(render.RenderMixin._frame_cache_key) \
        if hasattr(render, "RenderMixin") else inspect.getsource(render)
    assert 'getattr(sc, "grid", None)' in src


def _live(vp):
    for _ in range(3):
        vp.update()
        QApplication.processEvents()
    image = vp.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
    w, h = image.width(), image.height()
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        (h, image.bytesPerLine() // 4, 4))[:, :w, :3].astype(int)


def test_the_grid_is_drawn_on_the_ground_and_not_in_exports(cube_viewport):
    from core.style import Style
    vp = cube_viewport
    scene = vp.scene
    scene.clear()
    scene.show_axes = False
    scene.display_style = Style(sky=False, ground=False, edges=False,
                                profiles=False, background=(1, 1, 1))
    vp.camera.set_view("top")
    vp.camera.perspective = False
    vp.camera.target = V(0, 0)
    vp.camera.distance = 8
    scene.version += 1
    plain = _live(vp)
    gridmod.set_grid(scene, visible=True, spacing=0.5, color=(0, 0, 0))
    gridded = _live(vp)
    assert (np.abs(gridded - plain).sum(axis=2) > 60).mean() > 0.005
    exported = vp.render_image(300, 200, overlays=False)
    gridmod.set_grid(scene, visible=False)
    assert exported == vp.render_image(300, 200, overlays=False)


# ---- The window ------------------------------------------------------------------------------

def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    _app.processEvents()
    return win


def test_the_status_bar_has_two_icon_switches_with_tooltips():
    from core.i18n import tr
    win = _window()
    try:
        bar = win._status_toggles
        assert bar.keys() == ["grid", "inferences"]
        assert bar.parent() is win.statusBar()
        grid, inf = bar.button("grid"), bar.button("inferences")
        assert grid.defaultAction() is win._act_grid_switch
        assert grid.menu() is win._grid_menu   # a click lists, as Inferences
        assert grid.popupMode() == QToolButton.InstantPopup
        assert grid.contextMenuPolicy() == Qt.CustomContextMenu
        assert win._grid_menu.actions()[:2] == [win._act_grid_show,
                                                win._act_grid_snap]
        assert win._act_grid_settings in win._grid_menu.actions()
        assert inf.menu() is win._inference_menu
        assert inf.popupMode() == QToolButton.InstantPopup  # a click lists
        for button in (grid, inf):            # the icon, not the name
            assert button.toolButtonStyle() == Qt.ToolButtonIconOnly
            assert not button.icon().isNull()
            assert button.toolTip()           # what it is, on hover
        assert grid.toolTip().startswith(tr("Grid"))
        assert win._act_grid_switch.statusTip() in grid.toolTip()
        assert inf.toolTip().startswith(tr("Inferences"))
        assert win._act_grid_show.shortcut().toString() == "F7"
        assert win._act_grid_snap.shortcut().toString() == "F9"
        assert not win._act_grid_switch.isCheckable()   # never highlighted
        assert not win._act_grid_show.isChecked()
        assert not win._act_grid_snap.isChecked()
        # Inferences opens a list: it is no switch, never highlighted.
        assert not win._act_inferences_switch.isCheckable()
        assert not inf.isChecked()
        assert win._act_inferences_all.isChecked()      # all on by default
    finally:
        win.close()
        win.deleteLater()


def test_the_icons_are_drawn_and_differ_from_the_four_views():
    from views.icons import tool_icon

    def pixels(key):
        img = tool_icon(key).pixmap(48, 48).toImage()
        return bytes(img.constBits())[: img.sizeInBytes()]

    grid, inf, four = pixels("grid"), pixels("inferences"), pixels("four_views")
    assert any(grid) and any(inf)
    assert len({grid, inf, four}) == 3


def test_a_click_on_the_grid_icon_lists_its_checks_and_changes_nothing():
    from PySide6.QtCore import QTimer
    win = _window()
    try:
        scene = win.viewport.scene
        button = win._status_toggles.button("grid")
        menu = win._grid_menu
        shown = []
        menu.aboutToShow.connect(lambda: (shown.append(True),
                                          QTimer.singleShot(0, menu.close)))
        button.click()
        assert shown and not button.isChecked()
        assert not gridmod.grid_of(scene)["visible"]
        assert all(a.isCheckable() for a in (win._act_grid_show,
                                              win._act_grid_snap))
        win._act_grid_show.trigger()                # the grid from its list
        assert gridmod.grid_of(scene)["visible"]
        assert not button.isChecked()               # the icon stays plain
        win._act_grid_snap.trigger()
        assert gridmod.snap_active(scene)
    finally:
        win.close()
        win.deleteLater()


def test_the_switches_drive_the_documents_grid():
    win = _window()
    try:
        scene = win.viewport.scene
        win._act_grid_snap.trigger()               # snap on shows the grid
        assert gridmod.grid_of(scene)["visible"] and gridmod.snap_active(scene)
        assert win._act_grid_show.isChecked()
        win._act_grid_show.trigger()               # hidden: snap reads off
        assert not gridmod.snap_active(scene)
        assert not win._act_grid_snap.isChecked()
        win._act_grid_show.trigger()               # back: snap comes back
        assert win._act_grid_snap.isChecked()
        scene.grid = None                          # as a new document has it
        win._sync_section_menu()
        assert not win._act_grid_show.isChecked()
    finally:
        win.close()
        win.deleteLater()


def test_a_click_on_inferences_lists_them_and_switches_nothing_off():
    """The Inferences button only opens the list: a click never turns
    the inferences off (they are on, as always, until one is unticked)."""
    from PySide6.QtCore import QSettings, QTimer
    win = _window()
    try:
        button = win._status_toggles.button("inferences")
        shown = []
        menu = win._inference_menu
        menu.aboutToShow.connect(lambda: (shown.append(True),
                                          QTimer.singleShot(0, menu.close)))
        button.click()
        assert shown
        assert disabled_snap_toggles() == frozenset()
        assert not button.isChecked()
    finally:
        QSettings().remove(win._INFERENCES_OFF_KEY)
        win.close()
        win.deleteLater()


def test_the_all_check_switches_every_inference_on_or_off():
    """«Turn all inferences on» is a check: ticked while every one is on,
    unticked switches them all off, ticked again all on."""
    from PySide6.QtCore import QSettings
    win = _window()
    try:
        every = win._act_inferences_all
        assert every.isCheckable() and every.isChecked()
        every.setChecked(False)
        assert disabled_snap_toggles() == {t.key for t in SNAP_TOGGLES}
        assert not any(a.isChecked() for a in win._inference_actions.values())
        every.setChecked(True)
        assert disabled_snap_toggles() == frozenset()
        assert all(a.isChecked() for a in win._inference_actions.values())
        win._inference_actions["origin"].setChecked(False)   # one off…
        assert not every.isChecked()                          # …not all on
        win._inference_actions["origin"].setChecked(True)
        assert every.isChecked()
    finally:
        QSettings().remove(win._INFERENCES_OFF_KEY)
        win.close()
        win.deleteLater()


def test_grid_settings_dialog_round_trip():
    from views.grid_dialog import GridDialog
    dlg = GridDialog({"visible": True, "snap": False, "spacing": 0.25,
                      "major": 4, "color": None})
    assert dlg.spacing.value() == pytest.approx(0.25)
    dlg.major.setValue(5)
    dlg.snap_box.setChecked(True)
    out = dlg.settings()
    assert out == {"visible": True, "snap": True, "spacing": pytest.approx(0.25),
                   "major": 5, "color": None}
    dlg.deleteLater()


def test_every_new_message_is_translated():
    import json
    from core.i18n import _I18N_DIR
    keys = ["Snap to Grid", "Grid Settings…", "On grid", "Line color:",
            "Show the grid on the ground, snap to it (F7, F9) and choose its spacing.",
            "Choose which point inferences are on.",
            "Tick to switch every point inference of this menu on, untick to switch them all off.",
            "Major line every:", "Show the grid"]
    for path in _I18N_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert all(k in data for k in keys), path.stem


def test_the_icons_light_up_only_while_their_list_is_open():
    """The accent while the pointer is on an icon or its list is open, as
    the toolbars' buttons; nothing left lit once the list closes."""
    from PySide6.QtCore import QTimer
    win = _window()
    try:
        css = win._status_toggles.styleSheet()
        assert "QToolButton:open" in css and "QToolButton:hover" in css
        assert ":checked" not in css
        for key, menu in (("grid", win._grid_menu),
                          ("inferences", win._inference_menu)):
            button = win._status_toggles.button(key)
            QTimer.singleShot(50, menu.close)
            button.showMenu()
            _app.processEvents()
            assert not button.isDown() and not button.isChecked()
    finally:
        win.close()
        win.deleteLater()


def test_the_icons_sit_at_the_far_right_after_the_measurements_box():
    win = _window()
    try:
        win.show()
        bar = win.statusBar()
        win._vcb_name.setText("Length")
        win._vcb_value.setText("2.50 m")
        win._vcb_name.show()
        win._vcb_value.show()
        _app.processEvents()
        icons = win._status_toggles.geometry()
        box = win._vcb_value.geometry()
        assert icons.left() >= box.right()                # box on their left…
        assert icons.left() - box.right() < 16            # …right beside them
        assert bar.width() - icons.right() < 30           # nothing after them
        win._vcb_value.hide()                             # Select: no box
        win._vcb_name.hide()
        _app.processEvents()
        assert bar.width() - win._status_toggles.geometry().right() < 30
    finally:
        win.close()
        win.deleteLater()
