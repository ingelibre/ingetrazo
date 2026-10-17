# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Axes: the world's red/green/blue drawing axes can be switched off.
Only the world's: a group open for editing keeps showing its own axes. The
flag travels in the .igz (only when off) and a new or opened document
brings them back. The render checks need a GL context that really draws;
skipped where the platform has none or draws nothing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _square(x0, y0=0.0):
    m = Mesh()
    m.add_face([V(x0, y0, 0), V(x0 + 2, y0, 0), V(x0 + 2, y0 + 2, 0),
                V(x0, y0 + 2, 0)])
    return m


# ---- the document ----------------------------------------------------------

def test_axes_are_shown_by_default():
    assert Scene().show_axes is True


def test_hidden_axes_travel_in_the_file(tmp_path):
    s = Scene()
    s.mesh = _square(0)
    s.show_axes = False
    path = tmp_path / "sin-ejes.igz"
    igz.save_scene(s, path)
    assert b"axes_hidden" in path.read_bytes()
    back = Scene()
    igz.load_into(back, path)
    assert back.show_axes is False


def test_shown_axes_stay_implicit_and_older_files_open_with_them(tmp_path):
    s = Scene()
    s.mesh = _square(0)
    path = tmp_path / "con-ejes.igz"
    igz.save_scene(s, path)
    assert b"axes_hidden" not in path.read_bytes()
    back = Scene()
    back.show_axes = False               # left over from a previous document
    igz.load_into(back, path)
    assert back.show_axes is True


def test_a_new_document_brings_the_axes_back():
    s = Scene()
    s.mesh = _square(0)
    s.show_axes = False
    s.clear()
    assert s.show_axes is True


# ---- the menu --------------------------------------------------------------

def _window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    for _ in range(10):
        _app.processEvents()
    return w


def test_the_view_menu_switches_the_scene_flag():
    w = _window()
    try:
        act = w._act_show_axes
        assert act.isCheckable() and act.isChecked()
        camera_actions = [a for m in w.menuBar().actions() if m.menu()
                        for a in m.menu().actions()]
        assert act in camera_actions
        act.trigger()
        assert w.viewport.scene.show_axes is False
        act.trigger()
        assert w.viewport.scene.show_axes is True
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()


def test_alt_a_is_its_own_shortcut():
    """Alt+A switches the axes, and no other command of the window has it."""
    from PySide6.QtGui import QAction, QKeySequence, QShortcut
    w = _window()
    try:
        alt_a = QKeySequence("Alt+A")
        assert w._act_show_axes.shortcut() == alt_a
        others = [a.text() for a in w.findChildren(QAction)
                  if a is not w._act_show_axes and alt_a in a.shortcuts()]
        others += ["QShortcut" for s in w.findChildren(QShortcut)
                   if s.key() == alt_a]
        assert others == []
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()


def test_the_checkmark_follows_the_document():
    w = _window()
    try:
        w.viewport.scene.show_axes = False
        w._sync_section_menu()
        assert not w._act_show_axes.isChecked()
        assert w.viewport.scene.show_axes is False   # syncing did not write
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()


# ---- the render ------------------------------------------------------------

def _reddish_near(vp, p, radius=3):
    vp.update()
    _app.processEvents()
    img = vp.grabFramebuffer()
    x, y = vp._world_to_pixel(p)
    r = img.devicePixelRatio()
    cx, cy = int(x * r), int(y * r)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            c = img.pixelColor(cx + dx, cy + dy)
            if c.redF() > 0.6 and c.greenF() < 0.45 and c.blueF() < 0.5:
                return True
    return False


def test_hiding_drops_the_world_axes_but_an_open_group_keeps_its_own():
    w = _window()
    vp = w.viewport
    try:
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        sc = vp.scene
        sc.groups.clear()
        comp = Group(_square(-6, -1), name="caja")
        comp.xform = QMatrix4x4()
        comp.xform.translate(0, 5, 0)            # its own axes at (0, 5, 0)
        sc.groups.append(comp)
        sc.version += 1
        vp.camera.set_view("top")
        vp.camera.target = V(2, 2.5, 0)
        vp.camera.distance = 20

        on_world_x = V(3, 0, 0)
        if not _reddish_near(vp, on_world_x):
            pytest.skip("the platform draws nothing (offscreen GL)")
        w._act_show_axes.setChecked(False)
        assert not _reddish_near(vp, on_world_x)

        vp.begin_group_edit(comp)
        from core import axes as _axes
        vp.update()
        _app.processEvents()
        assert not _axes.is_world()
        assert _reddish_near(vp, V(3, 5, 0))     # the group's own red axis
        vp.end_group_edit()
        assert not _reddish_near(vp, on_world_x)  # back out: still hidden

        w._act_show_axes.setChecked(True)
        assert _reddish_near(vp, on_world_x)
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()
