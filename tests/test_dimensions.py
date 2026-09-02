# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Static dimensions: the entity's geometry, the Add/Delete commands, the tool's
3-click placement, and .igz round-trip."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.dimension import Dimension
from core.history import (
    AddDimensionCommand,
    DeleteDimensionsCommand,
    History,
)
from core.scene import Scene
from formats import igz
from tools.base import ToolContext
from tools.dimension import DimensionTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


# ---- Entity --------------------------------------------------------------------

def test_dimension_value_and_line_points():
    d = Dimension(V(0, 0, 0), V(4, 0, 0), V(0, 0, 2))
    assert d.value() == 4.0
    assert d.label() == "4.00 m"
    ap, bp = d.line_points()
    assert ap == V(0, 0, 2) and bp == V(4, 0, 2)
    assert d.midpoint() == V(2, 0, 2)


def test_offset_for_cursor_is_perpendicular():
    # Cursor above the +X segment at (2, 0, 3): offset should be the vertical
    # component only (the along-segment part is dropped).
    off = Dimension.offset_for_cursor(V(0, 0, 0), V(4, 0, 0), V(2, 0, 3))
    assert off == V(0, 0, 3)


# ---- Commands ------------------------------------------------------------------

def test_add_and_delete_dimension_commands():
    scene = Scene()
    hist = History(scene)
    d = Dimension(V(0, 0, 0), V(4, 0, 0), V(0, 0, 2))
    hist.execute(AddDimensionCommand(d))
    assert scene.dimensions == [d]
    hist.undo()
    assert scene.dimensions == []
    hist.redo()
    assert scene.dimensions == [d]

    hist.execute(DeleteDimensionsCommand([d]))
    assert scene.dimensions == []
    hist.undo()
    assert scene.dimensions == [d]            # restored at its index


# ---- Tool ----------------------------------------------------------------------

class _StubVP:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass


def _ctx(vp, world):
    return ToolContext(viewport=vp, world=world, screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def test_dimension_tool_three_clicks_place_a_dimension():
    scene = Scene()
    vp = _StubVP(scene)
    tool = DimensionTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))         # first endpoint
    assert not scene.dimensions
    tool.on_click(_ctx(vp, V(4, 0, 0)))         # second endpoint
    assert not scene.dimensions                 # still placing the offset
    tool.on_click(_ctx(vp, V(2, 0, 3)))         # offset placement
    assert len(scene.dimensions) == 1
    d = scene.dimensions[0]
    assert d.value() == 4.0
    assert d.offset == V(0, 0, 3)
    assert tool.a is None                       # reset for the next dimension


def test_dimension_tool_preview_lines():
    scene = Scene()
    vp = _StubVP(scene)
    tool = DimensionTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_hover(_ctx(vp, V(4, 0, 0)))
    assert tool.rubber_band_lines() == [(V(0, 0, 0), V(4, 0, 0))]  # measuring
    tool.on_click(_ctx(vp, V(4, 0, 0)))
    tool.on_hover(_ctx(vp, V(2, 0, 3)))
    lines = tool.rubber_band_lines()
    assert len(lines) == 3                       # 2 extension + 1 dimension line


# ---- .igz round-trip -----------------------------------------------------------

def test_dimension_survives_igz_round_trip(tmp_path):
    scene = Scene()
    hist = History(scene)
    hist.execute(AddDimensionCommand(
        Dimension(V(0, 0, 0), V(4, 0, 0), V(0, 0, 2))))
    path = tmp_path / "dim.igz"
    igz.save_scene(scene, path)

    loaded = Scene()
    igz.load_into(loaded, path)
    assert len(loaded.dimensions) == 1
    d = loaded.dimensions[0]
    assert d.a == V(0, 0, 0) and d.b == V(4, 0, 0) and d.offset == V(0, 0, 2)
    assert d.value() == 4.0


# ---- Select + delete -----------------------------------------------------------

def test_select_tool_deletes_a_dimension():
    from tools.select import SelectTool

    scene = Scene()
    vp = _StubVP(scene)
    d = Dimension(V(0, 0, 0), V(4, 0, 0), V(0, 0, 2))
    vp.history.execute(AddDimensionCommand(d))
    scene.selection.add(d)

    tool = SelectTool()
    tool.on_key(vp, Qt.Key_Delete, Qt.NoModifier)
    assert d not in scene.dimensions
    assert d not in scene.selection          # selection cleared of the deleted dim

    vp.history.undo()
    assert d in scene.dimensions             # undo brings it back


# ---- Style (precision / units) -------------------------------------------------

def test_format_dim_value_respects_units_and_precision():
    from views.viewport import Viewport
    f = Viewport._format_dim_value
    assert f(4.0, {"units": "m", "decimals": 2}) == "4.00 m"
    assert f(4.0, {"units": "cm", "decimals": 0}) == "400 cm"
    assert f(4.0, {"units": "mm", "decimals": 1}) == "4000.0 mm"


def test_dimension_style_survives_igz_round_trip(tmp_path):
    scene = Scene()
    scene.dimension_style.update({"decimals": 0, "units": "cm", "font_size": 14})
    path = tmp_path / "style.igz"
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    assert loaded.dimension_style["decimals"] == 0
    assert loaded.dimension_style["units"] == "cm"
    assert loaded.dimension_style["font_size"] == 14


# ---- Occlusion (vectorised, cached — the orbit-speed fix) -----------------------

def test_is_occluded_matches_geometry():
    # A wall between the camera and the point occludes it; a point in front
    # of the wall (or with no geometry) is visible. Exercises the cached
    # NumPy Möller–Trumbore path headless (plaza.igz slowdown report).
    from PySide6.QtGui import QVector3D
    from views.viewport import Viewport

    scene = Scene()
    scene.mesh.add_face([QVector3D(-2, 0, -2), QVector3D(2, 0, -2),
                         QVector3D(2, 0, 2), QVector3D(-2, 0, 2)])  # wall y=0

    class _Cam:
        def eye(self):
            return QVector3D(0.0, -10.0, 0.0)

    class _VP:
        # Occlusion reaches into the pick index, which pulls in a handful of
        # viewport helpers; bind whatever it asks for rather than listing them.
        def __getattr__(self, name):
            import inspect
            raw = inspect.getattr_static(Viewport, name, None)
            if raw is None:
                raise AttributeError(name)
            # Plain functions bind to the stub; staticmethods are taken as-is.
            bound = (raw.__get__(self) if inspect.isfunction(raw)
                     else getattr(Viewport, name))
            setattr(self, name, bound)
            return bound

    vp = _VP()
    vp.scene = scene
    vp.camera = _Cam()
    vp.plano_style = None
    vp.style_override = None
    occluded = Viewport._is_occluded.__get__(vp)

    assert occluded(QVector3D(0, 5, 0)) is True       # behind the wall
    assert occluded(QVector3D(0, -5, 0)) is False     # in front of it
    assert occluded(QVector3D(5, 5, 0)) is False      # past the wall's edge
    assert occluded(QVector3D(0, 0, 0)) is False      # ON the wall (epsilon)
    scene.mesh.add_face([QVector3D(-2, 2, -2), QVector3D(2, 2, -2),
                         QVector3D(2, 2, 2), QVector3D(-2, 2, 2)])
    scene.version += 1                                # cache must refresh
    assert occluded(QVector3D(0, 5, 0)) is True
    assert occluded(QVector3D(0, 1, 0)) is True       # behind wall 1 only


def test_xray_and_wireframe_let_snaps_through_faces():
    # SketchUp: in X-ray (or wireframe) nothing hides geometry, so the snap
    # engine must not reject a point behind a face — that is how you
    # dimension the floor of a pool through its water (Marco, 2026-09-02).
    # Shaded/hidden-line styles keep the visible-only rule.
    from PySide6.QtGui import QVector3D
    from core.style import Style
    from views.viewport import Viewport

    scene = Scene()
    scene.mesh.add_face([QVector3D(-2, 0, -2), QVector3D(2, 0, -2),
                         QVector3D(2, 0, 2), QVector3D(-2, 0, 2)])  # wall y=0

    class _Cam:
        def eye(self):
            return QVector3D(0.0, -10.0, 0.0)

    class _VP:
        def __getattr__(self, name):
            import inspect
            raw = inspect.getattr_static(Viewport, name, None)
            if raw is None:
                raise AttributeError(name)
            bound = (raw.__get__(self) if inspect.isfunction(raw)
                     else getattr(Viewport, name))
            setattr(self, name, bound)
            return bound

    vp = _VP()
    vp.scene = scene
    vp.camera = _Cam()
    vp.plano_style = None
    vp.style_override = None
    occluded = Viewport._is_occluded.__get__(vp)
    behind = QVector3D(0, 5, 0)

    assert occluded(behind) is True                        # default style
    scene.display_style = Style(name="X-ray", face_mode="xray")
    assert occluded(behind) is False
    scene.display_style = Style(name="Wireframe", face_mode="wireframe")
    assert occluded(behind) is False
    scene.display_style = Style(name="Hidden line", face_mode="hidden_line")
    assert occluded(behind) is True
    # The composer's line-drawing override wins over the scene style.
    scene.display_style = Style(name="Default")
    vp.plano_style = "lineas"
    assert occluded(behind) is False
    vp.plano_style = "tecnico"
    assert occluded(behind) is True


def test_geometry_inside_a_group_occludes_too():
    """A group is solid to the eye, so it must hide what is behind it.

    Occlusion read ``scene.faces`` — the LOOSE mesh — so a wall that lived in
    a group hid nothing, and drawing on a box snapped through it to the edge
    on the far side (Marco, 2026-08-27). It asks the pick index now, which
    holds every group's triangles as well.
    """
    from PySide6.QtGui import QVector3D
    from core.group import Group
    from core.mesh import Mesh
    from views.viewport import Viewport

    wall = Mesh()
    wall.add_face([QVector3D(-2, 0, -2), QVector3D(2, 0, -2),
                   QVector3D(2, 0, 2), QVector3D(-2, 0, 2)])
    scene = Scene()
    scene.groups.append(Group(wall, name="Muro"))
    assert scene.faces == []                       # nothing loose at all

    class _Cam:
        def eye(self):
            return QVector3D(0.0, -10.0, 0.0)

    class _VP:
        # Occlusion reaches into the pick index, which pulls in a handful of
        # viewport helpers; bind whatever it asks for rather than listing them.
        def __getattr__(self, name):
            import inspect
            raw = inspect.getattr_static(Viewport, name, None)
            if raw is None:
                raise AttributeError(name)
            # Plain functions bind to the stub; staticmethods are taken as-is.
            bound = (raw.__get__(self) if inspect.isfunction(raw)
                     else getattr(Viewport, name))
            setattr(self, name, bound)
            return bound

    vp = _VP()
    vp.scene = scene
    vp.camera = _Cam()
    vp.plano_style = None
    vp.style_override = None
    occluded = Viewport._is_occluded.__get__(vp)

    assert occluded(QVector3D(0, 5, 0)) is True     # behind the grouped wall
    assert occluded(QVector3D(0, -5, 0)) is False   # in front of it
    assert occluded(QVector3D(5, 5, 0)) is False    # past its edge


def test_world_under_cursor_uses_cached_pick():
    # Zoom-to-cursor's pick rides the cached NumPy triangles (fast wheel
    # bursts must not re-triangulate the model per event). Nearest hit wins;
    # empty scene falls back to the ground plane.
    from PySide6.QtGui import QVector3D
    from views.viewport import Viewport

    scene = Scene()
    scene.mesh.add_face([QVector3D(-2, 0, -2), QVector3D(2, 0, -2),
                         QVector3D(2, 0, 2), QVector3D(-2, 0, 2)])   # wall y=0
    scene.mesh.add_face([QVector3D(-2, 3, -2), QVector3D(2, 3, -2),
                         QVector3D(2, 3, 2), QVector3D(-2, 3, 2)])   # wall y=3

    class _Cam:
        target = QVector3D(0, 0, 0)
        def eye(self):
            return QVector3D(0.0, -10.0, 0.0)

    class _VP:
        # Occlusion reaches into the pick index, which pulls in a handful of
        # viewport helpers; bind whatever it asks for rather than listing them.
        def __getattr__(self, name):
            import inspect
            raw = inspect.getattr_static(Viewport, name, None)
            if raw is None:
                raise AttributeError(name)
            # Plain functions bind to the stub; staticmethods are taken as-is.
            bound = (raw.__get__(self) if inspect.isfunction(raw)
                     else getattr(Viewport, name))
            setattr(self, name, bound)
            return bound

    vp = _VP()
    vp.scene = scene
    vp.camera = _Cam()
    vp._pixel_to_ray = lambda x, y: (QVector3D(0, -10, 0), QVector3D(0, 1, 0))
    vp._pick_index = Viewport._pick_index.__get__(vp)
    vp._placements = Viewport._placements.__get__(vp)
    vp._expand_placements = Viewport._expand_placements.__get__(vp)
    vp._ray_hits = Viewport._ray_hits.__get__(vp)
    under = Viewport._world_under_cursor.__get__(vp)

    hit = under(0, 0)
    assert abs(hit.y() - 0.0) < 1e-6          # nearest wall, not the far one
    scene.mesh.clear()
    scene.version += 1                        # cache refresh on scene change
    vp._pixel_to_ray = lambda x, y: (QVector3D(0, 0, 10),
                                     QVector3D(0, 0, -1))
    ground = under(0, 0)
    assert abs(ground.z()) < 1e-6             # falls back to the ground plane


# ---- Custom dimension text (SketchUp: double-click the value) ---------------

def test_dimension_custom_text_and_placeholder():
    from PySide6.QtGui import QVector3D
    from core.dimension import Dimension
    d = Dimension(QVector3D(0, 0, 0), QVector3D(2.4, 0, 0), QVector3D(0, 1, 0))
    assert d.display_text("2.40 m") == "2.40 m"              # automatic
    d.text = "H = <> (verificar)"
    assert d.display_text("2.40 m") == "H = 2.40 m (verificar)"
    d.text = "VARIABLE"
    assert d.display_text("2.40 m") == "VARIABLE"


def test_edit_dimension_text_command_undo_redo():
    from PySide6.QtGui import QVector3D
    from core.dimension import Dimension
    from core.history import EditDimensionTextCommand, History
    from core.scene import Scene
    scene = Scene()
    history = History(scene)
    d = Dimension(QVector3D(0, 0, 0), QVector3D(2, 0, 0), QVector3D(0, 1, 0))
    scene.dimensions.append(d)
    history.execute(EditDimensionTextCommand(d, "Ø <>"))
    assert d.text == "Ø <>"
    history.undo()
    assert d.text is None
    history.redo()
    assert d.text == "Ø <>"
    history.execute(EditDimensionTextCommand(d, None))       # back to auto
    assert d.text is None


def test_select_double_click_edits_dimension_text(monkeypatch, tmp_path):
    """Double-clicking a cota with Select opens the text dialog (SketchUp),
    commits the new text as one undoable command, and a bare "<>" or the
    measured value itself returns the cota to its automatic label. The text
    survives the .igz round trip."""
    from types import SimpleNamespace
    from PySide6.QtGui import QVector3D
    from PySide6.QtWidgets import QInputDialog
    from core.dimension import Dimension
    from core.history import History
    from core.scene import Scene
    from formats import igz as igz_format
    from tools.select import SelectTool

    scene = Scene()
    history = History(scene)
    d = Dimension(QVector3D(0, 0, 0), QVector3D(2.4, 0, 0), QVector3D(0, 1, 0))
    scene.dimensions.append(d)
    viewport = SimpleNamespace(
        scene=scene, history=history,
        pick_group=lambda x, y: None, pick_edge=lambda x, y: None,
        pick_dimension=lambda x, y: d,
        pick_text_label=lambda x, y, rect_only=False: None,
        pick_geopath=lambda x, y: None, pick_face=lambda x, y: None,
        pick_section_plane=lambda x, y: None, pick_guide=lambda x, y: None,
        pick_image_plane=lambda x, y: None,
        window=lambda: None, update=lambda: None)
    ctx = SimpleNamespace(viewport=viewport,
                          screen=SimpleNamespace(x=lambda: 0, y=lambda: 0),
                          modifiers=0)
    asked = {}

    def fake_get_text(parent, title, label, text="", **kw):
        asked["prefill"] = text
        return asked["answer"], True

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake_get_text))
    asked["answer"] = "H = <>"
    SelectTool().on_double_click(ctx)
    assert asked["prefill"] == "2.40 m"                      # shows the value
    assert d.text == "H = <>"
    assert d.display_text("2.40 m") == "H = 2.40 m"
    history.undo()
    assert d.text is None
    history.redo()

    asked["answer"] = "<>"                                   # back to automatic
    SelectTool().on_double_click(ctx)
    assert asked["prefill"] == "H = <>"
    assert d.text is None

    d.text = "VARIABLE"
    path = tmp_path / "cota.igz"
    igz_format.save_scene(scene, path)
    fresh = Scene()
    igz_format.load_into(fresh, path)
    assert fresh.dimensions[0].text == "VARIABLE"
