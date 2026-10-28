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


def test_export_ifc_cancel_does_not_export(monkeypatch):
    import core.bim
    from formats import ifc as ifc_format
    from views.filedialogs import file_dialogs
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        monkeypatch.setattr(core.bim, "collect_objects", lambda scene: [object()])
        monkeypatch.setattr(file_dialogs, "getSaveFileName", lambda *a, **k: ("", ""))
        saved = []
        monkeypatch.setattr(ifc_format, "save_ifc", lambda scene, path: saved.append(path))
        win._on_export_ifc()
        assert not saved
        assert "IFC elements exported" not in win.statusBar().currentMessage()
    finally:
        win._confirm_discard = lambda *a, **k: True
        win.close()


def test_export_shows_status_bar_message(tmp_path, monkeypatch):
    from views.filedialogs import file_dialogs
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        out_path = tmp_path / "model.obj"
        monkeypatch.setattr(file_dialogs, "getSaveFileName", lambda *a, **k: (str(out_path), ""))
        called = []
        win._export("OBJ", "obj", "OBJ (*.obj)", lambda scene, path: called.append(path))
        assert len(called) == 1
        msg = win.statusBar().currentMessage()
        assert "Exported OBJ" in msg
        assert "model.obj" in msg
    finally:
        win._confirm_discard = lambda *a, **k: True
        win.close()


def test_save_shows_status_bar_message_with_missing_textures(tmp_path, monkeypatch):
    from formats import igz as igz_format
    from PySide6.QtWidgets import QMessageBox
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        save_path = tmp_path / "warn_proj.igz"
        monkeypatch.setattr(igz_format, "save_scene", lambda *a, **k: {"embedded": 0, "missing": 2})
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
        win._do_save(save_path)
        msg = win.statusBar().currentMessage()
        assert "Saved" in msg
        assert "warn_proj.igz" in msg
        assert "Saving" not in msg
    finally:
        win._confirm_discard = lambda *a, **k: True
        win.close()

