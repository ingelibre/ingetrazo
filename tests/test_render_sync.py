# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Render ▸ «Sync with the view» (#181; Marco: «camine por el modelo, me
detenga y la ventana de la imagen del render automáticamente detecte y haga
el render»): one Blender kept open with the scene, a camera per request,
face-me figures turned in Blender instead of exporting again."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage, QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication([])

from core import render_blender as rb  # noqa: E402
from core.camera import OrbitCamera  # noqa: E402
from core.group import make_billboard_group  # noqa: E402
from core.scene import Scene  # noqa: E402

HAS_BLENDER = shutil.which("blender") is not None


def _box(scene):
    pts = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0),
           V(0, 0, 2), V(2, 0, 2), V(2, 2, 2), V(0, 2, 2)]
    for loop in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        scene.mesh.add_face([pts[i] for i in loop])


def _scene_with_figure(tmp_path):
    scene = Scene()
    _box(scene)
    img = QImage(16, 32, QImage.Format_ARGB32)
    img.fill(QColor(220, 40, 40, 255))
    img.save(str(tmp_path / "fig.png"))
    fig = make_billboard_group(str(tmp_path / "fig.png"), 1.7, "figure", 0.8)
    fig.xform = QMatrix4x4()
    fig.xform.translate(4, 1, 0)
    scene.groups.append(fig)
    return scene


def _camera(scene):
    cam = OrbitCamera()
    cam.set_aspect(320, 180)
    cam.yaw, cam.pitch = -1.0, 0.3
    lo, hi = scene.bounds()
    cam.fit_to(lo, hi)
    return cam


def _glb_json(path):
    data = Path(path).read_bytes()
    n = int.from_bytes(data[12:16], "little")
    return json.loads(data[20:20 + n])


def test_face_me_figures_travel_as_nodes_with_their_feet_and_heading(tmp_path):
    scene = _scene_with_figure(tmp_path)
    cam = _camera(scene)
    job = rb.write_job(scene, cam, tmp_path, serve=True)
    gltf = _glb_json(tmp_path / "model.glb")
    figures = [n for n in gltf["nodes"] if "extras" in n]
    assert len(figures) == 1 and len(gltf["nodes"]) == 2
    fx, fy, fz, yaw = figures[0]["extras"]["ingetrazo_faceme"]
    assert (round(fx, 3), round(fy, 3), round(fz, 3)) == (4.0, 1.0, 0.0)
    eye = cam.eye()
    import math
    assert yaw == pytest.approx(math.atan2(eye.y() - fy, eye.x() - fx))
    spec = json.loads(Path(job).read_text())
    assert spec["serve"] is True and spec["blend"] is None


def test_a_file_export_without_camera_brings_the_figure_standing(tmp_path):
    """A file has no camera, and the figures used to stay out of it; a
    user wants them in (#353): the model and the figure are nodes of their
    own, the figure standing toward the Front view and tagged as one."""
    from formats.gltf import save_glb
    scene = _scene_with_figure(tmp_path)
    save_glb(scene, tmp_path / "plain.glb")
    nodes = _glb_json(tmp_path / "plain.glb")["nodes"]
    figures = [n for n in nodes if "ingetrazo_faceme" in n.get("extras", {})]
    assert len(figures) == 1 and len(nodes) == 2


def test_a_sync_request_is_one_line_with_the_camera_and_a_draft_quality():
    scene = Scene()
    _box(scene)
    cam = _camera(scene)
    line = rb.sync_request(cam, "/tmp/x.png", 960, 540, "cycles")
    assert line.endswith("\n") and line.count("\n") == 1
    req = json.loads(line)
    assert req["camera"] == rb.camera_dict(cam)
    assert req["samples"] == rb.SYNC_SAMPLES["cycles"]
    assert (req["width"], req["height"]) == (960, 540)


def test_the_camera_key_changes_with_the_camera_only():
    scene = Scene()
    _box(scene)
    cam = _camera(scene)
    key = rb.camera_key(cam)
    assert rb.camera_key(cam) == key
    cam.yaw += 0.1
    assert rb.camera_key(cam) != key


# ---- The panel ------------------------------------------------------------------

@pytest.fixture
def window(monkeypatch):
    from core import extensions
    from core.paths import app_root
    monkeypatch.setattr(extensions, "plugin_dirs",
                        lambda: [app_root() / "plugins"])
    if not HAS_BLENDER:
        monkeypatch.setattr(rb, "find_blender",
                            lambda saved=None: rb.BlenderFound(
                                ["/x/blender"], "/x/blender"))
    from views.main_window import MainWindow
    win = MainWindow()
    yield win
    for panel in _panels(win):
        panel._sync.stop()
    win._saved_version = win.viewport.scene.version
    win.close()


def _panels(win):
    return [w for d in win._extension_docks
            for w in [d.widget()] if type(w).__name__ == "RenderPanel"]


def test_selecting_does_not_reload_the_synced_scene(window):
    panel = _panels(window)[0]
    scene = window.viewport.scene
    _box(scene)
    scene.version += 1
    key = panel._sync_scene_key()
    scene.select([next(iter(scene.mesh.faces))])
    assert panel._sync_scene_key() == key          # only the view changed
    scene.mesh.add_face([V(5, 0, 0), V(6, 0, 0), V(6, 1, 0)])
    scene.version += 1
    assert panel._sync_scene_key() != key


def test_no_draft_while_a_mouse_button_is_held(window, monkeypatch):
    panel = _panels(window)[0]
    sync = panel._sync
    calls = []
    monkeypatch.setattr(sync, "_load", lambda key: calls.append(key))
    monkeypatch.setattr(QApplication, "mouseButtons",
                        staticmethod(lambda: __import__(
                            "PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton))
    sync._seen_key = rb.camera_key(window.viewport.camera)
    sync._still_since = time.monotonic() - 10
    sync._poll()
    assert calls == []
    monkeypatch.setattr(QApplication, "mouseButtons",
                        staticmethod(lambda: __import__(
                            "PySide6.QtCore", fromlist=["Qt"]).Qt.NoButton))
    sync._still_since = time.monotonic() - 10
    sync._poll()
    assert len(calls) == 1


def _run(seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until is not None else True


@pytest.mark.slow
@pytest.mark.skipif(not HAS_BLENDER, reason="no Blender on this machine")
def test_a_real_blender_follows_the_camera_when_it_rests(window):
    panel = _panels(window)[0]
    _box(window.viewport.scene)
    window.viewport.scene.version += 1
    images = []
    panel._sync.image.connect(images.append)
    panel._sync_box.setChecked(True)
    assert _run(120, lambda: len(images) >= 1), "no first draft"
    assert panel._viewer is not None and panel._viewer.sync_box.isChecked()
    _run(1.5)
    assert len(images) == 1                        # at rest: nothing new
    window.viewport.camera.yaw += 0.7
    assert _run(60, lambda: len(images) >= 2), "no draft after moving"
    assert images[-1].is_file() and images[-1] != images[0]
    panel._viewer.close()
    _run(0.5)
    assert not panel._sync.active and not panel._sync_box.isChecked()
    assert panel._sync._proc is None


@pytest.mark.slow
@pytest.mark.skipif(not HAS_BLENDER, reason="no Blender on this machine")
def test_a_serving_blender_renders_each_camera_and_quits(tmp_path):
    scene = _scene_with_figure(tmp_path)
    cam = _camera(scene)
    job = rb.write_job(scene, cam, tmp_path, width=160, height=90,
                       serve=True)
    proc = subprocess.Popen(rb.command(rb.find_blender(), job),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, env=rb.clean_env())
    seen = []

    def until(tag):
        for line in proc.stdout:
            seen.append(line)
            if line.startswith("INGETRAZO " + tag):
                return line
        raise AssertionError("".join(seen[-30:]))

    until("ready")
    assert any(line.startswith("INGETRAZO figures 1") for line in seen)
    for i, yaw in enumerate((-1.0, 1.2)):
        cam.yaw = yaw
        proc.stdin.write(rb.sync_request(cam, tmp_path / f"s{i}.png",
                                         160, 90))
        proc.stdin.flush()
        until("done")
        assert (tmp_path / f"s{i}.png").is_file()
    proc.stdin.write('{"quit": true}\n')
    proc.stdin.flush()
    assert proc.wait(60) == 0
