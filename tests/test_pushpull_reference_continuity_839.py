# SPDX-License-Identifier: GPL-3.0-or-later
"""Broad face/edge references must not yank a cap away from a steady drag.

From @hamzah1985's PR #839. The fix differs from the PR's proximity gate:
the walls of the face being pushed, and edges along the push axis, are not
references (they move with the push or say nothing about how far); every
other face or edge still engages at any distance, the classic inference."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V

from core.orient import is_closed
from tools.base import ToolContext
from tools.pushpull import PushPullTool
from views.viewport import Viewport


@pytest.fixture
def box_drag():
    vp = Viewport()
    vp.flash_status = lambda *args, **kwargs: None
    vp.resize(1200, 800)
    vp.camera.set_aspect(1200, 800)
    vp.camera.target = V(0, 0, 1)
    vp.camera.distance = 8
    rings = [
        [(-1, -1, 0), (-1, 1, 0), (1, 1, 0), (1, -1, 0)],
        [(-1, -1, 2), (1, -1, 2), (1, 1, 2), (-1, 1, 2)],
        [(-1, -1, 0), (1, -1, 0), (1, -1, 2), (-1, -1, 2)],
        [(1, -1, 0), (1, 1, 0), (1, 1, 2), (1, -1, 2)],
        [(1, 1, 0), (-1, 1, 0), (-1, 1, 2), (1, 1, 2)],
        [(-1, 1, 0), (-1, -1, 0), (-1, -1, 2), (-1, 1, 2)],
    ]
    faces = [vp.scene.mesh.add_face([V(*p) for p in ring]) for ring in rings]
    vp.scene.version += 1
    tool = PushPullTool()
    vp.active_tool = tool
    tool.hovered_face = faces[1]
    at = faces[1].centroid()
    pixel = vp._world_to_pixel(at)
    tool.on_click(ToolContext(vp, at, QPointF(*pixel), Qt.NoModifier, None))
    assert tool._prism_cap
    yield vp, tool, pixel
    tool.on_cancel(vp)
    vp.deleteLater()


def _context(vp, point):
    point = V(*point)
    return ToolContext(vp, point, QPointF(*vp._world_to_pixel(point)), Qt.NoModifier, None)


def _shape(vp):
    mesh = vp.scene.mesh
    return (sorted(tuple(round(c, 5) for c in v.position.toTuple()) for v in mesh.vertices),
            len(mesh.edges), len(mesh.faces))


def test_a_steady_inward_push_never_jumps_back_to_its_side_faces(box_drag):
    vp, tool, pixel = box_drag
    distances = []
    for offset in range(1, 221):
        vp._process_hover(QPointF(pixel[0], pixel[1] + offset), Qt.NoModifier)
        distances.append(tool.extrusion)
    # Before the fix, offsets 87 -> 88 changed -0.769 to -0.007 as the
    # reference switched to the original side face. Leaving the origin's
    # snap radius later jumped from -2.000 back to -1.058.
    assert all(b <= a + 1e-5 for a, b in zip(distances, distances[1:]))
    # The intentional origin snap remains, within its normal pixel radius.
    assert max(abs(b - a) for a, b in zip(distances, distances[1:])) < 0.12
    assert distances[-1] == pytest.approx(-2.0)


@pytest.mark.parametrize("kind", ["vertex", "face", "edge", "origin",
                                 "guide_point", "guide_line"])
def test_deliberate_reference_alignment_still_engages(box_drag, kind):
    vp, tool, _pixel = box_drag
    mesh = vp.scene.mesh
    point = (0, 0, 3)
    if kind == "vertex":
        mesh.add_edge(V(0, 0, 3), V(0.5, 0, 3))
    elif kind == "face":
        mesh.add_face([V(-2, -2, 3), V(2, -2, 3), V(2, 2, 3), V(-2, 2, 3)])
    elif kind == "edge":
        vp._hover_edge = mesh.add_edge(V(-1, -1, 3), V(1, 1, 3))
    elif kind == "origin":
        point = (0, 0, 0)
    elif kind == "guide_point":
        vp.scene.guides.append(SimpleNamespace(point=V(0, 0, 3), direction=None))
    else:
        vp.scene.guides.append(SimpleNamespace(point=V(0, 0, 3),
                                               direction=V(1, 1, 0).normalized()))
    vp.scene.version += 1
    tool.on_hover(_context(vp, point))
    assert tool._inference_kind == kind
    assert tool.extrusion == pytest.approx(point[2] - 2, abs=1e-5)


def test_cancel_restores_the_original_closed_box(box_drag):
    vp, tool, pixel = box_drag
    before = _shape(vp)
    for offset in (30, 88, 180, 201, 219):
        vp._process_hover(QPointF(pixel[0], pixel[1] + offset), Qt.NoModifier)
    tool.on_cancel(vp)
    assert _shape(vp) == before
    assert is_closed(vp.scene.mesh)


def test_commit_undo_and_redo_keep_the_closed_box(box_drag):
    vp, tool, pixel = box_drag
    before = _shape(vp)
    vp._process_hover(QPointF(pixel[0], pixel[1] - 80), Qt.NoModifier)
    distance = tool.extrusion
    tool.on_click(_context(vp, (0, 0, 2 + distance)))
    assert not tool.dragging
    assert len(vp.history.undo_stack) == 1
    assert is_closed(vp.scene.mesh)
    vp.history.undo()
    assert _shape(vp) == before
    vp.history.redo()
    assert is_closed(vp.scene.mesh)
    assert max(v.position.z() for v in vp.scene.mesh.vertices) == pytest.approx(2 + distance)


def test_typed_distance_keeps_its_exact_value(box_drag):
    vp, tool, pixel = box_drag
    vp._process_hover(QPointF(pixel[0], pixel[1] - 60), Qt.NoModifier)
    assert tool.on_value(vp, 1.25)
    assert not tool.dragging
    assert len(vp.history.undo_stack) == 1
    assert is_closed(vp.scene.mesh)
    assert max(v.position.z() for v in vp.scene.mesh.vertices) == pytest.approx(3.25)


def test_a_second_drag_after_cancel_follows_the_cursor(box_drag):
    vp, tool, pixel = box_drag
    tool.on_cancel(vp)
    tool.hovered_face = next(f for f in vp.scene.mesh.faces if f.centroid().z() > 1.99)
    tool.on_click(_context(vp, (0, 0, 2)))
    vp._process_hover(QPointF(pixel[0], pixel[1] + 88), Qt.NoModifier)
    assert tool.extrusion == pytest.approx(-0.7782507, abs=1e-5)


def test_a_far_face_still_engages_however_far_from_the_cap(box_drag):
    """The classic inference stays: hovering another face levels the cap
    with the point under the cursor, even far from the free drag."""
    vp, tool, _pixel = box_drag
    vp.scene.mesh.add_face([V(1.5, -1, 4), V(3, -1, 4), V(3, 1, 4), V(1.5, 1, 4)])
    vp.scene.version += 1
    tool.on_hover(_context(vp, (2.2, 0.3, 4)))
    assert tool._inference_kind == "face"
    assert tool.extrusion == pytest.approx(2.0, abs=1e-4)
