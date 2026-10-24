# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Just past a loose edge's end there is no «On edge» to snap to.

#587 (@BastelBaus): beyond the endpoint's 9 px, inside the edge's 14 px,
the engine offered «On edge» — at the endpoint itself, clamped there, and
not a point the user could pick. Past the end the nearest point of the
edge IS the endpoint, which its own snap had already turned down."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.edits import build_add_edges  # noqa: E402
from tools.line import LineTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def _vp():
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("top")
    vp.camera.target = V(2, 0, 0)
    vp.camera.distance = 10
    vp.history.execute(build_add_edges(
        vp.scene, [(V(0, 0, 0), V(4, 0, 0))], detect_faces=False))
    t = LineTool()
    vp.active_tool = t
    t.on_activate(vp)
    return vp


def test_past_the_end_is_endpoint_then_nothing_of_the_edge():
    vp = _vp()
    ex, ey = vp._world_to_pixel(V(4, 0, 0))
    kinds = [vp.inference.snap(ex + dx, ey, Qt.NoModifier).kind
             for dx in range(0, 30)]
    assert "on_edge" not in kinds
    assert kinds[0] == "endpoint"


def test_along_the_edge_it_is_still_on_edge():
    vp = _vp()
    x, y = vp._world_to_pixel(V(3, 0, 0))
    assert vp.inference.snap(x, y + 6, Qt.NoModifier).kind == "on_edge"
