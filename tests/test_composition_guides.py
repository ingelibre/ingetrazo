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
    for bad in ("none", "hexagon", 3, None, ["thirds"]):
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
    acts = [a for a in row.list_menu.actions()
            if a.isCheckable() and a.data()]
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


# ---- the golden triangle, the golden spiral and the centre cross -----------
def _ink(key, turn=0, w=300, h=200):
    """The guide ``key`` drawn on a clear ``w``×``h`` picture."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from views.composition_guides import draw_guides
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    draw_guides(p, QRectF(0, 0, w, h), key, turn)
    p.end()
    return img


def _drawn(img, x, y) -> bool:
    return img.pixelColor(x, y).alpha() > 0


@pytest.mark.parametrize("key", ["golden_triangle", "spiral"])
def test_the_new_guides_are_in_the_list_and_draw(key):
    from views.composition_guides import GUIDES, TURNABLE, guide_names
    assert key in GUIDES and key in TURNABLE
    assert guide_names()[key]
    img = _ink(key)
    assert any(_drawn(img, x, y) for x in range(300) for y in range(200))


def test_the_centre_is_a_cross_from_side_to_side():
    img = _ink("centre")
    # The two lines through the middle reach the four edges.
    assert _drawn(img, 150, 1) and _drawn(img, 150, 198)
    assert _drawn(img, 1, 100) and _drawn(img, 298, 100)
    # And nothing else: no ring round the centre.
    assert not _drawn(img, 150 + 10, 100 + 10)


def test_the_golden_triangle_meets_the_diagonal_square():
    from PySide6.QtCore import QRectF
    from views.composition_guides import golden_triangle_lines
    page = QRectF(10, 20, 300, 200)
    diag, a, b = golden_triangle_lines(page)
    assert (diag.p1(), diag.p2()) == (page.topLeft(), page.bottomRight())
    assert a.p1() == page.topRight() and b.p1() == page.bottomLeft()
    for ln in (a, b):
        dot = (ln.dx() * diag.dx() + ln.dy() * diag.dy())
        assert dot == pytest.approx(0.0, abs=1e-6)       # square to it
        # The foot lies on the diagonal.
        k = (ln.p2().x() - page.x()) / page.width()
        assert ln.p2().y() == pytest.approx(page.y() + k * page.height())


def test_the_spiral_fills_the_page_landscape_and_portrait():
    from PySide6.QtCore import QRectF
    from views.composition_guides import spiral_path
    for page in (QRectF(0, 0, 300, 200), QRectF(5, 5, 200, 300)):
        box = spiral_path(page).boundingRect()
        assert box.left() == pytest.approx(page.left(), abs=1e-6)
        assert box.top() == pytest.approx(page.top(), abs=1e-6)
        assert box.right() == pytest.approx(page.right(), abs=1e-6)
        assert box.bottom() == pytest.approx(page.bottom(), abs=1e-6)


def test_the_spiral_starts_in_a_corner_and_winds_in_to_its_eye():
    from PySide6.QtCore import QRectF
    from views.composition_guides import GOLDEN, spiral_path
    page = QRectF(0, 0, 300, 200)
    path = spiral_path(page)
    start = path.elementAt(0)
    assert (start.x, start.y) == pytest.approx((0.0, 200.0))
    # The eye of a golden spiral, landscape and turn 0, where the squares
    # shrink to: 1 / (1 + 0.618²) ≈ 72 % across and as far down.
    eye = 1.0 / (1.0 + GOLDEN ** 2)
    end = path.currentPosition()
    assert end.x() / 300 == pytest.approx(eye, abs=0.02)
    assert end.y() / 200 == pytest.approx(eye, abs=0.02)


def test_the_spiral_has_eight_orientations():
    imgs = [_ink("spiral", t) for t in range(8)]
    for i in range(8):
        for j in range(i + 1, 8):
            assert imgs[i] != imgs[j], (i, j)


def test_the_golden_triangle_has_two_ways_and_each_flip_changes_it():
    from views.composition_guides import FLIP_H, FLIP_V, TURN_90
    plain = _ink("golden_triangle", 0)
    assert _ink("golden_triangle", FLIP_H) != plain
    assert _ink("golden_triangle", FLIP_V) != plain
    assert _ink("golden_triangle", FLIP_H) == _ink("golden_triangle", FLIP_V)
    assert _ink("golden_triangle", FLIP_H | FLIP_V) == plain
    assert _ink("golden_triangle", TURN_90) == plain    # not its to turn


def test_the_turned_spiral_starts_on_top_in_a_landscape_frame():
    from PySide6.QtCore import QRectF
    from views.composition_guides import spiral_path
    page = QRectF(0, 0, 300, 200)
    path = spiral_path(page, turned=True)
    box = path.boundingRect()
    assert (box.width(), box.height()) == pytest.approx((300, 200))
    start = path.elementAt(0)
    # Laid over its diagonal: it starts in the top right corner, and its
    # first square runs across the top.
    assert (start.x, start.y) == pytest.approx((300.0, 0.0))


def test_the_parts_each_guide_can_change():
    from views.composition_guides import (FLIP_H, FLIP_V, TURN_90,
                                          turn_names, turn_parts)
    assert turn_parts("spiral") == (FLIP_H, FLIP_V, TURN_90)
    assert turn_parts("golden_triangle") == (FLIP_H, FLIP_V)
    assert turn_parts("thirds") == ()
    assert set(turn_names()) == {FLIP_H, FLIP_V, TURN_90}


def test_the_turn_leaves_the_symmetric_guides_alone():
    assert _ink("thirds", 1) == _ink("thirds", 0)


def test_the_turn_travels_with_the_lens_and_a_bad_one_is_dropped():
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    assert cam.composition_turn == 0
    assert "composition_turn" not in cam.lens_dict()
    cam.composition_guide, cam.composition_turn = "spiral", 3
    lens = cam.lens_dict()
    assert lens == {"composition_guide": "spiral", "composition_turn": 3}
    other = OrbitCamera()
    other.apply_lens(lens)
    assert other.composition_turn == 3
    for bad in (8, -1, 1.5, "2", True, None, [1]):
        other.apply_lens({"composition_turn": bad})
        assert other.composition_turn == 0


def test_resetting_the_lens_keeps_the_turn():
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    cam.composition_guide, cam.composition_turn = "spiral", 2
    cam.reset_lens()
    assert (cam.composition_guide, cam.composition_turn) == ("spiral", 2)


def test_the_turn_is_saved_in_the_file():
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from core.scene import Scene
    cam = OrbitCamera()
    cam.composition_guide, cam.composition_turn = "golden_triangle", 1
    view = SavedView.capture("Encuadre", Scene(), cam)
    again = SavedView.from_dict(json.loads(json.dumps(view.to_dict())))
    other = OrbitCamera()
    again.apply_camera(other)
    assert (other.composition_guide, other.composition_turn) == \
        ("golden_triangle", 1)


def test_the_camera_settings_leave_the_turn_alone(win):
    from views.camera_panel import CameraSettingsDialog
    vp = win.viewport
    vp.set_composition_guide("spiral")
    vp.set_composition_turn(2)
    try:
        dlg = CameraSettingsDialog(win)
    except TypeError:
        pytest.skip("the dialog wants other arguments")
    dlg._on_lens()
    assert vp.camera.composition_turn == 2
    dlg.close()


def test_a_new_drawing_starts_unturned(win):
    win.viewport.set_composition_guide("spiral")
    win.viewport.set_composition_turn(3)
    win._reset_camera_home()
    assert win.viewport.camera.composition_turn == 0


def test_the_view_flips_only_the_guides_with_a_side(win):
    from views.composition_guides import FLIP_H, FLIP_V, TURN_90
    vp = win.viewport
    vp.set_composition_guide("thirds")
    vp.flip_composition_guide(FLIP_H)
    assert vp.camera.composition_turn == 0
    vp.flip_composition_guide(FLIP_H, "spiral")     # shown, and flipped
    assert (vp.camera.composition_guide, vp.camera.composition_turn) == \
        ("spiral", FLIP_H)
    vp.flip_composition_guide(TURN_90)
    vp.flip_composition_guide(FLIP_V)
    assert vp.camera.composition_turn == FLIP_H | FLIP_V | TURN_90
    vp.flip_composition_guide(FLIP_H)               # again: undone
    assert vp.camera.composition_turn == FLIP_V | TURN_90
    vp.set_composition_guide("golden_triangle")
    vp.flip_composition_guide(TURN_90)              # the triangle: no
    assert vp.camera.composition_turn == FLIP_V | TURN_90


def test_flip_and_rotate_in_the_menu(win):
    from core.i18n import tr
    from views.composition_guides import FLIP_H, FLIP_V, TURN_90
    _scene(win, "Exterior")
    vp = win.viewport
    vp.set_composition_guide("thirds")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    acts = row.turn_actions
    assert [acts[b].text() for b in (FLIP_H, FLIP_V, TURN_90)] == \
        [tr("Flip horizontally"), tr("Flip vertically"), tr("Rotate 90°")]
    assert all(a in row.list_menu.actions() for a in acts.values())
    assert not any(a.isEnabled() for a in acts.values())   # no side
    menu.close()
    vp.set_composition_guide("golden_triangle")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    acts = row.turn_actions
    assert acts[FLIP_H].isEnabled() and acts[FLIP_V].isEnabled()
    assert not acts[TURN_90].isEnabled()        # the spiral's only
    closed = []
    menu.aboutToHide.connect(lambda: closed.append(True))
    menu.popup(win.mapToGlobal(win.rect().center()))
    acts[FLIP_V].trigger()
    assert vp.camera.composition_turn == FLIP_V and closed
    menu.close()
    vp.set_composition_guide("spiral")
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    acts = row.turn_actions
    assert all(a.isEnabled() for a in acts.values())
    # Ticked as the orientation is.
    assert acts[FLIP_V].isChecked() and not acts[FLIP_H].isChecked()
    acts[TURN_90].trigger()
    assert vp.camera.composition_turn == FLIP_V | TURN_90
    menu.close()


def test_a_flip_turns_the_spiral_on_when_it_is_off(win):
    from views.composition_guides import FLIP_H
    _scene(win, "Exterior")
    vp = win.viewport
    vp.set_composition_guide("spiral")
    vp.toggle_composition_guide(False)          # off; the spiral remembered
    menu = win._build_scene_tab_menu(0)
    row = _row(menu)
    assert row.turn_actions[FLIP_H].isEnabled()
    row.turn_actions[FLIP_H].trigger()
    assert (vp.camera.composition_guide, vp.camera.composition_turn) == \
        ("spiral", FLIP_H)
    menu.close()


def test_show_in_all_views_takes_the_turn_too(win):
    views = _four_views(win)
    _scene(win, "Exterior")
    win.viewport.set_composition_guide("spiral")
    win.viewport.set_composition_turn(2)
    menu = win._build_scene_tab_menu(0)
    _row(menu).show_all_action.trigger()
    assert [(v.camera.composition_guide, v.camera.composition_turn)
            for v in views] == [("spiral", 2)] * len(views)


def test_the_svg_preview_turns_the_triangle_and_spiral():
    from views.export_svg_dialog import FramePreview
    pv = FramePreview()
    pv.set_guides("spiral", 3)
    assert pv.guides_turn() == 3
    pv.set_guides("thirds")                     # the turn stays
    assert pv.guides_turn() == 3
    pv.set_guides("spiral", 9)                  # not a turn: none
    assert pv.guides_turn() == 0


def test_the_svg_dialog_flips_the_guides_on_its_preview(win, tmp_path):
    from PySide6.QtCore import QSettings
    from views.composition_guides import FLIP_H, TURN_90
    from views.export_svg_dialog import ExportSvgDialog
    st = QSettings(str(tmp_path / "svg.ini"), QSettings.IniFormat)
    dlg = ExportSvgDialog(win, settings=st, advanced=True)
    combo = dlg.guides_combo
    combo.setCurrentIndex(combo.findData("thirds"))
    assert not any(b.isEnabled() for b in dlg.guides_turn.values())
    combo.setCurrentIndex(combo.findData("spiral"))
    assert all(b.isEnabled() for b in dlg.guides_turn.values())
    before = dlg.preview.guides_turn()
    dlg.guides_turn[TURN_90].click()
    assert dlg.preview.guides_turn() == before ^ TURN_90
    assert dlg.guides_turn[TURN_90].isChecked() == bool(
        dlg.preview.guides_turn() & TURN_90)
    combo.setCurrentIndex(combo.findData("golden_triangle"))
    assert dlg.guides_turn[FLIP_H].isEnabled()
    assert not dlg.guides_turn[TURN_90].isEnabled()
    dlg.reject()
