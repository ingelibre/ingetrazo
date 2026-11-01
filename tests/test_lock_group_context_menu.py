# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Lock and Unlock from the right-click on the model (#782).

The Browser's padlock was the only way to lock a group, and the only way
back: a locked group refuses every click, so its right-click must find it
on its own (as a locked reference image's does) and offer Unlock."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

import views.main_window as mw  # noqa: E402
from core.group import Group  # noqa: E402
from core.history import LockCommand  # noqa: E402
from core.layers import Layer  # noqa: E402
from core.mesh import Mesh  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Menu(QMenu):
    opened: list = []

    def exec(self, *a, **k):            # noqa: A003
        _Menu.opened.append(self)


def _texts():
    return [a.text() for a in _Menu.opened[-1].actions()]


def _action(text):
    return next(a for a in _Menu.opened[-1].actions() if a.text() == text)


def _group(scene, name, x0=0.0):
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    g = Group(m, name)
    xf = QMatrix4x4()
    xf.translate(x0, 0, 0)
    g.xform = xf
    scene.groups.append(g)
    scene.version += 1
    return g


def _window(monkeypatch):
    _Menu.opened.clear()
    monkeypatch.setattr(mw, "QMenu", _Menu)
    win = mw.MainWindow()
    vp = win.viewport
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.camera.set_view("top")
    vp.camera.target = V(3, 1, 0)
    vp.camera.distance = 12
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_lock_locks_every_selected_group_in_one_step(monkeypatch):
    win = _window(monkeypatch)
    try:
        scene = win.viewport.scene
        a, b = _group(scene, "muro"), _group(scene, "losa", 4)
        scene.select([a, b])
        win.show_viewport_context_menu(QPoint(0, 0))
        assert "Lock" in _texts()
        _action("Lock").trigger()
        assert a.locked and b.locked
        assert a not in scene.selection and b not in scene.selection
        assert win.viewport.history.undo()           # one step for both
        assert not a.locked and not b.locked
    finally:
        _close(win)


def test_lock_leaves_the_edit_of_the_group_it_locks(monkeypatch):
    win = _window(monkeypatch)
    try:
        scene = win.viewport.scene
        g = _group(scene, "muro")
        win.viewport.begin_group_edit(g)
        assert scene.edit_group is g
        win._lock_groups([g])
        assert scene.edit_group is None and g.locked
    finally:
        _close(win)


def test_no_lock_entry_without_a_group(monkeypatch):
    win = _window(monkeypatch)
    try:
        scene = win.viewport.scene
        face = scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
        scene.select([face])
        win.show_viewport_context_menu(QPoint(0, 0))
        assert "Lock" not in _texts()
    finally:
        _close(win)


def test_the_locked_group_under_the_cursor_is_found_and_unlocked(monkeypatch):
    win = _window(monkeypatch)
    try:
        vp = win.viewport
        scene = vp.scene
        g = _group(scene, "muro")
        px = vp._world_to_pixel(V(1, 1, 0))
        assert vp.pick_group(*px) is g                # the block is built
        vp.history.execute(LockCommand([g], True))
        assert vp.pick_group(*px) is None             # still not pickable
        assert vp.pick_locked_group(*px) is g         # but the menu finds it
        empty = vp._world_to_pixel(V(3, 1, 0))
        assert vp.pick_locked_group(*empty) is None   # off the group
        win.show_viewport_context_menu(QPoint(0, 0), locked_group=g)
        assert "Unlock “muro”" in _texts()
        _action("Unlock “muro”").trigger()
        assert not g.locked and g in scene.selection
        assert vp.history.undo()                       # undoable
        assert g.locked
    finally:
        _close(win)


def test_an_unlocked_group_is_not_offered_for_unlock(monkeypatch):
    win = _window(monkeypatch)
    try:
        vp = win.viewport
        _group(vp.scene, "muro")
        px = vp._world_to_pixel(V(1, 1, 0))
        assert vp.pick_locked_group(*px) is None
    finally:
        _close(win)


def test_a_hidden_or_layer_locked_group_is_not_offered(monkeypatch):
    win = _window(monkeypatch)
    try:
        vp = win.viewport
        scene = vp.scene
        g = _group(scene, "muro")
        g.locked = True
        g.layer = "Capa"
        scene.layers.append(Layer("Capa", locked=True))
        scene.version += 1
        px = vp._world_to_pixel(V(1, 1, 0))
        assert vp.pick_locked_group(*px) is None       # its layer is locked
        scene.layers[-1].locked = False
        scene.version += 1
        assert vp.pick_locked_group(*px) is g
        scene.layers[-1].visible = False
        scene.version += 1
        assert vp.pick_locked_group(*px) is None       # its layer is hidden
    finally:
        _close(win)


def test_a_loose_face_in_front_hides_the_locked_group(monkeypatch):
    win = _window(monkeypatch)
    try:
        vp = win.viewport
        scene = vp.scene
        g = _group(scene, "muro")
        g.locked = True
        scene.mesh.add_face([V(0, 0, 1), V(2, 0, 1), V(2, 2, 1), V(0, 2, 1)])
        scene.version += 1
        px = vp._world_to_pixel(V(1, 1, 0))
        assert vp.pick_locked_group(*px) is None
    finally:
        _close(win)
