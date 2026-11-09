# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser's «Material ▸» menu (#565, @fafecm): paint several rows with
any material of the document, or a recent paint, without going to the
Materials tab — colours and textures alike, one undo step."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core import outliner
from core.group import Group
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene


def _quad(x=0.0):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return m


TEX = {"path": "C:/no/such/ladrillo.png", "sw": 0.5, "sh": 0.25}


# --- the list ----------------------------------------------------------------

def test_the_documents_materials_come_first_by_name():
    scene = Scene()
    scene.materials = {
        "ladrillo": Material("ladrillo", texture=dict(TEX)),
        "Acero": Material("Acero", color=(0.5, 0.5, 0.55)),
        "Vidrio": Material("Vidrio", color=(0.7, 0.9, 1.0), opacity=0.3),
    }
    choices = outliner.material_choices(scene)
    assert [label for label, _p in choices] == ["Acero", "ladrillo", "Vidrio"]
    paints = dict(choices)
    assert paints["ladrillo"]["texture"] == TEX
    assert "color" not in paints["ladrillo"]
    assert paints["Vidrio"]["opacity"] == 0.3
    assert paints["Acero"]["mat"] == "Acero"


def test_recent_paints_follow_without_repeating_a_material():
    scene = Scene()
    scene.materials = {"Acero": Material("Acero", color=(0.5, 0.5, 0.55))}
    recent = [{"color": [0.5, 0.5, 0.55], "mat": "Acero"},   # listed already
              {"color": [1.0, 0.0, 0.0]},
              {"texture": {"path": "D:/tex/madera.jpg", "sw": 1, "sh": 1}},
              {"color": [1.0, 0.0, 0.0]}]                    # twice
    labels = [label for label, _p in outliner.material_choices(scene, recent)]
    assert labels == ["Acero", "#FF0000", "madera.jpg"]


def test_nothing_to_offer_is_an_empty_list():
    assert outliner.material_choices(Scene(), []) == []


# --- painting from the Browser -----------------------------------------------

def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.viewport.scene.groups.clear()
    win.viewport.scene.version += 1
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_several_rows_take_a_texture_in_one_undo_step():
    win = _window()
    try:
        scene = win.viewport.scene
        a, b = Group(_quad(), name="A"), Group(_quad(3.0), name="B")
        scene.groups.extend([a, b])
        scene.materials["ladrillo"] = Material("ladrillo", texture=dict(TEX))
        panel = win.project_browser.outliner
        paint = dict(outliner.material_choices(scene))["ladrillo"]
        steps = len(win.viewport.history.undo_stack)
        panel.paint_groups([a, b], material=paint)
        assert a.material["texture"] == TEX and b.material["texture"] == TEX
        assert a.material["mat"] == "ladrillo"
        assert len(win.viewport.history.undo_stack) == steps + 1
        win.viewport.history.undo()
        assert a.material is None and b.material is None
    finally:
        _close(win)


def test_a_named_recent_paint_is_registered_with_the_step():
    win = _window()
    try:
        scene = win.viewport.scene
        a = Group(_quad(), name="A")
        scene.groups.append(a)
        scene.materials.pop("Pino", None)
        panel = win.project_browser.outliner
        panel.paint_groups([a], material={"color": [0.8, 0.6, 0.3],
                                          "mat": "Pino"})
        assert "Pino" in scene.materials
        assert scene.materials["Pino"].color == (0.8, 0.6, 0.3)
        win.viewport.history.undo()
        assert "Pino" not in scene.materials and a.material is None
    finally:
        _close(win)


def test_the_row_menu_offers_the_materials():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from core.i18n import tr
    win = _window()
    try:
        scene = win.viewport.scene
        a = Group(_quad(), name="A")
        scene.groups.append(a)
        scene.materials["Acero"] = Material("Acero", color=(0.5, 0.5, 0.55))
        panel = win.project_browser.outliner
        panel.refresh()
        item = panel.tree.topLevelItem(0).child(0)
        panel.tree.setCurrentItem(item)
        found = {}

        def read():
            menu = QApplication.activePopupWidget()
            if menu is None:
                QTimer.singleShot(10, read)
                return
            for act in menu.actions():
                if act.text() == tr("Material"):
                    sub = act.menu()
                    found["items"] = [x.text() for x in sub.actions()]
            menu.close()
        QTimer.singleShot(0, read)
        panel._on_context_menu(panel.tree.visualItemRect(item).center())
        assert "Acero" in found["items"]
    finally:
        _close(win)
