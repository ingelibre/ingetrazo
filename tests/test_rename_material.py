# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Renaming and recolouring a material of the model.

A colour picked from the library entered the model under its library
name and kept it for good: there was no way to rename it, and editing its
colour left «RAL 7035» on a colour that is not RAL 7035. Now the model's
material can be renamed (on every face and group that wears it, one
undo), and a library colour edited in the model becomes a new material —
the library file itself never changes."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.history import (History, RestampMaterialCommand,        # noqa: E402
                          SetGroupMaterialCommand)
from core.materials import Material, free_name                    # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from tools.paint import PaintTool, rename_recent                  # noqa: E402


def _quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(4, 0, z),
                          QVector3D(4, 4, z), QVector3D(0, 4, z)])


def _painted_scene():
    """«Azul» on a loose face, on a face inside a nested component and on
    a group painted whole; «Rojo» beside it."""
    scene = Scene()
    history = History(scene)
    azul = Material("Azul", color=(0.1, 0.4, 0.9), finish="matte")
    rojo = Material("Rojo", color=(0.9, 0.1, 0.1))
    scene.materials.update({"Azul": azul, "Rojo": rojo})
    loose = _quad(scene.mesh)
    loose.attrs.update(azul.face_attrs())
    red = _quad(scene.mesh, z=1.0)
    red.attrs.update(rojo.face_attrs())
    outer = Group(Mesh(), name="Caja")
    inner = Group(Mesh(), name="Tapa")
    deep = _quad(inner.mesh, z=5.0)
    deep.attrs.update(azul.face_attrs())
    outer.adopt([inner])
    scene.groups.append(outer)
    whole = Group(Mesh(), name="Bloque")
    _quad(whole.mesh, z=7.0)
    scene.groups.append(whole)
    history.execute(SetGroupMaterialCommand(whole, azul.face_attrs()))
    return scene, history, loose, red, deep, whole


def test_renaming_restamps_every_face_and_group_and_undoes():
    scene, history, loose, red, deep, whole = _painted_scene()
    azul = scene.materials["Azul"]
    history.execute(RestampMaterialCommand("Azul", Material(
        "Fachada norte", color=azul.color, finish=azul.finish)))

    assert "Azul" not in scene.materials
    assert scene.materials["Fachada norte"].finish == "matte"
    for attrs in (loose.attrs, deep.attrs, whole.material):
        assert attrs["mat"] == "Fachada norte"
        assert tuple(attrs["color"]) == (0.1, 0.4, 0.9)
    assert red.attrs["mat"] == "Rojo"                 # untouched

    history.undo()
    assert scene.materials["Azul"] is azul
    assert "Fachada norte" not in scene.materials
    for attrs in (loose.attrs, deep.attrs, whole.material):
        assert attrs["mat"] == "Azul"

    history.redo()
    assert set(scene.materials) == {"Fachada norte", "Rojo"}
    assert loose.attrs["mat"] == "Fachada norte"


def test_undo_puts_back_an_entry_the_rename_landed_on():
    """The command itself does not refuse a taken name (the panel does);
    if it ever lands on one, undo must give that entry back intact."""
    scene, history, *_ = _painted_scene()
    rojo = scene.materials["Rojo"]
    history.execute(RestampMaterialCommand(
        "Azul", Material("Rojo", color=(0.5, 0.5, 0.5))))
    history.undo()
    assert scene.materials["Rojo"] is rojo
    assert "Azul" in scene.materials


def test_free_name():
    assert free_name("Muro", {}) == "Muro"
    assert free_name("Muro", {"Muro": 1}) == "Muro (2)"
    assert free_name("Muro", {"Muro", "Muro (2)"}) == "Muro (3)"


def test_recents_follow_the_rename():
    entries = [{"mat": "Azul", "color": [0.1, 0.4, 0.9]},
               {"mat": "Rojo", "color": [0.9, 0.1, 0.1]},
               {"color": [0.3, 0.3, 0.3]}]
    out = rename_recent(entries, "Azul", Material(
        "Fachada", color=(0.2, 0.2, 0.2)).face_attrs())
    assert out[0] == {"mat": "Fachada", "color": [0.2, 0.2, 0.2]}
    assert out[1:] == entries[1:]


# ---- The panel -------------------------------------------------------------

@pytest.fixture
def window():
    from views.main_window import MainWindow
    saved = (PaintTool.recent, PaintTool.current_material,
             PaintTool.current_color, PaintTool.current_texture,
             PaintTool.current_is_default)
    PaintTool.recent = []
    w = MainWindow()
    try:
        yield w
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()
        (PaintTool.recent, PaintTool.current_material,
         PaintTool.current_color, PaintTool.current_texture,
         PaintTool.current_is_default) = saved


def _panel(w):
    import views.tray as T
    return w.findChild(T.MaterialsPanel)


def _paint_loose_face(w, panel, rgb, name):
    """Pick a swatch in the panel and paint one loose face with it."""
    from core.history import SetFaceMaterialTagCommand
    panel._apply_color(rgb, name=name)
    face = _quad(w.viewport.scene.mesh)
    face.attrs.update(PaintTool._current_as_material())
    mat = PaintTool.current_material
    w.viewport.history.execute(SetFaceMaterialTagCommand([], mat.name, mat))
    return face


def test_the_name_field_renames_the_active_material(window):
    panel = _panel(window)
    face = _paint_loose_face(window, panel, (0.1, 0.4, 0.9), "Azul")
    assert panel._name_edit.text() == "Azul"
    panel._name_edit.setText("Fachada norte")
    panel._on_name_edited()
    scene = window.viewport.scene
    assert face.attrs["mat"] == "Fachada norte"
    assert "Azul" not in scene.materials
    assert PaintTool.current_material.name == "Fachada norte"
    assert panel._name_edit.text() == "Fachada norte"
    assert window.viewport.history.undo()
    assert face.attrs["mat"] == "Azul"


def test_the_name_field_refuses_a_name_already_taken(window):
    panel = _panel(window)
    _paint_loose_face(window, panel, (0.9, 0.1, 0.1), "Rojo")
    face = _paint_loose_face(window, panel, (0.1, 0.4, 0.9), "Azul")
    panel._name_edit.setText("Rojo")
    panel._on_name_edited()
    assert face.attrs["mat"] == "Azul"
    assert panel._name_edit.text() == "Azul"          # field put back
    assert window.viewport.scene.materials["Rojo"].color == (0.9, 0.1, 0.1)


def test_naming_a_swatch_not_yet_in_the_model_names_the_next_paint(window):
    panel = _panel(window)
    panel._apply_color((0.3, 0.6, 0.3), name="RAL 6011 Reseda green")
    panel._name_edit.setText("Zócalo")
    panel._on_name_edited()
    assert PaintTool.current_material.name == "Zócalo"
    assert PaintTool.current_color == (0.3, 0.6, 0.3)
    assert "Zócalo" not in window.viewport.scene.materials   # until painted


def test_recolouring_a_library_colour_makes_a_new_material(window,
                                                          monkeypatch):
    """«RAL 7035» in another colour would be a lie: the faces take a new
    material «… (modified)», the library file stays byte for byte."""
    import views.tray as T
    ral = T._RAL_FILE.read_bytes()
    entry = next(c for fam in __import__("json").loads(ral)["families"]
                 for c in fam["colors"] if c["code"] == "RAL 7035")
    name = "%s %s" % (entry["code"], entry["name"])
    panel = _panel(window)
    face = _paint_loose_face(window, panel, tuple(entry["rgb"]), name)
    assert panel._recolour_active((0.2, 0.8, 0.2))
    new = face.attrs["mat"]
    assert new != name and new.startswith(name)
    assert tuple(face.attrs["color"]) == (0.2, 0.8, 0.2)
    scene = window.viewport.scene
    assert name not in scene.materials and new in scene.materials
    assert T._RAL_FILE.read_bytes() == ral
    assert T._ral_rgb(name) == pytest.approx(tuple(entry["rgb"]))
    # A colour of the user's own keeps its name when recoloured.
    own = _paint_loose_face(window, panel, (0.5, 0.5, 0.5), "Muro")
    assert panel._recolour_active((0.6, 0.6, 0.6))
    assert own.attrs["mat"] == "Muro"


def test_rename_from_the_in_model_menu(window, monkeypatch):
    import views.tray as T
    panel = _panel(window)
    face = _paint_loose_face(window, panel, (0.1, 0.4, 0.9), "Azul")
    monkeypatch.setattr(T.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Techo", True)))
    panel._ask_rename("Azul")
    assert face.attrs["mat"] == "Techo"
