# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet cotas: double-click edits the text, <> stands for the value."""
from __future__ import annotations

from core.composition import CotaItem


def test_cota_text_placeholder_expands_to_the_value():
    ct = CotaItem(dx_mm=80.0, dy_mm=0.0, scale_n=100.0)
    assert ct.label() == "8.00 m"
    ct.text = "H = <> (verificar)"
    assert ct.label() == "H = 8.00 m (verificar)"
    ct.text = "VARIABLE"
    assert ct.label() == "VARIABLE"


def test_double_click_edits_the_cota_text(monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from views.composer import ComposerWindow, CotaCanvasItem
    from views.main_window import MainWindow

    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        ct = CotaItem(x_mm=30.0, y_mm=30.0, dx_mm=60.0, dy_mm=0.0,
                      scale_n=40.0)
        comp.comp.cotas.append(ct)
        comp._rebuild_canvas()
        item = next(it for it in comp.canvas.items()
                    if isinstance(it, CotaCanvasItem) and it.model is ct)
        asked = {}

        def fake_get_text(parent, title, label, text="", **kw):
            asked["prefill"] = text
            return asked["answer"], True
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(fake_get_text))

        asked["answer"] = "H = <>"
        comp.edit_cota_text(item)
        assert asked["prefill"] == "2.40 m"              # shows the value
        assert ct.text == "H = <>" and ct.label() == "H = 2.40 m"
        comp.history.undo()
        assert ct.text == ""
        comp.history.redo()

        asked["answer"] = "<>"                           # back to automatic
        comp.edit_cota_text(item)
        assert asked["prefill"] == "H = <>"
        assert ct.text == "" and ct.label() == "2.40 m"
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
