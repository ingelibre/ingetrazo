# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""3D mouse navigation (issue #108) — without a device.

Nobody on the team has a SpaceMouse, so what can be pinned here is pinned:
the mapping «you hold the model» (each cap movement against the camera it
must produce, checked by where the model lands on screen), the two device
frames, and the two wire formats (spacenavd packets, HID reports). What only
a device can tell — the SIGNS its firmware really sends — is one line per
axis in ``core/ndof.py``'s ``from_hid``/``from_spacenavd``.
"""
from __future__ import annotations

import struct

import pytest
from PySide6.QtGui import QVector3D

from core.camera import OrbitCamera
from core.ndof import (NdofSample, NdofSettings, apply_ndof, from_hid,
                       from_spacenavd, mapped_movements, shape)
from views.ndof_input import parse_hid_report, parse_spnav_packets


def _cam():
    c = OrbitCamera()
    c.set_aspect(800, 600)
    return c


def _on_screen(cam, p=QVector3D(0, 0, 0)):
    """Where world point *p* lands in normalised device coordinates."""
    m = cam.projection_matrix() * cam.view_matrix()
    v = m.map(p)
    return v.x(), v.y()


def _push(sample, cam=None, dt=0.05, **kw):
    cam = cam or _cam()
    moved = apply_ndof(cam, sample, dt, 600, NdofSettings(**kw))
    return cam, moved


def test_the_cap_at_rest_moves_nothing():
    cam, moved = _push(NdofSample(right=0.03, spin=-0.04))   # under the dead zone
    assert not moved
    assert shape(0.03, 0.05) == 0.0
    assert shape(1.0, 0.05) == pytest.approx(1.0)
    assert shape(-1.0, 0.05) == pytest.approx(-1.0)


def test_moving_the_cap_right_carries_the_model_right():
    x0, y0 = _on_screen(_cam())
    cam, moved = _push(NdofSample(right=1.0))
    x1, y1 = _on_screen(cam)
    assert moved and x1 > x0 + 0.01 and y1 == pytest.approx(y0, abs=1e-6)


def test_lifting_the_cap_lifts_the_model():
    x0, y0 = _on_screen(_cam())
    cam, _ = _push(NdofSample(up=1.0))
    x1, y1 = _on_screen(cam)
    assert y1 > y0 + 0.01               # NDC y grows upwards


def test_pushing_the_cap_away_pushes_the_model_away():
    d0 = _cam().distance
    cam, _ = _push(NdofSample(forward=1.0))
    assert cam.distance > d0
    cam, _ = _push(NdofSample(forward=-1.0))
    assert cam.distance < d0


def test_twisting_anticlockwise_turns_the_near_side_to_the_right():
    # A point on the model's near side (toward the eye, on the ground).
    base = _cam()
    toward_eye = base.eye() - base.target
    near = QVector3D(toward_eye.x(), toward_eye.y(), 0.0).normalized() * 3
    x0, _ = _on_screen(base, near)
    cam, _ = _push(NdofSample(spin=1.0))
    x1, _ = _on_screen(cam, near)
    assert x1 > x0 + 0.01


def test_tilting_the_cap_away_shows_more_of_the_top():
    p0 = _cam().pitch
    cam, _ = _push(NdofSample(tilt=1.0))
    assert cam.pitch > p0               # the eye rises over the model


def test_roll_does_nothing_and_rotation_can_be_locked():
    cam, moved = _push(NdofSample(roll=1.0))
    assert not moved                    # the camera has no roll
    cam, moved = _push(NdofSample(spin=1.0, tilt=1.0), lock_rotation=True)
    assert not moved


def test_speed_follows_time_and_sensitivity_and_a_stall_is_capped():
    a, _ = _push(NdofSample(forward=1.0), dt=0.02)
    b, _ = _push(NdofSample(forward=1.0), dt=0.04)
    c, _ = _push(NdofSample(forward=1.0), dt=0.02, sensitivity=2.0)
    d0 = _cam().distance
    assert (b.distance - d0) > (a.distance - d0)
    assert c.distance == pytest.approx(b.distance)
    stall, _ = _push(NdofSample(forward=1.0), dt=5.0)
    capped, _ = _push(NdofSample(forward=1.0), dt=0.1)
    assert stall.distance == pytest.approx(capped.distance)


def test_invert_flips_each_group():
    cam, _ = _push(NdofSample(forward=1.0), invert_zoom=True)
    assert cam.distance < _cam().distance
    assert not _push(NdofSample(forward=1.0), enabled=False)[1]


def test_each_axis_inverts_on_its_own():
    """Issue #108 (a SpaceMouse user): one box per axis. Right flipped
    alone leaves up alone; the old pair switch still flips both, and a
    per-axis box on top of it flips that axis back."""
    x0, y0 = _on_screen(_cam())

    def moved(sample, **kw):
        cam, _ = _push(sample, **kw)
        x, y = _on_screen(cam)
        return x - x0, y - y0

    dx, dy = moved(NdofSample(right=1.0, up=1.0), invert_pan_x=True)
    assert dx < 0 and dy > 0                   # left, still up
    dx, dy = moved(NdofSample(right=1.0, up=1.0), invert_pan_y=True)
    assert dx > 0 and dy < 0                   # right, now down
    dx, dy = moved(NdofSample(right=1.0, up=1.0), invert_pan=True)
    assert dx < 0 and dy < 0                   # the old pair: both
    dx, dy = moved(NdofSample(right=1.0, up=1.0), invert_pan=True,
                   invert_pan_x=True)
    assert dx > 0 and dy < 0                   # the box flips x back
    base = _push(NdofSample(spin=1.0))[0]
    flipped = _push(NdofSample(spin=1.0), invert_spin=True)[0]
    tilted = _push(NdofSample(spin=1.0), invert_tilt=True)[0]
    assert flipped.yaw != base.yaw and tilted.yaw == pytest.approx(base.yaw)


# ---- device frames -----------------------------------------------------------

def test_spacenavd_frame():
    # Y up, Z toward the user: lifting is +y, pushing away is −z.
    s = from_spacenavd(0, 350, -350, 0, 0, 0)
    assert s.up == pytest.approx(1.0) and s.forward == pytest.approx(1.0)
    # +ry is anticlockwise seen from above = our +spin
    assert from_spacenavd(0, 0, 0, 0, 350, 0).spin == pytest.approx(1.0)
    # −rx takes the top away from the user = our +tilt
    assert from_spacenavd(0, 0, 0, -350, 0, 0).tilt == pytest.approx(1.0)


def test_hid_frame():
    # X right, Y away from the user, Z down: pressing the cap down is +z.
    s = from_hid(350, 0, 350, 0, 0, 0)
    assert s.right == pytest.approx(1.0) and s.up == pytest.approx(-1.0)
    assert from_hid(0, 350, 0, 0, 0, 0).forward == pytest.approx(1.0)
    # with Z down, +rz is clockwise seen from above
    assert from_hid(0, 0, 0, 0, 0, 350).spin == pytest.approx(-1.0)
    assert from_hid(0, 0, 0, 999, 0, 0).tilt == pytest.approx(-1.0)  # clipped


@pytest.mark.parametrize("hid", [
    (350, 0, 0, 0, 0, 0), (0, 350, 0, 0, 0, 0), (0, 0, 350, 0, 0, 0),
    (0, 0, 0, 350, 0, 0), (0, 0, 0, 0, 350, 0), (0, 0, 0, 0, 0, 350)])
def test_hid_and_spacenavd_agree_through_freecads_frames(hid):
    # FreeCAD posts (−x, y, z, −rx, ry, rz) for a HID report and
    # (−x, −z, −y, −rx, −rz, −ry) for spacenavd: the same physical move,
    # read by either driver, must give the same sample.
    x, y, z, rx, ry, rz = hid
    assert from_hid(*hid) == from_spacenavd(x, -z, -y, rx, -rz, -ry)


# ---- wire formats ------------------------------------------------------------

def test_spacenavd_packets():
    motion = struct.pack("=8i", 0, 10, 20, 30, 1, 2, 3, 16)
    press = struct.pack("=8i", 1, 0, 0, 0, 0, 0, 0, 0)
    got = parse_spnav_packets(motion + press + b"\x00" * 5)   # a torn tail
    assert got == [(0, [10, 20, 30, 1, 2, 3, 16]), (1, [0, 0, 0, 0, 0, 0, 0])]


def test_hid_reports_old_split_and_new_combined():
    state: dict = {}
    trans = bytes([1]) + struct.pack("<3h", 100, 0, 0)
    s = parse_hid_report(trans, state)
    assert s.right == pytest.approx(100 / 350)
    rot = bytes([2]) + struct.pack("<3h", 0, 0, 350)
    s = parse_hid_report(rot, state)
    assert s.right == pytest.approx(100 / 350)   # the translation is kept
    assert s.spin == pytest.approx(-1.0)
    both = bytes([1]) + struct.pack("<6h", 0, 0, 0, 0, 0, -350)
    s = parse_hid_report(both, {})
    assert s.spin == pytest.approx(1.0) and s.right == 0.0
    buttons = bytes([3, 0b10, 0, 0, 0])
    st: dict = {}
    assert parse_hid_report(buttons, st) is None and st["buttons"] == 2


def test_the_linux_driver_reads_a_spacenavd_socket(tmp_path, monkeypatch):
    """A fake spacenavd: the real protocol over a real Unix socket, read by
    the real QSocketNotifier path."""
    import socket
    import sys
    if not sys.platform.startswith("linux"):
        pytest.skip("spacenavd is the Linux driver")
    from PySide6.QtCore import QCoreApplication, QEventLoop
    from views import ndof_input
    app = QCoreApplication.instance() or QCoreApplication([])
    path = str(tmp_path / "spnav.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    monkeypatch.setattr(ndof_input, "SPNAV_SOCKETS", (path,))
    monkeypatch.setattr(ndof_input.sys, "platform", "linux")
    dev = ndof_input.NdofInput()
    got, buttons = [], []
    dev.motion.connect(lambda s, dt: got.append((s, dt)))
    dev.button.connect(lambda n, down: buttons.append((n, down)))
    raws = []
    dev.raw.connect(raws.append)
    try:
        assert dev.start() and dev.backend_name == "spacenavd"
        conn, _ = server.accept()
        conn.sendall(struct.pack("=8i", 0, 350, 0, 0, 0, 0, 0, 16)
                     + struct.pack("=8i", 1, 1, 0, 0, 0, 0, 0, 0))
        for _ in range(30):
            app.processEvents(QEventLoop.AllEvents, 10)
            if got and buttons:
                break
        assert got and got[0][0].right == pytest.approx(1.0)
        assert got[0][1] == pytest.approx(0.016)       # the daemon's period
        assert buttons == [(1, True)]
        assert raws == [(350, 0, 0, 0, 0, 0)]   # as the daemon sent it
        conn.close()
    finally:
        dev.stop()
        server.close()


# ---- the driver's wheel imitation --------------------------------------------

def test_the_cap_counts_as_in_use_past_the_dead_zone_and_a_moment_after(
        monkeypatch):
    from views import ndof_input
    dev = ndof_input.NdofInput()
    clock = [100.0]
    monkeypatch.setattr(ndof_input.time, "monotonic", lambda: clock[0])
    assert not dev.in_use()
    dev._emit_motion(NdofSample(right=0.03))      # resting noise
    assert not dev.in_use()
    dev._emit_motion(NdofSample(forward=0.5))
    assert dev.in_use()
    clock[0] += dev.WHEEL_QUIET_S - 0.05
    assert dev.in_use()
    clock[0] += 0.1
    assert not dev.in_use()
    # the dead zone is the user's: a wider one ignores a bigger resting drift
    monkeypatch.setattr(ndof_input, "current_settings",
                        lambda: NdofSettings(deadzone=0.2))
    dev._emit_motion(NdofSample(forward=0.15))
    assert not dev.in_use()
    dev._emit_motion(NdofSample(forward=0.25))
    assert dev.in_use()


def test_wheel_notches_do_not_zoom_while_the_cap_moves_the_view(monkeypatch):
    """3Dconnexion's driver turns a push of the cap into wheel notches for
    programs it does not know; with ours reading the device too, the view
    took a zoom step about eight times a second (12-10 video)."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from views import ndof_input
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(400, 300)

    def notch():
        QApplication.sendEvent(vp, QWheelEvent(
            QPointF(200, 150), QPointF(200, 150), QPoint(), QPoint(0, 120),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))

    class Busy:
        def in_use(self):
            return True

    monkeypatch.setattr(ndof_input, "_shared", Busy())
    d0 = vp.camera.distance
    notch()
    assert vp.camera.distance == d0
    monkeypatch.setattr(ndof_input, "_shared", None)
    notch()
    assert vp.camera.distance < d0                # an ordinary wheel zooms


# ---- configurable physical-axis mapping -------------------------------------

def test_original_preset_preserves_legacy_inversion():
    from core.ndof import mapped_movements
    st = NdofSettings(invert_pan_x=True)
    assert mapped_movements(NdofSample(right=1), st)["pan_x"] == -1


def test_custom_axis_can_drive_different_action():
    from core.ndof import mapped_movements
    st = NdofSettings(mapping_preset="custom")
    st.axis_mapping["right"] = "zoom"
    st.axis_mapping["forward"] = "pan_x"
    result = mapped_movements(NdofSample(right=1), st)
    assert result["zoom"] == 1
    assert result["pan_x"] == 0


def test_custom_inversion_and_per_axis_speed():
    from core.ndof import mapped_movements
    st = NdofSettings(mapping_preset="custom")
    st.axis_inversion["right"] = True
    st.axis_sensitivity["right"] = 0.5
    assert mapped_movements(NdofSample(right=1), st)["pan_x"] == pytest.approx(-0.5)


def test_duplicate_actions_sum_and_clamp():
    from core.ndof import mapped_movements
    st = NdofSettings(mapping_preset="custom")
    st.axis_mapping["up"] = "pan_x"
    result = mapped_movements(NdofSample(right=0.5, up=0.5), st)
    assert result["pan_x"] > 0.5
    assert mapped_movements(NdofSample(right=1, up=1), st)["pan_x"] == 1


def test_sixth_axis_can_be_assigned_and_rotation_lock_still_applies():
    st = NdofSettings(mapping_preset="custom")
    st.axis_mapping["roll"] = "orbit_x"
    cam, moved = _push(NdofSample(roll=1), cam=_cam(),
                       mapping_preset="custom", axis_mapping=st.axis_mapping)
    assert moved
    cam, moved = _push(NdofSample(roll=1), cam=_cam(),
                       mapping_preset="custom", axis_mapping=st.axis_mapping,
                       lock_rotation=True)
    assert not moved


def test_disabled_axis_does_nothing():
    st = NdofSettings(mapping_preset="custom")
    st.axis_mapping["right"] = "disabled"
    assert not _push(NdofSample(right=1), mapping_preset="custom",
                     axis_mapping=st.axis_mapping)[1]


def test_freecad_style_preset_matches_hardware_test():
    from core.ndof import FREECAD_MAPPING, FREECAD_INVERSION, mapped_movements
    st = NdofSettings(mapping_preset="freecad")
    assert FREECAD_MAPPING == {
        "right": "pan_x", "up": "zoom", "forward": "pan_y",
        "tilt": "orbit_y", "spin": "disabled", "roll": "orbit_x"}
    assert FREECAD_INVERSION["up"] and FREECAD_INVERSION["tilt"]
    output = mapped_movements(NdofSample(up=1, forward=1), st)
    assert output["zoom"] == -1 and output["pan_y"] == 1


def test_profile_json_round_trip(tmp_path):
    from core.ndof_profiles import save_profile, load_profile
    st = NdofSettings(mapping_preset="custom", sensitivity=1.75)
    st.axis_mapping["roll"] = "pan_y"
    st.axis_inversion["roll"] = True
    st.axis_sensitivity["roll"] = 2.25
    path = tmp_path / "custom.json"
    save_profile(path, st)
    loaded = load_profile(path)
    assert loaded.mapping_preset == "custom"
    assert loaded.axis_mapping == st.axis_mapping
    assert loaded.axis_inversion == st.axis_inversion
    assert loaded.axis_sensitivity == st.axis_sensitivity
    assert loaded.sensitivity == st.sensitivity


@pytest.mark.parametrize("change", [
    {"version": 99},
    {"mapping": {"right": "bad"}},
    {"inversion": {"right": "true"}},
    {"sensitivity": {"right": float("nan")}},
    {"global_speed": 100},
])
def test_profile_rejects_invalid_data(change):
    from core.ndof_profiles import profile_to_dict, profile_from_dict
    from copy import deepcopy
    data = profile_to_dict(NdofSettings())
    for key, value in change.items():
        if isinstance(value, dict):
            data[key].update(value)
        else:
            data[key] = value
    with pytest.raises(ValueError):
        profile_from_dict(data)


# ---- the default profile moves the camera exactly as before the mapping ------

def _legacy_movements(sample, st):
    """The five camera inputs as apply_ndof computed them before the
    axis mapping existed (main a369d1e), kept here as the reference."""
    right = shape(sample.right, st.deadzone)
    up = shape(sample.up, st.deadzone)
    forward = shape(sample.forward, st.deadzone)
    tilt = spin = 0.0
    if not st.lock_rotation:
        tilt = shape(sample.tilt, st.deadzone)
        spin = shape(sample.spin, st.deadzone)
    if st.invert_pan != st.invert_pan_x:
        right = -right
    if st.invert_pan != st.invert_pan_y:
        up = -up
    if st.invert_zoom:
        forward = -forward
    if st.invert_rotate != st.invert_tilt:
        tilt = -tilt
    if st.invert_rotate != st.invert_spin:
        spin = -spin
    return right, up, forward, tilt, spin


def _samples():
    vals = (-1.0, -0.7, -0.04, 0.0, 0.3, 1.0)   # from_raw clamps to ±1
    for i, r in enumerate(vals):
        for j, t in enumerate(vals):
            yield NdofSample(right=r, up=vals[(i + 1) % 6],
                             forward=vals[(i + 2) % 6], tilt=t,
                             spin=vals[(j + 3) % 6], roll=vals[(i + j) % 6])


@pytest.mark.parametrize("flags", range(128))
def test_the_default_profile_changes_nothing(flags):
    """Every combination of the old inversion boxes and the rotation lock,
    on a grid of deflections (roll included, which was always ignored):
    apply_ndof gets the same five inputs the old code computed (what it
    does with them is unchanged)."""
    names = ("invert_pan", "invert_zoom", "invert_rotate", "invert_pan_x",
             "invert_pan_y", "invert_tilt", "invert_spin")
    kw = {n: bool(flags >> k & 1) for k, n in enumerate(names)}
    for lock in (False, True):
        st = NdofSettings(lock_rotation=lock, **kw)
        assert st.mapping_preset == "original"
        for s in _samples():
            right, up, forward, tilt, spin = _legacy_movements(s, st)
            m = mapped_movements(s, st)
            if st.lock_rotation:
                m["orbit_x"] = m["orbit_y"] = 0.0
            assert (m["pan_x"], m["pan_y"], m["zoom"],
                    m["orbit_y"], m["orbit_x"]) == (right, up, forward,
                                                    tilt, spin)


def test_preferences_ok_untouched_keeps_the_motion(tmp_path, monkeypatch):
    """Opening Preferences and pressing OK without touching the 3D mouse
    page must not change how the cap moves the view, whatever the old
    inversion boxes said."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication([])
    import views.preferences_dialog as prefs_mod
    from views import ndof_input
    path = tmp_path / "p.ini"
    mk = lambda: QSettings(str(path), QSettings.IniFormat)   # noqa: E731
    monkeypatch.setattr(prefs_mod, "QSettings", mk)
    monkeypatch.setattr(ndof_input, "QSettings", mk, raising=False)
    import PySide6.QtCore as QtCore
    monkeypatch.setattr(QtCore, "QSettings", mk)
    st = mk()
    for key in ("invert_pan_x", "invert_tilt", "invert_zoom"):
        st.setValue(f"ndof/{key}", "1")
    st.setValue("ndof/sensitivity", 1.5)
    st.sync()
    before = ndof_input.load_settings()
    assert before.mapping_preset == "original"

    class _Win(QWidget):
        def __init__(self):
            super().__init__()

            class _VP:
                edit_rest_mode = "fade"

                def set_edit_rest_mode(self, mode):
                    self.edit_rest_mode = mode
            self.viewport = _VP()
            self._rest_actions = {}

    win = _Win()
    dlg = prefs_mod.PreferencesDialog(win)
    dlg.accept()
    after = ndof_input.load_settings()
    assert after.sensitivity == before.sensitivity
    for s in _samples():
        for lock in (False, True):
            before.lock_rotation = after.lock_rotation = lock
            assert mapped_movements(s, after) == mapped_movements(s, before)
            a, b = _cam(), _cam()
            apply_ndof(a, s, 0.05, 600, before)
            apply_ndof(b, s, 0.05, 600, after)
            assert (a.yaw, a.pitch, a.distance, a.target) == \
                   (b.yaw, b.pitch, b.distance, b.target)
