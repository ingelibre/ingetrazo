# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Camera from Photo in the window: the photo scene, its lines
dragged with the mouse, the camera locked to the photo until it moves, one
undo step, and the photo kept inside the document."""
from __future__ import annotations

import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import core.extensions as extensions  # noqa: E402
from core import photo_match as PM  # noqa: E402

PHOTO_COLOUR = (200, 30, 180)


def make_photo(path, w=600, h=400, focal_35=None, orientation=1):
    """A flat-coloured JPEG, with an EXIF block when asked."""
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(*PHOTO_COLOUR))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPG", 95)
    data = bytes(ba)
    if focal_35 is not None or orientation != 1:
        entries = [(0x0112, 3, 1, struct.pack("<H", orientation) + b"\0\0")]
        n0 = len(entries) + (1 if focal_35 else 0)
        exif_at = 8 + 2 + 12 * n0 + 4
        tiff = b"II" + struct.pack("<HI", 42, 8) + struct.pack("<H", n0)
        for tag, typ, count, val in entries:
            tiff += struct.pack("<HHI", tag, typ, count) + val
        if focal_35:
            tiff += struct.pack("<HHII", 0x8769, 4, 1, exif_at)
        tiff += struct.pack("<I", 0)
        if focal_35:
            tiff += struct.pack("<H", 1)
            tiff += struct.pack("<HHI", 0xA405, 3, 1)
            tiff += struct.pack("<H", focal_35) + b"\0\0"
            tiff += struct.pack("<I", 0)
        app1 = b"Exif\0\0" + tiff
        data = (data[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2)
                + app1 + data[2:])
    path.write_bytes(data)
    return path


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _send(vp, kind, pos, buttons=Qt.LeftButton):
    button = Qt.LeftButton if kind != QMouseEvent.MouseMove else Qt.NoButton
    ev = QMouseEvent(kind, QPointF(pos), vp.mapToGlobal(QPointF(pos)),
                     button, buttons, Qt.NoModifier)
    QApplication.sendEvent(vp, ev)


def _drag(vp, a, b, steps=5):
    _send(vp, QMouseEvent.MouseButtonPress, a)
    for k in range(1, steps + 1):
        t = k / steps
        _send(vp, QMouseEvent.MouseMove,
              QPointF(a.x() + (b.x() - a.x()) * t,
                      a.y() + (b.y() - a.y()) * t))
    _send(vp, QMouseEvent.MouseButtonRelease, b, Qt.NoButton)


def test_a_photo_becomes_a_scene_with_the_photo_behind(win, tmp_path):
    from tools.photo_match import PhotoMatchTool
    vp = win.viewport
    before = len(vp.scene.saved_views)
    view = win.start_camera_from_photo(str(make_photo(tmp_path /
                                                      "esquina.jpg")))
    assert view is not None and view.name == "esquina"
    assert len(vp.scene.saved_views) == before + 1
    assert view.photo.aspect == pytest.approx(1.5)
    assert vp.photo_view is view
    assert isinstance(vp.active_tool, PhotoMatchTool)
    assert vp.camera.frame_aspect == pytest.approx(1.5)
    # The camera is the one the default lines give.
    sol = PM.solve(view.photo)
    want = PM.view_fov_deg(sol, 1.5, vp.width(), vp.height())
    assert vp.camera.fov_deg == pytest.approx(want)
    # The scene keeps that camera, for its thumbnail and the sheets.
    assert view.fov_deg == pytest.approx(want)


def test_dragging_a_line_end_moves_the_camera(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    start = tool.to_screen(vp, view.photo.x_lines[0][1])
    fov0 = vp.camera.fov_deg
    _drag(vp, start, QPointF(start.x() + 25, start.y() + 12))
    assert view.photo.x_lines[0][1] != list(PM.DEFAULT_X_LINES[0][1])
    end = tool.to_screen(vp, view.photo.x_lines[0][1])
    assert end.x() == pytest.approx(start.x() + 25, abs=0.5)
    assert vp.camera.fov_deg != pytest.approx(fov0)
    # Still on the photo: the camera moved because the lines did.
    vp._check_photo()
    assert vp.photo_view is view


def test_dragging_a_line_by_its_middle_moves_both_ends(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    a0, b0 = [list(p) for p in view.photo.y_lines[1]]
    pa, pb = tool.to_screen(vp, a0), tool.to_screen(vp, b0)
    mid = QPointF((pa.x() + pb.x()) / 2, (pa.y() + pb.y()) / 2)
    _drag(vp, mid, QPointF(mid.x(), mid.y() + 20))
    a1, b1 = view.photo.y_lines[1]
    dv = 20 / tool._frame(vp)[3]
    assert a1[1] - a0[1] == pytest.approx(dv, abs=1e-3)
    assert b1[1] - b0[1] == pytest.approx(dv, abs=1e-3)


def test_the_blue_handle_stays_on_the_blue_axis(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    s = tool.to_screen(vp, view.photo.scale_point)
    _drag(vp, s, QPointF(s.x() + 40, s.y() - 30))       # off to the side
    pm = view.photo
    sol = PM.solve(pm)
    o = pm.to_image(pm.origin)
    p = pm.to_image(pm.scale_point)
    d = sol.axis_image_direction(o, (0, 0, 1))
    across = (p[0] - o[0]) * d[1] - (p[1] - o[1]) * d[0]
    assert across == pytest.approx(0.0, abs=1e-6)


def test_typing_a_length_sets_the_scale(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    eye0 = PM.solve(view.photo).eye
    assert vp.active_tool.on_value(vp, 6.0)
    assert view.photo.scale_length == 6.0
    eye1 = PM.solve(view.photo).eye
    assert eye1 == pytest.approx(tuple(2 * c for c in eye0))


def test_enter_keeps_the_lines_as_one_undo_step(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    before = view.photo.to_dict()
    h = tool.to_screen(vp, view.photo.origin)
    _drag(vp, h, QPointF(h.x() - 30, h.y() + 10))
    moved = view.photo.to_dict()
    assert moved != before
    steps = len(vp.history.undo_stack)
    assert tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    assert len(vp.history.undo_stack) == steps + 1
    assert vp.active_tool is win._tools["select"]
    # The photo stays behind the model, for tracing.
    assert vp.photo_view is view
    vp.history.undo()
    assert view.photo.to_dict() == before
    vp.history.redo()
    assert view.photo.to_dict() == moved


def test_esc_puts_the_lines_back(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    before = view.photo.to_dict()
    fov = vp.camera.fov_deg
    h = tool.to_screen(vp, view.photo.x_lines[1][0])
    _drag(vp, h, QPointF(h.x() + 30, h.y() + 30))
    steps = len(vp.history.undo_stack)
    tool.on_cancel(vp)
    assert view.photo.to_dict() == before
    assert vp.camera.fov_deg == pytest.approx(fov)
    assert len(vp.history.undo_stack) == steps
    assert vp.active_tool is win._tools["select"]


def test_orbiting_leaves_the_photo(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    vp.camera.orbit(30, 0, vp.height())
    vp._check_photo()
    assert vp.photo_view is None
    # The frame the photo put on the camera comes off with it.
    assert vp.camera.frame_aspect is None
    # Showing the scene again brings the photo and its camera back.
    win.tray.scenes.show_view(view, animate=False)
    assert vp.photo_view is view
    assert vp.camera.frame_aspect == pytest.approx(1.5)


def test_orbiting_while_laying_the_lines_keeps_them(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    h = tool.to_screen(vp, view.photo.origin)
    _drag(vp, h, QPointF(h.x() + 15, h.y()))
    moved = view.photo.to_dict()
    vp.camera.orbit(30, 0, vp.height())
    vp._check_photo()
    assert tool.done
    assert view.photo.to_dict() == moved
    assert vp.active_tool is win._tools["select"]


def test_another_scene_takes_the_photo_away(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    from core.saved_views import SavedView
    from core.history import AddSceneCommand
    other = SavedView("Plain", target=(0, 0, 0), distance=30.0)
    vp.history.execute(AddSceneCommand(other))
    win.tray.scenes.show_view(other, animate=False)
    assert vp.photo_view is None
    assert vp.camera.distance == pytest.approx(30.0)
    win.tray.scenes.show_view(view, animate=False)
    assert vp.photo_view is view


def test_edit_photo_lines_takes_up_the_shown_photo(win, tmp_path):
    from tools.photo_match import PhotoMatchTool
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    tool = win.edit_photo_lines()
    assert isinstance(tool, PhotoMatchTool) and tool.view is view
    tool.on_cancel(vp)
    # No photo scene in sight or selected: it says so.
    vp.leave_photo()
    vp.scene.saved_views.remove(view)
    assert win.edit_photo_lines() is None


def test_the_photo_travels_inside_the_document(win, tmp_path):
    from core.scene import Scene
    from formats import igz
    vp = win.viewport
    src = make_photo(tmp_path / "fachada.jpg", focal_35=28)
    view = win.start_camera_from_photo(str(src))
    tool = vp.active_tool
    h = tool.to_screen(vp, view.photo.y_lines[0][0])
    _drag(vp, h, QPointF(h.x() - 10, h.y() + 5))
    tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    doc = tmp_path / "modelo.igz"
    igz.save_scene(vp.scene, doc)
    import zipfile
    assert zipfile.is_zipfile(doc)
    with zipfile.ZipFile(doc) as z:
        assert any(n.startswith("textures/") and n.endswith("fachada.jpg")
                   for n in z.namelist())
    out = Scene()
    igz.load_into(out, doc)
    back = [v for v in out.saved_views if v.name == "fachada"][0]
    assert back.photo is not None
    assert os.path.isfile(back.photo.path)
    mine = view.photo.to_dict()
    theirs = back.photo.to_dict()
    mine.pop("texture")
    theirs.pop("texture")
    assert theirs == mine
    assert back.photo.exif_focal_35 == 28.0


def test_the_exif_focal_length_is_shown_and_can_be_kept(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg",
                                                      focal_35=50)))
    tool = vp.active_tool
    texts = [t for t, _w in tool.info_lines(tool.result)]
    assert any("50 mm" in t for t in texts)
    assert tool.on_key(vp, Qt.Key_F, Qt.NoModifier)
    assert view.photo.use_exif_focal
    sol = tool.result
    assert PM.focal_35mm(sol.focal, view.photo.aspect) == pytest.approx(50.0)
    assert "F" in tool.status_clause()


def test_a_photo_on_its_side_is_stood_upright(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(
        tmp_path / "retrato.jpg", 600, 400, orientation=6)))
    assert (view.photo.width_px, view.photo.height_px) == (400, 600)
    img = QImage(view.photo.path)
    assert (img.width(), img.height()) == (400, 600)


def test_a_file_that_is_no_photo_is_refused(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    said = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: said.append(a))
    bad = tmp_path / "nota.jpg"
    bad.write_text("not a photo")
    n = len(win.viewport.scene.saved_views)
    assert win.start_camera_from_photo(str(bad)) is None
    assert said and len(win.viewport.scene.saved_views) == n


def test_the_status_bar_says_what_to_do(win, tmp_path):
    win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    bar = win.statusBar()
    text = getattr(bar, "_base", "") or bar.currentMessage()
    assert "Enter" in text


def test_the_photo_is_drawn_behind_the_model(win, tmp_path):
    """The picture of the view, with nothing in the model: the photo's
    colour fills the frame."""
    vp = win.viewport
    win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    vp.repaint()
    QApplication.processEvents()
    assert vp.photo_view is not None
    img = vp.render_image(600, overlays=False)
    if img is None:
        pytest.skip("no OpenGL in this session")
    from core.camera import frame_rect
    x, y, w, h = frame_rect(img.width(), img.height(), 1.5)
    # A spot away from the axes drawn over the photo.
    c = img.pixelColor(int(x + w * 0.1), int(y + h * 0.1))
    assert (abs(c.red() - PHOTO_COLOUR[0]) < 25
            and abs(c.green() - PHOTO_COLOUR[1]) < 25
            and abs(c.blue() - PHOTO_COLOUR[2]) < 25), c.getRgb()


def test_a_look_at_the_lines_changes_nothing(win, tmp_path):
    """Edit Photo Lines, then Enter without moving any: no undo step, the
    document is not marked changed."""
    vp = win.viewport
    win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    steps = len(vp.history.undo_stack)
    version = vp.scene.version
    tool = win.edit_photo_lines()
    tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    assert len(vp.history.undo_stack) == steps
    assert vp.scene.version == version


# ---- Menus and the panel ------------------------------------------------------
def _titles(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_the_camera_menu_holds_the_photo_submenu(win, tmp_path):
    menu = win._photo_menu
    assert [a.objectName() for a in menu.actions()] == [
        "camera_from_photo", "edit_photo_lines", "reset_photo_lines"]
    win._sync_photo_menu()
    assert not win._act_edit_photo_lines.isEnabled()      # no photo yet
    win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    win._sync_photo_menu()
    assert win._act_edit_photo_lines.isEnabled()
    assert win._act_reset_photo_lines.isEnabled()


def test_reset_photo_lines_from_the_menu(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    h = tool.to_screen(vp, view.photo.origin)
    _drag(vp, h, QPointF(h.x() + 40, h.y()))
    tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    assert view.photo.origin != list(PM.DEFAULT_ORIGIN)
    tool = win.reset_photo_lines()
    assert tool is vp.active_tool
    assert view.photo.origin == list(PM.DEFAULT_ORIGIN)


def test_the_right_click_menu_does_what_the_keys_do(win, tmp_path):
    from PySide6.QtWidgets import QMenu
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg",
                                                      focal_35=35)))
    tool = vp.active_tool
    menu = QMenu()
    tool.fill_menu(menu, vp)
    titles = _titles(menu)
    for want in ("Done", "Cancel", "Reset lines", "Swap red and green",
                 "Use the photo's focal length", "Show model",
                 "Photo in front of the model", "Grid"):
        assert want in titles
    acts = {a.text(): a for a in menu.actions()}
    x0 = [list(p) for p in view.photo.x_lines[0]]
    acts["Swap red and green"].trigger()
    assert view.photo.y_lines[0] == x0
    acts["Use the photo's focal length"].setChecked(True)
    assert view.photo.use_exif_focal
    assert acts["Photo in front of the model"].isChecked()   # the default
    acts["Photo in front of the model"].setChecked(False)
    assert not view.photo.photo_front
    acts["Photo in front of the model"].setChecked(True)
    assert view.photo.photo_front
    grid = acts["Grid"].menu()
    grid.actions()[0].setChecked(True)
    assert "xy" in type(tool).grid_planes
    grid.actions()[0].setChecked(False)
    inside = acts["Reset lines"].menu().actions()[1]
    inside.trigger()
    assert view.photo.origin == list(PM.PRESETS["inside"][2])
    acts["Done"].trigger()
    assert tool.done and vp.active_tool is win._tools["select"]


def test_the_other_side_is_one_click_from_the_menu(win, tmp_path):
    from PySide6.QtWidgets import QMenu
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    tool = vp.active_tool
    menu = QMenu()
    tool.fill_menu(menu, vp)
    acts = {a.text(): a for a in menu.actions()}
    assert "Show the other side" in acts
    before = tool.result.eye
    acts["Show the other side"].setChecked(True)
    assert view.photo.flip_sides
    assert tool.result.eye == pytest.approx((-before[0], -before[1],
                                             before[2]), abs=1e-6)
    acts["Show the other side"].setChecked(False)
    assert not view.photo.flip_sides
    assert tool.result.eye == pytest.approx(before, abs=1e-6)


def test_a_photo_scene_tab_offers_its_lines(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    from core.history import AddSceneCommand
    from core.saved_views import SavedView
    vp.history.execute(AddSceneCommand(SavedView("Plain")))
    win._refresh_scene_tabs()
    QApplication.processEvents()
    views = win._scene_tabs.tabs.views
    photo_menu = win._build_scene_tab_menu(views.index(view))
    plain_menu = win._build_scene_tab_menu(
        [i for i, v in enumerate(views) if v.name == "Plain"][0])
    assert "Edit Photo Lines" in _titles(photo_menu)
    assert "Edit Photo Lines" not in _titles(plain_menu)
    act = [a for a in photo_menu.actions()
           if a.text() == "Edit Photo Lines"][0]
    act.trigger()
    assert vp.active_tool.view is view


def test_the_scenes_list_offers_the_lines_of_a_photo_scene(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    panel = win.tray.scenes
    panel.refresh()
    panel.select_view(view)
    item = panel.tree.currentItem()
    assert item is not None
    assert "Edit Photo Lines" in _titles(panel.context_menu(item))


def _tab_shown(win):
    dock = win.photo_dock()
    return (not dock.isHidden() and dock in win._sidebar_docks()
            and not dock.visibleRegion().isEmpty())


def test_the_panel_is_a_tab_of_the_tray_while_editing(win, tmp_path):
    """A tab among the side tray's, in front while the lines are laid,
    gone when that ends — and the tab that was in front comes back."""
    vp = win.viewport
    win.tray.show()
    win.tray.raise_()
    QApplication.processEvents()
    win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    QApplication.processEvents()
    dock = win.photo_dock()
    panel = win.photo_panel()
    assert _tab_shown(win) and panel.tool is vp.active_tool
    assert dock in win.tabifiedDockWidgets(win.tray)
    assert win.dockWidgetArea(dock) == win.dockWidgetArea(win.tray)
    assert dock.windowTitle() == "Camera from Photo"
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    QApplication.processEvents()
    assert dock.isHidden() and panel.tool is None
    assert dock not in win._sidebar_docks()       # never kept as a tray
    assert not win.tray.visibleRegion().isEmpty()  # Properties back
    tool = win.edit_photo_lines()
    QApplication.processEvents()
    assert _tab_shown(win)
    vp.camera.orbit(30, 0, vp.height())        # an orbit ends it too
    vp._check_photo()
    assert tool.done and dock.isHidden()


def test_the_panel_tab_is_not_listed_once_gone(win, tmp_path):
    """Window ▸ Panels lists it only while it is there, and Qt's own
    panel list never does."""
    from PySide6.QtWidgets import QMenu
    vp = win.viewport
    win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    menu = QMenu()
    win._fill_panels_menu(menu)
    assert "Camera from Photo" in _titles(menu)
    assert not win.photo_dock().toggleViewAction().isVisible()
    vp.active_tool.on_key(vp, Qt.Key_Return, Qt.NoModifier)
    win._fill_panels_menu(menu)
    assert "Camera from Photo" not in _titles(menu)


def test_a_button_of_the_panel_gives_the_keys_back_to_the_model(
        win, tmp_path):
    vp = win.viewport
    win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    panel = win.photo_panel()
    panel.swap.setFocus()
    panel.swap.click()
    QApplication.processEvents()
    assert vp.hasFocus() or QApplication.focusWidget() is vp


def test_the_panel_drives_the_tool(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg",
                                                      focal_35=28)))
    panel = win.photo_panel()
    pm = view.photo
    assert "28 mm" in panel.info.text()
    # Blue length typed in the field.
    panel.length.setText("6")
    panel._on_length()
    assert pm.scale_length == pytest.approx(6.0)
    # Nonsense keeps the value and puts it back in the field.
    panel.length.setText("abc")
    panel._on_length()
    assert pm.scale_length == pytest.approx(6.0)
    assert "6" in panel.length.text()
    panel.exif.setChecked(True)
    assert pm.use_exif_focal
    panel.start.setCurrentIndex(2)             # seen from above
    panel.reset.click()
    assert pm.origin == list(PM.PRESETS["above"][2])
    lines = [list(p) for p in pm.x_lines[0]]
    panel.swap.click()
    assert pm.y_lines[0] == lines
    assert panel.front.isChecked()             # in front by default
    panel.front.setChecked(False)
    assert not pm.photo_front and not panel.opacity.isEnabled()
    panel.front.setChecked(True)
    assert pm.photo_front and panel.opacity.isEnabled()
    panel.opacity.setValue(30)
    assert pm.photo_opacity == pytest.approx(0.3)
    panel.model.setChecked(False)
    assert not pm.show_model and not panel.front.isEnabled()
    panel.planes["xz"].setChecked(True)
    from tools.photo_match import PhotoMatchTool
    assert "xz" in PhotoMatchTool.grid_planes
    panel.spacing.setText("0,5")
    panel._on_spacing()
    assert PhotoMatchTool.grid_spacing == pytest.approx(0.5)
    panel.planes["xz"].setChecked(False)
    PhotoMatchTool.grid_spacing = 1.0
    steps = len(vp.history.undo_stack)
    panel.done.click()
    assert len(vp.history.undo_stack) == steps + 1
    assert win.photo_dock().isHidden()


def test_the_panel_cancel_puts_everything_back(win, tmp_path):
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    panel = win.photo_panel()
    before = view.photo.to_dict()
    panel.front.setChecked(False)
    panel.swap.click()
    panel.cancel.click()
    assert view.photo.to_dict() == before
    assert win.photo_dock().isHidden()


def test_the_photo_in_front_is_painted_over_the_model(win, tmp_path):
    from PySide6.QtGui import QPainter
    from core.camera import frame_rect
    vp = win.viewport
    view = win.start_camera_from_photo(str(make_photo(tmp_path / "a.jpg")))
    pm = view.photo

    def painted():
        img = QImage(vp.width(), vp.height(), QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0))
        p = QPainter(img)
        vp._draw_photo_in_front(p)
        p.end()
        x, y, w, h = frame_rect(vp.width(), vp.height(), pm.aspect)
        return img.pixelColor(int(x + w / 2), int(y + h / 2))
    assert 70 < painted().red() < 130          # in front by default, half
    pm.photo_front = False
    assert painted().red() == 0                # behind only: nothing over
    pm.show_model = False
    c = painted()
    assert abs(c.red() - PHOTO_COLOUR[0]) < 25
    pm.show_model = True
    pm.photo_front = True
    pm.photo_opacity = 0.5
    assert 70 < painted().red() < 130          # half over black


# ---- The toolbar ---------------------------------------------------------------
def test_the_photo_toolbar_starts_shown_and_is_offered(win):
    """Camera from Photo as a toolbar of its own: shown on a fresh start,
    listed with the others on the toolbars' right-click menu to hide."""
    from PySide6.QtWidgets import QToolBar
    tb = win.findChild(QToolBar, "photo_match_toolbar")
    assert tb is not None and tb is win._photo_toolbar
    assert not tb.isHidden()
    tb.hide()
    assert tb.windowTitle() == "Camera from Photo"
    assert [a.objectName() for a in tb.actions()] == [
        "camera_from_photo", "edit_photo_lines", "reset_photo_lines"]
    assert all(not a.icon().isNull() for a in tb.actions())
    menu = win.createPopupMenu()
    toggle = [a for a in menu.actions() if a.text() == "Camera from Photo"]
    assert toggle and toggle[0].isCheckable() and not toggle[0].isChecked()
    toggle[0].trigger()
    assert not tb.isHidden()


def test_restore_default_toolbars_shows_it_again(win):
    tb = win._photo_toolbar
    tb.hide()
    win.restore_default_toolbars()
    for _ in range(5):
        QApplication.processEvents()
    assert not tb.isHidden()
    assert not win._photo_toolbar_cramped()


def test_a_hidden_photo_toolbar_stays_hidden_next_time(win, tmp_path,
                                                       monkeypatch):
    """Hidden by the user, the saved layout keeps it hidden."""
    tb = win._photo_toolbar
    tb.hide()
    QApplication.processEvents()
    state = win.saveState()
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    other = MainWindow()
    try:
        assert not other._photo_toolbar.isHidden()   # a fresh start
        other.restoreState(state)
        assert other._photo_toolbar.isHidden()
    finally:
        other._saved_version = other.viewport.scene.version
        other.close()


def _bars_in_row(win, bar):
    from PySide6.QtWidgets import QToolBar
    y = bar.geometry().y()
    return sorted((b for b in win.findChildren(QToolBar)
                   if b.parent() is win and not b.isHidden()
                   and not b.isFloating()
                   and win.toolBarArea(b) == win.toolBarArea(bar)
                   and b.geometry().y() == y),
                  key=lambda b: b.geometry().x())


def test_shown_the_first_time_it_goes_after_the_standard_views(win):
    """Not at the head of the top row, where Qt leaves a new bar: right
    after Standard Views, with the other camera buttons."""
    from PySide6.QtCore import QSettings
    QSettings().remove(win._PHOTO_TOOLBAR_PLACED)
    tb = win._photo_toolbar
    tb.hide()
    tb.show()
    for _ in range(5):
        QApplication.processEvents()
    views = win.toolbars["views"]
    row = _bars_in_row(win, views)
    # Its three buttons always in sight: right after Standard Views when
    # they fit there, else on a row with room.
    assert not win._photo_toolbar_cramped()
    assert win.toolBarArea(tb) == win.toolBarArea(views)
    if tb in row:
        assert row.index(tb) == row.index(views) + 1
    # Once placed, a hide and show leaves it where it is.
    assert QSettings().value(win._PHOTO_TOOLBAR_PLACED) is not None
    win.restore_default_toolbars()          # placed again, from scratch
    for _ in range(5):
        QApplication.processEvents()
    assert QSettings().value(win._PHOTO_TOOLBAR_PLACED) is not None
    assert not win._photo_toolbar_cramped()


def test_seating_the_toolbar_never_loops(win, monkeypatch):
    """Seating the bar shows it again; with settings that keep nothing
    (a profile that cannot be written) that show seated it again and
    again — a recursion found while checking this by hand."""
    import views.main_window as MW

    class Forgetful:
        def value(self, *_a, **_k):
            return None

        def setValue(self, *_a):
            pass

        def remove(self, *_a):
            pass
    monkeypatch.setattr(MW, "QSettings", Forgetful)
    tb = win._photo_toolbar
    tb.hide()
    tb.show()
    for _ in range(5):
        QApplication.processEvents()
    assert not tb.isHidden()
    assert win.toolBarArea(tb) == win.toolBarArea(win.toolbars["views"])


def test_a_full_row_does_not_hide_its_buttons(win):
    """A window too narrow for the bar after Standard Views: it moves on,
    and all three of its buttons show."""
    from PySide6.QtCore import QSettings
    QSettings().remove(win._PHOTO_TOOLBAR_PLACED)
    win.resize(700, 600)
    QApplication.processEvents()
    tb = win._photo_toolbar
    tb.hide()
    tb.show()
    for _ in range(10):
        QApplication.processEvents()
    assert not win._photo_toolbar_cramped()
    assert all(tb.widgetForAction(a) is not None
               and tb.widgetForAction(a).isVisible() for a in tb.actions())
