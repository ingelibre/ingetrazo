# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet snapping: a wireframe frame offers the vertices behind the faces
too, and a dimension line being placed snaps onto the line of a parallel
cota already on the sheet."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import CotaItem
from tests.test_composer_canvas import _FakeViewport
from tests.test_composer_cota_cadena import _composer
from views.composer import ComposerWindow

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _add_box(mesh, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for f in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
              (4, 5, 6, 7), (3, 2, 1, 0)):
        mesh.add_face([p[i] for i in f])


def _box_composer():
    """Seen from the front, a 6 × 1 × 3 m box hides a small 2 × 1 × 1 m
    one standing 2 m behind it — whose edges fall INSIDE the big one's
    outline on paper, not on top of its edges."""
    host = QWidget()
    host.viewport = _FakeViewport()
    m = host.viewport.scene.mesh
    _add_box(m, 0, 0, 0, 6, 1, 3)
    _add_box(m, 2, 3, 1, 4, 4, 2)
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.view_key = "std:front"
    frame.scale_n = 100.0
    composer.snap_cache.clear()
    return composer, frame


def _depths(composer, frame):
    _page, world = composer.frame_snap_points(frame)
    return {round(float(w[1]), 6) for w in world}


def test_a_wireframe_frame_snaps_to_the_vertices_behind():
    composer, frame = _box_composer()
    frame.style = "style:Hidden line"
    hidden = _depths(composer, frame)
    frame.style = "style:Wireframe"            # the cache sees the change
    wire = _depths(composer, frame)
    assert 3.0 not in hidden                   # only what is in front
    assert 3.0 in wire                         # the box behind too


def test_hidden_lines_inked_snap_too():
    composer, frame = _box_composer()
    frame.style = "vectorial"
    assert not composer._frame_sees_through(frame)
    frame.hidden_lines = True
    assert composer._frame_sees_through(frame)
    assert 3.0 in _depths(composer, frame)


def test_the_dimension_line_snaps_onto_a_parallel_cota():
    composer, _host = _composer()
    view = composer._view
    composer.comp.cotas.append(CotaItem(x_mm=20.0, y_mm=50.0, dx_mm=30.0,
                                        dy_mm=0.0, sep_mm=-10.0))  # line y=40
    composer._set_tool_mode("cota")
    view._drag_start = QPointF(70.0, 52.0)
    view._second_pt = QPointF(100.0, 52.0)
    thr = view._snap_thr_mm()
    near = view._cota_sep(QPointF(85.0, 40.0 + thr * 0.5))
    assert near == pytest.approx(40.0 - 52.0)  # on the other cota's line
    assert view._snap_marker is not None
    far = view._cota_sep(QPointF(85.0, 40.0 + thr * 3))
    assert far == pytest.approx(40.0 + thr * 3 - 52.0)   # free
    assert view._snap_marker is None


def test_a_slanted_cota_does_not_pull_a_horizontal_line():
    composer, _host = _composer()
    view = composer._view
    composer.comp.cotas.append(CotaItem(x_mm=20.0, y_mm=40.0, dx_mm=30.0,
                                        dy_mm=10.0))
    view._drag_start = QPointF(70.0, 52.0)
    view._second_pt = QPointF(100.0, 52.0)
    raw = QPointF(85.0, 40.2)
    assert view._cota_sep(raw) == pytest.approx(40.2 - 52.0)


class _Move:
    def __init__(self, x, y):
        self._pos = QPointF(x, y)

    def pos(self):
        return self._pos


def test_dragging_a_cota_line_snaps_onto_a_parallel_cota():
    from views.composer import CotaCanvasItem
    composer, _host = _composer()
    other = CotaItem(x_mm=20.0, y_mm=50.0, dx_mm=30.0, dy_mm=0.0,
                     sep_mm=-10.0)                          # line at y = 40
    moved = CotaItem(x_mm=70.0, y_mm=52.0, dx_mm=30.0, dy_mm=0.0)
    composer.comp.cotas += [other, moved]
    composer._rebuild_canvas()
    item = next(it for it in composer.canvas.items()
                if isinstance(it, CotaCanvasItem) and it.model is moved)
    view = composer._view
    thr = view._snap_thr_mm()
    item._sep_dragging = True
    item.mouseMoveEvent(_Move(15.0, -12.0 + thr * 0.5))
    assert moved.sep_mm == pytest.approx(-12.0)     # on the other line
    assert view._snap_marker is not None
    item.mouseMoveEvent(_Move(15.0, -12.0 + thr * 3))
    assert moved.sep_mm == pytest.approx(-12.0 + thr * 3)   # free again
    assert view._snap_marker is None
    item.mouseMoveEvent(_Move(15.0, 0.1))            # never onto itself
    assert moved.sep_mm == pytest.approx(0.1)


def test_a_chain_offset_on_the_drawing_keeps_its_geometry_snap():
    """The chain's offset click snaps to the MODEL like its points do; the
    line-to-line snap must not take that dot away, nor pull it off."""
    composer, _host = _composer()
    view = composer._view
    composer.comp.cotas.append(CotaItem(x_mm=20.0, y_mm=50.0, dx_mm=30.0,
                                        dy_mm=0.0, sep_mm=-10.0))  # line y=40
    composer._set_tool_mode("cota_cadena")
    view._chain_click(QPointF(70.0, 52.0), None)
    view._chain_click(QPointF(100.0, 52.0), None)
    on_model = QPointF(85.0, 40.3)               # near the other line too
    view._show_snap_marker(on_model.x(), on_model.y())
    view._last_hit = (on_model.x(), on_model.y(), (0.0, 0.0, 0.0), None)
    sep = view._sep_between(QPointF(70.0, 52.0), QPointF(100.0, 52.0),
                            on_model)
    assert sep == pytest.approx(40.3 - 52.0)     # the model point, exactly
    assert view._snap_marker is not None         # its dot still shows
    view._last_hit = None                        # off the model: lines snap
    sep = view._sep_between(QPointF(70.0, 52.0), QPointF(100.0, 52.0),
                            on_model)
    assert sep == pytest.approx(40.0 - 52.0)


def test_drawn_points_beat_hidden_ones():
    """A see-through frame offers the hidden box's corners, but only where
    nothing drawn is in reach: the drawn corners keep the snap."""
    composer, frame = _box_composer()
    frame.style = "style:Wireframe"
    pts, world = composer.frame_snap_points(frame)
    nv = composer.frame_snap_visible(frame)
    assert 0 < nv < len(pts)
    assert all(round(float(w[1]), 6) != 3.0 for w in world[:nv])
    hx, hy = pts[nv]                                  # a hidden point
    assert composer.nearest_snap_point(hx, hy, 0.5)[2][1] == 3.0
    vx, vy = pts[0]                                   # a drawn one
    hit = composer.nearest_snap_point(vx, vy, 50.0)   # both in reach
    assert (hit[0], hit[1]) == (vx, vy)
