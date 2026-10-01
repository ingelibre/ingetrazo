# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #178 (Esteban Penzo): right-click ▸ Flip Along ▸ Red / Green /
Blue mirrors the selection in place about its centre in one click, as
modelling tutorials do — the same mirror as the Flip tool's."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _xs(mesh):
    return sorted(round(v.position.x(), 3) for v in mesh.vertices)


def test_flip_along_red_mirrors_a_group_in_place_in_one_undo(window):
    scene = window.viewport.scene
    m = Mesh()
    m.add_face([V(1, 0), V(3, 0), V(1, 1)])        # a wedge, thick on the left
    g = Group(m)
    scene.groups.append(g)
    scene.selection.add(g)
    assert _xs(g.mesh) == [1.0, 1.0, 3.0]
    window._on_flip_along("x")
    # Mirrored about the centre x = 2: the thick end is now on the right.
    tip = min(g.mesh.vertices, key=lambda v: v.position.x())
    assert round(tip.position.x(), 3) == 1.0
    assert _xs(g.mesh) == [1.0, 3.0, 3.0]          # same span, in place
    ys_at_3 = sorted(round(v.position.y(), 3) for v in g.mesh.vertices
                     if round(v.position.x(), 3) == 3.0)
    assert ys_at_3 == [0.0, 1.0]                   # the tall side moved right
    assert window.viewport.history.undo()
    ys_at_1 = sorted(round(v.position.y(), 3) for v in g.mesh.vertices
                     if round(v.position.x(), 3) == 1.0)
    assert ys_at_1 == [0.0, 1.0]                   # back as it was


def test_flip_along_blue_turns_loose_geometry_upside_down(window):
    scene = window.viewport.scene
    f = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 2)])
    scene.selection.add(f)
    window._on_flip_along("z")
    face = scene.mesh.faces[0]
    zs = sorted(round(v.z(), 3) for v in face.vertices)
    assert zs == [0.0, 2.0, 2.0]                   # mirrored about z = 1


def test_nothing_selected_changes_nothing(window):
    n = len(window.viewport.history.undo_stack) if hasattr(
        window.viewport.history, "undo_stack") else None
    window._on_flip_along("y")
    if n is not None:
        assert len(window.viewport.history.undo_stack) == n
