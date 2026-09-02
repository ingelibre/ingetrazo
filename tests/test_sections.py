# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section planes (SketchUp sections): entity, commands, tool, persistence,
scenes and the composer's HLR cut."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import (
    DeleteSectionPlanesCommand,
    History,
    MoveSectionPlanesCommand,
    PlaceSectionPlaneCommand,
    ReverseSectionPlaneCommand,
    RotateSectionPlanesCommand,
    SetActiveSectionCommand,
)
from core.scene import Scene
from core.section import SectionPlane
from tools.base import ToolContext
from tools.section import SectionPlaneTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self._face = None            # what pick_face_any returns

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass

    def pick_face_any(self, x, y):
        return self._face, None


def _ctx(vp, x, y, z=0.0, mods=Qt.NoModifier):
    return ToolContext(viewport=vp, world=V(x, y, z),
                       screen=QPointF(0, 0), modifiers=mods, snap=None)


# ---- Entity -----------------------------------------------------------------

def test_plane_side_flip_and_roundtrip():
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1), name="Planta", symbol="1")
    assert sp.side(V(0, 0, 3)) > 0            # above = hidden side
    assert sp.side(V(0, 0, 0)) < 0
    sp.flip()                                  # SketchUp's Reverse
    assert sp.side(V(0, 0, 3)) < 0
    again = SectionPlane.from_dict(sp.to_dict())
    assert again.name == "Planta" and again.symbol == "1"
    assert again.uid == sp.uid
    assert (again.normal - sp.normal).length() < 1e-9
    fresh = SectionPlane(V(0, 0, 0), V(1, 0, 0))
    assert fresh.uid != sp.uid                # loaded uids never collide


# ---- Scene + commands -------------------------------------------------------

def test_place_activates_and_keeps_one_active():
    scene = Scene()
    hist = History(scene)
    a = SectionPlane(V(0, 0, 1), V(0, 0, 1))
    b = SectionPlane(V(0, 0, 2), V(0, 0, 1))
    hist.execute(PlaceSectionPlaneCommand(a))
    assert scene.active_section() is a        # placing = active cut (SketchUp)
    hist.execute(PlaceSectionPlaneCommand(b))
    assert scene.active_section() is b        # one active per context
    assert a.active is False
    assert hist.undo()
    assert scene.section_planes == [a]
    assert scene.active_section() is a        # previous active restored

    hist.execute(SetActiveSectionCommand(None))
    assert scene.active_section() is None
    assert hist.undo()
    assert scene.active_section() is a

    hist.execute(ReverseSectionPlaneCommand(a))
    assert a.side(V(0, 0, 3)) < 0
    hist.execute(MoveSectionPlanesCommand([a], V(0, 0, 5)))
    assert abs(a.point.z() - 6.0) < 1e-9
    hist.execute(RotateSectionPlanesCommand([a], V(0, 0, 0), V(1, 0, 0), 90))
    assert abs(abs(a.normal.y()) - 1.0) < 1e-6
    hist.execute(DeleteSectionPlanesCommand([a]))
    assert scene.section_planes == []
    assert hist.undo()
    assert scene.section_planes == [a]


# ---- Tool -------------------------------------------------------------------

def test_tool_aligns_to_hovered_face_and_places_active():
    scene = Scene()
    vp = _Vp(scene)
    wall = scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0),
                                V(2, 0, 2), V(0, 0, 2)])  # a Y-normal wall
    vp._face = wall
    t = SectionPlaneTool()
    t.on_activate(vp)
    t.on_hover(_ctx(vp, 1, 0, 1))
    t.on_click(_ctx(vp, 1, 0, 1))
    assert len(scene.section_planes) == 1
    sp = scene.section_planes[0]
    assert sp.active                          # new plane = the active cut
    assert abs(abs(sp.normal.y()) - 1.0) < 1e-6   # aligned to the wall
    assert sp.symbol == "1"
    assert vp.history.undo()
    assert scene.section_planes == []


def test_tool_arrow_keys_and_ground_default():
    scene = Scene()
    vp = _Vp(scene)
    t = SectionPlaneTool()
    t.on_activate(vp)
    t.on_hover(_ctx(vp, 0, 0))                # empty ground → horizontal cut
    assert abs(t._current_normal().z() - 1.0) < 1e-9
    assert t.on_key(vp, Qt.Key_Right, Qt.NoModifier) is True   # red = X
    assert abs(t._current_normal().x() - 1.0) < 1e-9
    assert t.on_key(vp, Qt.Key_Left, Qt.NoModifier) is True    # green = Y
    assert abs(t._current_normal().y() - 1.0) < 1e-9
    assert t.on_key(vp, Qt.Key_Up, Qt.NoModifier) is True      # blue = Z
    assert abs(t._current_normal().z() - 1.0) < 1e-9
    assert t.on_key(vp, Qt.Key_Down, Qt.NoModifier) is True    # back to face
    assert t._axis_pick is None


# ---- Persistence + scenes ---------------------------------------------------

def test_igz_roundtrip_and_scene_recall(tmp_path):
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from formats import igz as igz_format

    scene = Scene()
    scene.mesh.add_edge(V(0, 0), V(1, 0))
    a = SectionPlane(V(0, 0, 1), V(0, 0, 1), name="Planta", symbol="1")
    b = SectionPlane(V(5, 0, 0), V(1, 0, 0), name="Corte A", symbol="A")
    scene.section_planes += [a, b]
    scene.set_active_section(b)
    scene.show_section_planes = False

    cam = OrbitCamera()
    scene.saved_views.append(SavedView.capture("Corte", scene, cam))

    path = tmp_path / "secciones.igz"
    igz_format.save_scene(scene, path)
    fresh = Scene()
    igz_format.load_into(fresh, path)

    assert [sp.name for sp in fresh.section_planes] == ["Planta", "Corte A"]
    assert fresh.active_section().symbol == "A"
    assert fresh.show_section_planes is False
    assert fresh.show_section_cuts is True

    # The saved view recalls the section state (SketchUp scenes).
    fresh.set_active_section(None)
    fresh.show_section_planes = True
    fresh.saved_views[0].apply(fresh, cam)
    assert fresh.active_section() is not None
    assert fresh.active_section().symbol == "A"
    assert fresh.show_section_planes is False


# ---- HLR (the composer's cut) ----------------------------------------------

def test_hlr_clip_cuts_triangles_edges_and_adds_cut_lines():
    from core.hlr import clip_to_section
    plane = SectionPlane(V(0, 0, 1), V(0, 0, 1))   # hide z > 1
    tris = [((0, 0, 0), (2, 0, 0), (0, 0, 2)),     # straddles the plane
            ((0, 0, 5), (1, 0, 5), (0, 1, 5)),     # fully hidden
            ((0, 0, 0), (1, 0, 0), (0, 1, 0))]     # fully kept
    hard = [((0, 0, 0), (0, 0, 4)),                # vertical: gets shortened
            ((0, 0, 3), (1, 0, 3)),                # fully hidden: dropped
            ((0, 0, 0), (1, 0, 0))]                # kept
    out_tris, out_hard, out_soft = clip_to_section(tris, hard, [], plane)

    assert all(max(p[2] for p in tri) <= 1.0 + 1e-6 for tri in out_tris)
    assert len(out_tris) >= 2                      # kept + clipped remainder
    # The shortened vertical edge now ends AT the plane.
    verts = [seg for seg in out_hard if seg[0][:2] == (0, 0)
             and seg[1][:2] == (0, 0)]
    assert any(abs(seg[1][2] - 1.0) < 1e-9 for seg in verts)
    assert all(seg != ((0, 0, 3), (1, 0, 3)) for seg in out_hard)
    # The plane∩triangle chord joined the drawing (the section-cut line).
    def on_plane(seg):
        return (abs(seg[0][2] - 1.0) < 1e-9 and abs(seg[1][2] - 1.0) < 1e-9
                and math.hypot(seg[0][0] - seg[1][0],
                               seg[0][1] - seg[1][1]) > 1e-6)
    assert any(on_plane(seg) for seg in out_hard)


def test_hlr_view_honours_the_active_section():
    from core.camera import OrbitCamera
    from core.hlr import hlr_view
    scene = Scene()
    # A 2 m vertical wall in the XZ plane.
    scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)])
    cam = OrbitCamera()
    cam.perspective = False
    full = hlr_view(scene, cam)
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1))      # cut at z = 1
    scene.section_planes.append(sp)
    scene.set_active_section(sp)
    cut = hlr_view(scene, cam)
    assert len(full) and len(cut)
    # With the cut hiding the top half the drawing changes.
    assert len(cut) != len(full) or not (cut == full).all()
    scene.show_section_cuts = False                # cuts hidden → full drawing
    back = hlr_view(scene, cam)
    assert len(back) == len(full)


# ---- Section fill + direct grab (round 2) -----------------------------------

def test_style_carries_section_fill():
    from core.style import Style
    st = Style()
    assert st.section_fill is True             # SketchUp 2018+ default: on
    st.section_fill = False
    st.section_fill_color = (0.1, 0.2, 0.3)
    again = Style.from_dict(st.to_dict())
    assert again.section_fill is False
    assert again.section_fill_color == (0.1, 0.2, 0.3)


def test_move_grabs_a_section_plane_directly():
    # SketchUp: no pre-selection — Move grabs the plane by its frame and the
    # cut follows live; the drop is one undoable command.
    from tools.move import MoveTool
    scene = Scene()
    vp = _Vp(scene)
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1))
    scene.section_planes.append(sp)
    scene.set_active_section(sp)
    vp.pick_section_plane = lambda x, y: sp
    vp.pick_group = lambda x, y: None
    vp.pick_edge = lambda x, y: None
    vp.pick_face = lambda x, y: None
    vp.pick_text_label = lambda *a, **k: None

    t = MoveTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0, 1))              # grab the plane directly
    assert t._splanes == [sp]
    t.on_hover(_ctx(vp, 0, 0, 3))              # live: the cut moves with it
    assert abs(sp.point.z() - 3.0) < 1e-9
    t.on_click(_ctx(vp, 0, 0, 3))              # drop
    assert abs(sp.point.z() - 3.0) < 1e-9
    assert vp.history.undo()
    assert abs(sp.point.z() - 1.0) < 1e-9


def test_rotate_grabs_a_section_plane_directly():
    from tools.rotate import RotateTool
    scene = Scene()
    vp = _Vp(scene)
    sp = SectionPlane(V(0, 0, 0), V(0, 0, 1))
    scene.section_planes.append(sp)
    vp.pick_section_plane = lambda x, y: sp
    vp.pick_group = lambda x, y: None
    vp.pick_edge = lambda x, y: None
    vp.pick_face = lambda x, y: None

    t = RotateTool()
    t.on_activate(vp)
    t.on_click(_ctx(vp, 0, 0))                 # centre grabs the plane
    assert t._splanes == [sp]
    t.on_click(_ctx(vp, 1, 0))                 # base arm
    t.on_hover(_ctx(vp, 0, 1))
    t.on_click(_ctx(vp, 0, 1))                 # +90° about Z... plane normal Z
    # Rotating about the world Z axis keeps a Z normal: check the command ran.
    assert len(vp.history.undo_stack) == 1
    assert vp.history.undo()


def test_scene_made_before_any_section_switches_the_cut_off(tmp_path):
    """SketchUp saves "Active Section Planes" per scene by default: a plan
    scene captured before any section plane exists recalls NO active cut, so
    a section activated later never bleeds into it (Marco: "cada escena
    debería ir separada", 2026-09-02). Views from documents older than
    sections (no "section" entry at all) stay hands-off."""
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from formats import igz as igz_format

    scene = Scene()
    scene.mesh.add_edge(V(0, 0), V(1, 0))
    cam = OrbitCamera()
    planta = SavedView.capture("Planta", scene, cam)       # no planes yet
    assert planta.section == {"active": None, "planes_shown": True,
                              "cuts_shown": True}
    scene.saved_views.append(planta)

    cut = SectionPlane(V(5, 0, 0), V(1, 0, 0), name="Corte A", symbol="A")
    scene.section_planes.append(cut)
    scene.set_active_section(cut)
    corte = SavedView.capture("Corte A", scene, cam)
    scene.saved_views.append(corte)

    planta.apply(scene, cam)
    assert scene.active_section() is None
    corte.apply(scene, cam)
    assert scene.active_section() is cut

    # The separation survives the document round trip.
    path = tmp_path / "escenas.igz"
    igz_format.save_scene(scene, path)
    fresh = Scene()
    igz_format.load_into(fresh, path)
    assert fresh.active_section() is not None
    fresh.saved_views[0].apply(fresh, cam)
    assert fresh.active_section() is None

    # A pre-sections view (no entry) still leaves the live cut alone.
    legacy = SavedView.from_dict({"name": "Vieja", "target": [0, 0, 0],
                                  "distance": 10.0, "yaw": 0.0, "pitch": 0.0})
    assert legacy.section is None
    fresh.set_active_section(fresh.section_planes[0])
    legacy.apply(fresh, cam)
    assert fresh.active_section() is not None
