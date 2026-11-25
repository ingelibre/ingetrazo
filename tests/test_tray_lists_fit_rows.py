"""Lists inside a tray grow to their rows instead of scrolling on their
own — the tray's scroll is the only one (Marco, 2026-09-14: «no me gusta
hacer scroll dentro del scroll»)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_components_list_grows_with_its_rows():
    """(The Layers and Scenes lists have tabs of their own now, beside the
    Browser, and scroll there like the Browser's tree — #1158.)"""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        v = win.tray.components._in_model
        assert v.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        h_empty = v.height()
        assert h_empty >= 3 * v.fontMetrics().height()  # min rows
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
