# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A successful SKP import must be visible from the previous document's view."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D, QVector4D
from PySide6.QtWidgets import QMessageBox

from formats import skp as skp_format
from views.main_window import MainWindow


@pytest.fixture
def window():
    win = MainWindow()
    win.viewport.scene.clear()
    cam = win.viewport.camera
    cam.target = QVector3D(8.0, -23.0, 10.0)
    cam.distance = 0.19
    cam.yaw = 1.1
    cam.pitch = 0.45
    cam.set_aspect(600, 900)
    yield win
    win._saved_version = win.viewport.scene.version
    win.close()


def _payload():
    faces = [([(40.0, -180.0, z), (65.0, -180.0, z),
               (65.0, -145.0, z), (40.0, -145.0, z)], [], {})
             for z in (0.0, 5.0)]
    return {"groups": [{"name": "House", "faces": faces, "soft_edges": []}]}


def _assert_scene_fits_camera(window):
    lo, hi = window.viewport.scene.bounds()
    cam = window.viewport.camera
    mvp = cam.projection_matrix() * cam.view_matrix()
    for x in (lo.x(), hi.x()):
        for y in (lo.y(), hi.y()):
            for z in (lo.z(), hi.z()):
                clip = mvp.map(QVector4D(x, y, z, 1.0))
                assert clip.w() > 0
                assert all(abs(v / clip.w()) <= 1.001
                           for v in (clip.x(), clip.y(), clip.z()))


@pytest.mark.parametrize("opener", ["open_path", "import_skp_path"])
@pytest.mark.parametrize("projection", ["perspective", "parallel", "two_point"])
def test_skp_import_frames_geometry_far_from_the_old_view(
        window, monkeypatch, tmp_path, opener, projection):
    payload = _payload()
    monkeypatch.setattr(skp_format, "can_handle", lambda path: True)
    monkeypatch.setattr(window, "_parse_skp_threaded", lambda path, cb: (payload, None))
    cam = window.viewport.camera
    cam.set_projection(projection)

    assert getattr(window, opener)(tmp_path / "house.skp") is True

    scene = window.viewport.scene
    assert len(scene.groups) == 1 and len(scene.groups[0].mesh.faces) == 2
    # Project the imported bounds: all eight corners must be on screen,
    # including in a portrait viewport and with two-point perspective.
    _assert_scene_fits_camera(window)
    assert cam.projection_mode() == projection
    assert cam.yaw == 1.1 and cam.pitch == 0.45
    assert len(window.viewport.history.undo_stack) == 1
    window.viewport.history.undo()
    assert not scene.groups


def test_skp_import_frames_existing_geometry_together_with_the_new_model(
        window, monkeypatch, tmp_path):
    scene = window.viewport.scene
    scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                         QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    payload = _payload()
    monkeypatch.setattr(skp_format, "can_handle", lambda path: True)
    monkeypatch.setattr(window, "_parse_skp_threaded", lambda path, cb: (payload, None))

    assert window.import_skp_path(tmp_path / "house.skp") is True

    assert len(scene.mesh.faces) == 1 and len(scene.groups) == 1
    _assert_scene_fits_camera(window)
    assert len(window.viewport.history.undo_stack) == 1
    window.viewport.history.undo()
    assert len(scene.mesh.faces) == 1 and not scene.groups


@pytest.mark.parametrize("result", ["empty", "empty_with_existing_geometry",
                                   "unreadable", "error"])
def test_empty_or_failed_skp_import_keeps_the_camera(
        window, monkeypatch, tmp_path, result):
    path = tmp_path / "empty.skp"
    if result == "empty_with_existing_geometry":
        skp_format.apply_payload(window.viewport.scene, _payload())
    before_groups = list(window.viewport.scene.groups)
    payload, exc = {"empty": True}, None
    if result == "unreadable":
        payload, exc = None, skp_format.NeedsConverter(path, "skp")
    elif result == "error":
        payload, exc = None, ValueError("broken model")
    monkeypatch.setattr(skp_format, "can_handle", lambda path: True)
    monkeypatch.setattr(window, "_parse_skp_threaded", lambda path, cb: (payload, exc))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    cam = window.viewport.camera
    before = (QVector3D(cam.target), cam.distance, cam.yaw, cam.pitch)

    assert window.import_skp_path(path) is result.startswith("empty")

    assert (cam.target, cam.distance, cam.yaw, cam.pitch) == before
    assert window.viewport.scene.groups == before_groups
