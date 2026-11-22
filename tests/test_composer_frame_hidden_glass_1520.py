# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A sheet frame whose scene hides a layer hides that layer's GLASS too
(issue #1520). The composer switches the frame's layers on and off
without a version bump; the instanced placements re-key on the layer
states by themselves, but translucent faces never draw instanced — they
ride the consolidated buffers, which were kept for as long as the scene
version held. So the frame drew the glass the LIVE layers showed: right
after opening a file (every layer on) a ground-floor window pane floated
in the attic's 3D view, correct only after a refresh.

The rendering case needs a GL context; skipped where there is none."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D as V
from PySide6.QtWidgets import QApplication, QWidget

from core.layers import Layer
from core.saved_views import SavedView

_app = QApplication.instance() or QApplication([])


def _rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    buf = np.frombuffer(img.constBits(), np.uint8)
    px = buf.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return px.reshape(img.height(), img.width(), 4)[..., :3].astype(np.int32)


def _pane(scene, layer):
    """A 2 × 2 m blue glass pane as a GROUP on *layer* — a window's glass."""
    from core.group import Group
    from core.mesh import Mesh
    group = Group(Mesh(), name="Glass")
    group.layer = layer
    face = group.mesh.add_face([V(-1, 0, 0), V(1, 0, 0), V(1, 0, 2),
                                V(-1, 0, 2)])
    face.attrs["color"] = [0.1, 0.2, 0.9]
    face.attrs["opacity"] = 0.6
    scene.groups.append(group)


def test_the_frame_rebuilds_the_buffers_its_layers_change():
    """GL-free: entering and leaving a frame asks the viewport to look at
    the layers again (the content key decides whether anything is rebuilt)."""
    from tests.test_composer_canvas import _FakeViewport
    from views.composer import ComposerWindow
    host = QWidget()
    host.viewport = _FakeViewport()
    seen = []

    def render_image(w, h, overlays=True, sharp_shadows=False):
        seen.append(host.viewport._edges_version)
        return None

    host.viewport.render_image = render_image
    comp = ComposerWindow(host)
    try:
        comp._auto_render = False
        frame = comp.comp.frames[0]
        host.viewport._edges_version = 7
        comp.render_frame(frame)
        assert seen == [-1]                       # stale inside the frame
        assert host.viewport._edges_version == -1  # and after it
    finally:
        comp.close()


def test_a_frame_hides_the_glass_of_a_layer_its_scene_hides():
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        win.show()
        _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        scene = vp.scene
        scene.layers.append(Layer("EG"))                  # on in the model
        _pane(scene, "EG")
        scene.version += 1
        scene.saved_views.append(SavedView(
            "Ohne EG", target=(0.0, 0.0, 1.0), distance=8.0, yaw=0.0,
            pitch=0.0, perspective=False, hidden_layers=["EG"]))
        comp = ComposerWindow(win)
        comp._auto_render = False
        frame = comp.comp.frames[0]
        frame.view_key = "scene:Ohne EG"
        eg = next(ly for ly in scene.layers if ly.name == "EG")

        def render():
            # The live view draws first, with ITS layers: the buffers the
            # frame used to inherit.
            vp.repaint()
            _app.processEvents()
            comp.render_cache.clear()
            return _rgb(comp.render_frame(frame))

        with_eg_live = render()
        eg.visible = False
        scene.bump_view()
        without_eg_live = render()
        changed = np.abs(with_eg_live - without_eg_live).sum(axis=2) > 30
        assert changed.sum() == 0, "the hidden layer's glass is in the frame"
        assert eg.visible is False
        eg.visible = True
        scene.bump_view()
        assert (np.abs(render() - without_eg_live).sum(axis=2) > 30).sum() == 0

        # And the live view gets its own glass back after the frame.
        live = _rgb(vp.render_image(320, 240, overlays=False))
        eg.visible = False
        scene.bump_view()
        hidden = _rgb(vp.render_image(320, 240, overlays=False))
        assert (np.abs(live - hidden).sum(axis=2) > 30).sum() > 0
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
