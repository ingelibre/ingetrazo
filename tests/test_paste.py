# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Paste tool: stamp copied geometry at the cursor, as one undoable step."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.base import ToolContext
from tools.paste import PasteTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _VP:
    def __init__(self, scene, history, clipboard):
        self.scene, self.history, self.clipboard = scene, history, clipboard

    def update(self):
        pass


def test_paste_stamps_clipboard_at_cursor():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    vp = _VP(scene, hist, clip)

    tool = PasteTool()
    tool.on_activate(vp)
    ctx = ToolContext(viewport=vp, world=V(5, 5, 0),
                      screen=QPointF(0, 0), modifiers=Qt.NoModifier, snap=None)
    tool.on_click(ctx)

    assert len(scene.mesh.faces) == 2
    pasted = [f for f in scene.mesh.faces
              if {(round(v.x()), round(v.y())) for v in f.vertices}
              == {(5, 5), (7, 5), (7, 7), (5, 7)}]
    assert len(pasted) == 1                 # the ref corner landed at the cursor

    assert hist.undo() is True
    assert len(scene.mesh.faces) == 1


def test_paste_preview_follows_cursor():
    scene = Scene()
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    vp = _VP(scene, History(scene), clip)
    tool = PasteTool()
    tool.on_activate(vp)
    ctx = ToolContext(viewport=vp, world=V(3, 0, 0),
                      screen=QPointF(0, 0), modifiers=Qt.NoModifier, snap=None)
    tool.on_hover(ctx)
    segs = tool.rubber_band_lines()
    assert len(segs) == 4                    # the square's 4 edges, offset by +3 x
    xs = {round(p.x()) for seg in segs for p in seg}
    assert xs == {3, 5}


def test_paste_keeps_face_attrs_and_reanchors_texture():
    # Copying a painted/textured face used to paste it bare (the "copia sin
    # textura" report): the clipboard now carries attrs, and a positioned
    # texture's world-anchored uvw map is re-fitted to the paste offset so
    # the image lands ON the pasted face instead of staying behind.
    from views.viewport import Viewport
    scene = Scene()
    vp = _VP(scene, History(scene), None)
    f = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    f.attrs["color"] = (1.0, 0.0, 0.0, 1.0)
    f.attrs["texture"] = {"path": "/tmp/tex.png", "sw": 1.0, "sh": 1.0,
                          "uvw": [1, 0, 0, 0, 0, 1, 0, 0]}
    scene.selection.add(f)
    assert Viewport.copy_selection(vp)

    f.attrs["color"] = (0.0, 1.0, 0.0, 1.0)   # re-paint AFTER copy: snapshot
    _paste_at(vp, 5, 0)

    pasted = next(k for k in scene.mesh.faces if k is not f)
    assert pasted.attrs.get("color") == (1.0, 0.0, 0.0, 1.0)
    tex = pasted.attrs.get("texture")
    assert tex is not None and tex["path"] == "/tmp/tex.png"
    # u = 1·x + c with the face moved +5 in x → c must become −5 so the
    # texture's origin follows the face.
    assert tex["uvw"][3] == -5.0 and tex["uvw"][7] == 0.0
    # The original's map was not mutated by the re-anchor.
    assert f.attrs["texture"]["uvw"][3] == 0


# ---- Groups in the clipboard (the "can't copy a group" report) --------------

def _make_group(scene, x0=0.0):
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    f = m.add_face([V(x0, 0), V(x0 + 2, 0), V(x0 + 2, 2), V(x0, 2)])
    f.attrs["color"] = (0.5, 0.5, 0.5, 1.0)
    g = Group(m, name="Caja")
    g.layer = "Muros"
    scene.groups.append(g)
    return g


def _copy(vp):
    from views.viewport import Viewport
    return Viewport.copy_selection(vp)


def _paste_at(vp, x, y):
    tool = PasteTool()
    tool.on_activate(vp)
    ctx = ToolContext(viewport=vp, world=V(x, y, 0),
                      screen=QPointF(0, 0), modifiers=Qt.NoModifier, snap=None)
    tool.on_click(ctx)
    return tool


def test_copy_paste_group():
    scene = Scene()
    vp = _VP(scene, History(scene), None)
    g = _make_group(scene)
    scene.selection.add(g)

    assert _copy(vp)                        # a lone group IS copyable now
    _paste_at(vp, 5, 0)

    assert len(scene.groups) == 2
    pasted = next(k for k in scene.groups if k is not g)
    assert pasted.name == "Caja" and pasted.layer == "Muros"
    assert pasted.mesh is not g.mesh        # deep copy, no aliasing
    xs = sorted(round(v.x()) for f in pasted.mesh.faces for v in f.vertices)
    assert xs == [5, 5, 7, 7]               # ref corner landed at the cursor
    assert list(pasted.mesh.faces)[0].attrs.get("color") is not None
    assert pasted in scene.selection

    assert vp.history.undo() is True
    assert scene.groups == [g]              # one undoable step


def test_copy_paste_instance_shares_prototype():
    from core.group import Group
    from core.mesh import Mesh
    from PySide6.QtGui import QMatrix4x4
    scene = Scene()
    vp = _VP(scene, History(scene), None)
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    inst = Group(proto, name="Poste")
    inst.xform = QMatrix4x4()
    scene.groups.append(inst)
    scene.selection.add(inst)

    assert _copy(vp)
    _paste_at(vp, 10, 0)

    pasted = next(k for k in scene.groups if k is not inst)
    assert pasted.mesh is proto             # sibling instance, shared prototype
    assert pasted.xform is not None and pasted.xform is not inst.xform
    assert round(pasted.xform.map(V(0, 0, 0)).x()) == 10


class _PreviewVP(_VP):
    """Stub viewport recording the frozen-scratch preview calls — the
    pipeline that draws copied groups following the cursor (chunk arrays
    upload once; each hover frame is one translated MVP)."""

    def __init__(self, scene, history, clipboard):
        super().__init__(scene, history, clipboard)
        self.began = None
        self.offsets = []
        self.ended = 0

    def begin_groups_preview(self, groups=(), external=False):
        self.began = (list(groups), external)

    def set_groups_preview_offset(self, off):
        self.offsets.append(off)

    def end_groups_preview(self):
        self.ended += 1


def test_group_paste_previews_via_frozen_scratch():
    # A copied group follows the cursor through the scratch-VBO pipeline —
    # the FULL model at zero per-frame cost. The old per-frame Python
    # wireframe/face rebuild froze the app on a 17k-face plant (piscina).
    scene = Scene()
    vp = _PreviewVP(scene, History(scene), None)
    g = _make_group(scene)                    # a 2×2 square at the origin
    scene.selection.add(g)
    assert _copy(vp)
    assert "group_lines" not in vp.clipboard  # no per-edge preview walk

    tool = PasteTool()
    tool.on_activate(vp)
    assert vp.began is not None and vp.began[1] is True
    assert vp.began[0] == vp.clipboard["groups"]   # the snapshots, not g
    ctx = ToolContext(viewport=vp, world=V(10, 0, 0),
                      screen=QPointF(0, 0), modifiers=Qt.NoModifier, snap=None)
    tool.on_hover(ctx)
    assert round(vp.offsets[-1].x()) == 10    # offset = cursor − ref corner
    # Groups no longer flow through the per-frame preview paths.
    assert tool.preview_faces() == []
    assert tool.rubber_band_lines() == []
    tool.on_deactivate(vp)
    assert vp.ended == 1                      # scratch preview torn down


def test_group_paste_stamp_ends_the_scratch_preview():
    scene = Scene()
    vp = _PreviewVP(scene, History(scene), None)
    g = _make_group(scene)
    scene.selection.add(g)
    assert _copy(vp)
    tool = _paste_at(vp, 5, 0)
    assert len(scene.groups) == 2             # stamped
    assert vp.ended == 1                      # ended at the stamp...
    tool.on_deactivate(vp)
    assert vp.ended == 1                      # ...and not torn down twice


def test_planar_texture_preview_rides_with_the_drag():
    # A LOOSE face's texture with NO uvw (hand-painted, the billboard
    # figure) is planar-projected from world position, so the image used to
    # SWIM through the preview as the cursor moved. The preview must bake
    # the projection into an anchored uvw: evaluating it at the OFFSET
    # vertices reproduces the texture exactly as it looked at the original
    # spot. (Group previews ride in the scratch VBOs, UVs already baked.)
    from PySide6.QtGui import QVector3D as Q
    scene = Scene()
    vp = _VP(scene, History(scene), None)
    f = scene.mesh.add_face([V(1, 1), V(3, 1), V(3, 3), V(1, 3)])
    f.attrs["texture"] = {"path": "/tmp/tex.png", "sw": 2.0, "sh": 2.0}
    scene.selection.add(f)
    assert _copy(vp)

    tool = PasteTool()
    tool.on_activate(vp)
    off = Q(7, 0, 0)
    ctx = ToolContext(viewport=vp, world=V(1, 1) + off,   # ref corner + off
                      screen=QPointF(0, 0), modifiers=Qt.NoModifier, snap=None)
    tool.on_hover(ctx)
    prev = tool.preview_faces()[0]
    uvw = prev.attrs["texture"]["uvw"]
    gu = Q(uvw[0], uvw[1], uvw[2])
    for orig in f.vertices:
        moved = Q(orig) + off
        u_prev = Q.dotProduct(gu, moved) + uvw[3]
        u_orig = Q.dotProduct(gu, Q(orig))     # the renderer's planar value
        assert abs(u_prev - u_orig) < 1e-6     # identical look, no swimming


def test_clipboard_survives_deleting_the_original():
    scene = Scene()
    vp = _VP(scene, History(scene), None)
    g = _make_group(scene)
    scene.selection.add(g)
    assert _copy(vp)

    scene.groups.remove(g)                  # user deletes the original
    scene.selection.clear()
    _paste_at(vp, 3, 3)
    assert len(scene.groups) == 1
    assert scene.groups[0].name == "Caja"


def test_paste_stamps_once_and_returns_to_select():
    # One stamp per paste (SketchUp): after the click the Select tool is back,
    # nothing keeps following the cursor. The clipboard survives, so pasting
    # again stamps another copy.
    import sys
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.clipboard = {"faces": [([V(0, 0), V(1, 0), V(1, 1), V(0, 1)], [])],
                        "edges": [], "ref": V(0, 0, 0)}
        win._on_paste()
        assert isinstance(vp.active_tool, PasteTool)
        ctx = ToolContext(viewport=vp, world=V(5, 5, 0), screen=QPointF(0, 0),
                          modifiers=Qt.NoModifier, snap=None)
        vp.active_tool.on_click(ctx)
        assert vp.active_tool is win._tools["select"]
        assert len(vp.scene.mesh.faces) == 1
        win._on_paste()                      # clipboard kept: paste again works
        assert isinstance(vp.active_tool, PasteTool)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_cut_group_removes_it_and_paste_restores():
    from views.viewport import Viewport
    scene = Scene()
    vp = _VP(scene, History(scene), None)
    vp.copy_selection = lambda: Viewport.copy_selection(vp)
    g = _make_group(scene)
    scene.selection.add(g)

    assert Viewport.cut_selection(vp)
    assert scene.groups == []               # gone, and on the clipboard
    _paste_at(vp, 0, 0)
    assert len(scene.groups) == 1
    assert vp.history.undo() is True        # undo the paste
    assert scene.groups == []
    assert vp.history.undo() is True        # undo the cut
    assert scene.groups == [g]
