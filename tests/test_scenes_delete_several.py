# SPDX-License-Identifier: GPL-3.0-or-later
"""Several scenes deleted at once, in one undo step (#280).

The Scenes list took one scene at a time, and deleting one could not be
undone. Ctrl/Shift+click now picks several, − (or Delete) removes them
all, and Undo brings each back in its place."""
from __future__ import annotations

from core.saved_views import SavedView


def test_three_of_four_scenes_go_and_come_back():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        cam = win.viewport.camera
        views = [SavedView.capture(f"S{i}", scene, cam) for i in range(4)]
        scene.saved_views[:] = list(views)
        panel = win.tray.scenes
        panel.refresh()
        for i in (0, 2, 3):
            panel.list.item(i).setSelected(True)
        panel._on_delete()
        assert [v.name for v in scene.saved_views] == ["S1"]
        assert panel.list.count() == 1
        win._on_undo()                       # Ctrl+Z, as the user does
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        assert [v.name for v in scene.saved_views] == ["S0", "S1", "S2", "S3"]
        assert panel.list.count() == 4       # the list follows the undo
        win.viewport.history.redo()
        assert [v.name for v in scene.saved_views] == ["S1"]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
