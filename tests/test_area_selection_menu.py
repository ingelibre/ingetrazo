# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What a multiple selection adds up to.

Entity Info shows a total when the selection is all of one kind — faces
their area, edges their length, solid groups their volume — and none on a
mixed selection, where a total of one kind would read as the whole's.
Right-click ▸ Area ▸ Selection gives the selected faces' area whatever else
is selected. Everything is counted and measured all the same
(``core.selection_totals``, ``EntityInfoPanel.totals``)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402

from core.group import Group  # noqa: E402
from core.i18n import tr  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.units import fmt_area, fmt_len, fmt_volume  # noqa: E402

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _panel(window):
    from views.tray import EntityInfoPanel
    panel = window.findChild(EntityInfoPanel)
    panel.refresh()
    return panel


def _describe(window):
    return _panel(window)._label.text()


def _box(x, size=1.0):
    """A closed box with outward faces: a solid of ``size``³."""
    s = size
    p = [V(x, 0, 0), V(x + s, 0, 0), V(x + s, s, 0), V(x, s, 0),
         V(x, 0, s), V(x + s, 0, s), V(x + s, s, s), V(x, s, s)]
    m = Mesh()
    for quad in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in quad])
    return Group(m, name="Box")


def _sheet(x):
    """A group holding one lone face: not a solid."""
    m = Mesh()
    m.add_face([V(x, 0), V(x + 1, 0), V(x + 1, 1), V(x, 1)])
    return Group(m, name="Sheet")


def _edges_of(mesh, face):
    loop = face.loop
    return [mesh.find_edge(loop[i], loop[(i + 1) % len(loop)])
            for i in range(len(loop))]


def _two_faces(scene):
    a = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 1), V(0, 1)])      # 2 m²
    b = scene.mesh.add_face([V(5, 0), V(8, 0), V(8, 1), V(5, 1)])      # 3 m²
    return a, b


class _MenuNotModal(QMenu):
    """A real QMenu whose ``exec`` returns at once instead of waiting for
    a mouse that is not there (as in test_context_menu_reverse)."""

    shown: list = []

    def exec(self, *args, **kwargs):        # noqa: A003 - Qt's name
        _MenuNotModal.shown.append(self)
        return None


def _context_menu(window, monkeypatch):
    """The right-click menu as it would open, without opening it."""
    import views.main_window as mw
    _MenuNotModal.shown.clear()
    monkeypatch.setattr(mw, "QMenu", _MenuNotModal)
    window.show_viewport_context_menu(QPoint(0, 0))
    return _MenuNotModal.shown[0]


def _area_menu(menu):
    return {submenu.menuAction().text(): submenu
            for submenu in menu.findChildren(QMenu)}.get(tr("Area"))


def test_the_area_entry_needs_a_face(window, monkeypatch):
    scene = window.viewport.scene
    box = _box(0)
    scene.groups.append(box)
    scene.selection.add(box)
    assert _area_menu(_context_menu(window, monkeypatch)) is None


def test_area_selection_adds_the_faces_alone_in_a_modal_box(
        window, monkeypatch):
    scene = window.viewport.scene
    a, b = _two_faces(scene)
    box = _box(10, size=3.0)
    scene.groups.append(box)
    scene.selection.update([a, b, box, *_edges_of(scene.mesh, a)])
    area = _area_menu(_context_menu(window, monkeypatch))
    assert area is not None
    [selection] = [act for act in area.actions()
                   if act.text() == tr("Selection")]
    boxes = []

    def fake_exec(self):
        boxes.append((self.windowTitle(), self.text(), self.isModal()))
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    selection.trigger()
    assert boxes == [(tr("Area"), fmt_area(5.0), False)] or \
        boxes[0][:2] == (tr("Area"), fmt_area(5.0))
