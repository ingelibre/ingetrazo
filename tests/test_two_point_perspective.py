"""Two-point perspective (Camera ▸ Two-Point Perspective): the
verticals of the model stay vertical on screen, and the target stays in the
middle of it, like an architectural perspective (José Castro Basso,
FADU–UDELAR)."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D, QVector4D

from core.camera import OrbitCamera
from core.saved_views import SavedView


def _screen(cam, p):
    q = (cam.projection_matrix() * cam.view_matrix()).map(
        QVector4D(p.x(), p.y(), p.z(), 1.0))
    return q.x() / q.w(), q.y() / q.w()


def _cam(pitch_deg=30.0):
    cam = OrbitCamera()
    cam.set_aspect(1600, 900)
    cam.target = QVector3D(2.0, 3.0, 1.5)
    cam.yaw = math.radians(-35.0)
    cam.pitch = math.radians(pitch_deg)
    cam.distance = 25.0
    return cam


def test_verticals_stay_vertical_and_the_target_centred():
    cam = _cam()
    base, top = QVector3D(8.0, -4.0, 0.0), QVector3D(8.0, -4.0, 9.0)
    x0, _ = _screen(cam, base)
    x1, _ = _screen(cam, top)
    assert abs(x0 - x1) > 1e-3             # an ordinary perspective leans it
    cam.toggle_two_point()
    x0, _ = _screen(cam, base)
    x1, _ = _screen(cam, top)
    assert abs(x0 - x1) < 1e-5          # float32 matrices
    tx, ty = _screen(cam, cam.target)
    assert abs(tx) < 1e-5 and abs(ty) < 1e-5


def test_looking_down_steeply_is_an_ordinary_perspective():
    cam = _cam(pitch_deg=85.0)
    plain = cam.projection_matrix() * cam.view_matrix()
    cam.toggle_two_point()
    assert cam.projection_matrix() * cam.view_matrix() == plain


def test_parallel_turns_it_off_and_turning_it_on_brings_perspective():
    cam = _cam()
    cam.perspective = False
    cam.toggle_two_point()
    assert cam.two_point and cam.perspective
    cam.toggle_projection()
    assert not cam.two_point and not cam.perspective


def test_a_scene_remembers_it():
    from core.scene import Scene

    cam = _cam()
    cam.toggle_two_point()
    raw = SavedView.capture("P", Scene(), cam).to_dict()
    assert raw["two_point"] is True
    other = _cam()
    SavedView.from_dict(raw).apply(Scene(), other)
    assert other.two_point


def test_the_three_projections_by_name():
    """The View toolbar's quick buttons: parallel, perspective, two-point —
    and two-point left on a parallel camera reads parallel."""
    cam = _cam()
    assert cam.projection_mode() == "perspective"
    for mode in ("two_point", "parallel", "perspective", "two_point"):
        cam.set_projection(mode)
        assert cam.projection_mode() == mode
    cam.perspective = False                     # a scene with two_point kept
    assert cam.projection_mode() == "parallel"
    cam.set_projection("nonsense")
    assert cam.projection_mode() == "parallel"


def test_the_quick_buttons_follow_the_camera(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    path = tmp_path / "prefs.ini"
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    import PySide6.QtCore as qc
    import views.main_window as mw
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory)
    win = mw.MainWindow()
    try:
        acts = win._projection_actions
        views_tb = win.toolbars["views"].actions()
        assert all(a in views_tb for a in acts.values())
        # the Camera menu holds the very same actions (one shortcut each)
        cam_menu = next(m.menu() for m in win.menuBar().actions()
                        if m.menu() and acts["two_point"] in m.menu().actions())
        assert all(a in cam_menu.actions() for a in acts.values())
        assert acts["perspective"].isChecked()
        acts["two_point"].trigger()
        assert win.viewport.camera.projection_mode() == "two_point"
        assert acts["two_point"].isChecked()
        win.viewport.toggle_projection()            # Shift+P
        assert acts["parallel"].isChecked()
        win.viewport.camera.perspective = True      # a scene restoring it
        win.viewport._sync_projection()             # what the next frame does
        assert acts["perspective"].isChecked()
        assert sum(a.isChecked() for a in acts.values()) == 1
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
