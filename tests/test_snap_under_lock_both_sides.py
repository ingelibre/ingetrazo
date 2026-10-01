# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fetching a point under a lock, whichever side of the start it is on
(issue #34, @pacaeiro on 0.4.5).

«When we draw a line with Snap active (axis Z, or other) and have several
lines to choose points from, a few errors: (1) a point at the same level
— no points are detected; (2) Origin not always detected… I think it is
if the position of the Origin is negative from the other point; (3) with
Shift (X)… not all of them are detected; (4) release Shift to orbit and
reactivate it: half of the Snap points are not detected; (5) pressing L
again with the first point defined should reset the command.» And why he
insists: «Snap is the foundation of every Assembly.»

Measured before the fix with the cursor exactly ON each reference, six
dashes around the start and five cameras: under the X lock, every camera
lost a different one; under the Z lock the three at the start's height
never showed. The lock line runs both ways, but the side a reference was
allowed on was decided by where the cursor RAY met the line — and with
the cursor on a reference far from the line, that is anywhere. And (4)
was a rule with no snaps at all: Shift held over a soft axis cue, when
the press had found nothing to capture.
"""
from __future__ import annotations

import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

from core.snap import compute_snap

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


# ---- pacaeiro's dashes, through the real viewport --------------------------

#: Short X-parallel dashes at three heights, on BOTH sides of the start.
DASHES = [(-1.5, 0.8, 0.6), (1.5, 0.8, 0.6), (-1.5, -0.8, 1.4),
          (1.5, -0.8, 1.4), (-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
INICIO = V(0.3, 0.2, 0.0)
CAMERAS = [("iso", None, None), ("obl-a", -30, 12), ("obl-b", -75, 55),
           ("obl-c", 20, 25), ("obl-d", 160, 40)]


def _scene():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1600, 900)
    _app.processEvents()
    vp = win.viewport
    for x, y, z in DASHES:
        vp.scene.mesh.add_edge(V(x, y, z), V(x + 0.4, y, z))
    vp.scene.version += 1
    win._activate_tool("line")
    return win, vp


def _camera(vp, name, yaw, pitch):
    if yaw is None:
        vp.camera.set_view(name)
    else:
        vp.camera.yaw = math.radians(yaw)
        vp.camera.pitch = math.radians(pitch)
    vp.camera.distance = 10.0
    vp.camera.target = V(0, 0, 0.5)
    _app.processEvents()


def _hover(vp, world):
    px = vp._world_to_pixel(world)
    vp._last_mouse_pos = QPointF(*px)
    vp._process_hover(QPointF(*px), Qt.NoModifier)
    return px


def _lock(vp, axis):
    tool = vp.active_tool
    tool.start_point = QVector3D(INICIO)
    tool.chain_first_point = tool.start_point
    vp.axis_lock = axis


@pytest.mark.parametrize("cam", CAMERAS, ids=[c[0] for c in CAMERAS])
def test_every_dash_is_found_under_the_x_lock_on_either_side(cam):
    win, vp = _scene()
    try:
        _camera(vp, *cam)
        _lock(vp, "x")
        for x, y, z in DASHES + [(0.0, 0.0, 0.0)]:
            _hover(vp, V(x, y, z))
            s = vp.last_snap
            assert s.kind in ("from_point", "origin"), (x, y, z, s.kind)
            assert s.point.x() == pytest.approx(x, abs=1e-5), (x, y, z)
            assert s.point.y() == pytest.approx(INICIO.y(), abs=1e-5)
            assert s.point.z() == pytest.approx(INICIO.z(), abs=1e-5)
    finally:
        win._saved_version = vp.scene.version
        win.close()


@pytest.mark.parametrize("cam", CAMERAS, ids=[c[0] for c in CAMERAS])
def test_under_the_z_lock_the_dashes_at_the_starts_own_level_show_too(cam):
    win, vp = _scene()
    try:
        _camera(vp, *cam)
        _lock(vp, "z")
        for x, y, z in DASHES:
            _hover(vp, V(x, y, z))
            s = vp.last_snap
            assert s.kind == "from_point", (x, y, z, s.kind)
            assert s.point.z() == pytest.approx(z, abs=1e-5), (x, y, z)
            assert s.point.x() == pytest.approx(INICIO.x(), abs=1e-5)
            # …and the guide runs from the dash to the foot, so a dash at the
            # start's own height reads as «level with it».
            assert s.guide is not None
            assert (s.guide[0] - V(x, y, z)).length() < 1e-5
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_clicking_the_level_foot_at_the_start_draws_nothing_and_breaks_nothing():
    win, vp = _scene()
    try:
        _camera(vp, "iso", None, None)
        _lock(vp, "z")
        px = _hover(vp, V(-1.0, 0.0, 0.0))          # a dash at the start's level
        assert vp.last_snap.kind == "from_point"
        assert (vp.last_snap.point - INICIO).length() < 1e-6
        edges = len(vp.scene.mesh.edges)
        vp._dispatch_tool_click(QMouseEvent(
            QMouseEvent.MouseButtonPress, QPointF(*px),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        assert len(vp.scene.mesh.edges) == edges          # no zero-length edge
        assert (vp.active_tool.start_point - INICIO).length() < 1e-6  # still drawing
    finally:
        win._saved_version = vp.scene.version
        win.close()


# ---- (4) Shift held over a soft axis cue: the rule that had no snaps ---------

def _w2p(p):
    return (p.x() * 100.0, -p.y() * 100.0)


CAJA = [SimpleNamespace(a=V(2, -1), b=V(6, -1), center=False),
        SimpleNamespace(a=V(6, -1), b=V(6, 3), center=False)]


def _shift_soft(cand, scene=None):
    def project(s, d):
        return s + d * QVector3D.dotProduct(cand - s, d)
    return compute_snap(
        candidate_world=cand, candidate_pixel=_w2p(cand),
        scene=scene if scene is not None else SimpleNamespace(edges=CAJA),
        world_to_pixel=_w2p, threshold_px=9.0, edge_threshold_px=14.0,
        start_point=V(0, 0, 0), project_onto_line=project, shift_held=True)


def test_shift_over_the_soft_axis_cue_finds_the_crossing():
    assert _shift_soft(V(6.0, 0.03, 0.0)).kind == "intersection"


def test_shift_over_the_soft_axis_cue_lines_up_with_a_hovered_corner():
    # The cursor on the box's corner, 1 m off the line: its foot on it.
    # (The soft cue needs the CANDIDATE near the axis, so the candidate is
    # the corner's foot and the pixel is the corner's.)
    corner = V(6, -1, 0)

    def project(s, d):
        return s + d * QVector3D.dotProduct(V(6, 0.02, 0) - s, d)
    r = compute_snap(
        candidate_world=V(6, 0.02, 0), candidate_pixel=_w2p(corner),
        scene=SimpleNamespace(edges=[CAJA[0]]), world_to_pixel=_w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=V(0, 0, 0),
        project_onto_line=project, shift_held=True)
    assert r.kind == "from_point"
    assert (r.point - V(6, 0, 0)).length() < 1e-6
    assert (r.guide[0] - corner).length() < 1e-6


def test_shift_over_the_soft_axis_cue_lands_on_a_vertex_on_the_line():
    borde = SimpleNamespace(a=V(4, 0), b=V(4, 2), center=False)
    r = _shift_soft(V(4.02, 0.01, 0.0), scene=SimpleNamespace(edges=[borde]))
    assert r.kind == "endpoint"


def test_shift_over_the_soft_axis_cue_still_locks_with_nothing_around():
    r = _shift_soft(V(3.0, 0.05, 0.0), scene=SimpleNamespace(edges=[]))
    assert r.kind == "axis" and r.axis == "x"
    assert r.point.y() == pytest.approx(0.0, abs=1e-9)


def _reference_edge(a, b):
    return SimpleNamespace(a=a, b=b, center=False)


def _reference_lock(mode, cand, edges, cursor=None, reference=None):
    if reference is None:
        reference = _reference_edge(V(-2, 0), V(2, 0))

    def project(start, direction):
        return start + direction * QVector3D.dotProduct(cand - start, direction)

    return compute_snap(
        candidate_world=cand,
        candidate_pixel=_w2p(cursor if cursor is not None else cand),
        scene=SimpleNamespace(edges=[reference, *edges]),
        world_to_pixel=_w2p, threshold_px=9.0, edge_threshold_px=14.0,
        start_point=V(0, 0), project_onto_line=project,
        reference_edge=reference, reference_mode=mode,
    )


@pytest.mark.parametrize(("mode", "candidate", "crossing"), [
    ("parallel", V(3.03, 0.04), V(3, 0)),
    ("perpendicular", V(0.04, 3.03), V(0, 3)),
])
def test_reference_edge_lock_snaps_to_crossings(mode, candidate, crossing):
    if mode == "parallel":
        edges = [_reference_edge(V(3, -1), V(3, 1))]
    else:
        edges = [_reference_edge(V(-1, 3), V(1, 3))]
    r = _reference_lock(mode, candidate, edges)
    assert r.kind == "intersection"
    assert (r.point - crossing).length() < 1e-6


@pytest.mark.parametrize(("mode", "candidate", "corner", "foot"), [
    ("parallel", V(3, 0.02), V(3, 1), V(3, 0)),
    ("perpendicular", V(0.02, 3), V(1, 3), V(0, 3)),
])
def test_reference_edge_lock_aligns_with_an_off_line_corner(
        mode, candidate, corner, foot):
    edges = [_reference_edge(corner, corner + V(1, 0))]
    r = _reference_lock(mode, candidate, edges, cursor=corner)
    assert r.kind == "from_point"
    assert (r.point - foot).length() < 1e-6


@pytest.mark.parametrize(("mode", "candidate", "locked"), [
    ("parallel", V(-3, 0.05), V(-3, 0)),
    ("perpendicular", V(0.05, -3), V(0, -3)),
])
def test_reference_edge_lock_keeps_its_direction_without_a_snap(
        mode, candidate, locked):
    r = _reference_lock(mode, candidate, [])
    assert r.kind == "reference"
    assert (r.point - locked).length() < 1e-6


@pytest.mark.parametrize(("mode", "candidate", "corner", "foot"), [
    ("parallel", V(3.01, 3.01), V(2, 4), V(3, 3)),
    ("perpendicular", V(-3.01, 3.01), V(-4, 2), V(-3, 3)),
])
def test_reference_edge_lock_aligns_points_to_diagonal_vectors(
        mode, candidate, corner, foot):
    reference = _reference_edge(V(0, 0), V(1, 1))
    edges = [_reference_edge(corner, corner + V(1, 0))]
    r = _reference_lock(mode, candidate, edges, cursor=corner,
                        reference=reference)
    assert r.kind == "from_point"
    assert (r.point - foot).length() < 1e-6


# ---- (5) L again resets the Line -------------------------------------------

def test_pressing_the_tools_key_again_releases_the_first_point():
    win, vp = _scene()
    try:
        _camera(vp, "iso", None, None)
        _lock(vp, "x")
        assert vp.active_tool.start_point is not None
        win._activate_tool("line")
        assert vp.active_tool.start_point is None
        assert vp.axis_lock is None
    finally:
        win._saved_version = vp.scene.version
        win.close()
