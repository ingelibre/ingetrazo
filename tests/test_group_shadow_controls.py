# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Entity Info shadow actions change the viewport and survive an IGZ save."""
from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core.group import Group, copy_group
from core.history import History
from core.scene import Scene
from formats.igz import load_into, save_scene


def _plate(name, size, height, component):
    group = Group(name=name)
    group.mesh.add_face([QVector3D(x, y, height) for x, y in (
        (-size, -size), (size, -size), (size, size), (-size, size))])
    if component:
        group.xform = QMatrix4x4()
        group.component = True
    return group


@pytest.mark.parametrize("fmt", ["json", "auto"])
def test_shadow_choices_are_instance_local_and_saved(tmp_path, fmt):
    scene = Scene()
    first = _plate("First", 1, 0, component=True)
    second = copy_group(first)
    scene.groups.extend([first, second])
    assert first.mesh is second.mesh
    assert first.casts_shadows and first.receives_shadows
    from core.history import GroupShadowCommand

    history = History(scene)
    history.execute(GroupShadowCommand([first], casting=True, enabled=False))
    history.execute(GroupShadowCommand([second], casting=False, enabled=False))
    assert history.undo() and second.receives_shadows
    assert history.redo() and not second.receives_shadows
    path = tmp_path / "shadows.igz"
    save_scene(scene, path, fmt=fmt)
    reopened = Scene()
    load_into(reopened, path)
    assert [(g.casts_shadows, g.receives_shadows) for g in reopened.groups] == [
        (False, True), (True, False),
    ]


def _pixels(image):
    rgba = image.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(rgba.constBits(), dtype=np.uint8).copy()


def _depth_pixels(vp):
    assert vp._frame_shadow is not None
    vp.makeCurrent()
    try:
        return _pixels(vp._frame_shadow.toImage())
    finally:
        vp.doneCurrent()


@pytest.mark.parametrize("component", [False, True])
def test_entity_info_shadow_buttons_change_the_correct_pass(component):
    from views.main_window import MainWindow
    from views.tray import Tray

    win = MainWindow()
    vp = win.viewport
    try:
        win.resize(1000, 700)
        win.show()
        QApplication.processEvents()
        if not vp.isValid():
            pytest.skip("No OpenGL viewport on this platform")
        vp._settle_shadow_fit = lambda *args: None
        receiver = _plate("Receiver", 5, 0, component)
        caster = _plate("Caster", 1, 2.5, component)
        vp.scene.groups.extend([receiver, caster])
        vp.scene.version += 1
        settings = vp.scene.shadows
        settings.enabled = True
        settings.month, settings.day, settings.hour = 6, 21, 12
        vp.camera.target = QVector3D(0, 0, 0.5)
        vp.camera.yaw = math.radians(-50)
        vp.camera.pitch = math.radians(58)
        vp.camera.distance = 13

        panel = win.findChild(Tray).entity_info
        vp.scene.select([receiver])
        panel.refresh()
        before = _pixels(vp.grabFramebuffer())
        depth = _depth_pixels(vp)
        panel._receive_shadows_button.click()
        assert not receiver.receives_shadows and receiver.casts_shadows
        assert np.count_nonzero(before != _pixels(vp.grabFramebuffer())) > 50
        assert np.array_equal(depth, _depth_pixels(vp))
        assert vp.history.undo() and receiver.receives_shadows

        vp.scene.select([caster])
        panel.refresh()
        before = _pixels(vp.grabFramebuffer())
        depth = _depth_pixels(vp)
        panel._cast_shadows_button.click()
        assert not caster.casts_shadows and caster.receives_shadows
        assert np.count_nonzero(before != _pixels(vp.grabFramebuffer())) > 50
        assert np.count_nonzero(depth != _depth_pixels(vp)) > 50
        assert vp.history.undo() and caster.casts_shadows
    finally:
        win._saved_version = vp.scene.version
        win.close()
