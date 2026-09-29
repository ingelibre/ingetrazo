# SPDX-License-Identifier: GPL-3.0-or-later
import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core import units
from tools.base import ToolContext
from tools.rectangle import RectangleTool
from views.viewport import Viewport


@pytest.mark.parametrize("distance", [.02, .03, .1, 1., 20.])
@pytest.mark.parametrize("perspective", [True, False])
def test_millimetre_closeup_drag_has_finite_preview(distance, perspective):
    vp = Viewport()
    vp.resize(800, 600)
    vp.camera.set_aspect(800, 600)
    vp.camera.distance = distance
    vp.camera.perspective = perspective
    old_scene = units._SCENE
    units.apply_units(vp.scene, {"length": "mm", "precision": 2})
    units.bind_scene(vp.scene)
    try:
        tool = RectangleTool()
        vp.active_tool = tool
        a = vp._world_from_pixel(400, 300)
        b = vp._world_from_pixel(450, 350)
        assert a is not None and b is not None
        assert all(math.isfinite(v) for p in (a, b) for v in p.toTuple())
        tool.on_click(ToolContext(vp, a, QPointF(400, 300), Qt.NoModifier, None))
        tool.on_hover(ToolContext(vp, b, QPointF(450, 350), Qt.NoModifier, None))
        label, _ = tool.value_label()
        assert "nan" not in label.lower() and "mm" in label
        assert len(tool.rubber_band_lines()) >= 4
        tool.on_click(ToolContext(vp, b, QPointF(450, 350), Qt.NoModifier, None))
        assert len(vp.scene.faces) == 1
    finally:
        units.bind_scene(old_scene)


def test_invalid_ray_cannot_poison_work_plane():
    vp = Viewport()
    assert vp._ray_plane(QVector3D(), QVector3D(float("nan"), 0, -1),
                         QVector3D(), QVector3D(0, 0, 1)) is None
