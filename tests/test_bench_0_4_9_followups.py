# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What Marco's first pass over the 0.4.9 bench turned up (2026-09-21):

- the ghost group's orange outline outlived switching the hidden view off
  (issue #53);
- a face closed by hand with Line, or the ring Offset draws, came out with
  its back up («cara invertida», tests 15 and 19);
- the Tape gave no sign that the axis under it was a guide source (Rafael's
  guide from an axis), although the pick worked.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.edits import build_add_edge, build_add_edges, face_up_or_toward  # noqa: E402
from core.group import Group  # noqa: E402
from core.history import History  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


# ---- fresh faces look up, or at the eye -----------------------------------

def test_a_square_closed_clockwise_with_line_still_faces_up():
    scene = Scene()
    hist = History(scene)
    ring = [V(0, 0), V(0, 2), V(2, 2), V(2, 0)]          # clockwise seen from +Z
    for a, b in zip(ring, ring[1:] + ring[:1]):
        hist.execute(build_add_edge(scene, a, b, detect_faces=True))
    (f,) = scene.faces
    assert f.normal().z() > 0.9


def test_offsets_ring_faces_up_whatever_the_walk_order():
    scene = Scene()
    hist = History(scene)
    ring = [V(0, 0), V(0, 3), V(3, 3), V(3, 0)]
    segs = list(zip(ring, ring[1:] + ring[:1]))
    hist.execute(build_add_edges(scene, segs, detect_faces=True))
    (f,) = scene.faces
    assert f.normal().z() > 0.9


def test_a_vertical_face_looks_at_the_eye_that_drew_it():
    wall = [V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)]     # in the XZ plane
    toward_minus_y = face_up_or_toward(wall, eye=V(1, -5, 1))
    toward_plus_y = face_up_or_toward(wall, eye=V(1, 5, 1))
    from core.edits import _newell
    assert _newell(toward_minus_y).y() < 0
    assert _newell(toward_plus_y).y() > 0
    assert face_up_or_toward(wall, eye=None) == wall             # nothing decides


def test_line_closing_a_wall_in_front_of_the_camera_shows_its_front():
    from views.viewport import Viewport
    from tools.line import LineTool
    vp = Viewport(None)
    vp.resize(800, 600)
    vp.camera.set_aspect(800, 600)
    vp.camera.set_view("front")            # the camera sits at -Y looking +Y
    scene = vp.scene
    tool = LineTool()
    pts = [V(0, 0, 0), V(0, 0, 2), V(2, 0, 2), V(2, 0, 0)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        vp.history.execute(tool._commit_edge(vp, a, b))
    (f,) = scene.faces
    eye = vp.camera.eye()
    assert QVector3D.dotProduct(f.normal(), eye - V(1, 0, 1)) > 0


# ---- the hidden view switched off drops the ghosts from the selection ----

def test_switching_the_hidden_view_off_deselects_the_ghost():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        m = Mesh()
        m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
        g = Group(m, "caja")
        g.xform = QMatrix4x4()
        g.hidden = True
        scene.groups.append(g)
        win._set_hidden_view("show_hidden_objects", True)
        scene.selection.add(g)
        win._set_hidden_view("show_hidden_objects", False)
        assert g not in scene.selection
        win._saved_version = scene.version
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- the Tape says it is on an axis --------------------------------------

def test_tape_and_line_show_on_axis_before_their_first_click():
    from views.viewport import Viewport
    from tools.line import LineTool
    from tools.tape import TapeMeasureTool
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("iso")
    vp.camera.target = V(4, 2, 0)
    vp.camera.distance = 16
    vp.set_active_tool(TapeMeasureTool())
    px = vp._world_to_pixel(V(3, 0, 0))
    vp._process_hover(QPointF(px[0], px[1] + 2), Qt.NoModifier)
    snap = vp.last_snap
    assert snap.kind == "on_axis" and snap.axis == "x"
    assert abs(snap.point.y()) < 1e-6 and abs(snap.point.z()) < 1e-6
    vp.set_active_tool(LineTool())
    vp._process_hover(QPointF(px[0], px[1] + 2), Qt.NoModifier)
    assert vp.last_snap.kind == "on_axis" and vp.last_snap.axis == "x"
    assert abs(vp.last_snap.point.y()) < 1e-6
    assert abs(vp.last_snap.point.z()) < 1e-6
