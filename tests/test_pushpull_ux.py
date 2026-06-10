"""Push/Pull UX parity with SketchUp: Ctrl = push/pull a copy (keep the base
face as a slab division), double-click = repeat the last distance, VCB accepts
negatives (reverse) and unit suffixes.

Headless: stub viewport + direct tool calls.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.orient import signed_volume
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

    def update(self):
        pass

    def set_hover(self, entity):
        pass

    def set_suppressed_faces(self, faces):
        pass

    def pick_face(self, x, y):
        return self._pick


def _ctx(vp, modifiers=Qt.NoModifier):
    return ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(0, 0),
                       modifiers=modifiers, snap=None)


def _cube(scene, hist, size=4.0, height=3.0):
    ground = [V(0, 0), V(size, 0), V(size, size), V(0, size)]
    hist.execute(build_add_edges(
        scene, [(ground[i], ground[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(ground))]))
    _push(scene, scene.faces[0], height)


def _push(scene, face, dist, keep_base=False):
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = face
    tool.extrusion = dist
    tool.dragging = True
    tool._anchor = face.centroid()
    tool._normal = face.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = [QVector3D(v) for v in face.vertices]
    tool._keep_base = keep_base
    tool._commit(vp)
    return vp


def _top(scene, z):
    return next(
        f for f in scene.faces
        if len(f.vertices) == 4 and all(abs(v.z() - z) < 1e-9 for v in f.vertices)
    )


# ---- Ctrl: push/pull a copy --------------------------------------------------

def test_ctrl_push_keeps_base_as_slab_division():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    top = _top(scene, 3.0)
    vp = _push(scene, top, 2.0, keep_base=True)

    assert top in scene.faces                  # the start face stays
    assert _top(scene, 5.0) is not None        # new cap above it
    # 6 cube faces + 4 stacked strips + the new cap = 11; the walls are NOT
    # merged into tall faces (the belt at z=3 divides them, SketchUp-style).
    assert len(scene.faces) == 11
    belt = [e for e in scene.mesh.edges
            if abs(e.a.z() - 3) < 1e-9 and abs(e.b.z() - 3) < 1e-9]
    assert belt and all(len(e.faces) == 3 for e in belt)  # wall + strip + slab face

    assert vp.history.undo() is True
    assert len(scene.faces) == 6               # back to the plain cube


def test_ctrl_push_overrides_prism_translation():
    # Without Ctrl this cap push is a prism translate (cube just gets taller,
    # 6 faces). With Ctrl it must stack a segment instead.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    _push(scene, _top(scene, 3.0), 2.0, keep_base=False)
    assert len(scene.faces) == 6               # translate path: no division
    scene2 = Scene()
    hist2 = History(scene2)
    _cube(scene2, hist2, height=3.0)
    _push(scene2, _top(scene2, 3.0), 2.0, keep_base=True)
    assert len(scene2.faces) == 11             # copy path: belt + strips


# ---- double-click repeats the last distance -----------------------------------

def test_double_click_repeats_last_distance():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    PushPullTool.last_distance = None

    # First push: normal commit records the distance.
    inner = [V(1, 1, 3), V(2, 1, 3), V(2, 2, 3), V(1, 2, 3)]
    hist.execute(build_add_edges(
        scene, [(inner[i], inner[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(inner))]))
    block = next(
        f for f in scene.faces
        if all(abs(v.z() - 3) < 1e-9 for v in f.vertices) and len(f.vertices) == 4
        and max(v.x() for v in f.vertices) <= 2.001
    )
    _push(scene, block, 1.5)
    assert PushPullTool.last_distance == 1.5

    # Second block: double-click pushes it by the same 1.5 without dragging.
    inner2 = [V(2.5, 2.5, 3), V(3.5, 2.5, 3), V(3.5, 3.5, 3), V(2.5, 3.5, 3)]
    hist.execute(build_add_edges(
        scene, [(inner2[i], inner2[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(inner2))]))
    block2 = next(
        f for f in scene.faces
        if all(abs(v.z() - 3) < 1e-9 for v in f.vertices) and len(f.vertices) == 4
        and min(v.x() for v in f.vertices) >= 2.499
    )
    vp = _StubViewport(scene, pick=block2)
    tool = PushPullTool()
    tool.on_double_click(_ctx(vp))
    tops = [f for f in scene.faces
            if len(f.vertices) == 4 and all(abs(v.z() - 4.5) < 1e-9 for v in f.vertices)]
    assert len(tops) == 2                      # both blocks now at z=4.5


def test_double_click_without_history_is_plain_click():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    PushPullTool.last_distance = None
    top = _top(scene, 3.0)
    vp = _StubViewport(scene, pick=top)
    tool = PushPullTool()
    tool.hovered_face = top
    tool.on_double_click(_ctx(vp))             # falls back to on_click
    assert tool.dragging is True               # started a drag, no commit
    assert len(scene.faces) == 6


# ---- VCB: negative reverses the direction -------------------------------------

def test_vcb_negative_value_reverses_direction():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    inner = [V(1, 1, 3), V(2, 1, 3), V(2, 2, 3), V(1, 2, 3)]
    hist.execute(build_add_edges(
        scene, [(inner[i], inner[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(inner))]))
    block = next(
        f for f in scene.faces
        if all(abs(v.z() - 3) < 1e-9 for v in f.vertices) and len(f.vertices) == 4
        and max(v.x() for v in f.vertices) <= 2.001
    )
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool.base_face = block
    tool.dragging = True
    tool.extrusion = 0.4   # user is dragging upward (+normal, outward)
    tool._anchor = block.centroid()
    tool._normal = block.normal()
    tool._attached, tool._prism_cap = tool._classify_base(scene)
    tool._cap_positions = [QVector3D(v) for v in block.vertices]
    assert tool.on_value(vp, -1.0) is True     # typed "-1" → carve down instead
    assert any(
        len(f.vertices) == 4 and all(abs(v.z() - 2.0) < 1e-9 for v in f.vertices)
        for f in scene.faces
    )                                          # recess floor at z=2
    assert signed_volume(scene.mesh) > 0


def test_vcb_zero_rejected():
    tool = PushPullTool()
    tool.dragging = True
    tool.base_face = object()
    assert tool.on_value(None, 0.0) is False


# ---- VCB parser: units + sign --------------------------------------------------

def test_parse_value_buffer_units_and_sign():
    from views.viewport import Viewport
    parse = Viewport._parse_value_buffer
    assert parse("2") == 2.0
    assert parse("-2") == -2.0
    assert parse("30cm") == 0.3
    assert parse("1500mm") == 1.5
    assert parse("2m") == 2.0
    assert parse("2,5") == 2.5
    assert parse("1;2;50cm") == (1.0, 2.0, 0.5)
    assert parse("-30cm") == -0.3
    assert parse("abc") is None
    assert parse("2x") is None
