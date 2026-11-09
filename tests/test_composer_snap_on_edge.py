# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""On a sheet, a point along an edge catches too (#1219).

The cota caught corners, joints and midpoints only: a dimension could not
start on a straight kerb. A corner still wins, and a point placed on an edge
must stay there, even with a corner close by.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import CotaItem
from views.composer import ComposerWindow
from tests.test_composer_canvas import _FakeViewport

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _composer(perspective=False):
    host = QWidget()
    host.viewport = _FakeViewport()
    # A wall 6 x 3 m, seen from the front.
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.view_key = "std:front"
    frame.scale_n = 100.0
    if perspective:
        frame.perspective = True
    composer.snap_cache.clear()
    composer.edge_snap_cache.clear()
    return composer, host, frame


def _page(composer, frame, *world):
    return composer._frame_world_to_page(frame, [world])[0]


def test_the_middle_of_an_edge_catches_with_its_model_point():
    composer, _host, frame = _composer()
    x, y = _page(composer, frame, 1.7, 0.0, 0.0)
    hit = composer.nearest_snap_point(x, y + 0.3, 1.0)
    assert hit is not None and hit.on_edge
    assert hit[3] is frame
    assert hit[0] == pytest.approx(x, abs=1e-6)
    assert hit[1] == pytest.approx(y, abs=1e-6)
    assert hit[2] == pytest.approx((1.7, 0.0, 0.0), abs=1e-6)


def test_a_corner_and_a_midpoint_still_win_over_the_edge():
    composer, _host, frame = _composer()
    for world in ((0.0, 0.0, 0.0), (3.0, 0.0, 0.0)):
        x, y = _page(composer, frame, *world)
        hit = composer.nearest_snap_point(x + 0.5, y + 0.3, 1.0)
        assert not getattr(hit, "on_edge", False)
        assert hit[2] == pytest.approx(world, abs=1e-6)


def test_nothing_catches_away_from_every_edge():
    composer, _host, frame = _composer()
    x, y = _page(composer, frame, 1.7, 0.0, 1.5)      # the wall's blank middle
    assert composer.nearest_snap_point(x, y, 1.0) is None


def test_a_hidden_view_offers_no_edge():
    composer, _host, frame = _composer()
    x, y = _page(composer, frame, 1.7, 0.0, 0.0)
    frame.hidden = True
    assert composer.nearest_snap_point(x, y, 1.0) is None


def test_points_only_asks_for_no_edge():
    composer, _host, frame = _composer()
    x, y = _page(composer, frame, 1.7, 0.0, 0.0)
    assert composer.nearest_snap_point(x, y, 1.0, edges=False) is None


def test_a_point_outside_the_frame_does_not_catch():
    composer, _host, frame = _composer()
    frame.w_mm = 20.0                                 # the wall runs past it
    composer.snap_cache.clear()
    composer.edge_snap_cache.clear()
    x, y = _page(composer, frame, 0.0, 0.0, 0.0)
    if frame.x_mm <= x <= frame.x_mm + frame.w_mm:
        pytest.skip("this framing keeps the wall's end inside")
    hit = composer.nearest_snap_point(x, y, 1.0)
    assert hit is None


def test_perspective_takes_the_model_point_through_the_depth():
    """In perspective the middle of an edge on the page is not its middle in
    the model: the point has to project back to where the cursor is."""
    composer, host, frame = _composer(perspective=True)
    # A second wall running away from the front view.
    host.viewport.scene.mesh.add_face(
        [V(6, 0, 0), V(6, 5, 0), V(6, 5, 3), V(6, 0, 3)])
    composer._geom_cache = None
    composer.snap_cache.clear()
    composer.edge_snap_cache.clear()
    edges = composer.frame_snap_edges(frame)
    assert edges[2] is not None and len(edges[0])
    # A wall edge seen at an angle: its two ends at different depths.
    k = int(np.argmax(np.abs(edges[2][:, 0] - edges[2][:, 1])))
    assert abs(edges[2][k, 0] - edges[2][k, 1]) > 0.5
    ax, ay, bx, by = edges[0][k]
    hit = composer.nearest_snap_point(ax + 0.37 * (bx - ax),
                                      ay + 0.37 * (by - ay), 1.0)
    assert hit is not None and hit.on_edge
    back = composer._frame_world_to_page(frame, [hit[2]])[0]
    assert back == pytest.approx((hit[0], hit[1]), abs=1e-6)
    # ...and it is not the plain interpolation.
    w0, w1 = edges[1][k]
    plain = w0 + 0.37 * (w1 - w0)
    assert np.linalg.norm(np.array(hit[2]) - plain) > 1e-3


def _anchored_cota(frame, a, b):
    cota = CotaItem(x_mm=0.0, y_mm=0.0, dx_mm=1.0, dy_mm=0.0)
    cota.anchor_uid = frame.uid
    cota.a_world, cota.b_world = list(a), list(b)
    return cota


def test_a_cota_on_an_edge_near_a_corner_stays_on_the_edge():
    """Re-attaching took the nearest point within 2.5 paper mm: at 1:100 a
    point 20 cm from the corner went to the corner."""
    composer, _host, frame = _composer()
    if not frame.uid:
        frame.uid = "wall"
    cota = _anchored_cota(frame, (0.2, 0.0, 0.0), (3.0, 0.0, 0.0))
    composer.comp.cotas.append(cota)
    composer._reproject_anchored_cotas()
    assert cota.a_world == pytest.approx([0.2, 0.0, 0.0], abs=1e-6)
    assert cota.b_world == pytest.approx([3.0, 0.0, 0.0], abs=1e-6)


def test_a_cota_off_the_edge_comes_back_onto_it():
    """The wall moved a little: the end goes to the edge, within the same
    paper tolerance a corner has."""
    composer, _host, frame = _composer()
    if not frame.uid:
        frame.uid = "wall"
    cota = _anchored_cota(frame, (2.0, 0.0, 0.1), (3.0, 0.0, 0.0))
    composer.comp.cotas.append(cota)
    composer._reproject_anchored_cotas()
    assert cota.a_world == pytest.approx([2.0, 0.0, 0.0], abs=1e-6)


def test_the_marker_tells_an_edge_from_a_point():
    composer, _host, frame = _composer()
    view = composer._view
    composer._set_tool_mode("cota")
    x, y = _page(composer, frame, 1.7, 0.0, 0.0)
    pos, snapped = view._snapped(QPointF(x, y))
    assert snapped
    edge_colour = view._snap_marker.brush().color().name()
    x, y = _page(composer, frame, 0.0, 0.0, 0.0)
    pos, snapped = view._snapped(QPointF(x, y))
    assert snapped
    assert view._snap_marker.brush().color().name() != edge_colour


def test_a_cota_goes_between_two_points_on_edges_and_anchors():
    composer, _host, frame = _composer()
    view = composer._view
    composer._set_tool_mode("cota")
    a = _page(composer, frame, 1.1, 0.0, 0.0)
    b = _page(composer, frame, 4.3, 0.0, 3.0)
    view._snapped(QPointF(*a))
    hit_a = view._last_hit
    view._snapped(QPointF(*b))
    hit_b = view._last_hit
    anchors = view._pair_anchors(hit_a, hit_b)
    assert anchors is not None
    assert anchors[0] is frame
    assert anchors[1] == pytest.approx((1.1, 0.0, 0.0), abs=1e-6)
    assert anchors[2] == pytest.approx((4.3, 0.0, 3.0), abs=1e-6)


def _place_and_stretch(composer, frame, a, b):
    composer.tool_mode = "cota"
    composer.place_tool(30.0, 100.0, 90.0, 100.0, sep_mm=6.0,
                        anchors=(frame, a, b))
    cota = composer.comp.cotas[-1]
    for v in composer._scene().mesh.vertices:
        if abs(v.position.x() - 6.0) < 1e-9:
            v.position.setX(6.2)
    composer._invalidate_geometry_caches()
    composer._reproject_anchored_cotas()
    return cota


def test_a_corner_left_on_a_stretched_wall_follows_the_corner():
    """The old corner sits on the longer wall now, and is still a corner."""
    composer, _host, frame = _composer()
    cota = _place_and_stretch(
        composer, frame, (0.0, 0.0, 0.0), (6.0, 0.0, 0.0))
    assert cota.b_world[0] == pytest.approx(6.2)


def test_a_point_along_an_edge_stays_after_the_wall_stretches():
    composer, _host, frame = _composer()
    cota = _place_and_stretch(
        composer, frame, (5.9, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert cota.a_world == pytest.approx([5.9, 0.0, 0.0], abs=1e-6)
    assert cota.b_world == pytest.approx([1.0, 0.0, 0.0], abs=1e-6)
