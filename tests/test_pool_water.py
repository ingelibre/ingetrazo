# SPDX-License-Identifier: GPL-3.0-or-later
"""Pool water is a native translucent paint in both material pickers."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QToolButton

from core.i18n import tr
from core.scene import Scene
from formats.igz import load_into, save_scene
from tools.base import ToolContext
from tools.paint import PaintTool
from views.outliner import library_catalog


def test_water_library_keeps_calm_water_and_adds_one_static_pool_material():
    entries = dict(library_catalog())[tr("Water")]
    assert [label for label, _paint, _swatch in entries] == ["water_calm", tr("Pool Water")]
    _, calm, _ = entries[0]
    assert calm["texture"]["sw"] == calm["texture"]["sh"] == 2.0
    assert calm["opacity"] == 0.75
    _, pool, swatch = entries[1]
    assert pool["texture"]["sw"] == pool["texture"]["sh"] == 3.0
    assert pool["opacity"] == 0.62
    assert Path(pool["texture"]["path"]).is_file()
    assert swatch() is not None


def test_pool_swatch_paints_undoes_and_embeds_its_texture(tmp_path, monkeypatch):
    from views.main_window import MainWindow

    paint_state = {key: value for key, value in vars(PaintTool).items()
                   if key.startswith("current_")}
    win = MainWindow()
    vp = win.viewport
    try:
        root = win.tray.materials.layout()
        section = next(root.itemAt(i).widget() for i in range(root.count())
                       if isinstance(root.itemAt(i).widget(), QToolButton)
                       and root.itemAt(i).widget().text().strip() == tr("Water") + "  (2)")
        section.setChecked(True)
        QApplication.processEvents()
        swatch = next(button for button in win.tray.materials.findChildren(QToolButton)
                      if button.toolTip() == tr("Pool Water"))
        face = vp.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(4, 0, 0),
                                       QVector3D(4, 4, 0), QVector3D(0, 4, 0)])
        before = (vp.scene.version, len(vp.history.undo_stack), dict(vp.scene.materials))
        swatch.click()
        assert before == (vp.scene.version, len(vp.history.undo_stack), dict(vp.scene.materials))
        assert isinstance(vp.active_tool, PaintTool)
        monkeypatch.setattr(vp, "pick_face_any", lambda *_: (face, None))
        vp.active_tool.on_click(ToolContext(
            viewport=vp, world=QVector3D(2, 2, 0), screen=QPointF(100, 100),
            modifiers=Qt.NoModifier, snap=None))
        assert face.attrs["mat"] == tr("Pool Water")
        assert face.attrs["opacity"] == 0.62
        assert len(vp.history.undo_stack) == before[1] + 1
        vp.history.undo()
        assert not face.attrs
        vp.history.redo()
        path = tmp_path / "pool.igz"
        save_scene(vp.scene, path)
        loaded = Scene()
        load_into(loaded, path)
        pool = loaded.materials[tr("Pool Water")]
        assert pool.opacity == 0.62
        assert pool.texture["sw"] == pool.texture["sh"] == 3.0
        embedded = Path(pool.texture["path"])
        assert embedded.is_file()
        assert embedded.read_bytes() == Path(PaintTool.current_texture["path"]).read_bytes()
    finally:
        win._saved_version = vp.scene.version
        win.close()
        for key, value in paint_state.items():
            setattr(PaintTool, key, value)
