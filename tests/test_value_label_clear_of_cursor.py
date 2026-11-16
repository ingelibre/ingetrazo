# SPDX-License-Identifier: GPL-3.0-or-later
"""The live value label stays clear of the pointer (#1262).

On a short measurement the label (drawn by the middle of the segment)
sat right where the tool's cursor icon is, so the Tape's icon hid the
number. It now moves just right of the pointer, or below it at the
view's right edge, and stays where it was when nothing covers it."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QVector3D as V

from views.viewport import label_clear_of

_VIEW = QRectF(0, 0, 800, 600)


def test_a_label_the_pointer_does_not_touch_stays_put():
    text = QRectF(100, 100, 60, 16)
    pointer = QRectF(300, 300, 32, 32)
    assert label_clear_of(text, pointer, _VIEW) == text


def test_a_covered_label_moves_just_right_of_the_pointer():
    pointer = QRectF(400, 300, 32, 32)
    text = QRectF(410, 290, 60, 16)              # over the icon
    out = label_clear_of(text, pointer, _VIEW)
    assert not out.intersects(pointer)
    assert out.left() == pytest.approx(pointer.right() + 4)
    assert out.top() == text.top()               # same height
    assert out.size() == text.size()


def test_at_the_right_edge_it_goes_below_the_pointer():
    pointer = QRectF(760, 300, 32, 32)
    text = QRectF(770, 290, 60, 16)
    out = label_clear_of(text, pointer, _VIEW)
    assert not out.intersects(pointer)
    assert out.top() == pytest.approx(pointer.bottom() + 4)
    assert _VIEW.contains(out)


def test_in_the_bottom_right_corner_it_goes_above_the_pointer():
    pointer = QRectF(760, 580, 32, 32)
    text = QRectF(770, 570, 60, 16)
    out = label_clear_of(text, pointer, _VIEW)
    assert not out.intersects(pointer)
    assert out.bottom() < pointer.top()


@pytest.fixture
def view():
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow(defer_extensions=True)
    vp = win.viewport
    vp.resize(800, 600)
    vp.scene.mesh = Mesh()
    vp.scene.groups = []
    vp.scene.mesh.add_face([V(0, 0, 0), V(0.1, 0, 0), V(0.1, 0.1, 0),
                            V(0, 0.1, 0)])        # a 10 cm square
    vp.scene.version += 1
    vp.camera.set_aspect(800, 600)
    vp.camera.set_view("top")
    vp.camera.perspective = False
    vp.camera.fit_to(V(-0.5, -0.5, -0.01), V(0.6, 0.6, 0.01))
    yield win, vp
    win._saved_version = vp.scene.version
    win.close()


def _mouse(vp, kind, pixel, buttons=Qt.NoButton):
    ev = QMouseEvent(kind, QPointF(*pixel), QPointF(*pixel),
                     Qt.LeftButton if buttons else Qt.NoButton, buttons,
                     Qt.NoModifier)
    {QMouseEvent.MouseMove: vp.mouseMoveEvent,
     QMouseEvent.MouseButtonPress: vp.mousePressEvent,
     QMouseEvent.MouseButtonRelease: vp.mouseReleaseEvent}[kind](ev)


def test_a_few_millimetres_measured_with_the_tape_read_clear_of_its_icon(view):
    win, vp = view
    win._activate_tool("tape")
    tool = vp.active_tool
    a = vp._world_to_pixel(V(0.0, 0.0, 0.0))
    _mouse(vp, QMouseEvent.MouseMove, a)
    vp._run_pending_hover()
    _mouse(vp, QMouseEvent.MouseButtonPress, a, Qt.LeftButton)
    _mouse(vp, QMouseEvent.MouseButtonRelease, a)
    b = vp._world_to_pixel(V(0.003, 0.0, 0.0))  # 3 mm on: a few pixels
    _mouse(vp, QMouseEvent.MouseMove, b)
    vp._run_pending_hover()
    assert tool.start_point is not None and tool.hover_point is not None
    pointer = vp._pointer_rect()
    assert pointer is not None
    assert not vp.cursor().pixmap().isNull()      # the Tape's own icon
    img = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    try:
        vp._draw_length_label(p)
    finally:
        p.end()
    label = vp._length_label_rect
    assert not label.intersects(pointer), (label, pointer)
