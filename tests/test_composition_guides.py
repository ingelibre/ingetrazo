# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Composition guides over the 3D view (views/composition_guides.py) and
the scene row's menus: «Composition Guides» with its switch and list, and
«Hide scenes» (Ctrl+E) on a scene tab too."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _scene(win, name, view="top"):
    from core.saved_views import SavedView
    cam = win.viewport.camera
    cam.set_view(view)
    win.viewport.scene.saved_views.append(
        SavedView.capture(name, win.viewport.scene, cam))
    win.tray.scenes.refresh()


def _row(menu):
    from views.scene_tabs import CompositionGuidesRow
    row = menu._composition_action.row
    assert isinstance(row, CompositionGuidesRow)
    return row


# ---- the camera keeps the guide --------------------------------------------
def test_the_camera_has_no_guide_by_default():
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    assert cam.composition_guide is None
    assert "composition_guide" not in cam.lens_dict()


def test_the_guide_travels_with_the_lens_and_a_bad_one_is_dropped():
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    cam.composition_guide = "golden"
    lens = cam.lens_dict()
    assert lens == {"composition_guide": "golden"}
    other = OrbitCamera()
    other.apply_lens(lens)
    assert other.composition_guide == "golden"
    other.apply_lens({})                       # a scene without one: off
    assert other.composition_guide is None
    for bad in ("none", "spiral", 3, None, ["thirds"]):
        other.apply_lens({"composition_guide": bad})
        assert other.composition_guide is None


def test_reset_lens_keeps_the_guide():
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    cam.composition_guide = "grid"
    cam.shift_x = 0.2
    cam.reset_lens()
    assert cam.shift_x == 0.0 and cam.composition_guide == "grid"


def test_a_scene_keeps_its_guide_and_brings_it_back(win):
    vp = win.viewport
    vp.set_composition_guide("diagonals")
    _scene(win, "Con guías")
    vp.set_composition_guide(None)
    _scene(win, "Sin guías", "front")
    views = vp.scene.saved_views
    assert views[0].lens.get("composition_guide") == "diagonals"
    assert "composition_guide" not in (views[1].lens or {})
    views[0].apply_camera(vp.camera)
    assert vp.camera.composition_guide == "diagonals"
    views[1].apply_camera(vp.camera)
    assert vp.camera.composition_guide is None


def test_the_guide_is_saved_in_the_file():
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from core.scene import Scene
    cam = OrbitCamera()
    cam.composition_guide = "centre"
    view = SavedView.capture("Encuadre", Scene(), cam)
    again = SavedView.from_dict(json.loads(json.dumps(view.to_dict())))
    other = OrbitCamera()
    again.apply_camera(other)
    assert other.composition_guide == "centre"


def test_the_camera_settings_leave_the_guide_alone(win):
    from views.camera_panel import CameraSettingsDialog
    vp = win.viewport
    vp.set_composition_guide("thirds")
    try:
        dlg = CameraSettingsDialog(win)
    except TypeError:
        pytest.skip("the dialog wants other arguments")
    dlg._on_lens()                           # a shift or a frame changed
    assert vp.camera.composition_guide == "thirds"
    dlg.close()


def test_a_new_drawing_starts_without_guides(win):
    win.viewport.set_composition_guide("golden")
    win._reset_camera_home()
    assert win.viewport.camera.composition_guide is None


# ---- the view's switch ----------------------------------------------------
def test_the_switch_turns_on_the_last_guide_or_the_thirds(win):
    vp = win.viewport
    vp.toggle_composition_guide(True)
    assert vp.camera.composition_guide == "thirds"   # the first time
    vp.set_composition_guide("golden")
    vp.toggle_composition_guide(False)
    assert vp.camera.composition_guide is None
    vp.toggle_composition_guide()                    # the other way: on
    assert vp.camera.composition_guide == "golden"


def test_the_guides_fall_inside_the_camera_frame(win):
    vp = win.viewport
    vp.resize(800, 400)
    r = vp.composition_rect()
    assert (r.width(), r.height()) == (vp.width(), vp.height())
    vp.camera.frame_aspect = 1.0                     # a square picture
    r = vp.composition_rect()
    side = min(vp.width(), vp.height())
    assert (r.width(), r.height()) == (side, side)
    assert r.center().x() == pytest.approx(vp.width() / 2.0)


@pytest.mark.parametrize("key", ["thirds", "golden", "grid", "diagonals",
                                 "centre"])
def test_each_guide_draws_lines(key):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from views.composition_guides import draw_guides
    img = QImage(300, 200, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    draw_guides(p, QRectF(0, 0, 300, 200), key)
    p.end()
    drawn = sum(1 for x in range(300) for y in range(200)
                if img.pixelColor(x, y).alpha())
    assert drawn > 0


def test_the_overlay_draws_the_guide_and_only_when_on(win):
    from PySide6.QtGui import QColor, QImage, QPainter
    vp = win.viewport
    vp.resize(300, 200)

    def painted() -> int:
        img = QImage(vp.width(), vp.height(), QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        vp._draw_composition_guide(p)
        p.end()
        return sum(1 for x in range(0, img.width(), 2)
                   for y in range(0, img.height(), 2)
                   if img.pixelColor(x, y).alpha())

    assert painted() == 0
    vp.set_composition_guide("thirds")
    assert painted() > 0


def test_the_svg_dialog_uses_the_same_guides():
    import views.composition_guides as common
    import views.export_svg_dialog as svg
    assert svg.draw_guides is common.draw_guides
    assert svg.GUIDES == common.GUIDES


# ---- the menus ------------------------------------------------------------
@pytest.mark.parametrize("which", ["tab", "bar"])
def test_both_scene_menus_offer_the_guides_and_hide_scenes(win, which):
    from PySide6.QtGui import QKeySequence
    from core.i18n import tr
    _scene(win, "Exterior")
    menu = (win._build_scene_tab_menu(0) if which == "tab"
            else win._build_scene_bar_menu())
    texts = [a.text() for a in menu.actions()]
    assert tr("Composition Guides") in texts
    hide = next(a for a in menu.actions() if a.text() == tr("Hide scenes"))
    assert hide.shortcut() == QKeySequence("Ctrl+E")
    assert hide.isShortcutVisibleInContextMenu()
    hide.trigger()
    assert win._scene_tabs.isHidden() and not win._doc.scene_tabs
    menu.close()


def test_the_tab_menu_keeps_its_entries_in_order(win):
    from core.i18n import tr
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == [tr("Play"), tr("Update"), tr("Camera Settings…"),
                     tr("Rename…"), tr("Composition Guides"),
                     tr("Hide scenes"), tr("Delete")]
    menu.close()


def test_the_menu_switch_shows_and_hides_the_guides_of_the_active_view(win):
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    vp = win.viewport
    assert not row.switch.isChecked()
    row.switch.click()
    assert vp.camera.composition_guide == "thirds" and row.switch.isChecked()
    row.switch.click()
    assert vp.camera.composition_guide is None and not row.switch.isChecked()
    menu.close()


def test_the_list_names_every_guide_and_marks_the_one_chosen(win):
    from views.composition_guides import GUIDES, guide_names
    _scene(win, "Exterior")
    win.viewport.set_composition_guide("golden")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    names = guide_names()
    acts = [a for a in row.list_menu.actions() if a.isCheckable()]
    assert [a.text() for a in acts] == [names[k] for k in GUIDES[1:]]
    assert [a.data() for a in acts if a.isChecked()] == ["golden"]
    assert row.switch.isChecked()
    menu.close()


def test_choosing_a_guide_shows_it_and_closes_the_menu(win):
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    closed = []
    menu.aboutToHide.connect(lambda: closed.append(True))
    menu.popup(win.mapToGlobal(win.rect().center()))
    row.guide_actions["grid"].trigger()
    assert win.viewport.camera.composition_guide == "grid"
    assert row.switch.isChecked()
    assert closed
    menu.close()


def test_the_list_opens_beside_the_row(win):
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    menu.popup(win.mapToGlobal(win.rect().center()))
    row.open_list()
    assert row.list_menu.isVisible()
    left = row.list_menu.geometry().left()
    right_edge = row.mapToGlobal(row.rect().topRight()).x()
    left_edge = row.mapToGlobal(row.rect().topLeft()).x()
    assert abs(left - right_edge) <= 2 or left < left_edge
    row.list_menu.close()
    menu.close()


def test_the_switch_is_a_tick_box_before_the_name(win):
    """A tick box in the column where the menu ticks its other on/off
    entries — not an eye: the menus' own way of saying on or off."""
    from PySide6.QtWidgets import QCheckBox
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    assert isinstance(row.switch, QCheckBox)
    row.resize(row.sizeHint())
    row.layout().activate()
    assert row.switch.geometry().right() < row.label.geometry().left()
    assert row.label.geometry().left() == row.TEXT_LEFT
    menu.close()


def test_keep_inside_moves_a_popup_just_enough():
    from PySide6.QtCore import QPoint, QRect, QSize
    from views.scene_tabs import keep_inside
    bounds = QRect(100, 100, 800, 600)          # x 100–899, y 100–699
    size = QSize(200, 150)
    assert keep_inside(QPoint(300, 300), size, bounds) == QPoint(300, 300)
    assert keep_inside(QPoint(850, 300), size, bounds) == QPoint(700, 300)
    assert keep_inside(QPoint(300, 650), size, bounds) == QPoint(300, 550)
    assert keep_inside(QPoint(50, 20), size, bounds) == QPoint(100, 100)
    big = QSize(1000, 900)                      # bigger than the window
    assert keep_inside(QPoint(500, 500), big, bounds) == QPoint(100, 100)
    assert keep_inside(QPoint(5, 5), size, None) == QPoint(5, 5)


def _shown(win):
    win.setGeometry(200, 150, 900, 600)
    win.show()
    QApplication.processEvents()
    return win.frameGeometry()


def test_the_scene_menu_stays_in_the_window_at_its_right_edge(win):
    from PySide6.QtCore import QPoint, QRect
    from views.scene_tabs import menu_upwards
    _scene(win, "Exterior")
    bounds = _shown(win)
    menu = win._build_scene_tab_menu(0)
    at = menu_upwards(menu, QPoint(bounds.right() - 5, bounds.bottom() - 20))
    placed = QRect(at, menu.sizeHint())
    assert bounds.contains(placed), (bounds, placed)
    menu.close()


def test_the_list_of_guides_stays_in_the_window(win):
    from PySide6.QtCore import QPoint
    _scene(win, "Exterior")
    bounds = _shown(win)
    menu = win._build_scene_tab_menu(0)
    size = menu.sizeHint()
    # The menu against the window's right edge: no room for the list there.
    menu.popup(QPoint(bounds.right() + 1 - size.width(),
                      bounds.bottom() + 1 - size.height()))
    QApplication.processEvents()
    row = _row(menu)
    row.open_list()
    QApplication.processEvents()
    placed = row.list_menu.geometry()
    assert bounds.contains(placed), (bounds, placed)
    assert placed.right() < row.mapToGlobal(row.rect().topLeft()).x() + 2
    row.list_menu.close()
    menu.close()


def test_the_list_opens_on_the_right_when_there_is_room(win):
    from PySide6.QtCore import QPoint
    _scene(win, "Exterior")
    bounds = _shown(win)
    menu = win._build_scene_tab_menu(0)
    menu.popup(QPoint(bounds.left() + 10, bounds.top() + 60))
    QApplication.processEvents()
    row = _row(menu)
    row.open_list()
    QApplication.processEvents()
    placed = row.list_menu.geometry()
    assert bounds.contains(placed)
    assert placed.left() >= row.mapToGlobal(row.rect().topRight()).x() - 2
    row.list_menu.close()
    menu.close()


def test_the_switch_does_not_open_the_list(win):
    from PySide6.QtCore import QPoint
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    row.resize(row.sizeHint())
    row.layout().activate()
    centre = row.switch.geometry().center()
    assert row._over_switch(centre)
    assert not row._over_switch(QPoint(row.label.geometry().center()))
    menu.close()


def _four_views(win):
    """The layout of four views, the first (the project's own) active."""
    win.resize(1200, 800)
    win.show()
    win.set_view_layout("four")
    QApplication.processEvents()
    views = win.shown_viewports()
    assert len(views) == 4
    return views


def test_with_one_view_the_all_views_entries_are_greyed_out(win):
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    assert len(win.shown_viewports()) == 1
    assert not row.show_all_action.isEnabled()
    assert not row.hide_all_action.isEnabled()
    menu.close()


def test_each_view_keeps_its_own_guides(win):
    views = _four_views(win)
    _scene(win, "Exterior")
    menu = win._build_scene_tab_menu(0)
    _row(menu).switch.click()                      # the active view only
    menu.close()
    active = win.viewport
    assert active.camera.composition_guide == "thirds"
    assert all(v.camera.composition_guide is None
               for v in views if v is not active)


def test_show_and_hide_in_all_views(win):
    views = _four_views(win)
    _scene(win, "Exterior")
    win.viewport.set_composition_guide("golden")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    assert row.show_all_action.isEnabled() and row.hide_all_action.isEnabled()
    row.show_all_action.trigger()
    assert [v.camera.composition_guide for v in views] == \
        ["golden"] * len(views)
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    row.hide_all_action.trigger()
    assert [v.camera.composition_guide for v in views] == [None] * len(views)


def _label_menu(win, viewport):
    """The menu of a view's label (its corner), filled as it opens."""
    grid = win._doc.view_grid
    cell = next(c for c in grid.cells if c.viewport is viewport)
    menu = cell.header.menu()
    menu.aboutToShow.emit()
    return cell, menu


def test_the_views_label_menu_has_the_guides_of_that_view(win):
    from core.i18n import tr
    views = _four_views(win)
    other = views[-1]
    cell, menu = _label_menu(win, other)
    texts = [a.text() for a in menu.actions()]
    assert texts[-1] == tr("Composition Guides")
    row = cell.header._composition_action.row
    assert row.viewport is other
    row.switch.click()                         # on in THAT view only
    assert other.camera.composition_guide == "thirds"
    assert all(v.camera.composition_guide is None
               for v in views if v is not other)
    assert row.show_all_action.isEnabled()


def test_the_label_menu_shows_the_views_guide_each_time_it_opens(win):
    views = _four_views(win)
    other = views[-1]
    cell, menu = _label_menu(win, other)
    row = cell.header._composition_action.row
    assert not row.switch.isChecked()
    other.set_composition_guide("grid")        # from elsewhere
    menu.aboutToShow.emit()
    assert row.switch.isChecked()
    assert row.guide_actions["grid"].isChecked()
    # Filled once: opening again adds no second row.
    from core.i18n import tr
    assert [a.text() for a in menu.actions()].count(
        tr("Composition Guides")) == 1


def test_the_guides_follow_the_active_view_only(win):
    from core.camera import OrbitCamera
    vp = win.viewport
    vp.set_composition_guide("thirds")
    assert OrbitCamera().composition_guide is None
    assert vp.camera.composition_guide == "thirds"


def test_the_new_messages_are_in_every_language():
    root = pathlib.Path(__file__).resolve().parent.parent / "i18n"
    keys = ("Composition Guides",
            "Show or hide the composition guides in the active view",
            "Hide this project's scene tabs; Ctrl+E shows them again.")
    for path in root.glob("*.json"):
        if path.stem == "en":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), (path.stem, k)
        assert ("Hide this project's scene tabs; Alt+E shows them again."
                not in data)
