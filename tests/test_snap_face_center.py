# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«Face center»: a snap point at the centre of area of the face under the
cursor — the middle of each of a box's six sides, the middle of a loose
rectangle — to align and place things on. Nothing is added to the model.
The point is offered when it falls within the face's outer boundary — in
the hole of a frame too, not in the elbow of an L. A selected face shows
its centre as a dot and offers it wherever the cursor is."""
from __future__ import annotations

import math
from types import SimpleNamespace

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.mesh import Mesh
from core.snap import COLOR_ON_FACE, compute_snap, face_center_of_face


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _close(a, b, tol=1e-6):
    return (a - b).length() < tol


def _box(mesh, x0, y0, z0, x1, y1, z1):
    """The six faces of an axis-aligned box."""
    c = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return [mesh.add_face([c[i] for i in q]) for q in quads]


# ---- The centre itself --------------------------------------------------------

def test_each_of_a_boxs_six_faces_has_its_centre():
    faces = _box(Mesh(), 0, 0, 0, 2, 4, 6)
    got = sorted((round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))
                 for p in (face_center_of_face(f) for f in faces))
    assert got == sorted([(1, 2, 0), (1, 2, 6), (1, 0, 3),
                          (2, 2, 3), (1, 4, 3), (0, 2, 3)])


def test_a_loose_rectangle_has_one_centre():
    f = Mesh().add_face([V(1, 1), V(5, 1), V(5, 3), V(1, 3)])
    assert _close(face_center_of_face(f), V(3, 2))


def test_the_centre_is_of_area_not_the_average_of_the_corners():
    # A trapezoid: the corners average to y = 1, the area centre is lower,
    # nearer the long side — y = h(b + 2a) / 3(b + a) = 2·(6 + 4)/(3·8) = 5/6.
    f = Mesh().add_face([V(0, 0), V(6, 0), V(4, 2), V(2, 2)])
    c = face_center_of_face(f)
    assert abs(c.x() - 3.0) < 1e-6                     # QVector3D: float32
    assert abs(c.y() - 5.0 / 6.0) < 1e-6
    assert abs(f.centroid().y() - 1.0) < 1e-6          # what it must not be


def test_many_corners_on_one_side_do_not_pull_the_centre():
    # A square whose bottom edge is cut in 20 pieces.
    pts = [V(i * 0.1, 0) for i in range(20)] + [V(2, 0), V(2, 2), V(0, 2)]
    c = face_center_of_face(Mesh().add_face(pts))
    assert _close(c, V(1, 1))


def test_no_centre_when_it_falls_outside_the_face():
    # An L: its centre of area (≈ 1.17, 1.17) sits in the missing corner.
    el = Mesh().add_face([V(0, 0), V(3, 0), V(3, 1), V(1, 1), V(1, 3), V(0, 3)])
    assert face_center_of_face(el) is None


def test_a_rings_centre_is_in_its_hole_and_an_off_centre_hole_moves_it():
    ring = Mesh().add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)],
                           [[V(1, 1), V(3, 1), V(3, 3), V(1, 3)]])
    assert _close(face_center_of_face(ring), V(2, 2))
    # A 1×1 hole in the right half: the centre moves left, away from it.
    side = Mesh().add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)],
                           [[V(2.5, 1.5), V(3.5, 1.5), V(3.5, 2.5), V(2.5, 2.5)]])
    c = face_center_of_face(side)
    # (16·2 − 1·3) / 15 = 29/15
    assert abs(c.x() - 29.0 / 15.0) < 1e-6 and abs(c.y() - 2.0) < 1e-6


def test_a_placed_faces_centre_is_in_the_world():
    f = Mesh().add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    xf = QMatrix4x4()
    xf.translate(10, 5, 1)
    xf.rotate(90, 1, 0, 0)                  # stood up on its side
    assert _close(face_center_of_face(f, xf), xf.map(V(1, 1)))


def test_a_degenerate_face_has_none():
    f = SimpleNamespace(vertices=[V(0, 0), V(1, 0), V(2, 0)], holes=[])
    assert face_center_of_face(f) is None


# ---- In the snap engine -------------------------------------------------------

def _w2p(p):                      # plan view, 100 px a metre
    return (p.x() * 100.0, -p.y() * 100.0)


def _snap(scene, cand, **kw):
    return compute_snap(cand, _w2p(cand), scene, _w2p, threshold_px=9.0,
                        edge_threshold_px=14.0, face_under_cursor=True, **kw)


def _square_scene():
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    return SimpleNamespace(edges=[SimpleNamespace(a=e.v0.position, b=e.v1.position)
                                  for e in m.edges])


def test_near_the_centre_the_engine_snaps_to_it_by_name():
    r = _snap(_square_scene(), V(1.04, 0.97), face_centers=[(V(1, 1), None)])
    assert r.kind == "face_center" and r.color == COLOR_ON_FACE
    assert _close(r.point, V(1, 1))


def test_away_from_the_centre_it_is_still_on_face():
    r = _snap(_square_scene(), V(1.4, 1.3), face_centers=[(V(1, 1), None)])
    assert r.kind == "on_face"


def test_a_corner_as_close_wins_the_tie():
    # A tiny face: the cursor exactly between a corner and the centre.
    scene = SimpleNamespace(edges=[SimpleNamespace(a=V(1, 1), b=V(1.1, 1))])
    r = _snap(scene, V(1.025, 1.025), face_centers=[(V(1.05, 1.05), None)])
    assert r.kind == "endpoint"


def test_the_centre_the_operation_started_on_is_not_offered_again():
    # A circle begun at the face's centre: its rim must not snap back onto
    # that same centre (a zero radius, and no disc).
    r = _snap(_square_scene(), V(1.04, 0.97), start_point=V(1, 1),
              face_centers=[(V(1, 1), None)])
    assert r.kind != "face_center"
    assert not _close(r.point, V(1, 1))

def test_inside_a_component_the_tip_says_so():
    r = _snap(_square_scene(), V(1.0, 1.02), face_centers=[(V(1, 1), "component")])
    assert r.kind == "face_center" and r.context == "component"


# ---- In the viewport ----------------------------------------------------------

def _offscreen_vp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("top")
    return vp


def _hover(vp, world):
    from PySide6.QtCore import QPointF, Qt
    px = vp._world_to_pixel(world)
    vp._process_hover(QPointF(*px), Qt.NoModifier)
    return vp.last_snap


def test_hovering_a_rectangle_near_its_middle_offers_the_face_center():
    from tools.line import LineTool
    vp = _offscreen_vp()
    vp.camera.target = V(2, 1.5, 0)
    vp.camera.distance = 12
    vp.scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 3), V(0, 3)])
    vp.scene.version += 1
    vp.set_active_tool(LineTool())
    snap = _hover(vp, V(2.03, 1.52, 0))
    assert snap.kind == "face_center", snap.kind
    assert _close(snap.point, V(2, 1.5, 0), 1e-5)
    assert snap.context is None
    assert len(vp.scene.mesh.vertices) == 4          # nothing added
    assert _hover(vp, V(3.2, 0.7, 0)).kind == "on_face"


def test_an_l_shaped_face_offers_no_centre():
    from tools.line import LineTool
    vp = _offscreen_vp()
    vp.camera.target = V(1.5, 1.5, 0)
    vp.camera.distance = 12
    vp.scene.mesh.add_face([V(0, 0), V(3, 0), V(3, 1), V(1, 1), V(1, 3), V(0, 3)])
    vp.scene.version += 1
    vp.set_active_tool(LineTool())
    assert vp._face_center_under(*vp._world_to_pixel(V(0.5, 0.5, 0))) is None


def test_a_groups_face_offers_its_centre_where_the_group_stands():
    from core.group import Group
    from tools.line import LineTool
    vp = _offscreen_vp()
    vp.camera.target = V(6, 5, 0)
    vp.camera.distance = 12
    mesh = Mesh()
    mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    g = Group(mesh, "pieza")
    xf = QMatrix4x4()
    xf.translate(5, 4, 0)
    g.xform = xf
    vp.scene.groups.append(g)
    vp.scene.version += 1
    vp.set_active_tool(LineTool())
    snap = _hover(vp, V(6.02, 5.03, 0))
    assert snap.kind == "face_center", snap.kind
    assert _close(snap.point, V(6, 5, 0), 1e-5)
    assert snap.context in ("group", "component")


def test_face_center_is_named_everywhere_it_must_be():
    from core.inference import InferenceEngine
    from tools.scale import ScaleTool
    from views.viewport import Viewport
    import json
    import pathlib
    assert "face_center" in Viewport._SNAP_LABELS
    assert "face_center" in Viewport._ENCOURAGING_KINDS
    assert "face_center" in InferenceEngine._NAMED_SNAPS
    assert "face_center" in ScaleTool._TARGET_KINDS
    root = pathlib.Path(__file__).resolve().parent.parent / "i18n"
    for p in root.glob("*.json"):
        if p.name == "en.json":
            continue
        assert "Face center" in json.loads(p.read_text(encoding="utf-8")), p.name


# ---- Selected faces -----------------------------------------------------------

def _ring_vp():
    """A 4 × 4 frame with a 2 × 2 hole, seen from above."""
    vp = _offscreen_vp()
    vp.camera.target = V(2, 2, 0)
    vp.camera.distance = 12
    ring = vp.scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)],
                                  [[V(1, 1), V(3, 1), V(3, 3), V(1, 3)]])
    vp.scene.version += 1
    return vp, ring


def test_a_selected_rings_centre_is_reached_from_its_hole():
    from tools.line import LineTool
    vp, ring = _ring_vp()
    vp.set_active_tool(LineTool())
    # Not selected: the cursor in the hole is on no face, nothing to offer.
    assert _hover(vp, V(2.03, 2.02, 0)).kind != "face_center"
    vp.scene.selection.add(ring)
    snap = _hover(vp, V(2.03, 2.02, 0))
    assert snap.kind == "face_center", snap.kind
    assert _close(snap.point, V(2, 2, 0), 1e-5)


def test_selected_faces_show_their_centres_as_dots():
    from PySide6.QtGui import QImage, QPainter
    vp, ring = _ring_vp()
    other = vp.scene.mesh.add_face([V(5, 0), V(7, 0), V(7, 2), V(5, 2)])
    vp.scene.version += 1
    img = QImage(1000, 600, QImage.Format_ARGB32)
    painter = QPainter(img)
    try:
        vp._draw_selected_face_centers(painter)          # nothing selected
        assert getattr(vp, "_sel_face_center_dots", None) is None
        vp.scene.selection.add(ring)
        vp.scene.selection.add(other)
        vp._draw_selected_face_centers(painter)
    finally:
        painter.end()
    dots = vp._sel_face_center_dots[1]
    want = [vp._world_to_pixel(V(2, 2, 0)), vp._world_to_pixel(V(6, 1, 0))]
    assert len(dots) == 2
    for w in want:
        assert any(math.hypot(d[0] - w[0], d[1] - w[1]) < 0.5 for d in dots), w


def test_a_selected_l_and_a_selected_group_offer_no_dots():
    from core.group import Group
    vp = _offscreen_vp()
    el = vp.scene.mesh.add_face([V(0, 0), V(3, 0), V(3, 1), V(1, 1), V(1, 3), V(0, 3)])
    mesh = Mesh()
    mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    g = Group(mesh, "pieza")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    vp.scene.selection.add(el)
    vp.scene.selection.add(g)
    assert vp._selected_face_centers() == []


def test_too_many_selected_faces_offer_no_dots():
    vp = _offscreen_vp()
    vp.FACE_CENTER_SELECTION_MAX = 3
    faces = [vp.scene.mesh.add_face([V(i * 2, 0), V(i * 2 + 1, 0),
                                     V(i * 2 + 1, 1), V(i * 2, 1)])
             for i in range(4)]
    vp.scene.version += 1
    for f in faces[:3]:
        vp.scene.selection.add(f)
    assert len(vp._selected_face_centers()) == 3
    vp.scene.selection.add(faces[3])
    assert vp._selected_face_centers() == []


def _marker_box(vp, kind):
    """Width and height in pixels of the marker drawn for a snap of
    ``kind`` (its tip left out)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from core.snap import SnapResult
    vp._SNAP_LABELS = {}                               # no tip text
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    vp._world_to_pixel = lambda _p: (100.0, 100.0)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        vp._draw_snap_indicator(painter, SnapResult(V(0, 0, 0), kind, COLOR_ON_FACE))
    finally:
        painter.end()
    xs, ys = [], []
    for y in range(200):
        for x in range(200):
            if img.pixelColor(x, y).alpha() > 40:
                xs.append(x)
                ys.append(y)
    return max(xs) - min(xs), max(ys) - min(ys)


def test_the_marker_is_the_size_of_the_endpoints():
    vp = _offscreen_vp()
    end = _marker_box(vp, "endpoint")
    centre = _marker_box(vp, "face_center")
    assert abs(centre[0] - end[0]) <= 1 and abs(centre[1] - end[1]) <= 1, (centre, end)


def test_a_selected_faces_dot_is_as_big_as_a_snap_marker():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    vp = _offscreen_vp()
    vp.camera.target = V(1, 1, 0)
    vp.camera.distance = 12
    f = vp.scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    vp.scene.version += 1
    vp.scene.selection.add(f)
    img = QImage(1000, 600, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        vp._draw_selected_face_centers(painter)
    finally:
        painter.end()
    cx, cy = (int(round(c)) for c in vp._world_to_pixel(V(1, 1, 0)))
    xs = [x for x in range(cx - 30, cx + 31) if img.pixelColor(x, cy).alpha() > 40]
    width = max(xs) - min(xs)
    end = _marker_box(_offscreen_vp(), "endpoint")[0]
    assert width >= end - 3, (width, end)
