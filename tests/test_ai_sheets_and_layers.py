"""The assistant's code must not leave foreign objects in the scene's lists,
and it can make sheets of the composer with ``sheet()``. Asked for «dos
láminas», a model appended plain strings to ``layers``: the step went
through and every paint raised «'str' object has no attribute 'name'»."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import ai  # noqa: E402

app = QApplication.instance() or QApplication([])


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def test_a_string_in_layers_is_refused_and_rolled_back():
    win = _window()
    try:
        vp = win.viewport
        before = list(vp.scene.layers)
        r = ai.run_transactional(
            vp, "layers.append('Lámina 1')", {"__name__": "__ai__"})
        assert r["error"] is not None and not r["changed"]
        assert "Layer" in r["stderr"]
        assert list(vp.scene.layers) == before
        assert all(not isinstance(ly, str) for ly in vp.scene.layers)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_layer_is_in_the_scope_and_works():
    win = _window()
    try:
        vp = win.viewport
        r = ai.run_transactional(
            vp, "layers.append(Layer('Muros'))", {"__name__": "__ai__"})
        assert r["error"] is None and r["changed"]
        assert vp.scene.layers[-1].name == "Muros"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_sheet_makes_composer_sheets_with_one_undo_each():
    win = _window()
    try:
        vp = win.viewport
        n = len(vp.scene.compositions)
        r = ai.run_transactional(
            vp, "sheet('Planta'); sheet('Corte', paper='A4')",
            {"__name__": "__ai__"})
        assert r["error"] is None and r["changed"]
        names = [c.name for c in vp.scene.compositions[n:]]
        assert names == ["Planta", "Corte"]
        assert all(c.frames for c in vp.scene.compositions[n:])
        vp.history.undo()
        assert len(vp.scene.compositions) == n
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
