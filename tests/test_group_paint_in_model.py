# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A material painted on a GROUP shows in the tray's «In the model» (#133,
@fafecm: it only appeared once the group was exploded)."""
from __future__ import annotations

import sys

from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _labels(panel):
    grid = panel._in_model_grid
    out = []
    for i in range(grid.count()):
        w = grid.itemAt(i).widget()
        if w is not None:
            out.append(w.toolTip() or w.text())
    return out


def test_a_painted_group_puts_its_material_in_the_model_list():
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        m = Mesh()
        m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
        g = Group(m, name="Caja")
        g.material = {"color": [0.8, 0.2, 0.2], "mat": "Ladrillo rojo"}
        scene.groups.append(g)
        from views.tray import MaterialsPanel
        panel = win.findChildren(MaterialsPanel)[0]
        panel.refresh_in_model()
        assert any("Ladrillo rojo" in t for t in _labels(panel))
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
