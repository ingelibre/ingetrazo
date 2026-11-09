# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Painting a component whose faces all carry their own material (#807).

The .skp of the report has cabinet parts as components with every face
painted: painting one as a whole keeps those materials (the SketchUp rule,
as in #408), so the click changed nothing on screen and read as «it won't
let me paint components». The status bar now says why and what to do."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from tools.paint import PaintTool  # noqa: E402


def _square(paint):
    m = Mesh()
    f = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    if paint:
        f.attrs["color"] = [0.2, 0.4, 0.6]
    return m


def test_a_component_with_every_face_painted_is_told_apart():
    assert PaintTool._every_face_painted(Group(_square(True), "panel"))
    assert not PaintTool._every_face_painted(Group(_square(False), "panel"))


def test_a_nested_unpainted_part_still_takes_the_paint():
    outer = Group(_square(True), "cabinet")
    inner = Group(_square(False), "door")
    inner.xform = QMatrix4x4()
    outer.adopt([inner])
    assert not PaintTool._every_face_painted(outer)


def test_the_click_says_why_nothing_changed():
    from types import SimpleNamespace as NS
    flashed = []
    group = Group(_square(True), "panela_porta")
    vp = NS(flash_status=flashed.append, history=NS(execute=lambda c: None),
            update=lambda: None, pick_group=lambda x, y: group,
            pick_face_any=lambda x, y: (group.mesh.faces[0], group))
    tool = PaintTool()
    tool._remember_current = lambda vp: None
    obj = tool._container_under(vp, group, 0, 0)
    assert obj is group
    name = "panela_porta"
    msg = ("{name}: every face has its own material, so nothing changed "
           "— open it and paint the faces")
    from core.i18n import tr
    assert tr(msg, name=name).startswith(name)
