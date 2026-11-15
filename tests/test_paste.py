# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Paste tool: stamp copied geometry at the cursor, as one undoable step."""
from __future__ import annotations

from types import SimpleNamespace

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
    assert pasted.mesh is not g.mesh        # snapshot: no aliasing the source
    # A pasted classic group is an INSTANCE of the clipboard snapshot
    # (copies share the definition until edited): stamping is O(1)
    # even on a 230k-face group, and begin_group_edit materializes on entry.
    assert pasted.xform is not None
    xs = sorted(round(pasted.xform.map(QVector3D(v)).x())
                for f in pasted.mesh.faces for v in f.vertices)
    assert xs == [5, 5, 7, 7]               # ref corner landed at the cursor
    assert list(pasted.mesh.faces)[0].attrs.get("color") is not None
    assert pasted in scene.selection

    _paste_at(vp, 9, 0)                     # stamp again: sibling instance
    third = next(k for k in scene.groups if k is not g and k is not pasted)
    assert third.mesh is pasted.mesh        # shared prototype, O(1) stamp
    assert round(third.xform.map(QVector3D(0, 0, 0)).x()) == 9

    assert vp.history.undo() is True        # undo the second paste
    assert vp.history.undo() is True
    assert scene.groups == [g]              # one undoable step per paste


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
    # One stamp per paste: after the click the Select tool is back,
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


def test_preview_faces_survive_viewport_memo_helpers():
    # The memoised _tris_of/_normal_of/_area_of assumed mesh faces (.loop);
    # a PREVIEW face (core.geometry) crashed every paint of a loose paste
    # preview — nothing followed the cursor (user report). Duck-typed now.
    from core.geometry import Face as PreviewFace
    from core.scene import Scene
    from views.viewport import Viewport

    class _MemoVP:
        def __init__(self):
            self.scene = Scene()

    vp = _MemoVP()
    face = PreviewFace([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    tris = Viewport._tris_of(vp, face)
    assert len(tris) == 2
    n = Viewport._normal_of(vp, face)
    assert round(abs(n.z()), 3) == 1.0
    assert Viewport._area_of(vp, face) == 4.0


def test_copy_paste_container_whose_own_mesh_is_empty():
    """«Seleccioné la luminaria, Ctrl+C, Ctrl+V, y en su lugar se pega la
    pérgola que había copiado antes» (Marco, 2026-09-11). The reference
    corner was read from each group's OWN mesh, and an imported component
    is a container whose own mesh is empty — nothing to hold the set by,
    so copy_selection returned False and the old clipboard stayed."""
    from core.group import Group, placement_points
    from core.mesh import Mesh
    from PySide6.QtGui import QMatrix4x4
    scene = Scene()
    vp = _VP(scene, History(scene), {"faces": [], "edges": [],
                                     "groups": [], "ref": V(99, 99, 0)})
    m = Mesh()
    m.add_face([V(3, 3), V(4, 3), V(4, 4), V(3, 4)])
    poste = Group(m, name="Poste")
    lamp = Group(Mesh(), name="Luminaria")
    lamp.adopt([poste])
    scene.groups.append(lamp)
    scene.selection.add(lamp)
    assert _copy(vp), "a container IS copyable"
    assert vp.clipboard["ref"] == V(3, 3, 0), "held by the corner of its parts"
    assert [g.name for g in vp.clipboard["groups"]] == ["Luminaria"]
    _paste_at(vp, 10, 10)
    pasted = next(k for k in scene.groups if k is not lamp)
    assert pasted.name == "Luminaria" and len(pasted.children) == 1
    pts = placement_points(pasted)
    assert abs(float(pts[:, 0].min()) - 10.0) < 1e-6
    assert abs(float(pts[:, 1].min()) - 10.0) < 1e-6


def test_a_face_pasted_over_another_merges_with_it():
    """Issue #73 (@pacaeiro): a rectangle copied on top of the previous
    one lay over it as a second face; like a rectangle drawn there, it now
    splits the plane into its regions."""
    from types import SimpleNamespace
    from PySide6.QtGui import QVector3D as V
    from core.history import History
    from core.scene import Scene
    from tools.paste import PasteTool
    sc = Scene()
    hist = History(sc)
    sc.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    sc.version += 1
    square = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]
    tool = PasteTool()
    tool._clip = {"faces": [(square, [], {})], "edges": [], "groups": [],
                  "ref": V(0, 0, 0)}
    tool._offset = V()
    tool._preview_on = False
    vp = SimpleNamespace(scene=sc, history=hist, update=lambda: None,
                         window=None)
    tool.on_click(SimpleNamespace(world=V(1, 1, 0), viewport=vp))
    # Overlapping 2×2 squares offset by (1,1): three regions, no stacking.
    areas = sorted(round(f.area(), 6) for f in sc.mesh.faces)
    assert areas == [1.0, 3.0, 3.0], areas


def test_paste_in_place_lands_on_the_original_and_selects_it():
    scene = Scene()
    hist = History(scene)
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [(V(5, 5), V(6, 5), False, None)], "ref": V(0, 0, 0)}
    vp = _VP(scene, hist, clip)

    assert PasteTool.in_place(vp) is True
    coords = {(round(v.x()), round(v.y())) for f in scene.mesh.faces
              for v in f.vertices}
    assert coords == {(0, 0), (2, 0), (2, 2), (0, 2)}   # no cursor offset
    assert len(scene.selection) == 2                    # the face and the edge

    assert hist.undo() is True                          # one step
    assert not scene.mesh.faces
    assert PasteTool.in_place(_VP(scene, hist, None)) is False


def test_paste_in_place_menu_action_keeps_the_active_tool():
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
        before = vp.active_tool
        win._on_paste_in_place()
        assert vp.active_tool is before
        assert len(vp.scene.mesh.faces) == 1
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_undoing_a_paste_leaves_no_loose_edges_behind():
    # Paste in Place inside a group: undo removed the faces but the edges
    # they had created stayed as debris in the group.
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    hist = History(scene)
    g = Group(Mesh(), name="B")
    scene.groups.append(g)
    scene.begin_group_edit(g)
    loop = [V(0, 0), V(2, 0), V(2, 2), V(0, 2)]
    clip = {"faces": [(loop, [])], "edges": [(V(0, 0), V(2, 0), False, None)],
            "ref": V(0, 0, 0)}
    vp = _VP(scene, hist, clip)

    assert PasteTool.in_place(vp)
    assert (len(g.mesh.faces), len(g.mesh.edges)) == (1, 4)
    assert hist.undo() is True
    assert (len(g.mesh.faces), len(g.mesh.edges)) == (0, 0)
    assert hist.redo() is True
    assert (len(g.mesh.faces), len(g.mesh.edges)) == (1, 4)


def test_undoing_a_paste_over_the_original_keeps_the_original_edges():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    before = len(scene.mesh.edges)
    assert PasteTool.in_place(_VP(scene, hist, clip))
    assert hist.undo() is True
    assert len(scene.mesh.edges) == before == 4


def test_undoing_a_paste_shrinks_the_group_back_and_redo_restores_it():
    # The group's edit box wraps its vertices: leftovers of an undone paste
    # kept it at the pasted size («quedó como si aún estuviera el cubo»).
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    hist = History(scene)
    g = Group(Mesh(), name="B")
    g.mesh.add_face([V(10, 0), V(12, 0), V(12, 2), V(10, 2)])
    scene.groups.append(g)
    scene.begin_group_edit(g)
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    vp = _VP(scene, hist, clip)

    def xs():
        return sorted({round(v.position.x()) for v in g.mesh.vertices})

    assert PasteTool.in_place(vp)
    assert xs() == [0, 2, 10, 12]
    assert hist.undo() is True
    assert xs() == [10, 12]                     # box back to the original size
    assert hist.redo() is True
    assert xs() == [0, 2, 10, 12]
    assert len(g.mesh.faces) == 2 and len(g.mesh.edges) == 8
    # a stamp can still weld onto the restored vertices
    assert PasteTool.in_place(vp)


def _loose_and_group(scene):
    """A loose square with its edges, and a group beside it, all selected."""
    face = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    edges = [e for e in scene.mesh.edges if face in e.faces]
    g = _make_group(scene, 3.0)
    scene.selection.update([face, *edges, g])
    return face, edges, g


def _move_targets(vp):
    from tools.move import gather_targets
    return gather_targets(SimpleNamespace(viewport=vp))


def test_a_mixed_paste_leaves_everything_it_pasted_selected():
    """Only the groups stayed selected, so the Move right after a paste
    carried them off and left the loose part behind."""
    scene = Scene()
    vp = _PreviewVP(scene, History(scene), None)
    face, edges, g = _loose_and_group(scene)
    assert _copy(vp)
    _paste_at(vp, 10, 10)
    assert face not in scene.selection and g not in scene.selection
    kinds = sorted(type(x).__name__ for x in scene.selection)
    assert kinds == ["Edge"] * 4 + ["Face", "Group"]
    groups, points = _move_targets(vp)
    assert len(groups) == 1 and groups[0] is not g
    assert len(points) == 4
    assert {round(p.x()) for p in points} == {10, 12}, "the original's corners"


def test_a_loose_paste_does_not_leave_the_originals_selected():
    """With no group in the clipboard the selection was not touched: the
    next Move or Delete acted on what was copied, not on the copy."""
    scene = Scene()
    vp = _PreviewVP(scene, History(scene), None)
    face = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    scene.selection.add(face)
    assert _copy(vp)
    _paste_at(vp, 10, 10)
    assert face not in scene.selection
    assert len(scene.selection) == 1
    _groups, points = _move_targets(vp)
    assert {round(p.x()) for p in points} == {10, 12}


def test_undoing_a_paste_leaves_nothing_dead_selected():
    scene = Scene()
    hist = History(scene)
    vp = _PreviewVP(scene, hist, None)
    face, edges, g = _loose_and_group(scene)
    assert _copy(vp)
    _paste_at(vp, 10, 10)
    assert hist.undo() is True
    live = {id(x) for x in (*scene.mesh.faces, *scene.mesh.edges,
                            *scene.groups)}
    assert all(id(x) in live for x in scene.selection)


def test_undoing_a_paste_in_place_leaves_nothing_dead_selected():
    scene = Scene()
    hist = History(scene)
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    assert PasteTool.in_place(_VP(scene, hist, clip)) is True
    assert len(scene.selection) == 1
    assert hist.undo() is True
    assert not scene.selection


def test_a_paste_merged_into_a_face_selects_no_original():
    """Over a face on the same plane the pasted one is split (#73): the
    pieces are not the paste's own, but the original must not stay selected."""
    scene = Scene()
    vp = _PreviewVP(scene, History(scene), None)
    face = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    scene.selection.add(face)
    assert _copy(vp)
    _paste_at(vp, 1, 1)
    assert face not in scene.selection
