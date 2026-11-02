"""Lists inside a tray grow to their rows instead of scrolling on their
own — the tray's scroll is the only one (Marco, 2026-09-14: «no me gusta
hacer scroll dentro del scroll»)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_scenes_and_components_lists_grow_with_their_rows():
    """(The Layers list has a tab of its own now, beside the Browser, and
    scrolls there like the Browser's tree.)"""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        tray = win.tray
        for v in (tray.scenes.list, tray.components._in_model):
            assert v.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        h_empty = tray.scenes.list.height()
        assert h_empty >= 3 * (tray.scenes.list.fontMetrics().height())  # min rows
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
