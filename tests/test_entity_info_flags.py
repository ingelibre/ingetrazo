# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Entity Info — the Hidden and Locked checkboxes on a group or component."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core.group import Group
from core.mesh import Mesh


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win


def test_entity_info_offers_hidden_and_locked_checkboxes():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        panel = win.tray.entity_info

        scene.select([g])
        panel.refresh()
        assert panel._hidden_check.isVisibleTo(panel)
        assert panel._locked_check.isVisibleTo(panel)
        assert not panel._hidden_check.isChecked()
        assert not panel._locked_check.isChecked()

        # Lock: one undo step, and the object leaves the selection.
        panel._locked_check.setChecked(True)
        assert g.locked and g not in scene.selection
        vp.history.undo()
        assert not g.locked

        # Hide: the same, but the object stops drawing too.
        scene.select([g])
        panel.refresh()
        panel._hidden_check.setChecked(True)
        assert g.hidden and g not in scene.selection
        vp.history.undo()
        assert not g.hidden
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_soft_checkbox_edits_selected_edges_with_undo_and_redo():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        face = scene.mesh.add_face([
            QVector3D(0, 0, 0), QVector3D(1, 0, 0),
            QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
        edges = scene.mesh.edges[:2]
        panel = win.tray.entity_info
        assert not panel._soft_check.isVisibleTo(panel)

        scene.select([edges[0]])
        panel.refresh()
        assert panel._soft_check.isVisibleTo(panel)
        assert panel._soft_check.checkState() == Qt.Unchecked
        panel._soft_check.click()
        assert edges[0].soft and not edges[1].soft
        assert panel._soft_check.checkState() == Qt.Checked

        scene.select([face, *edges])
        panel.refresh()
        assert panel._soft_check.checkState() == Qt.PartiallyChecked
        panel._soft_check.click()
        assert all(edge.soft for edge in edges)
        assert panel._soft_check.checkState() == Qt.Checked
        win._on_undo()
        assert edges[0].soft and not edges[1].soft
        assert panel._soft_check.checkState() == Qt.PartiallyChecked
        win._on_redo()
        assert all(edge.soft for edge in edges)
        assert panel._soft_check.checkState() == Qt.Checked
        panel._soft_check.click()
        assert not any(edge.soft for edge in edges)
        assert panel._soft_check.checkState() == Qt.Unchecked

        scene.select([face])
        panel.refresh()
        assert not panel._soft_check.isVisibleTo(panel)
    finally:
        win._saved_version = vp.scene.version
        win.close()
