# SPDX-License-Identifier: GPL-3.0-or-later
"""An edge midpoint is still an edge source for a parallel Tape guide."""
from types import SimpleNamespace
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V
from core.history import History
from core.scene import Scene
from tools.base import ToolContext
from tools.tape import TapeMeasureTool


def _setup():
    scene = Scene()
    edge = SimpleNamespace(a=V(0,0,0), b=V(4,0,0))
    vp = SimpleNamespace(scene=scene, history=History(scene), update=lambda:None,
                         flash_status=lambda *_:None, pick_edge_any=lambda *_:edge)
    return scene, vp, TapeMeasureTool()


def _ctx(vp, x, y, kind):
    return ToolContext(vp,V(x,y,0),QPointF(20,20),Qt.NoModifier,
                       SimpleNamespace(kind=kind))


def test_midpoint_pulls_a_preview_and_places_an_exact_parallel_guide():
    scene, vp, tool = _setup()
    tool.on_click(_ctx(vp,2,0,'midpoint'))
    tool.on_hover(_ctx(vp,3,1,'none'))
    assert tool.guide_preview_lines()
    assert tool.on_value(vp, .75)
    assert len(scene.guides) == 1
    guide = scene.guides[0]
    assert guide.is_line
    assert abs(guide.point.y()-.75) < 1e-6
    vp.history.undo()
    assert not scene.guides


def test_edge_source_and_distance_label_lie_on_the_measured_perpendicular():
    scene, vp, tool = _setup()
    tool.on_click(_ctx(vp,2,.05,'on_face'))  # within the edge pick tolerance
    tool.on_hover(_ctx(vp,3,1,'none'))
    a,b = tool.rubber_band_lines()[0]
    assert (a - V(2,0,0)).length() < 1e-6
    assert (b - V(2,1,0)).length() < 1e-6
    assert (tool.value_label()[1] - V(2,.5,0)).length() < 1e-6
