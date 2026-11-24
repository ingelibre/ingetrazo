# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A component's definition name, apart from each copy's own (#199).

A furniture maker names every piece of a cabinet so the workshop can label
it: ten copies of «Puerta» share the definition, and each copy may be
«Puerta izquierda», «Puerta derecha»… A group had one ``name``; the
definition's was whatever its first copy was called, so naming one copy
renamed the component in the Components panel, and the .skp import
dropped the definition's name when the copy had one."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402

from core.group import (Group, copy_group, definition_name,  # noqa: E402
                        has_own_name)
from core.history import (History, MakeUniqueCommand,  # noqa: E402
                          RenameDefinitionCommand, RenameGroupCommand,
                          ReplaceComponentCommand)
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402


def _quad(size=1.0):
    m = Mesh()
    m.add_face([V(0, 0, 0), V(size, 0, 0), V(size, size, 0), V(0, size, 0)])
    return m


def _doors(n=3):
    """``n`` copies of one «Puerta» component, side by side."""
    scene = Scene()
    first = Group(_quad(), name="Puerta")
    first.xform = QMatrix4x4()
    doors = [first] + [copy_group(first, V(2 * i, 0, 0))
                       for i in range(1, n)]
    scene.groups.extend(doors)
    return scene, History(scene), doors


# --- the model ---------------------------------------------------------------

def test_a_copy_without_a_definition_reads_its_own_name():
    g = Group(_quad(), name="Silla")
    assert definition_name(g) == "Silla" and not has_own_name(g)


def test_naming_one_copy_keeps_the_definition_for_all():
    """The bug: the copy's name WAS the definition's, so naming one copy
    «Puerta izquierda» left the definition with no name of its own."""
    scene, hist, doors = _doors()
    hist.execute(RenameGroupCommand(doors[0], "Puerta izquierda"))
    assert doors[0].name == "Puerta izquierda"
    assert [definition_name(d) for d in doors] == ["Puerta"] * 3
    assert has_own_name(doors[0]) and not has_own_name(doors[1])
    hist.undo()
    assert doors[0].name == "Puerta"
    assert all(d.definition is None for d in doors)
    hist.redo()
    assert definition_name(doors[0]) == "Puerta"


def test_renaming_the_definition_keeps_the_copies_named_on_their_own():
    scene, hist, doors = _doors()
    hist.execute(RenameGroupCommand(doors[0], "Puerta izquierda"))
    hist.execute(RenameDefinitionCommand(doors, "Puerta roble"))
    assert [definition_name(d) for d in doors] == ["Puerta roble"] * 3
    assert [d.name for d in doors] == ["Puerta izquierda", "Puerta roble",
                                       "Puerta roble"]
    hist.undo()
    assert [d.name for d in doors] == ["Puerta izquierda", "Puerta",
                                       "Puerta"]
    assert [definition_name(d) for d in doors] == ["Puerta"] * 3


def test_a_copy_carries_the_definition_name():
    scene, hist, doors = _doors(1)
    hist.execute(RenameGroupCommand(doors[0], "Puerta izquierda"))
    other = copy_group(doors[0], V(5, 0, 0))
    assert other.definition == "Puerta" and other.name == "Puerta izquierda"


def test_make_unique_gives_a_definition_of_its_own():
    scene, hist, doors = _doors()
    hist.execute(RenameGroupCommand(doors[2], "Puerta derecha"))
    hist.execute(MakeUniqueCommand(doors[1], rename=True))
    assert definition_name(doors[1]) == "Puerta #2"
    assert doors[1].name == "Puerta #2"         # it only wore the old name
    hist.execute(MakeUniqueCommand(doors[2], rename=True))
    assert definition_name(doors[2]) == "Puerta #3"
    assert doors[2].name == "Puerta derecha"    # its own name stays
    hist.undo()
    hist.undo()
    assert [definition_name(d) for d in doors] == ["Puerta"] * 3
    assert doors[1].name == "Puerta"


def test_replace_keeps_a_copys_own_name():
    scene, hist, doors = _doors(2)
    hist.execute(RenameGroupCommand(doors[0], "Puerta izquierda"))
    mesa = Group(_quad(3.0), name="Mesa")
    mesa.xform = QMatrix4x4()
    scene.groups.append(mesa)
    hist.execute(ReplaceComponentCommand(doors, mesa))
    assert [d.name for d in doors] == ["Puerta izquierda", "Mesa"]
    assert [definition_name(d) for d in doors] == ["Mesa", "Mesa"]
    hist.undo()
    assert [definition_name(d) for d in doors] == ["Puerta", "Puerta"]


# --- the file ----------------------------------------------------------------

def test_both_names_survive_the_igz(tmp_path):
    from formats import igz
    scene, hist, doors = _doors()
    hist.execute(RenameGroupCommand(doors[0], "Puerta izquierda"))
    hist.execute(RenameGroupCommand(doors[1], "Puerta derecha"))
    path = tmp_path / "puertas.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert sorted(g.name for g in back.groups) == [
        "Puerta", "Puerta derecha", "Puerta izquierda"]
    assert {definition_name(g) for g in back.groups} == {"Puerta"}
    assert len({id(g.mesh) for g in back.groups}) == 1


def test_a_document_without_definitions_opens_as_before(tmp_path):
    from formats import igz
    scene, _hist, doors = _doors(2)
    path = tmp_path / "antiguo.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert all(g.definition is None for g in back.groups)
    assert {definition_name(g) for g in back.groups} == {"Puerta"}


def test_skp_import_keeps_the_definition_and_each_copys_name():
    from formats import skp as skp_format
    sq = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    xf = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    proto = {"name": "closet_porta", "faces": [(sq, [], {})],
             "soft_edges": [], "instances": [list(xf), list(xf)],
             "instance_names": ["porta_esquerda", None]}
    scene = Scene()
    skp_format.apply_payload(scene, {"groups": [], "protos": [proto]})
    assert sorted(g.name for g in scene.groups) == ["closet_porta",
                                                    "porta_esquerda"]
    assert {definition_name(g) for g in scene.groups} == {"closet_porta"}


# --- the window --------------------------------------------------------------

def test_entity_info_and_components_panel_show_both_names():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        first = Group(_quad(), name="Puerta")
        first.xform = QMatrix4x4()
        second = copy_group(first, V(3, 0, 0))
        scene.groups.extend([first, second])
        scene.selection = {first}
        info = win.tray.entity_info
        info.refresh()
        assert not info._def_page.isHidden()
        assert info._def_edit.text() == "Puerta"
        # The copy's own name, through the panel.
        info._name_edit.setText("Puerta izquierda")
        info._on_name_edited()
        assert first.name == "Puerta izquierda"
        assert definition_name(second) == "Puerta"
        rows = win.tray.components._components_in_model()
        assert [r[0] for r in rows] == ["Puerta"]
        # The definition, through the panel: the other copy follows.
        info._def_edit.setText("Puerta roble")
        info._on_definition_edited()
        assert second.name == "Puerta roble"
        assert first.name == "Puerta izquierda"
        assert definition_name(first) == "Puerta roble"
        # A plain group shows only its name.
        plain = Group(_quad(), name="Mesa")
        scene.groups.append(plain)
        scene.selection = {plain}
        info.refresh()
        assert info._def_page.isHidden()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_browser_shows_the_definition_after_a_copys_own_name():
    """Reported in the manual test: a door named «roble» in Entity Info
    read «roble» alone in the Browser — nothing said it is a «Puerta».
    The cell reads «roble ‹Puerta›»; editing it edits «roble» alone."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QTreeWidgetItemIterator
    from views.main_window import MainWindow
    from views.outliner import COL_NAME
    win = MainWindow()
    try:
        scene = win.viewport.scene
        first = Group(_quad(), name="Puerta")
        first.xform = QMatrix4x4()
        second = copy_group(first, V(3, 0, 0))
        scene.groups[:] = [first, second]
        win.viewport.history.execute(RenameGroupCommand(first, "roble"))
        panel = win.project_browser.outliner
        panel.refresh()

        def row(group):
            it = QTreeWidgetItemIterator(panel.tree)
            while it.value():
                if it.value().data(COL_NAME, Qt.UserRole) is group:
                    return it.value()
                it += 1
            raise AssertionError("no row")

        assert row(first).text(COL_NAME) == "roble ‹Puerta›"
        assert row(second).text(COL_NAME) == "Puerta"
        # The editor gets the copy's own name, not the decoration.
        item = row(first)
        index = panel.tree.indexFromItem(item, COL_NAME)
        editor = QLineEdit()
        panel.tree.itemDelegateForColumn(COL_NAME).setEditorData(editor,
                                                                 index)
        assert editor.text() == "roble"
        # Confirming it unchanged renames nothing and keeps the label.
        before = len(win.viewport.history._undo) \
            if hasattr(win.viewport.history, "_undo") else None
        item.setText(COL_NAME, "roble")
        assert first.name == "roble"
        assert row(first).text(COL_NAME) == "roble ‹Puerta›"
        if before is not None:
            assert len(win.viewport.history._undo) == before
        # Renamed in the cell: the new name, still of «Puerta».
        row(first).setText(COL_NAME, "roble claro")
        assert first.name == "roble claro"
        assert definition_name(first) == "Puerta"
        assert row(first).text(COL_NAME) == "roble claro ‹Puerta›"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
