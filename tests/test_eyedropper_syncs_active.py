# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The eyedropper refreshes the Materials panel's «Activo» swatch.

After sampling a face (Alt, or the toolbar pipette) the swatch and the
texture size fields must say what the next click paints (issue #47). The
call went to the tray dock, which has no ``sync_from_paint`` — the method
lives on its Materials panel — so nothing ever refreshed."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from tools.base import ToolContext                                # noqa: E402
from tools.paint import PaintTool                                 # noqa: E402


@pytest.fixture(autouse=True)
def _reset_paint_state():
    saved = (PaintTool.current_color, PaintTool.current_texture,
             PaintTool.current_texture_plane, PaintTool.current_material,
             PaintTool.current_opacity, PaintTool.current_is_default)
    yield
    (PaintTool.current_color, PaintTool.current_texture,
     PaintTool.current_texture_plane, PaintTool.current_material,
     PaintTool.current_opacity, PaintTool.current_is_default) = saved


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win


def _sample(win, face, monkeypatch):
    vp = win.viewport
    monkeypatch.setattr(vp, "pick_face_any", lambda *_a: (face, None))
    monkeypatch.setattr(vp, "_pixel_to_ray", lambda *_a: (None, None))
    PaintTool().on_click(ToolContext(viewport=vp, world=QVector3D(),
                                     screen=QPointF(0, 0),
                                     modifiers=Qt.AltModifier, snap=None))


def _quad(win):
    return win.viewport.scene.mesh.add_face(
        [QVector3D(0, 0, 0), QVector3D(4, 0, 0),
         QVector3D(4, 4, 0), QVector3D(0, 4, 0)])


def test_sampled_colour_shows_in_the_active_swatch(monkeypatch):
    from views.tray import _color_pixmap
    win = _window()
    panel = win.tray.materials
    PaintTool.current_texture = None
    PaintTool.current_is_default = False
    PaintTool.current_color = (0.8, 0.45, 0.3)
    panel._refresh_preview()

    face = _quad(win)
    face.attrs["color"] = (0.1, 0.6, 0.2)
    _sample(win, face, monkeypatch)

    assert PaintTool.current_color == (0.1, 0.6, 0.2)
    shown = panel._preview.pixmap().toImage()
    assert shown == _color_pixmap((0.1, 0.6, 0.2)).toImage()
    win.close()


def test_sampled_texture_loads_the_size_fields(monkeypatch):
    win = _window()
    panel = win.tray.materials
    panel._sw_box.setValue(1.0)
    panel._sh_box.setValue(1.0)
    panel._rot_box.setValue(0.0)

    face = _quad(win)
    face.attrs["texture"] = {"path": "/no/such/ladrillo.png",
                             "sw": 2.5, "sh": 0.75, "rot": 30.0}
    _sample(win, face, monkeypatch)

    assert PaintTool.current_texture["sw"] == 2.5
    assert panel._sw_box.value() == pytest.approx(2.5)
    assert panel._sh_box.value() == pytest.approx(0.75)
    assert panel._rot_box.value() == pytest.approx(30.0)
    win.close()
