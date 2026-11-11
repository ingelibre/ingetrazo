# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The 2-point Arc rounds a corner the classic way (Rafael's review of
2026-09-10, C2: «te fuerza la misma distancia» on the other
edge, and the arc adapts to the face).

Start ON an edge and the preview is the arc tangent to it (cyan). On the
adjacent edge, at the same distance from the shared corner, the end point
snaps and the arc turns magenta — tangent to both edges. A double-click
there draws the fillet and trims the corner stubs, so the face keeps its
new rounded outline; a double-click near another two-edge corner repeats
the last distance. Alt keeps the stubs. «Ns» right after rebuilds the arc
with N segments.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.edits import build_add_edges
from tools.arc import COLOR_FILLET, ArcTool
from tools.base import ToolContext


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


def _square(vp, size=2.0):
    vp.scene.clear() if hasattr(vp.scene, "clear") else None
    vp.scene.mesh.clear()
    vp.history.undo_stack.clear()
    vp.history.redo_stack.clear()
    sq = [QVector3D(0, 0, 0), QVector3D(size, 0, 0),
          QVector3D(size, size, 0), QVector3D(0, size, 0)]
    vp.history.execute(build_add_edges(
        vp.scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)]))
    vp.camera.target = QVector3D(size / 2, size / 2, 0.0)
    vp.camera.distance = 8.0
    assert len(vp.scene.mesh.faces) == 1


def _ctx(vp, world, screen=None, modifiers=Qt.NoModifier):
    if screen is None:
        px = vp._world_to_pixel(world)
        assert px is not None
        screen = QPointF(*px)
    return ToolContext(viewport=vp, world=QVector3D(world), screen=screen,
                       modifiers=modifiers, snap=None)


def _tool(vp):
    tool = ArcTool()
    tool.on_activate(vp)
    vp._hover_edge = None
    return tool


def _arc_edges(mesh):
    return [e for e in mesh.edges if e.curve is not None]


def _corner_gone(mesh, p) -> bool:
    """No edge meets at ``p`` any more (the registry may keep a lone vertex)."""
    v = mesh.vertex_at(QVector3D(*p))
    return v is None or not v.edges


def test_start_on_an_edge_previews_the_tangent_arc(viewport):
    _square(viewport)
    tool = _tool(viewport)
    P1 = QVector3D(1.5, 0, 0)
    tool.on_click(_ctx(viewport, P1))
    assert tool._start_edge is not None
    # Away from any equidistant point: a tangent arc, cyan, not a chord.
    tool.on_hover(_ctx(viewport, QVector3D(1.0, 1.0, 0)))
    lines = tool.rubber_band_lines()
    assert len(lines) > 1
    from core.snap import COLOR_TANGENT
    assert tool.wireframe_color[:3] == COLOR_TANGENT
    assert tool.value_label()[0] == "Tangent to edge"
    # The arc leaves P1 along the edge: its first span is (nearly) along X.
    a, b = lines[0]
    d = (b - a).normalized()
    assert abs(d.y()) < 0.15 and abs(d.z()) < 1e-6


def test_the_adjacent_edge_snaps_at_the_same_distance_from_the_corner(viewport):
    _square(viewport)
    tool = _tool(viewport)
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    # Slightly off the equidistant point (a couple of pixels): it snaps.
    px = viewport._world_to_pixel(P2)
    near = QPointF(px[0] + 3, px[1] - 2)
    world = viewport._world_from_pixel(int(near.x()), int(near.y()))
    tool.on_hover(_ctx(viewport, world, near))
    assert tool._equidistant is not None
    V, snapped, edge = tool._equidistant
    assert (snapped - P2).length() < 1e-6
    assert (V - QVector3D(2, 0, 0)).length() < 1e-9
    assert tool.wireframe_color[:3] == COLOR_FILLET
    assert (tool.hover_point - P2).length() < 1e-6
    # Far along the same edge: no snap, cyan again.
    tool.on_hover(_ctx(viewport, QVector3D(2.0, 1.5, 0)))
    assert tool._equidistant is None
    assert tool.wireframe_color[:3] != COLOR_FILLET


def test_double_click_on_the_magenta_point_fillets_and_trims_the_corner(viewport):
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    tool.on_hover(_ctx(viewport, P2))
    tool.on_click(_ctx(viewport, P2))             # first press of the double-click
    assert tool._fillet is not None
    assert (tool.end_point - P2).length() < 1e-6
    tool.on_double_click(_ctx(viewport, P2))
    assert tool.start_point is None               # committed and reset
    assert len(mesh.faces) == 1
    assert _corner_gone(mesh, (2, 0, 0))
    arc = _arc_edges(mesh)
    assert len(arc) == tool.segments
    # Tangent to both edges: every arc point is 0.5 from the centre (1.5, 0.5).
    c = QVector3D(1.5, 0.5, 0)
    for e in arc:
        for p in (e.a, e.b):
            assert abs((p - c).length() - 0.5) < 1e-6
    assert ArcTool.last_fillet_d == pytest.approx(0.5)
    # One undo brings the square corner back.
    viewport.history.undo()
    assert not _corner_gone(mesh, (2, 0, 0))
    assert len(mesh.faces) == 1 and len(mesh.edges) == 4


def test_bulge_phase_snaps_to_the_fillet_and_to_the_half_circle(viewport):
    _square(viewport)
    tool = _tool(viewport)
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    tool.on_hover(_ctx(viewport, P2))
    tool.on_click(_ctx(viewport, P2))
    # The fillet bulge: sagitta of the quarter circle, on the corner's side.
    mid = (QVector3D(1.5, 0, 0) + P2) * 0.5
    half_chord = (P2 - QVector3D(1.5, 0, 0)).length() / 2.0
    h_fillet = 0.5 - math.sqrt(0.25 - half_chord ** 2)
    toward = (QVector3D(2, 0, 0) - mid).normalized()
    tool.on_hover(_ctx(viewport, mid + toward * h_fillet))
    assert tool._bulge_kind == "fillet"
    assert tool.wireframe_color[:3] == COLOR_FILLET
    assert tool.value_label()[0].startswith("Tangent to edge")
    # Half circle: bulge = half the chord, on the other side.
    tool.on_hover(_ctx(viewport, mid - toward * half_chord))
    assert tool._bulge_kind == "half"
    assert tool.value_label()[0].startswith("Half circle")
    # Somewhere else: plain bulge.
    tool.on_hover(_ctx(viewport, mid - toward * (half_chord * 2.5)))
    assert tool._bulge_kind is None
    # A single click at the fillet commits AND trims (the classic behaviour).
    tool.on_hover(_ctx(viewport, mid + toward * h_fillet))
    tool.on_click(_ctx(viewport, mid + toward * h_fillet))
    mesh = viewport.scene.mesh
    assert len(mesh.faces) == 1
    assert _corner_gone(mesh, (2, 0, 0))


def test_alt_keeps_the_corner_stubs(viewport):
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    tool.on_hover(_ctx(viewport, P2))
    tool.on_click(_ctx(viewport, P2))
    tool.on_double_click(_ctx(viewport, P2, modifiers=Qt.AltModifier))
    assert tool.start_point is None
    assert not _corner_gone(mesh, (2, 0, 0))
    assert len(mesh.faces) == 2                    # the corner sliver stays


def test_double_click_near_another_corner_repeats_the_last_distance(viewport):
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    tool.on_hover(_ctx(viewport, P2))
    tool.on_click(_ctx(viewport, P2))
    tool.on_double_click(_ctx(viewport, P2))
    assert ArcTool.last_fillet_d == pytest.approx(0.5)
    # Double-click a whisker away from the opposite corner (0, 2, 0): the
    # first press starts an arc there, the second rounds the corner.
    near = QVector3D(0.02, 1.98, 0)
    tool.on_click(_ctx(viewport, near))
    tool.on_double_click(_ctx(viewport, near))
    assert tool.start_point is None
    assert _corner_gone(mesh, (0, 2, 0))
    assert len(mesh.faces) == 1
    c = QVector3D(0.5, 1.5, 0)
    arcs = [e for e in _arc_edges(mesh)
            if abs((e.a - c).length() - 0.5) < 1e-6]
    assert len(arcs) == tool.segments


def test_a_three_edge_corner_is_not_trimmed(viewport):
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    # A third edge standing on the corner (a post): the fillet «won't cut».
    viewport.history.execute(build_add_edges(
        viewport.scene, [(QVector3D(2, 0, 0), QVector3D(2, 0, 1))]))
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    tool.on_hover(_ctx(viewport, P2))
    assert tool._equidistant is not None          # the inference still works
    tool.on_click(_ctx(viewport, P2))
    tool.on_double_click(_ctx(viewport, P2))
    assert not _corner_gone(mesh, (2, 0, 0))
    assert len(mesh.faces) == 2


def test_segments_typed_after_the_arc_rebuild_it(viewport):
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    tool.on_hover(_ctx(viewport, P2))
    tool.on_click(_ctx(viewport, P2))
    tool.on_double_click(_ctx(viewport, P2))
    assert len(_arc_edges(mesh)) == 16
    assert tool.on_segments_value(viewport, 6)
    assert len(_arc_edges(mesh)) == 6
    assert len(mesh.faces) == 1
    assert _corner_gone(mesh, (2, 0, 0))
    # The VCB spells it "6s".
    assert viewport._parse_value_buffer("6s") == ("segments", 6)
    assert viewport._parse_value_buffer("2.5r") == ("radius", 2.5)


def test_the_fillet_follows_the_faces_plane(viewport):
    """A vertical face: the arc lies on it, not on the ground (Rafael:
    «aquí se me orienta en el plano XY, no me deja orientarlo a la cara»)."""
    viewport.scene.mesh.clear()
    viewport.history.undo_stack.clear()
    sq = [QVector3D(0, 0, 0), QVector3D(2, 0, 0),
          QVector3D(2, 0, 2), QVector3D(0, 0, 2)]
    viewport.history.execute(build_add_edges(
        viewport.scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)]))
    viewport.camera.target = QVector3D(1, 0, 1)
    viewport.camera.distance = 8.0
    viewport.camera.pitch = 0.0
    viewport.camera.yaw = math.radians(-90.0)
    tool = _tool(viewport)
    tool.hover_plane = (QVector3D(0, 0, 0), QVector3D(0, 1, 0))
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0, 0.5)
    tool.hover_plane = (QVector3D(0, 0, 0), QVector3D(0, 1, 0))
    tool.on_hover(_ctx(viewport, P2))
    assert tool._equidistant is not None
    tool.on_click(_ctx(viewport, P2))
    tool.hover_plane = (QVector3D(0, 0, 0), QVector3D(0, 1, 0))
    tool.on_double_click(_ctx(viewport, P2))
    mesh = viewport.scene.mesh
    assert len(mesh.faces) == 1
    assert _corner_gone(mesh, (2, 0, 0))
    for e in _arc_edges(mesh):
        assert abs(e.a.y()) < 1e-6 and abs(e.b.y()) < 1e-6


# ---- @pacaeiro, issue #43: with both tangencies fixed, a number is the RADIUS

def test_a_typed_value_on_the_magenta_arc_is_the_fillet_radius(viewport):
    """«We click on the first edge, position cursor to get the 2nd tangent
    to edge and give a value (the arc Radius, keeping the tangency)…
    right now it is directed to bulge». On a right-angle corner a radius
    r puts the tangent points r from the corner (d = r / tan 45°), so
    typing 0.8 after arming the fillet at 0.5 rounds the corner with
    radius 0.8, tangent to both edges, and trims it."""
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
    P2 = QVector3D(2.0, 0.5, 0)
    tool.on_hover(_ctx(viewport, P2))
    tool.on_click(_ctx(viewport, P2))
    assert tool._fillet is not None
    tool.on_hover(_ctx(viewport, QVector3D(1.9, 0.4, 0)))   # anywhere
    assert tool.on_value(viewport, 0.8) is True
    assert tool.start_point is None                          # committed
    assert _corner_gone(mesh, (2, 0, 0))
    arc = _arc_edges(mesh)
    assert len(arc) == tool.segments
    c = QVector3D(2.0 - 0.8, 0.8, 0)                         # centre for r = 0.8
    for e in arc:
        for p in (e.a, e.b):
            assert abs((p - c).length() - 0.8) < 1e-6
    ends = {tuple(round(v, 6) for v in (p.x(), p.y(), p.z()))
            for e in arc for p in (e.a, e.b)}
    assert (1.2, 0.0, 0.0) in ends and (2.0, 0.8, 0.0) in ends   # tangent points
    assert ArcTool.last_fillet_d == pytest.approx(0.8)
    assert len(mesh.faces) == 1


def test_a_radius_the_edges_cannot_hold_is_refused_and_said(viewport):
    _square(viewport)
    tool = _tool(viewport)
    said = []
    viewport.flash_status = lambda msg, *a, **k: said.append(msg)
    try:
        tool.on_click(_ctx(viewport, QVector3D(1.5, 0, 0)))
        P2 = QVector3D(2.0, 0.5, 0)
        tool.on_hover(_ctx(viewport, P2))
        tool.on_click(_ctx(viewport, P2))
        tool.on_hover(_ctx(viewport, QVector3D(1.9, 0.4, 0)))
        assert tool.on_value(viewport, 3.0) is True           # 3 m on a 2 m edge
        assert said and "3.00" in said[-1]
        assert tool._fillet is not None                        # still armed
        assert not _corner_gone(viewport.scene.mesh, (2, 0, 0))
    finally:
        viewport.flash_status = lambda *a, **k: None


def test_off_the_fillet_a_typed_value_is_still_the_bulge(viewport):
    """The plain two-point arc keeps its VCB meaning."""
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    tool.on_click(_ctx(viewport, QVector3D(0.5, 1.0, 0)))    # off any edge
    tool.on_click(_ctx(viewport, QVector3D(1.5, 1.0, 0)))
    assert tool._fillet is None
    tool.on_hover(_ctx(viewport, QVector3D(1.0, 1.3, 0)))
    assert tool.on_value(viewport, 0.2) is True
    arc = _arc_edges(mesh)
    top = max(p.y() for e in arc for p in (e.a, e.b))
    assert top == pytest.approx(1.2, abs=1e-6)                # bulge 0.2


def _arc_on(mesh, centre, radius):
    """The curve edges with both ends ``radius`` from ``centre``."""
    return [e for e in _arc_edges(mesh)
            if all(abs((p - centre).length() - radius) < 1e-5 for p in (e.a, e.b))]


def _fillet(vp, tool, start, end):
    """Round a corner from ``start`` to the equidistant ``end``, by a
    double-click on the magenta point."""
    tool.on_click(_ctx(vp, start))
    tool.on_hover(_ctx(vp, end))
    assert tool._equidistant is not None, "the end point snaps magenta"
    tool.on_click(_ctx(vp, end))
    tool.on_double_click(_ctx(vp, end))
    assert tool.start_point is None


def test_a_corner_already_rounded_rounds_again_with_a_larger_arc(viewport):
    """#1354: once a corner is rounded its two edges no longer meet, and a
    second, larger arc found no equidistant point. It is measured from
    where the edges' lines meet, the corner as it was drawn."""
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    _fillet(viewport, tool, QVector3D(1.5, 0, 0), QVector3D(2.0, 0.5, 0))
    # A larger arc on the same corner: from the bottom edge, 1 from the old
    # corner, to the right edge at the same distance from it.
    tool.on_click(_ctx(viewport, QVector3D(1.0, 0, 0)))
    P2 = QVector3D(2.0, 1.0, 0)
    tool.on_hover(_ctx(viewport, P2))
    assert tool._equidistant is not None
    V, snapped, edge = tool._equidistant
    assert (V - QVector3D(2, 0, 0)).length() < 1e-6, "the corner before it was rounded"
    assert (snapped - P2).length() < 1e-6
    assert edge.curve is None
    assert tool.wireframe_color[:3] == COLOR_FILLET
    tool.on_click(_ctx(viewport, P2))
    tool.on_double_click(_ctx(viewport, P2))
    assert tool.start_point is None
    # Tangent to both edges: a whole arc of points 1 from (1, 1), and the
    # first arc still there.
    assert len(_arc_on(mesh, QVector3D(1.0, 1.0, 0), 1.0)) == tool.segments
    assert len(_arc_on(mesh, QVector3D(1.5, 0.5, 0), 0.5)) == tool.segments


def test_a_typed_radius_on_a_rounded_corner_is_measured_from_the_old_corner(viewport):
    _square(viewport)
    tool = _tool(viewport)
    mesh = viewport.scene.mesh
    _fillet(viewport, tool, QVector3D(1.5, 0, 0), QVector3D(2.0, 0.5, 0))
    arcs = len(_arc_edges(mesh))
    tool.on_click(_ctx(viewport, QVector3D(1.0, 0, 0)))
    tool.on_hover(_ctx(viewport, QVector3D(2.0, 1.0, 0)))
    tool.on_click(_ctx(viewport, QVector3D(2.0, 1.0, 0)))
    assert tool._fillet is not None
    # A radius whose arc would sit inside the one already there is refused.
    assert tool.on_value(viewport, 0.3) is False
    assert len(_arc_edges(mesh)) == arcs
    # 1.5 from the old corner on each edge: the edges reach it.
    assert tool.on_value(viewport, 1.5) is True
    assert len(_arc_on(mesh, QVector3D(0.5, 1.5, 0), 1.5)) == tool.segments
