# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull's mid-drag inference only reads references the user can see.

The tool sets ``uses_snap = False``, so its distance inference bypassed the
snap engine's filters: a mesh corner hidden behind geometry, or on the hidden
side of a section plane, still pinned the extrusion the moment the cursor
crossed it — the "jumpy push" (#270, and the section-cut snap of #384 from
the drawing tools' side). The same two rules the snaps follow now apply
here: what the cut hides is not snappable, and what geometry hides is not
either — except in X-ray and wireframe, where everything shows and
everything snaps, as it always did.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.section import SectionPlane  # noqa: E402
from core.style import Style  # noqa: E402
from tools.pushpull import PushPullTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402

from types import SimpleNamespace


def _vp():
    """A top-down viewport: nothing of the harness needs GL."""
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("top")
    vp.camera.target = V(3, 3, 0)
    vp.camera.distance = 14
    return vp


def _dragging_tool(base_face):
    """Push/Pull mid-drag on ``base_face``, the way on_hover leaves it."""
    tool = PushPullTool()
    tool.base_face = base_face
    tool.dragging = True
    tool._anchor = base_face.centroid()
    tool._normal = V(0, 0, 1)
    tool._cap_positions = tool._cap_loop_positions(base_face)
    return tool


def _hover_at(tool, vp, world):
    px, py = vp._world_to_pixel(world)
    return tool._infer_reference_distance(
        SimpleNamespace(viewport=vp, screen=QPointF(px, py)))


def _scene_with_reference_vertex(vp):
    """A reference corner at (2, 2, 2) (a stub edge puts it in the mesh)
    beside — never under — the face being pushed at x 4..8."""
    sc = vp.scene
    sc.mesh.add_edge(V(2, 2, 2), V(2, 2.5, 2))
    base = sc.mesh.add_face([V(4, 0, 0), V(8, 0, 0), V(8, 4, 0), V(4, 4, 0)])
    sc.version += 1
    return base


def _add_lid(vp, z=3.0):
    """A horizontal face over the reference corner: from the top view it
    hides whatever is below it."""
    lid = vp.scene.mesh.add_face(
        [V(0, 0, z), V(4, 0, z), V(4, 4, z), V(0, 4, z)])
    vp.scene.version += 1
    return lid


def test_a_corner_behind_geometry_no_longer_pins_the_push():
    vp = _vp()
    base = _scene_with_reference_vertex(vp)
    tool = _dragging_tool(base)
    # Nothing over it: the corner engages, as it always did.
    assert _hover_at(tool, vp, V(2, 2, 2)) == 2.0
    assert tool._inference_kind == "vertex"
    # A lid in front of the eye: the corner is gone; the push reads the
    # lid's plane instead (what the cursor can actually see).
    _add_lid(vp)
    assert _hover_at(tool, vp, V(2, 2, 2)) == 3.0
    assert tool._inference_kind == "face"


def test_xray_and_wireframe_snap_through_the_lid():
    vp = _vp()
    base = _scene_with_reference_vertex(vp)
    _add_lid(vp)
    tool = _dragging_tool(base)
    for mode in ("xray", "wireframe"):
        vp.scene.display_style = Style(name=mode.title(), face_mode=mode)
        assert _hover_at(tool, vp, V(2, 2, 2)) == 2.0, mode
        assert tool._inference_kind == "vertex", mode
    vp.scene.display_style = Style(name="Hidden line",
                                   face_mode="hidden_line")
    assert _hover_at(tool, vp, V(2, 2, 2)) != 2.0


def test_a_corner_on_the_cut_side_of_a_section_plane_is_not_a_reference():
    vp = _vp()
    base = _scene_with_reference_vertex(vp)
    tool = _dragging_tool(base)
    # The plane at z=1.5 hiding everything above it — the corner at z=2 is
    # on the hidden side, in full view of the camera but gone from the model.
    sp = SectionPlane(V(2, 2, 1.5), V(0, 0, 1))
    vp.scene.section_planes.append(sp)
    vp.scene.set_active_section(sp)
    assert _hover_at(tool, vp, V(2, 2, 2)) is None
    assert tool._inference_kind is None
    # Flip the cut — the same corner is the model again.
    sp.flip()
    assert _hover_at(tool, vp, V(2, 2, 2)) == 2.0
    assert tool._inference_kind == "vertex"
    # And the cut is the cut in X-ray too: what it hides is not snappable.
    vp.scene.display_style = Style(name="X-ray", face_mode="xray")
    sp.flip()
    assert _hover_at(tool, vp, V(2, 2, 2)) is None


def test_an_edge_reference_hidden_behind_geometry_is_skipped():
    from views.viewport import _SnapEdge
    vp = _vp()
    base = _scene_with_reference_vertex(vp)
    _add_lid(vp)
    tool = _dragging_tool(base)
    vp._hover_edge = _SnapEdge(V(0, 2, 2), V(4, 2, 2))   # under the lid
    # Over a stretch of the edge away from the reference vertex, so the
    # edge itself is what the inference must read.
    assert _hover_at(tool, vp, V(0.4, 2, 2)) == 3.0      # the lid's plane
    assert tool._inference_kind == "face"
    vp.scene.display_style = Style(name="X-ray", face_mode="xray")
    assert _hover_at(tool, vp, V(0.4, 2, 2)) == 2.0      # the edge again
    assert tool._inference_kind == "edge"
