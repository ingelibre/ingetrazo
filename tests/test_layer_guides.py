# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Guides live on a layer, like dimensions and texts (#272), and guides
and dimensions have a layer of their own to go to.

A guide had no layer: switching every layer off still left the
scaffolding on screen, in the snap and under the cursor, and nothing could
take it away short of deleting it. Now a guide carries a layer: a hidden
layer takes its guides off the screen, the snap and the pick, a locked one
keeps them visible but out of reach, and the guides drawn while a layer is
active go onto it. Reference images already had a layer but could not be
moved to another one from Entity Info, the right-click or the Layers panel:
they are taggable now too.

With no layer active, a new guide goes onto «Guides», a new dimension onto
«Dimensions» and a new text onto «Texts» (in the interface language:
«Guías», «Cotas», «Textos»), made the first time: the scaffolding and the
annotation are what one switches off all at once. An active layer still
wins.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core import layers as L
from core.guide import Guide
from core.dimension import Dimension
from core.history import (AddDimensionCommand, AddGuideCommand,
                          AddTextLabelCommand, AssignLayerCommand,
                          DeleteLayerCommand, History, MakeGroupCommand)
from core.textlabel import TextLabel
from core.image_plane import ImagePlane
from core.layers import DEFAULT_LAYER, Layer, layer_of
from core.purge import layer_carriers, used_layers
from core.scene import Scene
from core.select_ops import on_layers


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _scene_with(*names):
    scene = Scene()
    scene.layers += [Layer(n) for n in names]
    return scene


# ---- The record -------------------------------------------------------------

@pytest.mark.parametrize("guide", [
    Guide(V(1, 2, 3), V(1, 0, 0), layer="Guías"),
    Guide(V(1, 2, 3), None, V(0, 0, 0), layer="Guías"),
    Guide(V(1, 2, 3), None, layer="Guías"),
])
def test_a_guide_keeps_its_layer_through_the_file(guide):
    back = Guide.from_dict(json.loads(json.dumps(guide.to_dict())))
    assert back.layer == "Guías"
    assert (back.point, back.direction, back.origin) == (
        guide.point, guide.direction, guide.origin)


def test_a_guide_on_layer_0_writes_what_it_always_wrote():
    """Old files read the same and new files without layers stay as they
    were: no ``layer`` key for the default layer."""
    raw = Guide(V(0, 0, 0), V(0, 1, 0)).to_dict()
    assert "layer" not in raw
    assert Guide.from_dict(raw).layer is None
    assert layer_of(Guide.from_dict({"point": [0, 0, 0]})) == DEFAULT_LAYER


def test_igz_keeps_the_layer_of_every_guide(tmp_path):
    from formats import igz
    scene = _scene_with("Guías")
    scene.guides += [Guide(V(0, 0, 0), V(1, 0, 0), layer="Guías"),
                     Guide(V(5, 5, 0))]
    path = tmp_path / "guias.igz"
    igz.save_scene(scene, path)
    other = Scene()
    igz.load_into(other, path)
    assert [g.layer for g in other.guides] == ["Guías", None]


# ---- Visible, locked --------------------------------------------------------

def test_a_hidden_layer_hides_its_guides_and_a_locked_one_freezes_them():
    scene = _scene_with("Guías")
    g = Guide(V(0, 0, 0), V(1, 0, 0), layer="Guías")
    scene.guides.append(g)
    assert scene.entity_visible(g) and scene.entity_selectable(g)
    scene.layer("Guías").locked = True
    assert scene.entity_visible(g) and not scene.entity_selectable(g)
    scene.layer("Guías").locked = False
    scene.layer("Guías").visible = False
    assert not scene.entity_visible(g) and not scene.entity_selectable(g)


def _stub_viewport(scene):
    """Just what ``_shown_guides`` and ``pick_guide`` read: the scene, a
    pick threshold and a top view where world x, y are pixels."""
    from views.viewport import Viewport
    vp = SimpleNamespace(scene=scene, pick_threshold_px=8.0,
                         _clip_segment_front=lambda a, b: (a, b),
                         _world_to_pixel=lambda p: (p.x(), p.y()))
    vp._shown_guides = lambda: Viewport._shown_guides(vp)
    vp.pick_guide = lambda x, y: Viewport.pick_guide(vp, x, y)
    return vp


def test_only_the_guides_of_visible_layers_are_drawn_and_snapped():
    scene = _scene_with("Guías", "Otras")
    on = Guide(V(0, 0, 0), V(1, 0, 0), layer="Otras")
    off = Guide(V(0, 50, 0), V(1, 0, 0), layer="Guías")
    plain = Guide(V(30, 30, 0))
    scene.guides += [on, off, plain]
    vp = _stub_viewport(scene)
    assert vp._shown_guides() == [on, off, plain]
    scene.layer("Guías").visible = False
    assert vp._shown_guides() == [on, plain]
    scene.layer(DEFAULT_LAYER).visible = False
    assert vp._shown_guides() == [on]


def test_a_guide_on_a_hidden_or_locked_layer_is_not_picked():
    """The click, the Eraser and the Tape's «guide from a guide» all go
    through ``pick_guide``: a guide out of sight or locked is not there."""
    scene = _scene_with("Guías")
    g = Guide(V(0, 100, 0), V(1, 0, 0), layer="Guías")
    scene.guides.append(g)
    vp = _stub_viewport(scene)
    assert vp.pick_guide(40.0, 103.0) is g
    scene.layer("Guías").locked = True
    assert vp.pick_guide(40.0, 103.0) is None
    scene.layer("Guías").locked = False
    scene.layer("Guías").visible = False
    assert vp.pick_guide(40.0, 103.0) is None


def test_the_window_snaps_and_draws_only_the_shown_guides():
    """On the real viewport: the snap scene leaves out a guide whose layer
    is off and keeps it again when the layer comes back."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(1200, 800)
        scene = vp.scene
        scene.layers.append(Layer("Guías"))
        p = QVector3D(2.0, 3.0, 0.0)
        scene.guides.append(Guide(p, layer="Guías"))

        def has_point():
            return any((e.a - p).length() < 1e-9 and (e.b - p).length() < 1e-9
                       for e in vp._snap_scene(600, 400).edges)
        assert has_point()
        scene.layer("Guías").visible = False
        assert not has_point()
        scene.layer("Guías").visible = True
        assert has_point()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- Assigning, the active layer --------------------------------------------

def test_guides_and_reference_images_can_be_moved_to_a_layer():
    scene = _scene_with("Guías")
    g = Guide(V(0, 0, 0), V(1, 0, 0))
    im = ImagePlane("plano.png", V(0, 0, 0), V(1, 0, 0), V(0, 1, 0))
    assert L.taggable([g, im, object()]) == [g, im]
    history = History(scene)
    history.execute(AssignLayerCommand([g, im], "Guías"))
    assert layer_of(g) == layer_of(im) == "Guías"
    history.undo()
    assert layer_of(g) == DEFAULT_LAYER
    assert layer_of(im) == "Images"       # back where it was, not Layer 0
    scene.selection = {g}
    assert L.selection_layers(scene) == {DEFAULT_LAYER}


def test_a_guide_drawn_with_a_layer_active_goes_onto_it():
    scene = _scene_with("Guías")
    history = History(scene)
    L.set_active(scene, "Guías")
    history.execute(AddGuideCommand(Guide(V(0, 0, 0), V(0, 1, 0))))
    assert layer_of(scene.guides[-1]) == "Guías"
    history.undo()
    history.redo()
    assert layer_of(scene.guides[-1]) == "Guías"
    L.set_active(scene, DEFAULT_LAYER)
    history.execute(AddGuideCommand(Guide(V(5, 0, 0))))
    assert layer_of(scene.guides[-1]) == "Guides"     # its automatic layer


def test_deleting_and_renaming_a_layer_take_its_guides_along():
    scene = _scene_with("Guías", "Otra")
    g = Guide(V(0, 0, 0), V(1, 0, 0), layer="Guías")
    scene.guides.append(g)
    assert g in list(layer_carriers(scene))
    assert "Guías" in used_layers(scene)
    assert L.rename_layer(scene, "Guías", "Replanteo")
    assert g.layer == "Replanteo"
    history = History(scene)
    history.execute(DeleteLayerCommand("Replanteo", into="Otra"))
    assert g.layer == "Otra"
    history.undo()
    assert g.layer == "Replanteo"
    history.execute(DeleteLayerCommand("Replanteo"))
    assert layer_of(g) == DEFAULT_LAYER


def test_select_content_of_a_layer_takes_its_guides_and_images():
    scene = _scene_with("Guías")
    g = Guide(V(0, 0, 0), V(1, 0, 0), layer="Guías")
    im = ImagePlane("plano.png", V(0, 0, 0), V(1, 0, 0), V(0, 1, 0),
                    layer="Guías")
    other = Guide(V(9, 9, 0))
    scene.guides += [g, other]
    scene.image_planes.append(im)
    assert set(map(id, on_layers(scene, ["Guías"]))) == {id(g), id(im)}
    scene.layer("Guías").locked = True
    assert on_layers(scene, ["Guías"]) == []


def test_entity_info_offers_the_layer_of_a_selected_guide():
    """The Layer field of Entity Info shows for a guide (and an image) and
    moves it, as for any dimension."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        scene.layers.append(Layer("Guías"))
        g = Guide(V(0, 0, 0), V(1, 0, 0))
        scene.guides.append(g)
        scene.selection = {g}
        win._assign_layer("Guías")
        assert g.layer == "Guías"
        win.viewport.history.undo()
        assert layer_of(g) == DEFAULT_LAYER
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- Automatic layers: «Guides» and «Dimensions» ----------------------------

def _dimension(x=0.0):
    return Dimension(V(x, 0, 0), V(x + 2, 0, 0), V(0, -1, 0))


def test_with_no_layer_active_guides_and_dimensions_get_their_own_layers():
    scene = Scene()
    history = History(scene)
    history.execute(AddGuideCommand(Guide(V(0, 0, 0), V(1, 0, 0))))
    history.execute(AddDimensionCommand(_dimension()))
    assert layer_of(scene.guides[-1]) == "Guides"
    assert layer_of(scene.dimensions[-1]) == "Dimensions"
    assert [ly.name for ly in scene.layers] == [
        DEFAULT_LAYER, "Guides", "Dimensions"]
    # Guides never print: their layer is born «not printed», out of the
    # sheets' legend; dimensions print.
    assert not scene.layer("Guides").printable
    assert scene.layer("Dimensions").printable
    assert L.legend_rows(scene)[0] == [DEFAULT_LAYER, "Dimensions"]
    # The next ones join them: no second «Guides».
    history.execute(AddGuideCommand(Guide(V(3, 3, 0))))
    history.execute(AddDimensionCommand(_dimension(5)))
    assert [layer_of(g) for g in scene.guides] == ["Guides"] * 2
    assert [layer_of(d) for d in scene.dimensions] == ["Dimensions"] * 2
    assert len(scene.layers) == 3
    # Switching a layer off takes them all away at once.
    scene.layer("Guides").visible = False
    assert not any(scene.entity_visible(g) for g in scene.guides)


def test_with_no_layer_active_texts_get_their_own_layer():
    scene = Scene()
    history = History(scene)
    for word in ("Sala", "Cocina"):
        history.execute(AddTextLabelCommand(TextLabel(V(0, 0, 0),
                                                      V(0, 0, 1), word)))
    assert [layer_of(t) for t in scene.text_labels] == ["Texts"] * 2
    assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER, "Texts"]


def test_groups_and_loose_lines_stay_on_layer_0():
    scene = Scene()
    history = History(scene)
    f = scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    history.execute(MakeGroupCommand([f], list(scene.mesh.edges)))
    assert layer_of(scene.groups[-1]) == DEFAULT_LAYER
    inside = scene.groups[-1].mesh.edges
    assert all(layer_of(e) == DEFAULT_LAYER for e in inside)
    assert [ly.name for ly in scene.layers] == [DEFAULT_LAYER]


def test_the_active_layer_wins_over_the_automatic_ones():
    scene = _scene_with("Planta")
    history = History(scene)
    L.set_active(scene, "Planta")
    history.execute(AddGuideCommand(Guide(V(0, 0, 0))))
    history.execute(AddDimensionCommand(_dimension()))
    assert layer_of(scene.guides[-1]) == "Planta"
    assert layer_of(scene.dimensions[-1]) == "Planta"
    assert scene.layer("Guides") is None and scene.layer("Dimensions") is None


@pytest.mark.parametrize("hidden, locked", [(True, False), (False, True)])
def test_a_hidden_or_locked_automatic_layer_leaves_new_ones_on_layer_0(
        hidden, locked):
    """Nothing new is drawn straight into hiding: with «Guides» off, the
    guide just drawn stays in sight on Layer 0."""
    scene = Scene()
    scene.layers.append(Layer("Guides", visible=not hidden, locked=locked))
    history = History(scene)
    history.execute(AddGuideCommand(Guide(V(0, 0, 0))))
    assert layer_of(scene.guides[-1]) == DEFAULT_LAYER
    assert scene.entity_visible(scene.guides[-1])


def test_a_guide_or_dimension_that_has_a_layer_keeps_it():
    scene = _scene_with("Mía")
    history = History(scene)
    history.execute(AddGuideCommand(Guide(V(0, 0, 0), layer="Mía")))
    d = _dimension()
    d.layer = "Mía"
    history.execute(AddDimensionCommand(d))
    assert layer_of(scene.guides[-1]) == layer_of(d) == "Mía"
    assert scene.layer("Guides") is None and scene.layer("Dimensions") is None


def test_undo_and_redo_keep_the_automatic_layer():
    scene = Scene()
    history = History(scene)
    history.execute(AddGuideCommand(Guide(V(0, 0, 0))))
    g = scene.guides[-1]
    history.undo()
    assert g not in scene.guides
    history.redo()
    assert scene.guides[-1] is g and layer_of(g) == "Guides"
    assert [ly.name for ly in scene.layers].count("Guides") == 1


def test_the_automatic_layers_take_the_interface_language():
    from core.i18n import current_language, set_language
    before = current_language()
    set_language("es")
    try:
        scene = Scene()
        history = History(scene)
        history.execute(AddGuideCommand(Guide(V(0, 0, 0))))
        history.execute(AddDimensionCommand(_dimension()))
        history.execute(AddTextLabelCommand(TextLabel(V(0, 0, 0),
                                                      V(0, 0, 1), "Sala")))
        assert layer_of(scene.guides[-1]) == "Guías"
        assert layer_of(scene.dimensions[-1]) == "Dimensiones"
        assert layer_of(scene.text_labels[-1]) == "Textos"
    finally:
        set_language(before)
