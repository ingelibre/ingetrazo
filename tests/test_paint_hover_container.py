# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Paint tool's hover marks what its click paints.

A click on a face of a closed group or component paints the container as
a whole (#47), so the hover marks no face of it — marking the one face
under the cursor promised a paint the click did not do. Inside an open
container the click paints the face, and the face is what the hover
marks; the eyedropper samples one face and marks that face."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.history import History                                  # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from tools.base import ToolContext                                # noqa: E402
from tools.paint import PaintTool                                 # noqa: E402


def _quad(mesh):
    return mesh.add_face([QVector3D(0, 0, 0), QVector3D(4, 0, 0),
                          QVector3D(4, 4, 0), QVector3D(0, 4, 0)])


class _FakeViewport:
    """A viewport whose picks return chosen answers (GL picking needs a
    display). ``group`` is what ``pick_group`` gives: the closed container
    under the cursor, or ``None`` once that container is open."""

    def __init__(self, face, owner, group):
        self.scene = Scene()
        self.history = History(self.scene)
        self._face, self._owner, self._group = face, owner, group
        self.hover = "unset"

    def pick_face_any(self, _x, _y):
        return self._face, self._owner

    def pick_group(self, _x, _y):
        return self._group

    def set_hover(self, entity, placement=None):
        self.hover = entity

    def update(self):
        pass


def _ctx(vp, modifiers=Qt.NoModifier):
    return ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(0, 0),
                       modifiers=modifiers, snap=None)


@pytest.fixture
def boxed():
    mesh = Mesh()
    face = _quad(mesh)
    return face, Group(mesh, name="Caja")


@pytest.fixture(autouse=True)
def _reset_paint_state():
    yield
    PaintTool.sample_armed = False
    PaintTool.current_material = None
    PaintTool.current_texture = None
    PaintTool.current_is_default = False
    PaintTool.current_color = (0.80, 0.45, 0.30)


def test_hover_on_a_closed_group_marks_no_face(boxed):
    face, group = boxed
    vp = _FakeViewport(face, group, group)
    PaintTool().on_hover(_ctx(vp))
    assert vp.hover is None


def test_hover_and_click_agree_on_a_closed_group(boxed):
    face, group = boxed
    vp = _FakeViewport(face, group, group)
    tool = PaintTool()
    tool.on_hover(_ctx(vp))
    tool.on_click(_ctx(vp))
    assert vp.hover is None
    assert group.material is not None        # the click painted it whole
    assert "color" not in face.attrs


def test_hover_inside_an_open_group_marks_the_face(boxed):
    face, group = boxed
    # Open for editing: its faces come back loose, nothing is picked whole.
    vp = _FakeViewport(face, None, None)
    PaintTool().on_hover(_ctx(vp))
    assert vp.hover is face


def test_hover_on_loose_geometry_marks_the_face():
    vp = _FakeViewport(None, None, None)
    vp._face = _quad(vp.scene.mesh)
    PaintTool().on_hover(_ctx(vp))
    assert vp.hover is vp._face


@pytest.mark.parametrize("how", ["alt", "armed"])
def test_the_eyedropper_marks_the_face_it_samples(boxed, how):
    face, group = boxed
    vp = _FakeViewport(face, group, group)
    mods = Qt.NoModifier
    if how == "alt":
        mods = Qt.AltModifier
    else:
        PaintTool.sample_armed = True
    PaintTool().on_hover(_ctx(vp, mods))
    assert vp.hover is face
