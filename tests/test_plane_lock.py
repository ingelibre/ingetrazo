# SPDX-License-Identifier: GPL-3.0-or-later
"""Arrow keys lock a planar tool's drawing plane — before AND after the
first click (Marco, 2026-09-08: «quiero dibujar un círculo en el plano ZX…
me restringe a qué plano quiero dibujar apretando las teclas de
desplazamiento»; later, with the shape already under way: «também deve
funcionar»). With the first point down the plane is anchored at that point
and the shape stands on it; the same key frees it, a different one switches
it.

The one who does not join in is the rotated rectangle: with its base edge
down the arrows are the viewport's LINEAR axis lock, which its width reads
(``RotatedRectangleTool._width_dir``), so it keeps
``plane_lock_after_the_first_point = False`` and hands them back."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.arc import CenterArcTool
from tools.base import ToolContext
from tools.circle import CircleTool, PolygonTool
from tools.line import LineTool
from tools.rectangle import RectangleTool
from tools.rotated_rectangle import RotatedRectangleTool
from views.viewport import Viewport


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Stub:
    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)
        self.flashed = []

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        self.flashed.append(text)


def _ctx(vp, p):
    return ToolContext(viewport=vp, world=p, screen=QPointF(),
                       modifiers=Qt.NoModifier, snap=None)


def test_left_arrow_locks_a_circle_to_the_xz_plane_and_the_shape_spends_it():
    vp = _Stub()
    tool = CircleTool()
    tool.on_activate(vp)
    assert tool.on_key(vp, int(Qt.Key_Left), Qt.NoModifier)
    assert tool.plane_lock == "y" and "XZ" in vp.flashed[-1]
    tool.on_click(_ctx(vp, V(1, 2, 3)))                 # the centre
    assert tool.work_plane[1] == V(0, 1, 0)
    # after the first click the arrows hold the shape on the plane it is
    # drawing on — through the first point — and the same key hands it back
    assert tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)   # → XY, normal Z
    assert tool.plane_lock == "z"
    assert tool.work_plane == (V(1, 2, 3), V(0, 0, 1))
    assert tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)   # the same frees it
    assert tool.plane_lock is None and tool.work_plane is None
    assert tool.on_key(vp, int(Qt.Key_Left), Qt.NoModifier)  # …and back on XZ
    assert tool.plane_lock == "y"
    assert tool.work_plane == (V(1, 2, 3), V(0, 1, 0))
    tool.on_click(_ctx(vp, V(2.5, 2, 3)))               # the rim
    faces = vp.scene.mesh.faces
    assert len(faces) == 1
    assert all(abs(v.y() - 2.0) < 1e-9 for v in faces[0].vertices)
    assert {round(v.z(), 6) for v in faces[0].vertices} != {3.0}
    assert tool.plane_lock is None and tool.work_plane is None   # spent


def test_same_arrow_again_frees_and_right_up_pick_the_other_planes():
    vp = _Stub()
    tool = PolygonTool()
    tool.on_activate(vp)
    tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)
    assert tool.plane_lock == "x"
    tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)
    assert tool.plane_lock is None and "free" in vp.flashed[-1].lower() \
        or "libre" in vp.flashed[-1].lower()
    tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)
    assert tool.plane_lock == "z"
    assert tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)   # Down is ours too
    assert tool.plane_lock == "z"                          # (nothing hovered: no-op)
    tool.on_cancel(vp)
    assert tool.plane_lock is None                       # Esc releases it


def test_rectangle_and_centre_arc_lock_too():
    vp = _Stub()
    rect = RectangleTool()
    rect.on_activate(vp)
    rect.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)   # normal X → YZ
    rect.on_click(_ctx(vp, V(0, 0, 0)))
    rect.on_click(_ctx(vp, V(0, 3, 2)))
    face = vp.scene.mesh.faces[-1]
    assert all(abs(v.x()) < 1e-9 for v in face.vertices)
    assert len({round(v.z(), 6) for v in face.vertices}) == 2
    arc = CenterArcTool()
    arc.on_activate(vp)
    arc.on_key(vp, int(Qt.Key_Left), Qt.NoModifier)
    arc.on_click(_ctx(vp, V(5, 5, 5)))
    assert arc.work_plane == (V(5, 5, 5), V(0, 1, 0))


def test_an_arrow_after_the_first_corner_still_picks_the_plane():
    """Issue #543: «after the first click the arrows still choose the plane,
    and the typed size always follows the preview». Before the fix the arrow
    fell through to the viewport's linear axis lock and the rectangle kept
    the plane captured at the first click, so a 0.4 × 0.72 typed after the
    lock landed on the wrong plane."""
    vp = _Stub()
    rect = RectangleTool()
    rect.on_activate(vp)
    rect.on_click(_ctx(vp, V(0, 0, 0)))                 # first corner, nothing hit
    assert rect.work_plane is None
    assert rect.on_key(vp, int(Qt.Key_Left), Qt.NoModifier)   # the tool's, not
    assert rect.plane_lock == "y" and "XZ" in vp.flashed[-1]  # the axis lock's
    assert rect.work_plane == (V(0, 0, 0), V(0, 1, 0))  # re-aimed through it
    rect.on_hover(_ctx(vp, V(0, 0.4, 0.72)))            # cursor on that plane
    assert rect.on_value(vp, (0.4, 0.72))              # the typed size follows
    face = vp.scene.mesh.faces[-1]
    assert all(abs(v.y()) < 1e-9 for v in face.vertices)         # the XZ plane
    assert {round(v.x(), 6) for v in face.vertices} == {0.0, 0.4}
    assert {round(v.z(), 6) for v in face.vertices} == {0.0, 0.72}
    assert rect.plane_lock is None and rect.work_plane is None   # spent

    # The same arrow again frees it; the plane goes back to the cursor's.
    vp2 = _Stub()
    rect2 = RectangleTool()
    rect2.on_activate(vp2)
    rect2.on_click(_ctx(vp2, V(0, 0, 0)))
    rect2.on_key(vp2, int(Qt.Key_Left), Qt.NoModifier)
    rect2.on_key(vp2, int(Qt.Key_Left), Qt.NoModifier)
    assert rect2.plane_lock is None and rect2.work_plane is None
    assert "free" in vp2.flashed[-1].lower() or "libre" in vp2.flashed[-1].lower()


# ---- Down arrow: the magenta reference lock (issue #10) --------------------

class _Edge:
    def __init__(self, a, b):
        self.a, self.b = a, b


def _perp_to(n, c, verts, tol=1e-6):
    return all(abs(QVector3D.dotProduct(v - c, n)) < tol for v in verts)


def test_down_over_an_inclined_edge_draws_the_circle_perpendicular_to_it():
    """@pacaeiro's pipes: the axis line is inclined (50–55°), the circle must
    be normal to it for Follow Me — Down over the axis line, centre on its
    end, radius. No rotating afterwards."""
    vp = _Stub()
    tool = CircleTool()
    tool.on_activate(vp)
    vp._hover_edge = _Edge(V(0, 0, 0), V(3, 0, 4))      # a 53° axis line
    assert tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    n, kind = tool.plane_ref
    assert kind == "edge" and abs(n.x() - 0.6) < 1e-6 and abs(n.z() - 0.8) < 1e-6
    assert "perpendicular" in vp.flashed[-1].lower()
    assert tool.lock_color() == (0.85, 0.30, 0.80, 1.0)  # magenta, not an axis
    tool.on_click(_ctx(vp, V(3, 0, 4)))                 # centre on the line's end
    assert tool.work_plane[1] == n
    tool.on_click(_ctx(vp, V(3, 1, 4)))                 # the rim (Y is in-plane)
    faces = vp.scene.mesh.faces
    assert len(faces) == 1
    assert _perp_to(n, V(3, 0, 4), faces[0].vertices)
    assert abs(max((v - V(3, 0, 4)).length() for v in faces[0].vertices) - 1.0) < 1e-6
    assert tool.plane_ref is None and tool.work_plane is None   # spent


def test_down_again_frees_and_an_arrow_replaces_the_reference():
    vp = _Stub()
    tool = PolygonTool()
    tool.on_activate(vp)
    assert tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)  # nothing hovered:
    assert tool.plane_ref is None and not vp.flashed         # ours, but no-op
    vp._hover_edge = _Edge(V(0, 0, 0), V(0, 2, 0))
    tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    assert tool.plane_ref[0] == V(0, 1, 0)
    tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    assert tool.plane_ref is None
    assert "free" in vp.flashed[-1].lower() or "libre" in vp.flashed[-1].lower()
    tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)           # an axis wins
    assert tool.plane_ref is None and tool.plane_lock == "z"
    tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)         # and vice versa
    assert tool.plane_lock is None and tool.plane_ref[1] == "edge"
    tool.on_cancel(vp)
    assert tool.plane_ref is None                            # Esc releases it


def test_down_over_a_face_locks_its_plane_and_the_edge_beats_the_face():
    vp = _Stub()
    rect = RectangleTool()
    rect.on_activate(vp)
    rect.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)        # a YZ wall
    rect.on_click(_ctx(vp, V(0, 0, 0)))
    rect.on_click(_ctx(vp, V(0, 3, 2)))
    wall = vp.scene.mesh.faces[-1]
    vp._last_mouse_pos = QPointF(10, 10)
    vp.pick_face_placement = lambda x, y: (wall, None)
    tool = CircleTool()
    tool.on_activate(vp)
    tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    n, kind = tool.plane_ref
    assert kind == "face" and abs(abs(n.x()) - 1.0) < 1e-9
    assert "parallel" in vp.flashed[-1].lower() or "paralelo" in vp.flashed[-1].lower()
    tool.on_click(_ctx(vp, V(5, 5, 5)))                      # off the wall, same plane
    assert abs(abs(tool.work_plane[1].x()) - 1.0) < 1e-9
    tool.on_cancel(vp)
    vp._hover_edge = _Edge(V(0, 0, 0), V(0, 0, 1))           # an edge under the cursor too
    tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    assert tool.plane_ref[1] == "edge" and tool.plane_ref[0] == V(0, 0, 1)


# ---- The arrows with the first point already down («também deve funcionar») -

def test_a_different_arrow_switches_the_plane_through_the_first_point():
    """With the shape under way the plane is anchored at the first point: a
    different arrow moves it there (not through the cursor), the same one
    frees it, and re-pressing puts it back."""
    vp = _Stub()
    tool = RectangleTool()
    tool.on_activate(vp)
    tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)        # YZ, normal X
    tool.on_click(_ctx(vp, V(0, 4, 0)))                      # first corner
    assert tool.work_plane == (V(0, 4, 0), V(1, 0, 0))
    tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)           # → XY, normal Z
    assert tool.plane_lock == "z"
    assert tool.work_plane == (V(0, 4, 0), V(0, 0, 1))
    tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)           # the same frees it
    assert tool.plane_lock is None and tool.work_plane is None
    tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier)           # …and back it is
    assert tool.plane_lock == "z"
    assert tool.work_plane == (V(0, 4, 0), V(0, 0, 1))


def test_down_locks_the_reference_through_the_first_point_too():
    """The pipes gesture, with the centre already down: Down over the axis
    line puts the circle's plane perpendicular to it AT THE CENTRE, and the
    rim has only the radius left to ask for."""
    vp = _Stub()
    tool = CircleTool()
    tool.on_activate(vp)
    tool.on_click(_ctx(vp, V(1, 1, 1)))                      # the centre
    vp._hover_edge = _Edge(V(0, 0, 0), V(0, 5, 0))           # the axis, along Y
    assert tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    assert tool.plane_ref == (V(0, 1, 0), "edge")
    assert tool.work_plane == (V(1, 1, 1), V(0, 1, 0))
    tool.on_click(_ctx(vp, V(2, 1, 1)))                      # the rim, in that plane
    faces = vp.scene.mesh.faces
    assert len(faces) == 1
    assert _perp_to(V(0, 1, 0), V(1, 1, 1), faces[0].vertices)
    assert tool.plane_ref is None and tool.work_plane is None    # spent


def test_the_rotated_rectangle_keeps_the_arrows_for_its_width():
    """It is the one who opts out (``plane_lock_after_the_first_point``):
    with the base edge down its width reads the viewport's LINEAR axis lock
    (``_width_dir``, #70), so the tool hands the arrows back."""
    vp = _Stub()
    tool = RotatedRectangleTool()
    tool.on_activate(vp)
    assert tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)  # before: the plane
    assert tool.plane_lock == "x"
    tool.on_click(_ctx(vp, V(0, 0, 0)))                       # first corner
    assert tool.on_key(vp, int(Qt.Key_Up), Qt.NoModifier) is False
    assert tool.plane_lock == "x"      # untouched: the arrows are the viewport's


def test_a_line_is_not_a_plane_lock():
    """The arrows are its length lock — the viewport's — and it says so by
    not being a PlaneLock at all."""
    vp = _Stub()
    tool = LineTool()
    tool.on_activate(vp)
    assert tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier) is False
    assert tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier) is False
    assert getattr(tool, "plane_lock", None) is None


# ---- Shift marks the plane the shape is considering ------------------------

class _Vp(_Stub):
    """Enough viewport for the Shift mark: the tool in hand. The two hooks
    are the viewport's own, plugged in the way the real window calls them
    (``_capture_shift_lock`` gets them through the class, which this stub is
    not)."""

    _mark_plane_for_shift = Viewport._mark_plane_for_shift
    _release_shift_plane_mark = Viewport._release_shift_plane_mark

    def __init__(self, tool):
        super().__init__()
        self.active_tool = tool


def test_shift_marks_the_plane_the_shape_is_on_and_the_release_hands_it_back():
    """Shift is Down held: the plane stays put while the key is down — cue,
    preview and the locks that never yield all read ``plane_ref`` — and the
    release gives it back. ``work_plane`` is NOT touched: the mark does not
    freeze a parallel through the first point, which is #545's bug."""
    tool = RectangleTool()
    vp = _Vp(tool)
    vp._last_work_plane = (V(2, 0, 0), V(1, 0, 0))           # the wall it is over
    tool.on_activate(vp)
    tool.on_click(_ctx(vp, V(2, 1, 1)))                      # first corner on it
    before = tool.work_plane
    vp._mark_plane_for_shift()
    assert tool.plane_ref == (V(1, 0, 0), "plane")
    assert tool.lock_color() == (0.85, 0.30, 0.80, 1.0)      # magenta, like Down
    assert tool.preview_plane(vp, V(9, 9, 9)) == (V(9, 9, 9), V(1, 0, 0))
    assert tool.work_plane == before                         # the mark moves nothing
    vp._release_shift_plane_mark()
    assert tool.plane_ref is None


def test_shift_does_not_steal_a_plane_an_arrow_or_down_is_holding():
    """Additive to the pointer, not to the user's own lock: what was already
    locked stays locked, and Shift's release leaves it alone."""
    tool = CircleTool()
    vp = _Vp(tool)
    tool.on_activate(vp)
    tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)        # the user's lock
    vp._mark_plane_for_shift()
    assert tool.plane_ref is None and tool.plane_lock == "x"
    vp._release_shift_plane_mark()
    assert tool.plane_lock == "x"
    tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)        # freed…
    vp._hover_edge = _Edge(V(0, 0, 0), V(1, 0, 0))           # …and Down takes it
    tool.on_key(vp, int(Qt.Key_Down), Qt.NoModifier)
    assert tool.plane_ref[1] == "edge"
    vp._release_shift_plane_mark()                           # Shift must not undo it
    assert tool.plane_ref is not None and tool.plane_ref[1] == "edge"
