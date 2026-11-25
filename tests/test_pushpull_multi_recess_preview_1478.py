# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull on several faces, inward: no false face over the pockets (#1478).

A single face pushed into its solid hides itself for the drag, so the pocket
forming behind it shows. With several faces selected only the face under the
cursor did: every other one stayed drawn over its own pocket, a false face
hiding the movement until the release (@tomlai-git). Each recessing face is
hidden now; outward, or with Ctrl (a copy keeps its base), none is."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QGuiApplication, QVector3D

_app = QGuiApplication.instance() or QGuiApplication([])

from core.history import History  # noqa: E402
from core.scene import Scene  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from tools.pushpull import PushPullTool  # noqa: E402


class _Camera:
    def __init__(self, eye):
        self._eye = QVector3D(eye)

    def eye(self):
        return QVector3D(self._eye)


class _Vp:
    def __init__(self, scene, eye):
        self.scene = scene
        self.history = History(scene)
        self.camera = _Camera(eye)
        self.suppressed = set()

    def set_hover(self, *_):
        pass

    def set_suppressed_faces(self, faces):
        self.suppressed = set(faces)

    def update(self):
        pass

    def flash_status(self, *_):
        pass


def _box(mesh, x0, size=2.0, h=3.0):
    V = QVector3D
    p = [V(x0, 0, 0), V(x0 + size, 0, 0), V(x0 + size, size, 0),
         V(x0, size, 0), V(x0, 0, h), V(x0 + size, 0, h),
         V(x0 + size, size, h), V(x0, size, h)]
    faces = [mesh.add_face([p[i] for i in q]) for q in
             ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7))]
    return faces[1]                                      # the top


def _start(eye, keep=False):
    scene = Scene()
    tops = [_box(scene.mesh, 0.0), _box(scene.mesh, 5.0)]
    scene.select(tops)
    vp = _Vp(scene, eye)
    pp = PushPullTool()
    pp.on_activate(vp)
    pp.hovered_face = tops[0]
    pp._hover_group = None
    pp.on_click(ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(0, 0),
                            modifiers=Qt.ControlModifier if keep
                            else Qt.NoModifier, snap=None))
    assert pp._extra_faces == [tops[1]]
    return pp, vp, tops


def _preview(pp, vp, d):
    pp.extrusion = d
    pp._show_light_preview(vp)
    return vp.suppressed


def test_every_face_pushed_in_leaves_its_pocket_open():
    pp, vp, tops = _start(QVector3D(3.5, -8.0, 12.0))     # from above
    assert _preview(pp, vp, -1.0) == set(tops)
    # Outward the caps cover their bases: nothing to hide.
    assert _preview(pp, vp, +1.0) == set()


def test_seen_from_below_the_other_way_round():
    pp, vp, tops = _start(QVector3D(3.5, -8.0, -12.0))    # from under
    # Inward is TOWARD this eye: the tops never cover the pockets.
    assert _preview(pp, vp, -1.0) == set()
    assert _preview(pp, vp, +1.0) == set(tops)


def test_a_copy_keeps_every_base():
    pp, vp, tops = _start(QVector3D(3.5, -8.0, 12.0), keep=True)
    assert pp._keep_base
    assert _preview(pp, vp, -1.0) == set()
