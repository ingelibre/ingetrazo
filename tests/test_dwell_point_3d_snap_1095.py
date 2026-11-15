# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The dwell point's reference snap in 3D (issue #1095).

Two regressions, both on the Line tool:

1. 'Level with' an encouraged corner only worked on the ground plane
   (Z = 0): the foot was read off the work-plane point — which drops to the
   ground — instead of the cursor ray, so an elevated corner's horizontal
   axis lines never showed.
2. Once 'level with' was showing, Shift could not lock it: the 'from point'
   inference was not in the shift-lockable set and carried no axis.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.scene import Scene
from core.snap import AXIS_COLORS, COLOR_ENDPOINT, SnapResult, compute_snap


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _w2p(p):                      # an elevation: x → right, z → up
    return (p.x() * 100.0, -p.z() * 100.0)


def test_the_line_tool_levels_with_an_elevated_point_in_3d():
    scene = Scene()
    scene.mesh.add_edge(V(0, 0, 0), V(0, 0, 2))    # a wall corner, top at Z=2
    ref = V(0, 0, 2)
    cursor = V(2, 0, 2)                             # level with it along X

    def project(start, direction):
        return start + direction * QVector3D.dotProduct(cursor - start, direction)

    r = compute_snap(
        candidate_world=V(2, 0, 0),                 # the plane dropped it to the ground
        candidate_pixel=_w2p(cursor),               # …but the cursor pixel is at Z=2
        scene=scene, world_to_pixel=_w2p,
        threshold_px=9.0, edge_threshold_px=14.0,
        project_onto_line=project, acquired_point=ref, free_3d=True,
    )
    assert r.kind == "from_point"
    assert r.axis == "x"
    assert (r.point - V(2, 0, 2)).length() < 1e-6
    assert r.guide is not None and (r.guide[0] - ref).length() < 1e-9


def test_a_planar_shape_keeps_its_from_point_on_the_face():
    # free_3d=False (Rectangle & co.): the old behaviour — the horizontal
    # axis of an elevated corner is off the face, so 'from point' stays quiet
    # and the plane-constrained rules (e.g. 'aligned') take over (#545).
    scene = Scene()
    scene.mesh.add_edge(V(0, 0, 0), V(0, 0, 2))
    ref = V(0, 0, 2)
    cursor = V(2, 0, 2)

    def project(start, direction):
        return start + direction * QVector3D.dotProduct(cursor - start, direction)

    r = compute_snap(
        candidate_world=V(2, 0, 0), candidate_pixel=_w2p(cursor),
        scene=scene, world_to_pixel=_w2p, threshold_px=9.0,
        edge_threshold_px=14.0, project_onto_line=project,
        acquired_point=ref, free_3d=False,
        work_plane_normal=V(0, 0, 1), face_under_cursor=True,
    )
    assert r.kind != "from_point"


def test_shift_locks_a_from_point_reference():
    from views.viewport import Viewport

    class _Tool:
        def __init__(self):
            self.start_point = V(2, 3, 4)

    class _Stub:
        _SHIFT_LOCKABLE = Viewport._SHIFT_LOCKABLE
        _mark_plane_for_shift = Viewport._mark_plane_for_shift

        def __init__(self):
            self.last_snap = SnapResult(
                V(5, 3, 4), "from_point", COLOR_ENDPOINT, axis="y",
                guide=(V(5, 0, 4), V(5, 3, 4)), guide_color=AXIS_COLORS["y"],
            )
            self.active_tool = _Tool()
            self._shift_lock = None

    stub = _Stub()
    Viewport._capture_shift_lock.__get__(stub)()
    assert stub._shift_lock is not None
    assert stub._shift_lock[0] == QVector3D(0.0, 1.0, 0.0)


def test_the_line_tool_dwell_reference_works_in_3d_through_the_viewport():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.viewport import Viewport
    from tools.line import LineTool
    from tools.base import ToolContext

    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.scene.mesh.add_edge(V(0, 0, 0), V(0, 0, 2))   # a wall corner, top at Z=2
    vp.scene.version += 1
    tool = LineTool()
    vp.set_active_tool(tool)
    vp.camera.set_view("iso")
    vp.camera.target = V(1, 0, 1)
    vp.camera.distance = 15

    tool.on_click(ToolContext(viewport=vp, world=V(-2, -2, 0),
                              screen=QPointF(0, 0), modifiers=Qt.NoModifier,
                              snap=None))

    def hover(world):
        px = vp._world_to_pixel(world)
        assert px is not None
        vp._process_hover(QPointF(*px), Qt.NoModifier)
        return vp.last_snap

    hover(V(0, 0, 2))                              # pause on the elevated corner…
    vp._encourage_dwelt()                          # …it becomes the reference
    s = hover(V(2, 0, 2))                          # move +X, level with it
    assert s.kind == "from_point", s.kind
    assert s.axis == "x"
    assert abs(s.point.z() - 2.0) < 1e-6
    vp._capture_shift_lock()
    assert vp._shift_lock is not None
    assert vp._shift_lock[0] == QVector3D(1.0, 0.0, 0.0)


def test_the_magnetic_axis_holds_once_engaged():
    """Once the magnet engaged an axis, a drift past the 3° engage cone but
    within the 20° release cone still holds it (issue #1095 — a hand that
    follows the on-screen axis in perspective, where the axis reads as a
    diagonal)."""
    from types import SimpleNamespace
    scene = SimpleNamespace(edges=[])
    start = V(0, 0, 0)
    cand = V(2.0, 0.35, 0.0)                       # ~10° off X: past engage, within release

    def w2p(p):
        return (p.x() * 100.0, -p.y() * 100.0)

    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)

    base = dict(candidate_world=cand, candidate_pixel=w2p(cand), scene=scene,
                world_to_pixel=w2p, threshold_px=9.0, edge_threshold_px=14.0,
                start_point=start, project_onto_line=project,
                magnetic_axis_deg=3.0)

    r = compute_snap(**base, sticky_axis="x")
    assert r.kind == "axis"
    assert r.axis == "x"
    assert abs(r.point.y()) < 1e-6

    # Without the sticky axis the same drift is too far off to engage at all.
    free = compute_snap(**base)
    assert free.kind != "axis"

    # Past the release cone the sticky axis lets go.
    far = V(2.0, 1.0, 0.0)                         # ~26.5° off X

    def project_far(s, d):
        return s + d * QVector3D.dotProduct(far - s, d)

    broke = compute_snap(**{**base, "candidate_world": far,
                            "candidate_pixel": w2p(far),
                            "project_onto_line": project_far},
                         sticky_axis="x")
    assert broke.kind != "axis"



def test_a_shift_lock_keeps_the_from_point_guide():
    """Locking a 'from point' reference keeps its dashed axis line visible,
    so the cursor can go fetch another point without losing the reference
    (issue #1095)."""
    from types import SimpleNamespace
    scene = SimpleNamespace(edges=[])
    start = V(1.87, 0, 1.87)
    dwell = V(0, 0, 1.87)
    cand = V(0, 2.5, 1.87)

    def w2p(p):
        return (p.x() * 100.0, -p.y() * 100.0)

    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)

    r = compute_snap(
        cand, w2p(cand), scene, w2p, threshold_px=9.0, edge_threshold_px=14.0,
        start_point=start, project_onto_line=project,
        shift_lock_dir=V(0, 1, 0), shift_lock_color=AXIS_COLORS["y"],
        shift_lock_ref=(dwell, "y"),
    )
    assert r.kind == "reference"
    assert r.guide is not None
    assert (r.guide[0] - dwell).length() < 1e-6
    assert r.guide_color == AXIS_COLORS["y"]
    assert abs(r.guide[1].x()) < 1e-6 and abs(r.guide[1].y() - 2.5) < 1e-3


def test_a_shift_lock_before_the_first_click_anchors_on_the_dwell():
    """Before any click, Shift on a 'from point' reference locks the dwell's
    own axis line, so the first click starts level with it (issue #1095)."""
    from types import SimpleNamespace
    scene = SimpleNamespace(edges=[])
    dwell = V(0, 0, 1.87)
    cand = V(0, 2.5, 1.87)

    def w2p(p):
        return (p.x() * 100.0, -p.y() * 100.0)

    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)

    r = compute_snap(
        cand, w2p(cand), scene, w2p, threshold_px=9.0, edge_threshold_px=14.0,
        start_point=None, project_onto_line=project,
        shift_lock_dir=V(0, 1, 0), shift_lock_color=AXIS_COLORS["y"],
        shift_lock_ref=(dwell, "y"),
    )
    assert r.kind == "reference"
    assert (r.point - V(0, 2.5, 1.87)).length() < 1e-3
    assert r.guide is not None and (r.guide[0] - dwell).length() < 1e-6
    assert r.guide_color == AXIS_COLORS["y"]


def test_an_axis_lock_before_the_first_click_anchors_on_the_dwell():
    """Before any click, an arrow key constrains the first click to the
    encouraged point's own axis line (issue #1095)."""
    from types import SimpleNamespace
    scene = SimpleNamespace(edges=[])
    dwell = V(0, 0, 1.87)
    cand = V(0, 2.5, 1.87)

    def w2p(p):
        return (p.x() * 100.0, -p.y() * 100.0)

    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)

    r = compute_snap(
        cand, w2p(cand), scene, w2p, threshold_px=9.0, edge_threshold_px=14.0,
        start_point=None, project_onto_line=project,
        axis_lock="y", acquired_point=dwell, dwell_axis_lock=True,
    )
    assert r.kind == "axis" and r.axis == "y"
    assert (r.point - V(0, 2.5, 1.87)).length() < 1e-3
    assert r.guide is not None and (r.guide[0] - dwell).length() < 1e-6
    assert r.guide_color == AXIS_COLORS["y"]


