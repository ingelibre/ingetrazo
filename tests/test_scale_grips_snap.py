# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A held Scale grip snaps to another object's points (issue #233,
@ales-limon): hover an endpoint, a midpoint or an edge of something else
and the grip lands level with it — scale «to» another object. The point is
projected onto the grip's line; faces and the engine's own directional
inferences do not pull the grip; what is being scaled is left out of the
snap, so it never lands on itself."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

from tests.test_scale_grips import V, _tool_with_box

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _grip(tool, want):
    return next(g for g in tool._grips
                if tuple(round(c, 6) for c in (lambda p: (p.x(), p.y(), p.z()))(
                    tool._grip_pos(g))) == want)


def _ctx(kind, p):
    return SimpleNamespace(snap=SimpleNamespace(kind=kind, point=p))


def test_no_snap_until_a_grip_is_held():
    tool, vp = _tool_with_box()
    assert tool.uses_snap is False and tool.snap_excluded() is None
    tool._grab(vp, _grip(tool, (4.0, 1.5, 1.0)), (0, 0))
    assert tool.uses_snap is True
    edges, groups = tool.snap_excluded()
    assert edges and groups == set()


def test_a_face_grip_lands_level_with_a_snapped_endpoint():
    tool, vp = _tool_with_box(w=4.0)                    # box x 0..4
    tool._grab(vp, _grip(tool, (4.0, 1.5, 1.0)), (0, 0))   # the +X face grip
    f = tool._factors_for(_ctx("endpoint", V(7.0, 9.0, -3.0)), vp, 0, 0)
    assert f == pytest.approx((7.0 / 4.0, 1.0, 1.0))    # only x, projected


def test_a_corner_grip_scales_uniformly_to_the_point_projected_on_its_diagonal():
    tool, vp = _tool_with_box(w=4.0, d=3.0, h=2.0)
    tool._grab(vp, _grip(tool, (4.0, 3.0, 2.0)), (0, 0))   # anchor (0,0,0)
    f = tool._factors_for(_ctx("midpoint", V(8.0, 6.0, 4.0)), vp, 0, 0)
    assert f == pytest.approx((2.0, 2.0, 2.0))


def test_an_edge_grip_takes_both_axes_from_the_point():
    tool, vp = _tool_with_box(w=4.0, d=3.0, h=2.0)
    tool._grab(vp, _grip(tool, (4.0, 3.0, 1.0)), (0, 0))   # x and y
    f = tool._factors_for(_ctx("intersection", V(6.0, 1.5, 9.0)), vp, 0, 0)
    assert f == pytest.approx((1.5, 0.5, 1.0))


@pytest.mark.parametrize("kind", ["on_face", "axis", "reference", "none"])
def test_faces_and_directional_inferences_leave_the_grip_on_the_cursor(kind, monkeypatch):
    tool, vp = _tool_with_box()
    tool._grab(vp, _grip(tool, (4.0, 1.5, 1.0)), (0, 0))
    monkeypatch.setattr(tool, "_factors_from_cursor", lambda *a: ("cursor",))
    assert tool._factors_for(_ctx(kind, V(9, 9, 9)), vp, 0, 0) == ("cursor",)


def _box(scene, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    out = []
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        out.append(scene.mesh.add_face([p[i] for i in idx]))
    return out


def test_in_the_viewport_the_grip_lands_on_another_boxs_corner():
    """Front view: a 1 m cube and, beside it, a 2.5 m tall post. Grab the
    cube's top-face grip, hover the post's top corner: the cube becomes
    exactly 2.5 m tall. Hovering the cube's OWN corner does not snap."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(1000, 700)
        sc = vp.scene
        sc.guides.clear()
        cube = _box(sc, 0, 0, 0, 1, 1, 1)
        _box(sc, 3, 0, 0, 3.5, 1, 2.5)                     # the post
        sc.version += 1
        vp.camera.set_view("front")
        vp.camera.perspective = False
        vp.camera.fit_to(QVector3D(-1, 0, -0.5), QVector3D(4.5, 1, 3))
        sc.selection.clear()
        sc.selection.update(cube)
        win._activate_tool("scale")
        tool = vp.active_tool
        tool._refresh_box(vp)
        grip = _grip(tool, (0.5, 0.5, 1.0))               # top face grip
        tool._grab(vp, grip, (0, 0))

        def hover(p):
            px = vp._world_to_pixel(p)
            ev = QMouseEvent(QEvent.MouseMove, QPointF(*px), QPointF(*px),
                             Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            ctx = vp._build_ctx(ev)
            tool.on_hover(ctx)
            return ctx.snap

        s = hover(QVector3D(3.0, 0.0, 2.5))                # the post's corner
        assert s.kind == "endpoint"
        assert tool._factors[2] == pytest.approx(2.5, abs=1e-5)
        own = hover(QVector3D(1.0, 0.0, 1.0 * tool._factors[2]))
        assert not (own.kind == "endpoint"
                    and abs(own.point.x() - 1.0) < 1e-6), own
        tool.on_cancel(vp)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
