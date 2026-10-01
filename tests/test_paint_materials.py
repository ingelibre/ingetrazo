# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Painting with material identity (registry track, slices a/b/e).

The contract: painting a named material stamps attrs["mat"] alongside the
colour/texture and registers the material on first use; painting
anonymously CLEARS the identity (a red face is no longer "Concreto
visto"); the eyedropper picks the identity up; and editing a material
restamps every face that wears it — all of it undoable exactly."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.history import History, RestampMaterialCommand          # noqa: E402
from core.materials import Material                               # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from tools.paint import PaintTool                                 # noqa: E402
from tools.base import ToolContext                                # noqa: E402


def _quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(4, 0, z),
                          QVector3D(4, 4, z), QVector3D(0, 4, z)])


class _FakeViewport:
    """Just enough viewport for PaintTool: scene, history, and a pick that
    returns a chosen face (GL picking needs a real display)."""

    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)
        self._pick = None

    def pick_face_any(self, _x, _y):
        return self._pick, None

    def update(self):
        pass

    def set_hover(self, _f):
        pass


def _click(vp, face, modifiers=Qt.NoModifier):
    vp._pick = face
    tool = PaintTool()
    tool.on_click(ToolContext(viewport=vp, world=QVector3D(),
                              screen=QPointF(0, 0), modifiers=modifiers,
                              snap=None))


@pytest.fixture(autouse=True)
def _reset_paint_state():
    yield
    PaintTool.current_material = None
    PaintTool.current_texture = None
    PaintTool.current_color = (0.80, 0.45, 0.30)


# ---- (a) + (e): painting with identity ------------------------------------

def test_paint_named_material_stamps_and_registers():
    vp = _FakeViewport()
    face = _quad(vp.scene.mesh)
    PaintTool.current_color = (0.62, 0.60, 0.58)
    PaintTool.current_texture = None
    PaintTool.current_material = Material("Concreto visto",
                                          color=(0.62, 0.60, 0.58))
    _click(vp, face)

    assert face.attrs["mat"] == "Concreto visto"
    assert tuple(face.attrs["color"]) == (0.62, 0.60, 0.58)
    # (e): the library material registered itself on first use...
    assert "Concreto visto" in vp.scene.materials

    # ...and one undo removes stamp AND registry entry (it added it).
    assert vp.history.undo()
    assert "mat" not in face.attrs
    assert "Concreto visto" not in vp.scene.materials


def test_anonymous_paint_clears_identity():
    vp = _FakeViewport()
    face = _quad(vp.scene.mesh)
    vp.scene.materials["Concreto visto"] = Material(
        "Concreto visto", color=(0.62, 0.60, 0.58))
    face.attrs.update(vp.scene.materials["Concreto visto"].face_attrs())

    PaintTool.current_material = None                 # plain red, no name
    PaintTool.current_color = (0.8, 0.1, 0.1)
    PaintTool.current_texture = None
    _click(vp, face)

    assert "mat" not in face.attrs                    # takeoff stays honest
    assert tuple(face.attrs["color"]) == (0.8, 0.1, 0.1)
    assert "Concreto visto" in vp.scene.materials     # registry untouched

    vp.history.undo()
    assert face.attrs["mat"] == "Concreto visto"      # exact restore


def test_eyedropper_picks_up_identity():
    vp = _FakeViewport()
    mat = Material("Ladrillo", color=(0.7, 0.3, 0.2))
    vp.scene.materials["Ladrillo"] = mat
    face = _quad(vp.scene.mesh)
    face.attrs.update(mat.face_attrs())
    anon = _quad(vp.scene.mesh, z=1.0)
    anon.attrs["color"] = (0.1, 0.2, 0.3)

    _click(vp, face, modifiers=Qt.AltModifier)
    assert PaintTool.current_material is mat          # the registry object

    _click(vp, anon, modifiers=Qt.AltModifier)
    assert PaintTool.current_material is None         # anonymous sample


def test_textured_named_paint():
    vp = _FakeViewport()
    face = _quad(vp.scene.mesh)
    tex = {"path": "/tex/ladrillo.png", "sw": 1.0, "sh": 1.0, "rot": 0.0}
    PaintTool.current_texture = dict(tex)
    PaintTool.current_material = Material("Ladrillo visto", texture=dict(tex))
    _click(vp, face)
    assert face.attrs["mat"] == "Ladrillo visto"
    assert face.attrs["texture"]["path"] == "/tex/ladrillo.png"
    assert "Ladrillo visto" in vp.scene.materials


# ---- (b): edit a material, restamp its faces ------------------------------

def test_restamp_updates_registry_and_every_face():
    scene = Scene()
    history = History(scene)
    old = Material("Concreto visto", color=(0.62, 0.60, 0.58))
    scene.materials["Concreto visto"] = old
    worn = [_quad(scene.mesh), _quad(scene.mesh, z=1.0)]
    for f in worn:
        f.attrs.update(old.face_attrs())
    g = Group(Mesh(), name="Caseta")                  # faces inside groups too
    inner = _quad(g.mesh, z=5.0)
    inner.attrs.update(old.face_attrs())
    scene.groups.append(g)
    other = _quad(scene.mesh, z=2.0)                  # different paint
    other.attrs["color"] = (0.1, 0.1, 0.1)

    new = Material("Concreto visto", color=(0.3, 0.5, 0.7))
    history.execute(RestampMaterialCommand("Concreto visto", new))

    assert scene.materials["Concreto visto"].color == (0.3, 0.5, 0.7)
    for f in worn + [inner]:
        assert tuple(f.attrs["color"]) == (0.3, 0.5, 0.7)
    assert tuple(other.attrs["color"]) == (0.1, 0.1, 0.1)   # untouched

    history.undo()
    assert scene.materials["Concreto visto"] is old
    for f in worn + [inner]:
        assert tuple(f.attrs["color"]) == (0.62, 0.60, 0.58)


def test_restamp_reaches_groups_painted_whole():
    """Issue #155 (@fafecm): a colour painted on a loose face and on a group
    as a whole; editing the colour changed the face and left the group."""
    from core.history import SetGroupMaterialCommand
    scene = Scene()
    history = History(scene)
    old = Material("Azul", color=(0.1, 0.6, 0.9))
    scene.materials["Azul"] = old
    face = _quad(scene.mesh)
    face.attrs.update(old.face_attrs())
    box = Group(Mesh(), name="Caja")
    _quad(box.mesh, z=5.0)                       # default faces: show the paint
    inner = Group(Mesh(), name="Tapa")           # nested, painted too
    _quad(inner.mesh, z=6.0)
    box.adopt([inner])
    scene.groups.append(box)
    other = Group(Mesh(), name="Otro")           # a different paint
    _quad(other.mesh, z=7.0)
    scene.groups.append(other)
    history.execute(SetGroupMaterialCommand(box, old.face_attrs()))
    history.execute(SetGroupMaterialCommand(other, {"color": (0.2, 0.2, 0.2)}))
    history.execute(SetGroupMaterialCommand(inner, old.face_attrs()))

    history.execute(RestampMaterialCommand(
        "Azul", Material("Azul", color=(0.6, 1.0, 0.4))))
    assert tuple(face.attrs["color"]) == (0.6, 1.0, 0.4)
    assert tuple(box.material["color"]) == (0.6, 1.0, 0.4)
    assert tuple(inner.material["color"]) == (0.6, 1.0, 0.4)
    assert tuple(other.material["color"]) == (0.2, 0.2, 0.2)   # untouched

    history.undo()
    assert tuple(box.material["color"]) == (0.1, 0.6, 0.9)
    assert tuple(inner.material["color"]) == (0.1, 0.6, 0.9)


def test_restamp_from_texture_to_colour_drops_the_texture():
    scene = Scene()
    history = History(scene)
    old = Material("Piso", texture={"path": "/tex/p.png", "sw": 1.0, "sh": 1.0})
    scene.materials["Piso"] = old
    f = _quad(scene.mesh)
    f.attrs.update(old.face_attrs())

    history.execute(RestampMaterialCommand(
        "Piso", Material("Piso", color=(0.5, 0.5, 0.5))))
    assert "texture" not in f.attrs                   # recipe change is total
    assert tuple(f.attrs["color"]) == (0.5, 0.5, 0.5)

    history.undo()
    assert f.attrs["texture"]["path"] == "/tex/p.png"
    assert "color" not in f.attrs


def test_eyedropper_carries_a_positioned_texture_only_within_its_plane():
    """The eyedropper reproduces the MATERIAL on the next face. An
    explicit world->UV map says where the image sits in the world, so it only
    means the same thing on the plane it was fitted for: handing it to a
    perpendicular face put the ``v`` axis along that face's normal and smeared
    the image into stripes."""
    from core.texture import face_uv_axes

    vp = _FakeViewport()
    floor = _quad(vp.scene.mesh)                       # z = 0, normal +Z
    wall = vp.scene.mesh.add_face([QVector3D(0, 8, 0), QVector3D(2, 8, 0),
                                   QVector3D(2, 8, 2), QVector3D(0, 8, 2)])
    same_plane = vp.scene.mesh.add_face(
        [QVector3D(10, 0, 0), QVector3D(14, 0, 0),
         QVector3D(14, 4, 0), QVector3D(10, 4, 0)])    # z = 0 too
    floor.attrs["texture"] = {"path": "/tex/madera.png", "sw": 1.0,
                              "sh": 1.0, "rot": 0.0,
                              "uvw": [1, 0, 0, 0, 0, 1, 0, 0]}

    _click(vp, floor, modifiers=Qt.AltModifier)        # sample
    assert PaintTool.current_texture["uvw"]

    _click(vp, wall)                                   # paint another plane
    wtex = wall.attrs["texture"]
    assert wtex["path"] == "/tex/madera.png"
    assert wtex["sw"] == 1.0 and wtex["sh"] == 1.0     # same applied size
    assert "uvw" not in wtex                           # ...its own projection
    _gu, _cu, gv, _cv = face_uv_axes(wtex, wall.normal())
    assert abs(QVector3D.dotProduct(gv, wall.normal())) < 1e-6   # v IN plane

    _click(vp, same_plane)                             # paint the same plane
    assert same_plane.attrs["texture"]["uvw"] == [1, 0, 0, 0, 0, 1, 0, 0]


def test_the_eyedropper_button_arms_one_sample_and_pops_out():
    """The usual panel keeps a pipette beside the material: arm it, the next click
    samples (no Alt needed), and the button releases itself so what you see
    is the state you are in."""
    vp = _FakeViewport()
    released = []

    class _Win:
        def release_eyedropper(self):
            released.append(True)

    vp.window = lambda: _Win()
    src = _quad(vp.scene.mesh)
    src.attrs["color"] = (0.2, 0.4, 0.6)
    target = _quad(vp.scene.mesh, z=3.0)
    target.attrs["color"] = (0.9, 0.9, 0.9)

    PaintTool.sample_armed = True
    _click(vp, src)                                   # no Alt: still samples
    assert PaintTool.current_color == (0.2, 0.4, 0.6)
    assert PaintTool.sample_armed is False            # one shot
    assert released == [True]                         # the button popped out

    _click(vp, target)                                # and now it paints
    assert tuple(target.attrs["color"]) == (0.2, 0.4, 0.6)


def test_the_color_row_recolours_a_plain_colour_material(monkeypatch):
    """Marco, testing 0.5.7: with a colour material active he used the
    Color row of the texture section — it tinted nothing, since tinting
    needs a texture. For a plain colour it now edits the material itself,
    on the loose face and on the group painted whole, in one undo."""
    from PySide6.QtGui import QColor
    from core.history import SetGroupMaterialCommand, SetFaceMaterialTagCommand, CompoundCommand
    from views.main_window import MainWindow
    import views.color_dialog as color_dialog
    import views.tray as T
    w = MainWindow()
    try:
        vp = w.viewport
        scene = vp.scene
        panel = w.findChild(T.MaterialsPanel)
        face = _quad(scene.mesh)
        g = Group(Mesh(), name="Caja")
        _quad(g.mesh, z=5.0)
        scene.groups.append(g)
        panel._apply_color((0.1, 0.4, 0.9), name="Azul")
        paint = PaintTool._current_as_material()
        face.attrs.update(paint)
        mat = PaintTool.current_material
        vp.history.execute(CompoundCommand([
            SetFaceMaterialTagCommand([], mat.name, mat),
            SetGroupMaterialCommand(g, paint)]))
        monkeypatch.setattr(color_dialog.QColorDialog, "getColor",
                            staticmethod(lambda *a, **k: QColor(0, 255, 0)))
        panel._on_pick_tint()                       # choose → applies at once
        assert tuple(face.attrs["color"]) == (0.0, 1.0, 0.0)
        assert tuple(g.material["color"]) == (0.0, 1.0, 0.0)
        assert vp.history.undo()
        assert tuple(g.material["color"]) == pytest.approx((0.1, 0.4, 0.9))
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()
