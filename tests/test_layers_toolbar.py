# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Layers toolbar: the layer drop-down and the quick layer actions."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core import layers as L
from core.group import Group
from core.layers import DEFAULT_LAYER, Layer, layer_of
from core.mesh import Mesh
from core.scene import Scene


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _doc(win):
    scene = win.viewport.scene
    scene.layers += [Layer("A"), Layer("B")]
    ga = Group(Mesh(), name="ga")
    ga.layer = "A"
    gb = Group(Mesh(), name="gb")
    gb.layer = "B"
    scene.groups += [ga, gb]
    win.viewport.notify_scene_changed()
    return scene, ga, gb


def _pick(combo, name):
    i = combo.findText(name)
    combo.setCurrentIndex(i)
    combo.activated.emit(i)


def test_the_toolbar_holds_the_drop_down_and_the_actions(win):
    tb = win.toolbars["layers"]
    bar = win.layers_toolbar
    assert tb.objectName() == "layers" and not tb.isHidden()
    assert bar.combo in [tb.widgetForAction(a) for a in tb.actions()]
    keys = ["panel"] + [b[0] for b in bar.BUTTONS if b is not None]
    assert list(bar.actions) == keys
    for act in bar.actions.values():
        assert not act.icon().isNull() and act.text()


def test_the_list_drops_down_under_the_box(win):
    from PySide6.QtCore import QPoint
    scene, _, _ = _doc(win)
    combo = win.layers_toolbar.combo
    L.set_active(scene, "B")                         # current row not first
    combo.refresh()
    combo.showPopup()
    _app.processEvents()
    try:
        popup = combo.view().window()
        under = combo.mapToGlobal(QPoint(0, combo.height())).y()
        screen = combo.screen().availableGeometry()
        if under + popup.height() <= screen.bottom():
            assert popup.geometry().top() == under
    finally:
        combo.hidePopup()


def test_the_drop_down_shows_the_selection_or_the_active_layer(win):
    scene, ga, gb = _doc(win)
    combo = win.layers_toolbar.combo
    combo.refresh()
    assert combo.currentText() == DEFAULT_LAYER
    L.set_active(scene, "B")
    combo.refresh()
    assert combo.currentText() == "B"                # nothing selected
    scene.select([ga])
    combo.refresh()
    assert combo.currentText() == "A"                # the selection's
    scene.select([ga, gb])
    combo.refresh()
    assert combo.currentIndex() == -1                # several layers


def test_picking_a_layer_with_a_selection_moves_it_and_undoes(win):
    scene, ga, gb = _doc(win)
    combo = win.layers_toolbar.combo
    L.set_active(scene, "A")
    scene.select([ga, gb])
    combo.refresh()
    _pick(combo, "B")
    assert layer_of(ga) == layer_of(gb) == "B"
    assert L.active_layer(scene) == "A"              # the active stays
    win._on_undo()
    assert layer_of(ga) == "A" and layer_of(gb) == "B"


def test_picking_with_nothing_selected_sets_the_working_layer(win):
    from PySide6.QtGui import QVector3D as V
    from core.history import MakeGroupCommand
    scene, ga, gb = _doc(win)
    scene.clear_selection()
    combo = win.layers_toolbar.combo
    combo.refresh()
    _pick(combo, "A")
    assert L.active_layer(scene) == "A"
    assert (layer_of(ga), layer_of(gb)) == ("A", "B")
    assert not win.viewport.history.undo_stack
    f = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    win.viewport.history.execute(MakeGroupCommand([f], list(scene.mesh.edges)))
    assert layer_of(scene.groups[-1]) == "A"


def test_the_rows_eye_and_padlock_toggle_in_place(win):
    scene, _ga, _gb = _doc(win)
    combo = win.layers_toolbar.combo
    combo.toggle("A", "eye")
    assert not scene.layer("A").visible
    combo.toggle("A", "lock")
    assert scene.layer("A").locked
    combo.toggle("A", "eye")
    assert scene.layer("A").visible


def test_the_buttons_two_groups_then_hide_show_all_previous_together(win):
    assert list(win.layers_toolbar.actions) == [
        "panel", "make_active", "isolate", "lock", "to_active",
        "hide", "show_all", "previous"]
    tb = win.toolbars["layers"]
    acts = tb.actions()
    mine = win.layers_toolbar.actions
    to_active = acts.index(mine["to_active"])
    assert acts[to_active + 1].isSeparator()
    hide = acts.index(mine["hide"])
    assert acts[hide:hide + 3] == [mine["hide"], mine["show_all"],
                                   mine["previous"]]


def test_buttons_act_on_the_selections_layer(win):
    scene, ga, gb = _doc(win)
    bar = win.layers_toolbar
    scene.select([ga])
    bar.run("make_active")
    assert L.active_layer(scene) == "A"
    bar.run("isolate")
    assert [ly.visible for ly in scene.layers] == [True, True, False]
    bar.run("show_all")
    assert all(ly.visible for ly in scene.layers)
    scene.select([gb])
    bar.run("hide")
    assert not scene.layer("B").visible
    scene.select([ga])
    bar.run("lock")
    assert scene.layer("A").locked
    assert L.active_layer(scene) == DEFAULT_LAYER     # A locked: released


def test_make_active_refuses_a_selection_on_several_layers(win):
    scene, ga, gb = _doc(win)
    scene.select([ga, gb])
    win.layers_toolbar.run("make_active")
    assert L.active_layer(scene) == DEFAULT_LAYER
    assert "several layers" in win.statusBar().currentMessage()


def test_the_rows_target_isolates_and_a_second_click_brings_all_back(win):
    scene, _ga, _gb = _doc(win)
    combo = win.layers_toolbar.combo
    combo.toggle("A", "isolate")
    assert [ly.visible for ly in scene.layers] == [True, True, False]
    assert L.is_isolated(scene, "A") and not L.is_isolated(scene, "B")
    combo.toggle("B", "isolate")                    # another one: swaps
    assert [ly.visible for ly in scene.layers] == [True, False, True]
    combo.toggle("B", "isolate")                    # the isolated one: all
    assert all(ly.visible for ly in scene.layers)
    win.layers_toolbar.run("show_all")
    assert all(ly.visible for ly in scene.layers)


def test_is_isolated_reads_the_default_layer_as_always_on():
    scene = Scene()
    assert not L.is_isolated(scene, DEFAULT_LAYER)
    scene.layers.append(Layer("Solo"))
    assert not L.is_isolated(scene, "Solo")         # nothing else to hide
    scene.layers.append(Layer("Otra", visible=False))
    assert L.is_isolated(scene, "Solo")
    scene.layer("Solo").visible = False
    assert not L.is_isolated(scene, "Solo")


def test_buttons_that_need_a_selection_say_so(win):
    scene, _ga, _gb = _doc(win)
    scene.clear_selection()
    for key in ("make_active", "isolate", "hide", "lock", "to_active"):
        win.statusBar().clearMessage()
        win.layers_toolbar.run(key)
        assert "Select something" in win.statusBar().currentMessage()
    assert all(ly.visible and not ly.locked for ly in scene.layers)


def test_move_to_the_active_layer_is_one_undo_step(win):
    scene, ga, gb = _doc(win)
    L.set_active(scene, "B")
    scene.select([ga])
    win.layers_toolbar.run("to_active")
    assert layer_of(ga) == "B"
    win._on_undo()
    assert layer_of(ga) == "A"


def test_previous_state_walks_back_through_the_changes(win):
    scene, ga, _gb = _doc(win)
    bar = win.layers_toolbar
    panel = win.layers_dock.panel
    scene.select([ga])
    bar.combo.toggle("A", "isolate")         # 1: B hidden
    bar.combo.toggle("A", "lock")            # 2: A locked (from the list)
    bar.run("previous")
    assert not scene.layer("A").locked and not scene.layer("B").visible
    bar.run("previous")
    assert all(ly.visible and not ly.locked for ly in scene.layers)
    assert panel.previous_state() is False   # nothing earlier


def _holds(panel):
    from views.layers_panel import ROLE_HOLDS
    return sorted(panel._key(it)[1] for it in panel._all_items()
                  if it.data(0, ROLE_HOLDS))


def test_the_panel_marks_the_selections_layer_and_not_the_active(win):
    scene, ga, gb = _doc(win)
    panel = win.layers_dock.panel
    L.set_active(scene, "B")
    scene.select([ga])
    win.viewport.notify_scene_changed()
    assert _holds(panel) == ["A"]
    assert L.active_layer(scene) == "B"               # untouched
    scene.select([ga, gb])
    win.viewport.notify_scene_changed()
    assert _holds(panel) == ["A", "B"]                # several: all of them
    scene.clear_selection()
    win.viewport.notify_scene_changed()
    assert _holds(panel) == []


def test_a_folded_folder_carries_the_mark(win):
    scene, ga, _gb = _doc(win)
    panel = win.layers_dock.panel
    L.move_to_folder(scene, ["A"], "Arq")
    scene.select([ga])
    win.viewport.notify_scene_changed()
    folder = panel.item_for("Arq", "folder")
    assert _holds(panel) == ["A"]                     # open: the layer
    folder.setExpanded(False)
    assert _holds(panel) == ["A", "Arq"]              # folded: the folder too
    folder.setExpanded(True)
    assert _holds(panel) == ["A"]


def test_the_drop_down_knows_the_selections_layers(win):
    scene, ga, gb = _doc(win)
    combo = win.layers_toolbar.combo
    scene.select([gb])
    combo.refresh()
    assert combo.selection_layers == {"B"}
    assert combo.currentText() == "B"                 # the box: its layer
    scene.clear_selection()
    combo.refresh()
    assert combo.selection_layers == set()


@pytest.mark.parametrize("seed", range(10))
def test_selection_layers_matches_random_selections(seed):
    from PySide6.QtGui import QVector3D as V
    rng = random.Random(seed)
    scene = Scene()
    names = [f"L{i}" for i in range(4)]
    scene.layers += [Layer(n) for n in names]
    ents = []
    for i in range(8):
        g = Group(Mesh(), name=f"g{i}")
        g.layer = rng.choice(names + [None])
        scene.groups.append(g)
        ents.append(g)
    f = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    ents.append(f)
    pick = rng.sample(ents, rng.randint(0, len(ents)))
    scene.select(pick)
    assert L.selection_layers(scene) == {layer_of(e) for e in pick}


@pytest.mark.parametrize("seed", range(15))
def test_layer_state_round_trips(seed):
    rng = random.Random(seed)
    scene = Scene()
    scene.layers += [Layer(f"L{i}") for i in range(rng.randint(1, 6))]
    names = [ly.name for ly in scene.layers]
    for ly in scene.layers:
        ly.visible, ly.locked = rng.random() < 0.7, rng.random() < 0.3
    L.set_active(scene, rng.choice(names[1:]))
    saved = L.layer_state(scene)
    before = [(ly.name, ly.visible, ly.locked) for ly in scene.layers]
    active = scene.active_layer
    for ly in scene.layers:
        ly.visible, ly.locked = rng.random() < 0.5, rng.random() < 0.5
    scene.active_layer = None
    L.apply_layer_state(scene, saved)
    assert [(ly.name, ly.visible, ly.locked) for ly in scene.layers] == before
    assert scene.active_layer == active


def test_layer_state_skips_layers_made_or_deleted_since():
    scene = Scene()
    scene.layers += [Layer("A", visible=False), Layer("B")]
    L.set_active(scene, "B")
    saved = L.layer_state(scene)
    scene.layers.remove(scene.layer("B"))
    scene.layers.append(Layer("C", visible=False))
    scene.layer("A").visible = True
    L.apply_layer_state(scene, saved)
    assert not scene.layer("A").visible
    assert not scene.layer("C").visible               # untouched
    assert scene.active_layer is None                  # B is gone
