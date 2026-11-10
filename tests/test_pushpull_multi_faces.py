# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull on several selected faces at once: activated with two or more
faces of the loose mesh selected, a drag started on any of them moves them
all the same distance, each along its own outward normal, as ONE undo step.
A drag on a face outside the selection is the ordinary single push.

Headless: stub viewport + direct tool calls, as test_pushpull_ux.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.orient import is_closed
from core.scene import Scene
from tools.base import ToolContext
from tools.pushpull import PushPullTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(x, y, z)


class _StubViewport:
    def __init__(self, scene, pick=None):
        self.scene = scene
        self.history = History(scene)
        self._pick = pick

    last_status = None
    last_hover = None
    suppressed: set | None = None

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.last_status = text

    def set_hover(self, entity):
        self.last_hover = entity

    def set_suppressed_faces(self, faces):
        self.suppressed = set(faces)

    def pick_face(self, x, y):
        return self._pick

    def pick_face_any(self, x, y):
        return self._pick, None


def _ctx(vp, modifiers=Qt.NoModifier):
    return ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(0, 0),
                       modifiers=modifiers, snap=None)


def _sheet(scene, hist, x0, size=2.0):
    """A free square on the ground at ``x0``."""
    pts = [V(x0, 0), V(x0 + size, 0), V(x0 + size, size), V(x0, size)]
    hist.execute(build_add_edges(
        scene, [(pts[i], pts[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(pts))]))
    return next(f for f in scene.faces
                if all(abs(v.z()) < 1e-9 for v in f.vertices)
                and abs(min(v.x() for v in f.vertices) - x0) < 1e-9)


def _faces_at_z(scene, z):
    return [f for f in scene.faces
            if len(f.vertices) == 4
            and all(abs(v.z() - z) < 1e-9 for v in f.vertices)]


def _two_boxes(height=3.0):
    """Two separate boxes in the one loose mesh, x 0..2 and x 5..7."""
    scene = Scene()
    hist = History(scene)
    for x0 in (0.0, 5.0):
        face = _sheet(scene, hist, x0)
        tool = PushPullTool()
        tool.on_activate(_StubViewport(scene))
        vp = _StubViewport(scene, pick=face)
        tool.on_hover(_ctx(vp))
        tool.on_click(_ctx(vp))
        tool.extrusion = height
        tool.on_click(_ctx(vp))
    assert len(_faces_at_z(scene, height)) == 2
    return scene


def _drag(scene, lead, dist, modifiers=Qt.NoModifier):
    """Activate with the scene's current selection, start on ``lead`` and
    commit ``dist`` — the click-click gesture."""
    vp = _StubViewport(scene, pick=lead)
    tool = PushPullTool()
    tool.on_activate(vp)
    tool.on_hover(_ctx(vp))
    tool.on_click(_ctx(vp, modifiers))
    tool.extrusion = dist
    tool.on_click(_ctx(vp, modifiers))
    return tool, vp


def test_two_selected_tops_rise_together():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    scene.select([a, b])

    tool, vp = _drag(scene, a, 2.0)

    assert len(_faces_at_z(scene, 5.0)) == 2   # BOTH caps moved
    assert not _faces_at_z(scene, 3.0)
    assert is_closed(scene.mesh)
    # One undo step brings both back.
    assert len(vp.history.undo_stack) == 1
    assert vp.history.undo() is True
    assert len(_faces_at_z(scene, 3.0)) == 2
    assert not _faces_at_z(scene, 5.0)


def test_any_selected_face_can_lead_the_drag():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    scene.select([a, b])

    _drag(scene, b, -1.0)                      # pushed DOWN, led by the 2nd

    assert len(_faces_at_z(scene, 2.0)) == 2


def test_free_sheets_become_boxes_together():
    scene = Scene()
    hist = History(scene)
    for x0 in (0.0, 5.0, 10.0):
        _sheet(scene, hist, x0)
    # Looked up once all are drawn: a new sheet re-detects the old ones.
    a, b, c = sorted(scene.faces,
                     key=lambda f: min(v.x() for v in f.vertices))
    scene.select([a, b, c])

    _drag(scene, b, 2.5)

    assert len(_faces_at_z(scene, 2.5)) == 3   # three lids
    assert len(scene.faces) == 18              # three closed boxes
    assert is_closed(scene.mesh)


def test_each_face_moves_along_its_own_normal():
    # The top and the front of one box: pulling out 1 raises the top AND
    # brings the front forward (−y), not both up.
    scene = Scene()
    hist = History(scene)
    _sheet(scene, hist, 0.0)
    _drag(scene, scene.faces[0], 3.0)
    top = _faces_at_z(scene, 3.0)[0]
    front = next(f for f in scene.faces
                 if all(abs(v.y()) < 1e-9 for v in f.vertices))
    scene.select([top, front])

    _drag(scene, top, 1.0)

    assert _faces_at_z(scene, 4.0)
    assert any(all(abs(v.y() + 1.0) < 1e-9 for v in f.vertices)
               for f in scene.faces)
    assert is_closed(scene.mesh)


def test_face_outside_the_selection_pushes_alone():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    front = next(f for f in scene.faces
                 if all(abs(v.y()) < 1e-9 for v in f.vertices))
    scene.select([a, b])

    _drag(scene, front, 1.0)                   # not one of the selected

    assert len(_faces_at_z(scene, 3.0)) == 2   # tops untouched
    assert any(all(abs(v.y() + 1.0) < 1e-9 for v in f.vertices)
               for f in scene.faces)


def test_activation_says_how_it_works():
    scene = _two_boxes()
    scene.select(_faces_at_z(scene, 3.0))
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.on_activate(vp)

    assert tool.hovered_face is None           # no single-face arm
    assert vp.last_status and "2" in vp.last_status


def test_preview_sweeps_every_face():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    scene.select([a, b])
    vp = _StubViewport(scene, pick=a)
    tool = PushPullTool()
    tool.on_activate(vp)
    tool.on_hover(_ctx(vp))
    tool.on_click(_ctx(vp))
    tool.extrusion = 2.0
    tool._show_light_preview(vp)

    # A cap and four walls for each face; the model is not touched.
    assert len(tool.preview_faces()) == 10
    assert len(_faces_at_z(scene, 3.0)) == 2
    caps = [f for f in tool.preview_faces()
            if all(abs(v.z() - 5.0) < 1e-9 for v in f.vertices)]
    assert len(caps) == 2
    tool.on_cancel(vp)
    assert len(_faces_at_z(scene, 3.0)) == 2


def test_retype_moves_all_faces_again():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    scene.select([a, b])
    tool, vp = _drag(scene, a, 2.0)

    assert tool.on_value(vp, 4.0) is True      # typed right after

    assert len(_faces_at_z(scene, 7.0)) == 2
    assert not _faces_at_z(scene, 5.0)
    assert len(vp.history.undo_stack) == 1     # still one undo step


def test_double_click_repeats_on_all_faces():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    scene.select([a, b])
    PushPullTool.last_distance = 1.5
    vp = _StubViewport(scene, pick=b)
    tool = PushPullTool()
    tool.on_activate(vp)
    tool.on_double_click(_ctx(vp))

    assert len(_faces_at_z(scene, 4.5)) == 2


def _push_again(tool, vp, lead, dist):
    """Another push with the SAME tool, still active: no re-activation."""
    vp._pick = lead
    tool.on_hover(_ctx(vp))
    tool.on_click(_ctx(vp))
    tool.extrusion = dist
    tool.on_click(_ctx(vp))


def test_pushing_the_same_selection_again_moves_them_all():
    # The pushed caps stay selected; pushing again without re-activating
    # the tool used to move only the face under the cursor.
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    scene.select([a, b])
    tool, vp = _drag(scene, a, 1.0)
    assert len(_faces_at_z(scene, 4.0)) == 2
    assert len(scene.selection) == 2

    _push_again(tool, vp, _faces_at_z(scene, 4.0)[1], 1.0)

    assert len(_faces_at_z(scene, 5.0)) == 2


def test_selection_made_with_the_tool_active_counts():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.on_activate(vp)                       # nothing selected yet
    scene.select([a, b])                       # selected afterwards

    _push_again(tool, vp, a, 2.0)

    assert len(_faces_at_z(scene, 5.0)) == 2


def _step():
    """One solid with two tops: a 4x2 block 1.5 high, its top split at
    x=2 and the left half raised to 3."""
    scene = Scene()
    hist = History(scene)
    pts = [V(0, 0), V(4, 0), V(4, 2), V(0, 2)]
    hist.execute(build_add_edges(
        scene, [(pts[i], pts[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(pts))]))
    _drag(scene, scene.faces[0], 1.5)
    if not _faces_at_z(scene, 1.5):            # the sheet faced down
        _drag(scene, _faces_at_z(scene, 0.0)[0], 1.5)
    scene.select([])
    hist.execute(build_add_edges(scene, [(V(2, 0, 1.5), V(2, 2, 1.5))]))
    left = next(f for f in _faces_at_z(scene, 1.5)
                if max(v.x() for v in f.vertices) < 2.0 + 1e-9)
    _drag(scene, left, 1.5)
    scene.select([])
    assert len(_faces_at_z(scene, 3.0)) == 1
    assert len(_faces_at_z(scene, 1.5)) == 1
    return scene


def test_step_tops_rise_together_and_stay_clean():
    scene = _step()
    high = _faces_at_z(scene, 3.0)[0]
    low = _faces_at_z(scene, 1.5)[0]
    scene.select([high, low])

    _drag(scene, low, 3.0)

    assert _faces_at_z(scene, 6.0) and _faces_at_z(scene, 4.5)
    assert is_closed(scene.mesh)
    assert all(len(e.faces) == 2 for e in scene.mesh.edges)
    assert len(scene.faces) == 8               # still the same step
    assert len(scene.selection) == 2           # ready to push again


def test_ctrl_copy_stacks_on_every_face():
    scene = _two_boxes()
    a, b = _faces_at_z(scene, 3.0)
    scene.select([a, b])

    _drag(scene, a, 2.0, modifiers=Qt.ControlModifier)

    assert len(_faces_at_z(scene, 3.0)) == 2   # the bases stay as slabs
    assert len(_faces_at_z(scene, 5.0)) == 2


# ---- A face that cannot go the whole way stays where it was ----------------

def _box(scene, x0, height, size=2.0):
    face = _sheet(scene, History(scene), x0, size)
    tool = PushPullTool()
    tool.on_activate(_StubViewport(scene))
    vp = _StubViewport(scene, pick=face)
    tool.on_hover(_ctx(vp))
    tool.on_click(_ctx(vp))
    tool.extrusion = height
    tool.on_click(_ctx(vp))


def test_a_thin_solid_is_not_taken_away_by_a_push_meant_for_a_thick_one():
    """A slab 0.5 thick and a box 3 high, both tops selected, pushed down
    1.0 from the box: the slab's top went its 0.5 and the slab was gone,
    with nothing said."""
    scene = Scene()
    _box(scene, 0.0, 3.0)
    _box(scene, 5.0, 0.5)
    faces_before = len(scene.faces)
    box_top = _faces_at_z(scene, 3.0)[0]
    slab_top = _faces_at_z(scene, 0.5)[0]
    scene.select([box_top, slab_top])

    tool, vp = _drag(scene, box_top, -1.0)

    assert len(_faces_at_z(scene, 2.0)) == 1        # the box went down
    assert len(_faces_at_z(scene, 0.5)) == 1        # the slab is still there
    assert len(scene.faces) == faces_before
    assert is_closed(scene.mesh)
    assert "1" in vp.last_status and "2" in vp.last_status   # 1 of 2, said
    assert vp.history.undo() is True
    assert len(_faces_at_z(scene, 3.0)) == 1


def test_a_box_pushed_from_both_ends_is_not_flattened():
    """Top and bottom of a box 3 high, pushed in 2.0: the top went 2, the
    bottom the 1 that was left, and the box was one flat face."""
    scene = Scene()
    _box(scene, 0.0, 3.0)
    top = _faces_at_z(scene, 3.0)[0]
    bottom = _faces_at_z(scene, 0.0)[0]
    scene.select([top, bottom])

    tool, vp = _drag(scene, top, -2.0)

    assert is_closed(scene.mesh)
    assert len(scene.faces) == 6
    zs = sorted({round(v.z(), 6) for f in scene.faces for v in f.vertices})
    assert zs in ([0.0, 1.0], [2.0, 3.0])            # one end moved, not both
    assert "1" in vp.last_status and "2" in vp.last_status


def test_both_ends_still_go_when_there_is_room():
    scene = Scene()
    _box(scene, 0.0, 3.0)
    top = _faces_at_z(scene, 3.0)[0]
    bottom = _faces_at_z(scene, 0.0)[0]
    scene.select([top, bottom])

    _drag(scene, top, -1.0)

    assert is_closed(scene.mesh)
    zs = sorted({round(v.z(), 6) for f in scene.faces for v in f.vertices})
    assert zs == [1.0, 2.0]
