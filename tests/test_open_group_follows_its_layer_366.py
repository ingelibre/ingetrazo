# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What has no layer inside a group follows the group's layer (#366,
@joejivaros: hide «Layer 0» and the group on «Rez» can no longer be
edited; @mrmonkington: what you draw inside a group lands on the default
layer).

Closed, a group's layer already decides for everything in it. Open, its
geometry is drawn and picked as loose geometry, so its faces without a
layer answered to «Layer 0»: hiding it emptied the open group. Decision of
Marco (21-10): the untagged contents follow the group, as in SketchUp."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.history import MakeGroupCommand, History
from core.layers import Layer
from core.scene import Scene


def _scene():
    scene = Scene()
    m = scene.mesh
    m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    tagged = m.add_face([V(0, 0, 1), V(2, 0, 1), V(2, 2, 1), V(0, 2, 1)])
    tagged.attrs["layer"] = "Muebles"
    History(scene).execute(MakeGroupCommand(list(m.faces), list(m.edges)))
    group = scene.groups[0]
    group.layer = "Planta"
    for name in ("Planta", "Muebles"):
        if scene.layer(name) is None:
            scene.layers.append(Layer(name))
    loose = scene.mesh.add_face([V(5, 0, 0), V(6, 0, 0), V(6, 1, 0),
                                 V(5, 1, 0)])
    return scene, group, loose


def _faces(scene, layer):
    return [f for f in scene.mesh.faces if f.attrs.get("layer") == layer]


def test_hiding_layer_0_leaves_the_open_group_on_its_layer():
    scene, group, loose = _scene()
    scene.layer("Layer 0").visible = False
    assert not scene.entity_visible(loose)          # loose: Layer 0 rules
    scene.begin_group_edit(group)
    untagged = _faces(scene, None)
    assert untagged and all(scene.entity_visible(f) for f in untagged)
    assert all(scene.entity_selectable(f) for f in untagged)
    assert all(scene.entity_visible(e) for e in scene.mesh.edges)


def test_hiding_the_group_layer_hides_its_untagged_contents_too():
    scene, group, _ = _scene()
    scene.begin_group_edit(group)
    scene.layer("Planta").visible = False
    assert not any(scene.entity_visible(f) for f in _faces(scene, None))


def test_a_face_with_its_own_layer_still_answers_to_it():
    scene, group, _ = _scene()
    scene.begin_group_edit(group)
    scene.layer("Muebles").visible = False
    assert not any(scene.entity_visible(f) for f in _faces(scene, "Muebles"))
    assert all(scene.entity_visible(f) for f in _faces(scene, None))


def test_locking_the_group_layer_locks_its_untagged_contents():
    scene, group, _ = _scene()
    scene.begin_group_edit(group)
    scene.layer("Planta").locked = True
    assert not any(scene.entity_selectable(f) for f in _faces(scene, None))


def test_after_closing_the_group_nothing_changes():
    scene, group, loose = _scene()
    scene.begin_group_edit(group)
    scene.end_group_edit()
    scene.layer("Layer 0").visible = False
    assert scene.entity_visible(group)
    assert not scene.entity_visible(loose)
