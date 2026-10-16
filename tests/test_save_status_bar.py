# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #623: Status bar feedback and progress when saving / exporting."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_save_shows_status_bar_message(tmp_path):
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        scene = win.viewport.scene
        scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                            QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
        save_path = tmp_path / "project.igz"
        win._do_save(save_path)
        msg = win.statusBar().currentMessage()
        assert "Saved" in msg
        assert "project.igz" in msg
    finally:
        win._confirm_discard = lambda *a, **k: True
        win.close()


def test_save_scene_progress_callback(tmp_path):
    from core.scene import Scene
    from formats import igz as igz_format

    scene = Scene()
    scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                        QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    ticks = []
    save_path = tmp_path / "test_prog.igz"
    igz_format.save_scene(scene, save_path, progress=lambda frac, text: ticks.append((frac, text)))
    assert len(ticks) >= 3
    assert any("Serializing" in t[1] for t in ticks)
    assert any(t[0] == 1.0 for t in ticks)
