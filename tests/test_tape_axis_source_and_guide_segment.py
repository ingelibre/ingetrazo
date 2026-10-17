# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rafael, Revisión 3 (2026-09-20): the two guide gestures he found missing.

1. The Tape on a model AXIS, with nothing drawn, pulls a guide parallel to
   it — «poner la casa a 20 m y a 5 m del origen».
2. The Tape from a VERTEX leaves a guide POINT with its dashed guide
   segment back to the start — «un segmento guía que termina en un
   puntito», to centre a circle or set an overhang.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402

from core.guide import Guide  # noqa: E402
from core.history import History  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.snap import SnapResult  # noqa: E402
from formats import igz  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from tools.tape import TapeMeasureTool  # noqa: E402
from views.viewport import _guide_vertices  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene, axis=None):
        self.scene = scene
        self.history = History(scene)
        self._axis = axis
        self.flashed: list = []

    def update(self):
        pass

    def flash_status(self, text, *a, **k):
        self.flashed.append(text)

    def pick_edge(self, x, y):
        return None

    def pick_guide(self, x, y):
        return None

    def pick_axis(self, x, y):
        return self._axis


def _ctx(vp, x, y, z=0.0, kind=None):
    snap = SnapResult(V(x, y, z), kind, (0, 0, 0)) if kind else None
    return ToolContext(viewport=vp, world=V(x, y, z),
                       screen=QPointF(x * 100, y * 100),
                       modifiers=Qt.NoModifier, snap=snap)


# ---- 1. an axis is a guide source -----------------------------------------

def test_a_guide_pulled_from_the_red_axis_is_parallel_at_the_typed_distance():
    scene = Scene()
    vp = _Vp(scene, axis="x")
    tool = TapeMeasureTool()
    tool.on_click(_ctx(vp, 3, 0.02))                  # on the red axis
    assert tool._edge is not None
    assert (tool.start_point - V(3, 0)).length() < 1e-6   # the foot, not the click
    tool.on_hover(_ctx(vp, 3, 1.2))                   # pulling toward +Y
    assert tool.on_value(vp, 5.0)
    (g,) = scene.guides
    assert g.is_line and abs(abs(g.direction.x()) - 1.0) < 1e-6
    assert abs(g.point.y() - 5.0) < 1e-6 and abs(g.point.x() - 3.0) < 1e-6


def test_the_second_click_places_the_axis_guide_too():
    scene = Scene()
    vp = _Vp(scene, axis="y")
    tool = TapeMeasureTool()
    tool.on_click(_ctx(vp, 0.01, 2))                  # on the green axis
    tool.on_click(_ctx(vp, 20, 2))                    # 20 m off it
    (g,) = scene.guides
    assert abs(abs(g.direction.y()) - 1.0) < 1e-6 and abs(g.point.x() - 20.0) < 1e-6


def test_the_real_viewport_finds_the_axis_under_the_cursor():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.camera.set_view("top")
    vp.camera.target = V(0, 0, 0)
    vp.camera.distance = 12
    px = vp._world_to_pixel(V(3, 0, 0))
    assert vp.pick_axis(px[0], px[1] + 2) == "x"
    py = vp._world_to_pixel(V(0, 2.5, 0))
    assert vp.pick_axis(py[0] - 2, py[1]) == "y"
    far = vp._world_to_pixel(V(3, 3, 0))
    assert vp.pick_axis(*far) is None


def test_the_axis_cue_rule_lives_in_the_engine():
    """Step 4 of the split: the cue that paints the axis square is the
    engine's rule, and the viewport's name for it is a delegate. The pick
    (``pick_axis``) stays a viewport service the engine calls."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.viewport import Viewport

    class _AxisSourceTool:
        axis_source = True
        start_point = None

    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.camera.set_view("top")
    vp.camera.target = V(0, 0, 0)
    vp.camera.distance = 12
    vp.active_tool = _AxisSourceTool()
    px = vp._world_to_pixel(V(3, 0, 0))
    plain = SnapResult(V(3, 0, 0), "none")
    got = vp.inference._axis_source_cue(plain, px[0], px[1] + 2)
    assert got.kind == "on_axis" and got.axis == "x"
    assert (got.point - V(3, 0, 0)).length() < 1e-6   # the foot on the axis
    via_vp = vp._axis_source_cue(plain, px[0], px[1] + 2)
    assert (via_vp.kind, via_vp.axis) == ("on_axis", "x")


# ---- 2. a guide point with its segment ------------------------------------

def test_from_a_vertex_the_second_click_leaves_a_guide_point_with_its_segment():
    scene = Scene()
    vp = _Vp(scene)
    tool = TapeMeasureTool()
    tool.on_click(_ctx(vp, 1, 1, kind="endpoint"))
    tool.on_click(_ctx(vp, 3, 1))                     # free spot
    (g,) = scene.guides
    assert not g.is_line
    assert (g.point - V(3, 1)).length() < 1e-6
    assert g.origin is not None and (g.origin - V(1, 1)).length() < 1e-6
    assert any("segment" in t or "segmento" in t for t in vp.flashed)


def test_a_typed_distance_from_a_vertex_places_the_point_along_the_pull():
    scene = Scene()
    vp = _Vp(scene)
    tool = TapeMeasureTool()
    tool.on_click(_ctx(vp, 0, 0, kind="origin"))
    tool.on_hover(_ctx(vp, 4, 0))
    assert tool.on_value(vp, 1.5)
    (g,) = scene.guides
    assert (g.point - V(1.5, 0)).length() < 1e-6 and g.origin == V(0, 0)


def test_vertex_to_vertex_only_measures_and_free_space_too():
    scene = Scene()
    vp = _Vp(scene)
    tool = TapeMeasureTool()
    tool.on_click(_ctx(vp, 1, 1, kind="endpoint"))
    tool.on_click(_ctx(vp, 3, 1, kind="endpoint"))    # to another corner
    assert not scene.guides
    tool.on_click(_ctx(vp, 5, 5))                     # free space start
    tool.on_click(_ctx(vp, 7, 5))
    assert not scene.guides
    tool.on_click(_ctx(vp, 1, 1, kind="midpoint"))    # not a real point
    tool.on_click(_ctx(vp, 3, 1))
    assert not scene.guides


def test_the_segment_is_drawn_and_survives_the_igz(tmp_path):
    g = Guide(V(3, 1), None, V(1, 1))
    coords, spans = _guide_vertices([g], 0.2)
    assert spans and spans[0][1] >= 2                 # dashes along the segment
    assert Guide(V(3, 1), V(1, 0), V(0, 0)).origin is None   # lines never carry one
    scene = Scene()
    scene.guides.append(g)
    path = tmp_path / "guia.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    (b,) = back.guides
    assert b.origin is not None and (b.origin - V(1, 1)).length() < 1e-6


def test_guide_points_mode_keeps_the_segment_from_the_axis_to_a_centre():
    """#693 (Neil): SketchUp's guide point keeps its dashed segment back
    to the start — from a spot on the red axis to a circle's centre. Ours
    left a bare point in the guide-points mode, so the picture could not
    be drawn in any of the three."""
    scene = Scene()
    vp = _Vp(scene, axis="x")
    tool = TapeMeasureTool()
    tool._mode = "point"                              # Ctrl once
    tool.on_click(_ctx(vp, 2, 0, kind="on_edge"))     # on the red axis
    tool.on_click(_ctx(vp, 5, 3, kind="center"))      # the circle's centre
    (g,) = scene.guides
    assert not g.is_line and (g.point - V(5, 3)).length() < 1e-6
    assert g.origin is not None and (g.origin - V(2, 0)).length() < 1e-6
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_hover(_ctx(vp, 0, 4))
    assert tool.on_value(vp, 2.5)                     # typed, the same
    g = scene.guides[-1]
    assert (g.point - V(0, 2.5)).length() < 1e-6 and g.origin == V(0, 0)
