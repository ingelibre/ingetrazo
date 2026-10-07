"""Tray lists fit their rows; Layers has a compact, manually resizable default."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_tray_lists_fit_rows_and_layers_preserve_manual_height():
    from views.main_window import MainWindow
    from core.layers import Layer
    settings = QSettings()
    previous_height = settings.value("layers/panel_height")
    settings.remove("layers/panel_height")
    win = MainWindow()
    try:
        tray = win.tray
        for v in (tray.layers.tree, tray.scenes.list, tray.components._in_model):
            assert v.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        h0 = tray.layers.tree.height()
        scene = win.viewport.scene
        for i in range(8):
            scene.layers.append(Layer(name=f"capa {i}"))
        tray.layers.refresh()
        assert tray.layers.tree.height() > h0
        # Large layer sets keep the panel compact until the user resizes it.
        compact_height = tray.layers.tree.height()
        assert compact_height < 9 * tray.layers.tree.sizeHintForRow(0)
        assert tray.layers.tree.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        tray.layers._set_height(compact_height + 100)
        chosen_height = tray.layers.tree.height()
        scene.layers.append(Layer(name="another layer"))
        tray.layers.refresh()
        assert tray.layers.tree.height() == chosen_height
        assert chosen_height > compact_height
        h_empty = tray.scenes.list.height()
        assert h_empty >= 3 * (tray.scenes.list.fontMetrics().height())  # min rows
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
        if previous_height is None:
            settings.remove("layers/panel_height")
        else:
            settings.setValue("layers/panel_height", previous_height)
