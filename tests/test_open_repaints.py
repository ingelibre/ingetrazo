# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Opening a document asks the view for a frame once it is in. Painting is
off while it loads, and turning it back on asks for none: the view stayed
black until the first click."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


def test_the_view_is_asked_to_paint_after_opening(tmp_path):
    from views.main_window import MainWindow
    scene = Scene()
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    scene.groups.append(Group(m, name="Caja"))
    path = tmp_path / "caja.igz"
    igz.save_scene(scene, path)
    win = MainWindow()
    try:
        asked = []
        orig = win.viewport.update

        def update(*a):
            asked.append(win.viewport.updatesEnabled())
            return orig(*a)
        win.viewport.update = update
        assert win.open_path(path)
        assert True in asked                 # a frame asked with paint on
        assert win.viewport.updatesEnabled()
        assert [g.name for g in win.viewport.scene.groups] == ["Caja"]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
