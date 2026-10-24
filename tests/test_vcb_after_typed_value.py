# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #607 (Tim Burton): a rectangle typed as «1 3/8";1 9/16"» + Enter
was drawn at exactly that size, but the measurements box went on showing
the mouse preview it had before the Enter («102 61/64", 122 3/64"»): it
only refreshed on the next mouse move. In the default view a 4 cm
rectangle is too small to see, so the box was all the user had to go by,
and it said the typed size had been ignored. After a typed value commits,
the box shows what was typed."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import units  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.viewport.scene.units = {"length": "in-frac", "precision": 4}
    units.bind_scene(w.viewport.scene)
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()
    units.bind_scene(None)


def _flush(win):
    win._flush_status_texts()


def _rectangle_preview(win):
    vp = win.viewport
    win._activate_tool("rectangle")
    tool = vp.active_tool
    tool.start_point = QVector3D(0, 0, 0)
    tool.hover_point = QVector3D(2.615, 3.1, 0)      # a big mouse preview
    vp.measurementChanged.emit(vp._measurement_text())
    _flush(win)
    return vp, tool


def _enter(vp, typed):
    vp._set_value_buffer(typed)
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r"))


def test_the_box_shows_the_typed_size_not_the_old_preview(win):
    vp, _tool = _rectangle_preview(win)
    preview = win._vcb_value.text()
    assert "102" in preview                         # the mouse preview
    _enter(vp, '1 3/8";1 9/16"')
    _flush(win)
    face = vp.scene.mesh.faces[-1]
    xs = sorted({round(v.x(), 7) for v in face.vertices})
    ys = sorted({round(v.y(), 7) for v in face.vertices})
    assert xs == pytest.approx([0.0, 0.034925], abs=1e-6)     # 1 3/8"
    assert ys == pytest.approx([0.0, 0.0396875], abs=1e-6)    # 1 9/16"
    assert win._vcb_value.text() != preview
    assert win._vcb_value.text() == '1 3/8";1 9/16"'


def test_millimetres_typed_in_an_inch_document_are_kept_exactly(win):
    vp, _tool = _rectangle_preview(win)
    _enter(vp, "39.7mm;35mm")
    face = vp.scene.mesh.faces[-1]
    xs = sorted({round(v.x() * 1000, 3) for v in face.vertices})
    ys = sorted({round(v.y() * 1000, 3) for v in face.vertices})
    assert xs == [0.0, 39.7] and ys == [0.0, 35.0]
    _flush(win)
    assert win._vcb_value.text() == "39.7mm;35mm"



def test_a_bare_number_reads_in_the_document_unit_as_on_the_canvas(win):
    vp = win.viewport
    win.viewport.scene.units = {"length": "mm", "precision": 0}
    units.bind_scene(vp.scene)
    win._activate_tool("rectangle")
    tool = vp.active_tool
    tool.start_point = QVector3D(0, 0, 0)
    tool.hover_point = QVector3D(2.0, 3.0, 0)
    _enter(vp, "400;300")
    _flush(win)
    assert win._vcb_value.text() == units.typed_value_text("400;300") == "400;300 mm"


def test_a_hot_retype_shows_its_value_not_the_one_it_replaced(win):
    # Seen in a tutorial (#859): a push committed at 4.04 m, then «15» +
    # Enter with the tool idle redid it at 15 m, and the box went back to
    # «4.04 m». The retype undoes and re-commits, so the stack keeps its
    # length — "did something get drawn?" must see the new top command.
    from PySide6.QtCore import QPointF
    from tools.base import ToolContext
    vp = win.viewport
    vp.scene.units = {"length": "m", "precision": 2}
    units.bind_scene(vp.scene)
    V = QVector3D
    vp.scene.mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 3, 0), V(0, 3, 0)])
    vp.scene.version += 1
    win._activate_tool("pushpull")
    tool = vp.active_tool
    tool.hovered_face = vp.scene.mesh.faces[0]
    tool.on_click(ToolContext(viewport=vp, world=V(), screen=QPointF(0, 0),
                              modifiers=Qt.NoModifier, snap=None))
    assert tool.dragging
    _enter(vp, "2")                       # typed mid-drag: commits 2 m
    _flush(win)
    assert not tool.dragging
    assert win._vcb_value.text() == units.typed_value_text("2")
    depth = len(vp.history.undo_stack)
    _enter(vp, "3")                       # idle: the hot retype
    _flush(win)
    assert len(vp.history.undo_stack) == depth         # replaced, not stacked
    assert max(v.z() for f in vp.scene.mesh.faces for v in f.vertices) \
        == pytest.approx(3.0)
    assert win._vcb_value.text() == units.typed_value_text("3")
