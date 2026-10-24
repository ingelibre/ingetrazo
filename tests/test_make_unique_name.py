# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Names after Make Unique and Make Component (#620, @ibsgroupdubai-netizen):
«make an instance unique — name of new component not unique», and the
«Component #n» a new component is offered counted the copies, not the
names, so it skipped numbers and could repeat one."""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, copy_group
from core.history import History, MakeUniqueCommand
from core.kept_components import (make_template, names_in_use,
                                  numbered_name)
from core.mesh import Mesh
from core.scene import Scene


def _quad(size=1.0, z=0.0):
    m = Mesh()
    m.add_face([V(0, 0, z), V(size, 0, z), V(size, size, z), V(0, size, z)])
    return m


def _component(name, size=1.0):
    g = Group(_quad(size), name=name)
    g.xform = QMatrix4x4()
    return g


# --- the numbering ------------------------------------------------------------

def test_a_plain_name_takes_number_two():
    assert numbered_name("Silla", {"Silla"}) == "Silla #2"


def test_a_numbered_name_counts_on_and_skips_the_taken():
    assert numbered_name("Puerta #3", {"Puerta #3"}) == "Puerta #4"
    assert numbered_name("Silla", {"Silla", "Silla #2", "Silla #3"}) \
        == "Silla #4"


def test_names_in_use_reach_nested_groups_and_kept_templates():
    scene = Scene()
    silla = _component("Silla")
    muro = Group(_quad(3.0), name="Muro")
    muro.children = [_component("Varilla")]
    scene.groups.extend([silla, muro])
    scene.kept_components = [make_template(_component("Mesa"))]
    assert names_in_use(scene) == {"Silla", "Muro", "Varilla", "Mesa"}
    assert "Silla" not in names_in_use(scene, skip=silla)


# --- Make Unique --------------------------------------------------------------

def test_make_unique_gives_the_copy_a_name_of_its_own():
    scene = Scene()
    silla = _component("Silla")
    otra = copy_group(silla, V(5, 0, 0))
    scene.groups.extend([silla, otra])
    history = History(scene)
    history.execute(MakeUniqueCommand(otra, rename=True))
    assert otra.name == "Silla #2" and silla.name == "Silla"
    assert otra.mesh is not silla.mesh
    history.undo()
    assert otra.name == "Silla" and otra.mesh is silla.mesh
    history.redo()
    assert otra.name == "Silla #2"


def test_two_copies_made_unique_one_after_the_other_differ():
    scene = Scene()
    silla = _component("Silla")
    b = copy_group(silla, V(5, 0, 0))
    c = copy_group(silla, V(10, 0, 0))
    scene.groups.extend([silla, b, c])
    history = History(scene)
    history.execute(MakeUniqueCommand(b, rename=True))
    history.execute(MakeUniqueCommand(c, rename=True))
    assert {silla.name, b.name, c.name} == {"Silla", "Silla #2", "Silla #3"}


def test_the_last_copy_keeps_its_name_when_nothing_else_wears_it():
    scene = Scene()
    sola = _component("Banco")
    scene.groups.append(sola)
    History(scene).execute(MakeUniqueCommand(sola, rename=True))
    assert sola.name == "Banco"


def test_a_kept_definition_counts_as_wearing_the_name():
    scene = Scene()
    sola = _component("Banco")
    scene.groups.append(sola)
    scene.kept_components = [make_template(sola)]
    History(scene).execute(MakeUniqueCommand(sola, rename=True))
    assert sola.name == "Banco #2"


def test_make_unique_with_subgroups_also_renames_and_keeps_them():
    scene = Scene()
    caja = _component("Caja", 2.0)
    caja.children = [_component("Tapa")]
    otra = copy_group(caja, V(5, 0, 0))
    scene.groups.extend([caja, otra])
    History(scene).execute(MakeUniqueCommand(otra, rename=True))
    assert otra.name == "Caja #2"
    assert [c.name for c in otra.children] == ["Tapa"]


def test_without_rename_the_name_stays():
    """Opening a copied group makes it unique on the way in: no rename."""
    scene = Scene()
    silla = _component("Silla")
    otra = copy_group(silla, V(5, 0, 0))
    scene.groups.extend([silla, otra])
    History(scene).execute(MakeUniqueCommand(otra))
    assert otra.name == "Silla"


# --- the window's commands ----------------------------------------------------

def test_the_menu_make_unique_renames(monkeypatch):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        silla = _component("Silla")
        otra = copy_group(silla, V(5, 0, 0))
        scene.groups.extend([silla, otra])
        scene.selection.clear()
        scene.selection.add(otra)
        win._on_make_unique()
        assert otra.name == "Silla #2"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_offered_component_name_is_the_first_free_number(monkeypatch):
    from core.i18n import tr
    from views import prompts
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        uno = _component(tr("Component #{n}", n=1))
        # three copies of #1 used to offer «#4»; #2 is free
        scene.groups.extend([uno, copy_group(uno, V(3, 0, 0)),
                             copy_group(uno, V(6, 0, 0)),
                             _component(tr("Component #{n}", n=3))])
        scene.mesh.add_face([V(20, 0, 0), V(21, 0, 0), V(21, 1, 0),
                             V(20, 1, 0)])
        scene.selection.clear()
        scene.selection.update(scene.mesh.faces)
        offered = {}

        def ask(_parent, _title, _label, text="", **_k):
            offered["text"] = text
            return "", False                      # cancel: nothing made
        monkeypatch.setattr(prompts, "get_text", ask)
        win._on_make_component()
        assert offered["text"] == tr("Component #{n}", n=2)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
