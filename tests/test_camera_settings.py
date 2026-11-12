# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Camera Settings: the camera by the numbers — eye and target
typed in, the lens as a focal length, roll, frame shift, clipping and the
picture's frame — kept by scenes and by the document."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QVector3D, QVector4D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.camera import (OrbitCamera, focal_from_fov,  # noqa: E402
                         fov_from_focal, frame_rect)
from core.saved_views import SavedView  # noqa: E402


def _ndc(cam, p: QVector3D):
    mvp = cam.projection_matrix() * cam.view_matrix()
    v = mvp.map(QVector4D(p.x(), p.y(), p.z(), 1.0))
    return v.x() / v.w(), v.y() / v.w(), v.z() / v.w()


def _level_camera() -> OrbitCamera:
    """Eye 1.6 m up, 10 m south of a point at the same height, looking
    north: a level view of a facade."""
    cam = OrbitCamera()
    cam.set_aspect(1600, 900)
    assert cam.place(QVector3D(0, -10, 1.6), QVector3D(0, 0, 1.6))
    return cam


# ---- Lens arithmetic ---------------------------------------------------------

def test_focal_length_and_field_of_view_are_one_another():
    # 35 mm format by its 24 mm height: a 50 mm lens sees 27° vertically.
    assert fov_from_focal(50.0) == pytest.approx(26.99, abs=0.01)
    assert focal_from_fov(45.0) == pytest.approx(28.97, abs=0.01)
    for mm in (14.0, 24.0, 35.0, 85.0, 135.0):
        assert focal_from_fov(fov_from_focal(mm)) == pytest.approx(mm)
    cam = OrbitCamera()
    cam.fov_deg = fov_from_focal(35.0)
    assert cam.focal_mm == pytest.approx(35.0)


def test_an_ordinary_lens_draws_as_it_always_did():
    """No setting touched: the very same matrix as before the lens."""
    cam = _level_camera()
    assert cam.lens_dict() == {}
    from PySide6.QtGui import QMatrix4x4
    m = QMatrix4x4()
    m.perspective(cam.fov_deg, cam.aspect, cam.near_plane(), cam.far_plane())
    assert cam.projection_matrix() == m


def test_place_puts_the_eye_and_target_exactly():
    cam = OrbitCamera()
    eye, target = QVector3D(3.0, -7.5, 1.65), QVector3D(-2.0, 4.0, 1.2)
    assert cam.place(eye, target)
    assert (cam.eye() - eye).length() < 1e-5
    assert (cam.target - target).length() < 1e-5
    # The same point twice is no camera: refused, nothing moves.
    before = cam.eye()
    assert not cam.place(eye, eye)
    assert (cam.eye() - before).length() < 1e-9


# ---- Shift -------------------------------------------------------------------

def test_vertical_shift_slides_the_picture_and_keeps_verticals_upright():
    cam = _level_camera()
    cam.shift_y = 0.25
    # The point looked at sits half a screen below the centre…
    x, y, _ = _ndc(cam, QVector3D(0, 0, 1.6))
    assert x == pytest.approx(0.0, abs=1e-5)
    assert y == pytest.approx(-0.5, abs=1e-4)
    # …and a corner of a tall facade stays vertical on screen.
    a = _ndc(cam, QVector3D(4, 0, 0))
    b = _ndc(cam, QVector3D(4, 0, 12))
    assert a[0] == pytest.approx(b[0], abs=1e-5)


def test_horizontal_shift_and_shift_in_parallel():
    cam = _level_camera()
    cam.shift_x = -0.1
    x, _, _ = _ndc(cam, QVector3D(0, 0, 1.6))
    assert x == pytest.approx(0.2, abs=1e-4)
    cam.perspective = False
    x, _, _ = _ndc(cam, QVector3D(0, 0, 1.6))
    assert x == pytest.approx(0.2, abs=1e-4)


def test_shift_adds_to_a_two_point_rise():
    cam = _level_camera()
    cam.place(QVector3D(0, -10, 1.6), QVector3D(0, 0, 6.0))   # looking up
    cam.two_point = True
    _, y0, _ = _ndc(cam, cam.target)
    assert y0 == pytest.approx(0.0, abs=1e-4)                 # centred
    cam.shift_y = 0.1
    _, y1, _ = _ndc(cam, cam.target)
    assert y1 == pytest.approx(-0.2, abs=1e-4)


# ---- Roll ----------------------------------------------------------------------

def test_roll_turns_the_picture_about_the_sight_line():
    cam = _level_camera()
    cam.roll_deg = 90.0
    # Above the target is now beside it on screen, not above.
    x, y, _ = _ndc(cam, QVector3D(0, 0, 3.0))
    assert abs(y) < 1e-4 and abs(x) > 0.1
    # Panning follows the turned picture: a drag "up" moves along the roll.
    t = QVector3D(cam.target)
    cam.pan(0.0, 100.0, 900)
    moved = cam.target - t
    assert abs(moved.z()) < 1e-6 and abs(moved.x()) > 1e-3


def test_two_point_takes_no_roll():
    cam = _level_camera()
    cam.two_point = True
    cam.roll_deg = 30.0
    a = _ndc(cam, QVector3D(4, 0, 0))
    b = _ndc(cam, QVector3D(4, 0, 12))
    assert a[0] == pytest.approx(b[0], abs=1e-5)


# ---- Clipping ------------------------------------------------------------------

def test_near_clipping_looks_through_a_wall():
    cam = _level_camera()
    wall = QVector3D(0, -7, 1.6)          # 3 m in front of the eye
    assert -1.0 < _ndc(cam, wall)[2] < 1.0
    cam.clip_near = 4.0
    assert cam.near_plane() == pytest.approx(4.0)
    assert _ndc(cam, wall)[2] < -1.0      # in front of the near plane: gone
    assert -1.0 < _ndc(cam, QVector3D(0, 0, 1.6))[2] < 1.0


def test_far_clipping_and_clipping_in_parallel():
    cam = _level_camera()
    far = QVector3D(0, 30, 1.6)           # 40 m away
    cam.clip_far = 20.0
    assert _ndc(cam, far)[2] > 1.0
    cam.perspective = False
    cam.clip_near, cam.clip_far = 4.0, 20.0
    assert _ndc(cam, QVector3D(0, -7, 1.6))[2] < -1.0
    assert _ndc(cam, far)[2] > 1.0
    assert -1.0 < _ndc(cam, QVector3D(0, 0, 1.6))[2] < 1.0


def test_apply_lens_resets_and_cleans():
    cam = OrbitCamera()
    cam.apply_lens({"shift_y": 5.0, "roll_deg": 370.0, "clip_near": -1.0,
                    "clip_far": float("nan"), "frame_aspect": "x"})
    assert cam.shift_y == 1.0                 # at most a whole view
    assert cam.roll_deg == pytest.approx(10.0)
    assert cam.clip_near is None and cam.clip_far is None
    assert cam.frame_aspect is None
    cam.apply_lens({"clip_near": 5.0, "clip_far": 2.0})
    assert cam.clip_near == 5.0 and cam.clip_far is None   # far ≤ near dropped
    cam.apply_lens(None)
    assert cam.lens_dict() == {}


# ---- Frame ---------------------------------------------------------------------

def test_frame_is_the_largest_centred_rectangle():
    assert frame_rect(1600, 900, None) is None
    x, y, w, h = frame_rect(1600, 900, 1.0)
    assert (x, y, w, h) == (350.0, 0.0, 900.0, 900.0)
    x, y, w, h = frame_rect(1000, 1000, 2.0)
    assert (x, y, w, h) == (0.0, 250.0, 1000.0, 500.0)


# ---- Kept by scenes and by the document -------------------------------------------

def _Scene():
    from core.scene import Scene
    return Scene()


def test_a_scene_keeps_the_lens_and_an_old_scene_takes_it_off():
    cam = _level_camera()
    cam.apply_lens({"shift_y": 0.2, "roll_deg": -5.0, "clip_near": 3.0,
                    "frame_aspect": 16 / 9})
    view = SavedView.capture("Fachada", _Scene(), cam)
    raw = view.to_dict()
    assert raw["lens"]["shift_y"] == 0.2
    back = SavedView.from_dict(raw)
    other = OrbitCamera()
    back.apply(_Scene(), other)
    assert other.lens_dict() == cam.lens_dict()
    # A scene from before the lens (no "lens" key) is an ordinary lens.
    old = dict(raw)
    del old["lens"]
    SavedView.from_dict(old).apply(_Scene(), other)
    assert other.lens_dict() == {}


def test_the_document_keeps_the_lens(tmp_path):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        cam = win.viewport.camera
        cam.apply_lens({"shift_y": 0.15, "frame_aspect": 4 / 3})
        home = win._camera_dict()
        assert home["lens"] == {"shift_y": 0.15, "frame_aspect": 4 / 3}
        cam.reset_lens()
        win._apply_camera_dict(home)
        assert cam.shift_y == 0.15 and cam.frame_aspect == pytest.approx(4 / 3)
        win._reset_camera_home()                   # File ▸ New
        assert cam.lens_dict() == {}
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- The window -------------------------------------------------------------------

def test_the_settings_window_shows_and_sets_the_camera():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        assert win._act_camera_settings.text()
        assert not win._act_camera_settings.icon().isNull()
        win._show_camera_settings()
        dlg = win._camera_settings
        cam = win.viewport.camera
        cam.set_projection("perspective")
        # Typed coordinates move the camera there.
        dlg.eye[0].setValue(2.0)
        dlg.eye[1].setValue(-12.0)
        dlg.eye[2].setValue(1.7)
        for box, v in zip(dlg.target, (0.0, 0.0, 1.5)):
            box.setValue(v)
        assert (cam.eye() - QVector3D(2.0, -12.0, 1.7)).length() < 1e-3
        assert (cam.target - QVector3D(0.0, 0.0, 1.5)).length() < 1e-3
        # A 50 mm lens from the list.
        dlg.preset.setCurrentIndex(dlg.preset.findData(50.0))
        assert cam.focal_mm == pytest.approx(50.0, abs=0.01)
        assert dlg.fov.value() == pytest.approx(27.0, abs=0.06)
        # Shift, roll, clipping and frame.
        dlg.shift_y.setValue(20.0)
        assert cam.shift_y == pytest.approx(0.2)
        dlg.roll.setValue(10.0)
        assert cam.roll_deg == pytest.approx(10.0)
        dlg.near_on.setChecked(True)
        dlg.near.setValue(3.0)
        assert cam.clip_near == pytest.approx(3.0)
        dlg.frame.setCurrentIndex(dlg.frame.findText("16:9"))
        assert cam.frame_aspect == pytest.approx(16 / 9)
        # The mouse moves the camera: the window follows.
        cam.place(QVector3D(5.0, 5.0, 5.0), QVector3D(0.0, 0.0, 0.0))
        dlg.refresh()
        assert dlg.eye[2].value() == pytest.approx(5.0, abs=1e-3)
        # Reset Lens: the ordinary lens back, the place and angle kept.
        dlg.reset.click()
        assert cam.lens_dict() == {}
        assert cam.focal_mm == pytest.approx(50.0, abs=0.01)
        assert dlg.frame.currentIndex() == 0
        # Parallel has no focal length.
        dlg.projection.setCurrentIndex(dlg.projection.findData("parallel"))
        assert not cam.perspective and not dlg.focal.isEnabled()
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_every_language_names_the_window():
    import json
    from core.i18n import _I18N_DIR
    for p in _I18N_DIR.glob("*.json"):
        if p.stem == "en":
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "Camera Settings…" in data, p.stem


# ---- Export image keeps to the frame ------------------------------------------------

def _fake_view(monkeypatch, w=1000, h=500):
    """A viewport whose GL render is a synthetic picture: grey all over and
    red exactly where the camera frame lies, so a crop can be checked
    without a graphics card."""
    from PySide6.QtGui import QColor, QImage, QPainter
    from views import viewport as V
    cls = V.Viewport
    vp = cls.__new__(cls)
    monkeypatch.setattr(cls, "width", lambda self: w)
    monkeypatch.setattr(cls, "height", lambda self: h)
    monkeypatch.setattr(cls, "update", lambda self: None)
    vp._gl = vp._program = object()
    vp.camera = OrbitCamera()
    real = cls.render_image
    rendered = []

    def render(self, width_px, height_px=None, overlays=True,
               annotations_only=False, sharp_shadows=False,
               transparent=False, crop_to_frame=False):
        if crop_to_frame:
            return real(self, width_px, height_px, overlays,
                        annotations_only, sharp_shadows, transparent, True)
        hh = round(width_px * h / w)
        rendered.append((width_px, hh))
        img = QImage(width_px, hh, QImage.Format_RGB32)
        img.fill(QColor(128, 128, 128))
        rect = frame_rect(w, h, self.camera.frame_aspect)
        if rect is not None:
            k = width_px / w
            p = QPainter(img)
            p.fillRect(round(rect[0] * k), round(rect[1] * k),
                       round(rect[2] * k), round(rect[3] * k),
                       QColor(255, 0, 0))
            p.end()
        return img

    monkeypatch.setattr(cls, "render_image", render)
    return vp, rendered


def test_export_image_is_the_framed_shot(monkeypatch):
    vp, rendered = _fake_view(monkeypatch)          # a 2:1 view
    vp.camera.frame_aspect = 1.0                    # a square frame
    img = vp.render_image(800, crop_to_frame=True)
    # 800 px wide AND square: the frame, not the view.
    assert (img.width(), img.height()) == (800, 800)
    # Rendered twice as wide (the frame is half the view) and cut to it:
    # nothing outside the frame (grey) is left in the picture.
    assert rendered == [(1600, 800)]
    for x, y in ((0, 0), (799, 0), (0, 799), (799, 799), (400, 400)):
        assert img.pixelColor(x, y).red() == 255, (x, y)
        assert img.pixelColor(x, y).green() == 0, (x, y)


def test_export_image_tall_frame(monkeypatch):
    vp, rendered = _fake_view(monkeypatch, 800, 800)
    vp.camera.frame_aspect = 16 / 9                 # bands top and bottom
    img = vp.render_image(1920, crop_to_frame=True)
    assert (img.width(), img.height()) == (1920, 1080)
    assert img.pixelColor(960, 2).red() == 255
    assert img.pixelColor(960, 1077).red() == 255


def test_export_image_menu_crops_to_the_frame():
    """File ▸ Export Image asks for the framed shot."""
    import inspect
    from views.main_window import MainWindow
    src = inspect.getsource(MainWindow._on_export_image)
    assert "crop_to_frame=True" in src


# ---- Basic and advanced ----------------------------------------------------------

def test_basic_settings_first_advanced_on_request():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = win._show_camera_settings()
        # Tests never read the user's settings: basic to begin with.
        assert not dlg.is_advanced()
        for w in (dlg.projection, dlg.preset, dlg.focal, dlg.shift_y,
                  dlg.frame, dlg.reset):
            assert w.isVisibleTo(dlg), w
        for w in (dlg.eye[0], dlg.target[0], dlg.fov, dlg.roll,
                  dlg.shift_x, dlg.near, dlg.far):
            assert not w.isVisibleTo(dlg), w
        dlg.more.click()
        assert dlg.is_advanced()
        for w in (dlg.eye[0], dlg.fov, dlg.roll, dlg.shift_x, dlg.near):
            assert w.isVisibleTo(dlg), w
        dlg.more.click()
        assert not dlg.eye[0].isVisibleTo(dlg)
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- A scene's right-click ---------------------------------------------------------

def _window_with_scenes():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    cam = win.viewport.camera
    cam.place(QVector3D(0, -10, 1.6), QVector3D(0, 0, 1.6))
    a = SavedView.capture("Fachada", scene, cam)
    cam.place(QVector3D(10, 10, 8), QVector3D(0, 0, 0))
    b = SavedView.capture("Aérea", scene, cam)
    scene.saved_views += [a, b]
    win.tray.scenes.refresh()
    return win, a, b


def test_right_click_a_scene_edits_its_camera():
    win, a, b = _window_with_scenes()
    try:
        scene, cam = win.viewport.scene, win.viewport.camera
        hidden = list(a.hidden_layers)
        version = scene.version
        win.edit_scene_camera(a)
        dlg = win._camera_settings
        assert dlg.editing_scene() is a and dlg.scene_label.isVisibleTo(dlg)
        assert "Fachada" in dlg.scene_label.text()
        # The scene is what the view shows.
        assert (cam.eye() - QVector3D(0, -10, 1.6)).length() < 1e-4
        # A change made here goes into the scene, and only the camera.
        dlg.shift_y.setValue(25.0)
        dlg.preset.setCurrentIndex(dlg.preset.findData(24.0))
        assert a.lens.get("shift_y") == pytest.approx(0.25)
        assert focal_from_fov(a.fov_deg) == pytest.approx(24.0, abs=0.01)
        assert a.hidden_layers == hidden
        assert scene.version > version            # the document changed
        assert b.lens == {}                       # the other scene: untouched
        # Moving the view by other means ends it: the scene keeps what it had.
        cam.orbit(80.0, 0.0, 900)
        dlg.refresh()
        assert dlg.editing_scene() is None and not dlg.scene_label.isVisibleTo(dlg)
        dlg.frame.setCurrentIndex(dlg.frame.findText("1:1"))
        assert "frame_aspect" not in a.lens
        # The Camera menu opens it on the live view, not on a scene.
        win.edit_scene_camera(b)
        assert dlg.editing_scene() is b
        win._show_camera_settings()
        assert dlg.editing_scene() is None
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_scene_menus_offer_camera_settings():
    win, a, b = _window_with_scenes()
    try:
        # The scene tabs under the view.
        tabs = win._scene_tabs.tabs
        i = tabs.views.index(b)
        menu = win._build_scene_tab_menu(i)
        act = [x for x in menu.actions() if x.text() == "Camera Settings…"]
        assert act and act[0].isEnabled()
        act[0].trigger()
        assert win._camera_settings.editing_scene() is b
        # The Scenes panel's tree.
        panel = win.tray.scenes
        menu = panel.context_menu(panel.row_for(a))
        act = [x for x in menu.actions() if x.text() == "Camera Settings…"]
        assert act
        act[0].trigger()
        assert win._camera_settings.editing_scene() is a
        win._camera_settings.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_take_camera_keeps_only_the_camera():
    from core.scene import Scene
    scene = Scene()
    cam = _level_camera()
    view = SavedView("Vista", hidden_layers=["Muebles"])
    cam.apply_lens({"roll_deg": 5.0})
    view.take_camera(cam)
    assert view.hidden_layers == ["Muebles"]
    assert view.lens == {"roll_deg": 5.0}
    other = OrbitCamera()
    view.apply(scene, other)
    assert (other.eye() - cam.eye()).length() < 1e-5


# ---- Whole on the screen, centred, still when the options open --------------------------

def _inside(rect, area):
    return (rect.left() >= area.left() and rect.top() >= area.top()
            and rect.right() <= area.right() and rect.bottom() <= area.bottom())


def test_window_opens_centred_and_keeps_its_centre():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = win._show_camera_settings()
        QApplication.processEvents()
        area = dlg.screen().availableGeometry()
        fg = dlg.frameGeometry()
        assert _inside(fg, area)
        assert abs(fg.center().x() - area.center().x()) <= 2
        assert abs(fg.center().y() - area.center().y()) <= 2
        centre = fg.center()
        small = fg.height()
        dlg.more.click()                          # advanced: grows
        QApplication.processEvents()
        fg = dlg.frameGeometry()
        assert fg.height() > small or fg.height() >= area.height() - 2
        assert _inside(fg, area)
        assert abs(fg.center().x() - centre.x()) <= 2
        if fg.height() < area.height() - 2:      # room to stay centred
            assert abs(fg.center().y() - centre.y()) <= 2
        dlg.more.click()                          # basic again: shrinks back
        QApplication.processEvents()
        fg = dlg.frameGeometry()
        assert fg.height() == small and _inside(fg, area)
        assert abs(fg.center().y() - centre.y()) <= 2
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_window_never_taller_than_the_screen():
    """On a low screen the settings scroll; the window stays whole."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = win._show_camera_settings()
        dlg.set_advanced(True)
        QApplication.processEvents()
        area = dlg.screen().availableGeometry()
        assert _inside(dlg.frameGeometry(), area)
        assert dlg.height() <= area.height()
        dlg.set_advanced(False)
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_window_does_not_walk_when_toggled_many_times():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = win._show_camera_settings()
        QApplication.processEvents()
        first = dlg.frameGeometry()
        for _ in range(10):
            dlg.more.click()
            QApplication.processEvents()
            dlg.more.click()
            QApplication.processEvents()
        assert dlg.frameGeometry() == first
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_looks_like_the_other_panels():
    """Fold sections like the side panels' and a tick for the advanced
    options, which stays where it is while the window grows."""
    from PySide6.QtWidgets import QCheckBox
    from views.fold_section import FoldSection
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = win._show_camera_settings()
        QApplication.processEvents()
        assert isinstance(dlg.more, QCheckBox) and not dlg.more.isChecked()
        assert len(dlg.sections) == 4
        assert all(isinstance(s, FoldSection) for s in dlg.sections)
        basic = dlg.sections[0]
        assert basic.isVisibleTo(dlg)
        assert not any(s.isVisibleTo(dlg) for s in dlg.sections[1:])
        dlg.more.click()
        assert all(s.isVisibleTo(dlg) for s in dlg.sections)
        # Folding a section keeps the window whole and in its place.
        before = dlg.frameGeometry().center()
        open_ = dlg.sections[1].header.isChecked()
        dlg.sections[1].set_open(not open_)
        QApplication.processEvents()
        QApplication.processEvents()
        after = dlg.frameGeometry().center()
        assert abs(after.x() - before.x()) <= 1
        assert abs(after.y() - before.y()) <= 1
        dlg.sections[1].set_open(open_)
        dlg.more.click()
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- The sensor ---------------------------------------------------------------------

def test_a_picture_uses_the_largest_part_of_the_sensor_of_its_shape():
    from core.camera import FULL_FRAME, sensor_picture_height
    # Narrower than 3:2 (the usual view): the whole height.
    assert sensor_picture_height(FULL_FRAME, 1.4) == 24.0
    # 16:9 on a 3:2 sensor: the whole width, less height — as a camera films.
    assert sensor_picture_height(FULL_FRAME, 16 / 9) == pytest.approx(20.25)
    assert sensor_picture_height(None, None) == 24.0


def test_the_same_lens_sees_narrower_on_a_smaller_sensor():
    from core.camera import SENSORS
    cam = OrbitCamera()
    cam.set_aspect(1400, 1000)                     # narrower than 3:2
    ff = cam.fov_for_focal(50.0)
    cam.set_sensor(SENSORS["aps_c"])
    aps = cam.fov_for_focal(50.0)
    assert aps < ff
    # 50 mm on APS-C is what about 77 mm is on full frame (×1.54).
    cam.fov_deg = aps
    cam.set_sensor(None)
    assert cam.focal_mm == pytest.approx(50.0 * 24.0 / 15.6, rel=1e-6)
    # Changing the sensor keeps the picture: only the reading changes.
    cam.fov_deg = 40.0
    for size in SENSORS.values():
        cam.set_sensor(size)
        assert cam.fov_deg == 40.0
        assert cam.fov_for_focal(cam.focal_mm) == pytest.approx(40.0)


def test_the_sensor_is_kept_with_the_lens():
    from core.camera import SENSORS
    cam = OrbitCamera()
    assert "sensor" not in cam.lens_dict()           # full frame: nothing
    cam.set_sensor(SENSORS["micro_four_thirds"])
    assert cam.lens_dict()["sensor"] == [17.3, 13.0]
    other = OrbitCamera()
    other.apply_lens(cam.lens_dict())
    assert other.sensor_size() == (17.3, 13.0)
    # A scene keeps it, and an old scene goes back to full frame.
    from core.scene import Scene
    raw = SavedView.capture("V", Scene(), cam).to_dict()
    assert raw["lens"]["sensor"] == [17.3, 13.0]
    SavedView.from_dict(raw).apply(Scene(), other)
    assert other.sensor_size() == (17.3, 13.0)
    del raw["lens"]
    SavedView.from_dict(raw).apply(Scene(), other)
    assert other.sensor_size() == (36.0, 24.0)
    # Nonsense is not taken; Reset Lens keeps the sensor.
    other.apply_lens({"sensor": [0, 5]})
    assert other.sensor is None
    other.apply_lens({"sensor": "x", "roll_deg": 5})
    assert other.sensor is None and other.roll_deg == 5
    cam.roll_deg = 10.0
    cam.reset_lens()
    assert cam.roll_deg == 0.0 and cam.sensor_size() == (17.3, 13.0)


def test_the_window_picks_the_sensor():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = win._show_camera_settings()
        cam = win.viewport.camera
        cam.set_projection("perspective")
        cam.fov_deg = 40.0
        dlg.refresh()
        assert dlg.sensor.currentData() == "full_frame"
        assert not dlg.sensor_w.isVisibleTo(dlg)        # custom size hidden
        ff_mm = dlg.focal.value()
        dlg.sensor.setCurrentIndex(dlg.sensor.findData("aps_c"))
        assert cam.sensor_size() == (23.6, 15.6)
        assert cam.fov_deg == 40.0                       # the picture stays
        assert dlg.focal.value() < ff_mm                 # the reading changes
        # A 50 mm lens on that sensor.
        dlg.preset.setCurrentIndex(dlg.preset.findData(50.0))
        assert cam.focal_mm == pytest.approx(50.0, abs=0.01)
        # Custom: the size row shows, and stays picked even at a named size.
        dlg.sensor.setCurrentIndex(dlg.sensor.findData("custom"))
        assert dlg.sensor_w.isVisibleTo(dlg)
        dlg.sensor_w.setValue(36.0)
        dlg.sensor_h.setValue(24.0)
        assert cam.sensor_size() == (36.0, 24.0)
        assert dlg.sensor.currentData() == "custom"
        dlg.sensor_w.setValue(30.0)
        dlg.sensor_h.setValue(20.0)
        assert cam.sensor_size() == (30.0, 20.0)
        # Reopened, the list names it: a custom size reads «Custom».
        dlg.close()
        dlg = win._show_camera_settings()
        assert dlg.sensor.currentData() == "custom"
        cam.set_sensor(None)
        dlg.close()
        dlg = win._show_camera_settings()
        assert dlg.sensor.currentData() == "full_frame"
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- Zoom: the lens typed in the value box ------------------------------------------

def _type(vp, text):
    from PySide6.QtTest import QTest
    QTest.keyClicks(vp, text)
    QTest.keyClick(vp, Qt.Key_Return)


def test_typing_the_lens_with_zoom_on():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        cam = vp.camera
        cam.set_projection("perspective")
        vp.set_nav_mode("zoom")
        _type(vp, "35mm")
        assert cam.focal_mm == pytest.approx(35.0, abs=0.01)
        _type(vp, "60deg")
        assert cam.fov_deg == pytest.approx(60.0)
        _type(vp, "45")                               # bare: degrees
        assert cam.fov_deg == pytest.approx(45.0)
        _type(vp, "72,5°")
        assert cam.fov_deg == pytest.approx(72.5)
        # The sensor counts: 35mm on APS-C is a narrower view.
        from core.camera import SENSORS
        cam.set_sensor(SENSORS["aps_c"])
        _type(vp, "35mm")
        assert cam.focal_mm == pytest.approx(35.0, abs=0.01)
        assert cam.fov_deg < OrbitCamera().fov_for_focal(35.0)
        # Out of range: held to 10°–120°; nonsense changes nothing.
        _type(vp, "500deg")
        assert cam.fov_deg == 120.0
        before = cam.fov_deg
        assert not vp.apply_zoom_value("abc")
        assert cam.fov_deg == before
        # Letters before a digit are not taken (they stay shortcuts).
        assert vp._value_buffer == ""
        # A parallel view has no lens: nothing changes.
        cam.set_projection("parallel")
        _type(vp, "50mm")
        assert cam.fov_deg == before
        # Without Zoom, the value box is the tools' as before.
        cam.set_projection("perspective")
        vp.set_nav_mode(None)
        assert vp.active_tool is None
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        five = QKeyEvent(QEvent.KeyPress, Qt.Key_5, Qt.NoModifier, "5")
        assert not vp._handle_value_key(five)
        assert vp._value_buffer == ""
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_zoom_hint_says_what_to_type():
    from views.status_hints import NAV_HINTS
    assert "35mm" in NAV_HINTS["zoom"] and "60deg" in NAV_HINTS["zoom"]


def test_the_value_box_shows_with_zoom():
    """With Zoom on, the value box shows what is typed, and the focal
    length the view has when nothing is."""
    from PySide6.QtTest import QTest
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        QApplication.processEvents()
        cam = win.viewport.camera
        cam.set_projection("perspective")
        win._activate_nav("zoom")
        assert win._vcb_value.isVisibleTo(win)
        QTest.keyClicks(win.viewport, "35mm")
        assert win._vcb_value.text() == "35mm"
        QTest.keyClick(win.viewport, Qt.Key_Return)
        assert win._vcb_value.text() == "35 mm"       # the new focal
        win._activate_nav("orbit")
        assert not win._vcb_value.isVisibleTo(win)    # other nav: no box
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_an_ordinary_title_bar_like_the_other_dialogs():
    """The close cross of an ordinary dialog (the layer colour's), not a
    tool window's small one; and it does not block the model."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = win._show_camera_settings()
        flags = dlg.windowFlags()
        assert flags & Qt.WindowType_Mask == Qt.Dialog
        assert not flags & Qt.WindowContextHelpButtonHint
        assert not dlg.isModal()
        dlg.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_from_24_to_35_typing_with_a_space_and_capitals():
    """«35 MM» with Zoom on: the space is Select's shortcut and the
    letters are tools' — while a lens is being typed they belong to the
    box. And long lenses: 533 mm (2.6° on full frame) is not held to 10°."""
    from PySide6.QtTest import QTest
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        win.activateWindow()
        QApplication.processEvents()
        vp = win.viewport
        cam = vp.camera
        cam.set_projection("perspective")
        cam.apply_lens({})
        cam.fov_deg = cam.fov_for_focal(24.0)
        win._nav_actions["zoom"].trigger()          # the toolbar button
        vp.setFocus()
        QTest.keyClicks(vp, "35 MM")
        assert vp.nav_mode == "zoom"                # the space did not leave
        assert vp._value_buffer.lower() == "35 mm"
        QTest.keyClick(vp, Qt.Key_Return)
        assert cam.focal_mm == pytest.approx(35.0, abs=0.01)
        QTest.keyClicks(vp, "533mm")
        QTest.keyClick(vp, Qt.Key_Return)
        assert cam.focal_mm == pytest.approx(533.0, abs=0.1)
        assert cam.fov_deg == pytest.approx(2.58, abs=0.01)
        QTest.keyClicks(vp, "60deg")
        QTest.keyClick(vp, Qt.Key_Return)
        assert cam.fov_deg == pytest.approx(60.0)
        assert vp.nav_mode == "zoom"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_after_picking_a_scene_z_then_35mm_works():
    """Picking a scene in the Scenes list left the keyboard in the list,
    which kept the letters for its own search: Z did not reach Zoom and
    «35mm» was lost. Showing a scene, choosing Zoom and opening Camera
    Settings all leave the keyboard with the model."""
    from PySide6.QtTest import QTest
    from views.main_window import MainWindow
    win, a, b = _window_with_scenes()
    try:
        win.show()
        win.activateWindow()
        QApplication.processEvents()
        vp, cam = win.viewport, win.viewport.camera
        panel = win.tray.scenes
        item = next(panel.list.item(k) for k in range(panel.list.count())
                    if panel.list.item(k).data(Qt.UserRole) is a)
        panel.list.setFocus()
        panel._on_activate(item)                     # a double-click
        assert QApplication.focusWidget() is vp
        cam.fov_deg = cam.fov_for_focal(24.0)
        QTest.keyClick(vp, Qt.Key_Z)
        QTest.keyClicks(vp, "35mm")
        QTest.keyClick(vp, Qt.Key_Return)
        assert vp.nav_mode == "zoom"
        assert cam.focal_mm == pytest.approx(35.0, abs=0.01)
        # Zoom from its button, the keyboard elsewhere: it comes back.
        panel.list.setFocus()
        win._activate_nav("zoom")
        assert QApplication.focusWidget() is vp
        # Camera Settings opens without taking the keyboard.
        win._show_camera_settings()
        assert QApplication.focusWidget() is vp
        win._camera_settings.close()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
