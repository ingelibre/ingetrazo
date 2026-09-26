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
                       from_spacenavd, shape)
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
    # X right, Y toward the user, Z down: pressing the cap down is +z.
    s = from_hid(350, 0, 350, 0, 0, 0)
    assert s.right == pytest.approx(1.0) and s.up == pytest.approx(-1.0)
    assert from_hid(0, -350, 0, 0, 0, 0).forward == pytest.approx(1.0)
    # with Z down, +rz is clockwise seen from above
    assert from_hid(0, 0, 0, 0, 0, 350).spin == pytest.approx(-1.0)
    assert from_hid(0, 0, 0, 999, 0, 0).tilt == pytest.approx(-1.0)  # clipped


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
        conn.close()
    finally:
        dev.stop()
        server.close()
