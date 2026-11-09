# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The 3D Text dialog reads lengths in the model's unit (#287): someone
designing 3D-printed parts in millimetres was asked for the text height
and extrusion in metres. The parameters it returns stay in metres."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QDoubleSpinBox)

_app = QApplication.instance() or QApplication([])


def _run_dialog(monkeypatch, unit, typed, params=None):
    """Open the dialog in a ``unit`` document, note what the two length
    boxes show, type ``typed`` (height, thickness) and accept."""
    from core.units import apply_units
    from views.main_window import MainWindow
    win = MainWindow()
    seen = {}

    def fake_exec(dlg):
        boxes = dlg.findChildren(QDoubleSpinBox)
        seen["boxes"] = [b.text() for b in boxes]
        for box, text in zip(boxes, typed):      # typed, as a user does
            box.lineEdit().setText(text)
            box.interpretText()
        return QDialog.Accepted

    try:
        apply_units(win.viewport.scene, {"length": unit, "precision": 1})
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        out = win._text3d_dialog(params)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
    return seen["boxes"], out


def test_a_millimetre_model_asks_for_millimetres(monkeypatch):
    boxes, out = _run_dialog(monkeypatch, "mm", ("120", "8"))
    assert [b.replace(" ", "") for b in boxes] == ["250.0mm", "50.0mm"]
    assert out["height"] == pytest.approx(0.12)
    assert out["thickness"] == pytest.approx(0.008)


def test_editing_shows_the_text_in_the_model_unit(monkeypatch):
    boxes, out = _run_dialog(monkeypatch, "cm", ("30", "2"),
                             params={"text": "A", "height": 0.5,
                                     "thickness": 0.1})
    assert [b.replace(" ", "") for b in boxes] == ["50.0cm", "10.0cm"]
    assert out["height"] == pytest.approx(0.30)


def test_a_metre_model_is_as_before(monkeypatch):
    boxes, out = _run_dialog(monkeypatch, "m", ("0.4", "0.02"))
    assert [b.replace(" ", "") for b in boxes] == ["0.3m", "0.1m"] or \
        boxes[0].startswith("0.25")
    assert out["height"] == pytest.approx(0.4)
