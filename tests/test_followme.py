# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Follow Me sweep engine (core/sweep.py) and tool flow."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.mesh import Mesh
from core.orient import is_closed, signed_volume
from core.scene import Scene
from core.sweep import order_path_edges, sweep_profile
from tools.base import ToolContext


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _square_profile_xz(mesh, size=1.0):
    """Unit square in the XZ plane at y=0 (perpendicular to a +Y path)."""
    return mesh.add_face([V(0, 0, 0), V(size, 0, 0),
                          V(size, 0, size), V(0, 0, size)])


def test_straight_sweep_is_a_box():
    m = Mesh()
    f = _square_profile_xz(m)
    assert sweep_profile(m, f, [V(0, 0, 0), V(0, 3, 0)], closed=False)
    assert is_closed(m)
    assert abs(signed_volume(m) - 3.0) < 1e-6      # 1×1 profile × length 3
    assert len(m.faces) == 6


def test_l_path_mitred_corner():
    m = Mesh()
    f = _square_profile_xz(m)
    path = [V(0, 0, 0), V(0, 4, 0), V(4, 4, 0)]    # 90° corner in plan
    assert sweep_profile(m, f, path, closed=False)
    assert is_closed(m)
    # Mitre keeps the solid clean: volume = area × centreline length of the
    # outer/inner average — for a square profile hugging the corner, exactly
    # area × (4 + 4) minus the double-counted corner cube... just check sane.
    vol = signed_volume(m)
    assert 6.5 < vol < 8.5
    # The corner joint plane cuts at 45°: some ring vertices sit at y=4±x.
    corner_pts = [v for v in m.vertices
                  if abs(v.position.y() - 4.0 + v.position.x()) < 1e-6]
    assert corner_pts


def test_closed_path_makes_a_welded_torus():
    m = Mesh()
    # Square profile standing in the XZ plane at radius 4 on the +X axis.
    f = m.add_face([V(4, 0, 0), V(5, 0, 0), V(5, 0, 1), V(4, 0, 1)])
    n = 12
    ring = [V(4.5 * math.cos(2 * math.pi * i / n),
              4.5 * math.sin(2 * math.pi * i / n), 0.5) for i in range(n)]
    assert sweep_profile(m, f, ring, closed=True)
    assert is_closed(m)
    assert len(m.faces) == 4 * n                   # 4 walls per span, no caps
    assert signed_volume(m) > 0
    # A curved sweep softens its span seams (the torus reads smooth).
    assert any(e.soft for e in m.edges)


def test_holed_profile_sweeps_a_tube():
    m = Mesh()
    outer = [V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)]
    hole = [V(0.5, 0, 0.5), V(1.5, 0, 0.5), V(1.5, 0, 1.5), V(0.5, 0, 1.5)]
    f = m.add_face(outer, [hole])
    assert sweep_profile(m, f, [V(0, 0, 0), V(0, 5, 0)], closed=False)
    assert is_closed(m)
    assert abs(signed_volume(m) - (4 - 1) * 5) < 1e-6   # ring area 3 × len 5
    caps = [g for g in m.faces if g.hole_loops]
    assert len(caps) == 2                          # both caps keep the hole


def test_order_path_edges_chains_and_rejects_branches():
    m = Mesh()
    m.add_edge(V(0, 0, 0), V(1, 0, 0))
    m.add_edge(V(2, 0, 0), V(1, 0, 0))             # reversed on purpose
    m.add_edge(V(2, 0, 0), V(2, 1, 0))
    pts, closed = order_path_edges(list(m.edges))
    assert not closed
    xs = [(round(p.x(), 3), round(p.y(), 3)) for p in pts]
    assert xs[0] in ((0.0, 0.0), (2.0, 1.0)) and len(pts) == 4
    m.add_edge(V(1, 0, 0), V(1, 1, 0))             # branch at (1,0)
    assert order_path_edges(list(m.edges)) is None


def test_reversal_path_declines_cleanly():
    m = Mesh()
    f = _square_profile_xz(m)
    before_faces = len(m.faces)
    path = [V(0, 0, 0), V(0, 3, 0), V(0, 0, 0)]    # 180° reversal
    assert sweep_profile(m, f, path, closed=False) is False
    assert len(m.faces) == before_faces            # untouched


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.messages = []
        self._pick = None

    def update(self):
        pass

    def set_hover(self, *_):
        pass

    def flash_status(self, text, msec=2500):
        self.messages.append(text)

    def pick_face(self, x, y):
        return self._pick


def test_tool_flow_path_then_profile():
    from tools.followme import FollowMeTool

    scene = Scene()
    vp = _Vp(scene)
    m = scene.mesh
    profile = _square_profile_xz(m)
    e1 = m.add_edge(V(0, 0, 0), V(0, 4, 0))
    e2 = m.add_edge(V(0, 4, 0), V(4, 4, 0))
    scene.selection.update([e1, e2])               # only the path
    t = FollowMeTool()
    t.on_activate(vp)
    assert t._path is not None
    vp._pick = profile
    t.on_hover(ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                           modifiers=Qt.NoModifier, snap=None))
    t.on_click(ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                           modifiers=Qt.NoModifier, snap=None))
    assert is_closed(m)
    assert signed_volume(m) > 0
    assert vp.history.undo()                        # single undoable step
    assert len(m.faces) == 1                        # back to the lone profile


# ---- Manual drag (SketchUp: click the profile, drag along the path) --------

class _Vp2(_Vp):
    def __init__(self, scene):
        super().__init__(scene)
        self._edge = None
        self.hover = []

    def pick_edge(self, x, y):
        return self._edge

    def set_hover(self, entity):
        self.hover.append(entity)


def _ctx(vp, x=0.0, y=0.0, world=None, mods=Qt.NoModifier):
    return ToolContext(viewport=vp, world=world or V(0, 0), screen=QPointF(x, y),
                       modifiers=mods, snap=None)


def _vertex_at(m, p):
    return next(v for v in m.vertices if (v.position - p).length() < 1e-9)


def test_manual_drag_previews_live_and_a_click_finishes():
    from tools.followme import FollowMeTool
    scene = Scene()
    vp = _Vp2(scene)
    m = scene.mesh
    profile = _square_profile_xz(m)
    e1 = m.add_edge(V(0, 0, 0), V(0, 4, 0))
    e2 = m.add_edge(V(0, 4, 0), V(4, 4, 0))
    t = FollowMeTool()
    t.on_activate(vp)
    assert t._path is None and vp.messages          # the hint for the drag
    vp._pick = profile
    t.on_hover(_ctx(vp))
    t.on_click(_ctx(vp))                            # click the profile
    t.on_release(vp)                                # …its release: no motion
    assert t._profile is profile and t.preview_faces() == []
    vp._pick = None
    vp._edge = e1
    t.on_hover(_ctx(vp, 30, 0, world=V(0, 2, 0)))
    assert [v.position for v in t._chain] == [V(0, 0, 0), V(0, 4, 0)]
    assert len(t.rubber_band_lines()) == 1          # the red path so far
    assert len(t.preview_faces()) == 5              # 4 walls + far cap
    vp._edge = e2
    t.on_hover(_ctx(vp, 60, 0, world=V(2, 4, 0)))
    assert len(t._chain) == 3 and len(t.rubber_band_lines()) == 2
    assert len(t.preview_faces()) == 9
    assert len(m.faces) == 1                        # nothing committed yet
    t.on_click(_ctx(vp, 60, 0))                     # click: finish
    assert is_closed(m)
    assert 6.5 < signed_volume(m) < 8.5             # the mitred L
    assert t._profile is None and t.preview_faces() == []
    assert vp.history.undo()                        # one step
    assert len(m.faces) == 1


def test_manual_drag_bridges_skipped_segments_and_backs_up():
    from core.sweep import manual_path_extend
    scene = Scene()
    m = scene.mesh
    pts = [V(0, 0, 0), V(0, 1, 0), V(0, 2, 0), V(0, 3, 0), V(0, 4, 0)]
    edges = [m.add_edge(pts[i], pts[i + 1]) for i in range(4)]
    v = [_vertex_at(m, p) for p in pts]
    chain = [v[0], v[1]]
    assert manual_path_extend(chain, edges[2])     # skipped edges[1]
    assert chain == [v[0], v[1], v[2], v[3]]
    assert manual_path_extend(chain, edges[1])     # back over an earlier edge
    assert chain == [v[0], v[1], v[2]]
    assert manual_path_extend(chain, edges[1])     # the last edge again: back up
    assert chain == [v[0], v[1]]
    assert manual_path_extend(chain, edges[1]) and chain == [v[0], v[1], v[2]]
    assert not manual_path_extend(chain, edges[1], skip=lambda e: True)


def test_manual_drag_release_after_a_real_drag_finishes_and_esc_cancels():
    from tools.followme import FollowMeTool
    scene = Scene()
    vp = _Vp2(scene)
    m = scene.mesh
    profile = _square_profile_xz(m)
    e1 = m.add_edge(V(0, 0, 0), V(0, 3, 0))
    t = FollowMeTool()
    t.on_activate(vp)
    vp._pick = profile
    t.on_hover(_ctx(vp))
    t.on_click(_ctx(vp, 10, 10))
    vp._pick = None
    vp._edge = e1
    t.on_hover(_ctx(vp, 12, 11, world=V(0, 1, 0)))   # a jitter, not a drag
    t.on_release(vp)
    assert t._profile is profile and len(m.faces) == 1
    t.on_cancel(vp)                                  # Esc: start over
    assert t._profile is None and t.preview_faces() == []
    assert len(m.faces) == 1
    vp._pick = profile
    t.on_hover(_ctx(vp))
    t.on_click(_ctx(vp, 10, 10))
    vp._pick = None
    t.on_hover(_ctx(vp, 80, 10, world=V(0, 2, 0)))    # a real drag
    t.on_release(vp)
    assert is_closed(m) and abs(signed_volume(m) - 3.0) < 1e-6


def test_alt_over_a_face_follows_its_perimeter():
    from tools.followme import FollowMeTool
    scene = Scene()
    vp = _Vp2(scene)
    m = scene.mesh
    # a square path on the ground, the profile standing over its first corner
    # (lifted, so the moulding shares no edge with the ground face itself)
    path_face = m.add_face([V(0, 0, 0), V(6, 0, 0), V(6, 6, 0), V(0, 6, 0)])
    profile = m.add_face([V(0, 0, 0.5), V(-1, 0, 0.5), V(-1, 0, 1.5),
                          V(0, 0, 1.5)])
    t = FollowMeTool()
    t.on_activate(vp)
    vp._pick = profile
    t.on_hover(_ctx(vp))
    t.on_click(_ctx(vp))
    vp._pick = path_face
    t.on_hover(_ctx(vp, 40, 40, mods=Qt.AltModifier))
    pts, closed = t.path_points()
    assert closed and len(pts) == 4 and len(t.preview_faces()) == 16
    assert len(t.rubber_band_lines()) == 4
    t.on_click(_ctx(vp, 40, 40, mods=Qt.AltModifier))
    assert len(m.faces) == 1 + 16                    # the ground face + frame
    # the frame is watertight: every edge of the moulding has two faces
    assert all(len(e.faces) == 2 for e in m.edges
               if e.a.z() > 1e-6 or e.b.z() > 1e-6)
    assert vp.history.undo() and len(m.faces) == 2


def test_edges_in_the_profile_plane_are_not_path_edges():
    from tools.followme import FollowMeTool
    scene = Scene()
    vp = _Vp2(scene)
    m = scene.mesh
    profile = _square_profile_xz(m)
    in_plane = m.add_edge(V(2, 0, 0), V(2, 0, 2))     # y = 0: the profile's plane
    t = FollowMeTool()
    t.on_activate(vp)
    vp._pick = profile
    t.on_hover(_ctx(vp))
    t.on_click(_ctx(vp))
    vp._pick = None
    vp._edge = in_plane
    t.on_hover(_ctx(vp, 30, 0))
    assert t._chain == [] and t.preview_faces() == []
    t.on_click(_ctx(vp, 30, 0))                      # nothing to sweep yet
    assert len(m.faces) == 1 and vp.messages[-1].startswith("Follow Me: touch")
