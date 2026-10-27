# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Hide must reach the non-geometry too (#272).

``HideCommand`` — Edit ▸ Hide, and what every «isolate selection»
extension builds on — only kept entities carrying a ``hidden`` or an
``attrs`` attribute. Dimensions, text labels, image planes and guides
carried neither, so the command silently dropped them: hide (or
isolate) a scene and the geometry went away while every annotation,
reference image and guide stayed on screen, with no way for a plugin
to do better.

The four classes now carry a plain ``hidden`` flag of their own —
an ``attrs`` dict like a face's will not do: ``core.layers`` reads
an entity's layer out of that dict, so borrowing it would silently
take their layer away. With the flag, the command, ``Scene.
entity_visible`` (which the draw, pick and export passes already
ask for these kinds) and the .igz round trip all treat a hidden
dimension, label, image or guide like any other hidden entity.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QVector3D as V  # noqa: E402

_app = QGuiApplication.instance() or QGuiApplication([])

from core.dimension import Dimension  # noqa: E402
from core.guide import Guide  # noqa: E402
from core.history import HideCommand, History, _is_hidden  # noqa: E402
from core.image_plane import ImagePlane  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.textlabel import TextLabel  # noqa: E402
from formats import igz  # noqa: E402


def _non_geometry(scene):
    dim = Dimension(V(0, 0, 0), V(3, 0, 0), V(0, 1, 0))
    label = TextLabel(V(1, 1, 0), V(0, 1, 0), "cota")
    image = ImagePlane("plano.png", V(0, 0, 0), V(4, 0, 0), V(0, 3, 0), 0.75)
    guide = Guide(V(2, 2, 0))
    scene.dimensions.append(dim)
    scene.text_labels.append(label)
    scene.image_planes.append(image)
    scene.guides.append(guide)
    return [dim, label, image, guide]


def test_hide_command_keeps_dimensions_labels_images_and_guides():
    scene = Scene()
    entities = _non_geometry(scene)
    cmd = HideCommand(entities, hidden=True)
    assert cmd.entities == entities


def test_hidden_non_geometry_is_invisible_and_undo_brings_it_back():
    scene = Scene()
    history = History(scene)
    entities = _non_geometry(scene)
    history.execute(HideCommand(entities, hidden=True))
    for e in entities:
        assert _is_hidden(e)
        assert scene.entity_hidden(e)
        assert not scene.entity_visible(e)
    history.undo()
    for e in entities:
        assert not _is_hidden(e)
        assert scene.entity_visible(e)


def test_isolate_hides_the_annotations_with_the_geometry():
    """The reporter's shape: hide everything but one face — the
    dimension, label, image and guides must go with the rest."""
    scene = Scene()
    entities = _non_geometry(scene)
    keep = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    rest = scene.mesh.add_face([V(3, 0, 0), V(4, 0, 0), V(4, 1, 0), V(3, 1, 0)])
    history = History(scene)
    history.execute(HideCommand([rest, *entities], hidden=True))
    assert not scene.entity_visible(rest)
    for e in entities:
        assert not scene.entity_visible(e)
    assert scene.entity_visible(keep)


def test_layer_hiding_still_reaches_them():
    """The flag must not cost them their layer: an entity that starts
    carrying a face-style ``attrs`` dict would read as default-layer
    forever (``core.layers.layer_of`` looks there first)."""
    from core.layers import Layer
    scene = Scene()
    scene.layers.append(Layer("Anotaciones", visible=False))
    dim = Dimension(V(0, 0, 0), V(3, 0, 0), V(0, 1, 0), layer="Anotaciones")
    label = TextLabel(V(1, 1, 0), V(0, 1, 0), "cota", layer="Anotaciones")
    image = ImagePlane("plano.png", V(0, 0, 0), V(4, 0, 0), V(0, 3, 0),
                       0.75, layer="Anotaciones")
    for e in (dim, label, image):
        assert not scene.entity_visible(e)
    scene.layer("Anotaciones").visible = True
    for e in (dim, label, image):
        assert scene.entity_visible(e)


def test_hidden_state_round_trips_through_dicts():
    label = TextLabel(V(1, 1, 0), V(0, 1, 0), "cota")
    label.hidden = True
    assert TextLabel.from_dict(label.to_dict()).hidden

    image = ImagePlane("plano.png", V(0, 0, 0), V(4, 0, 0), V(0, 3, 0), 0.75)
    image.hidden = True
    assert ImagePlane.from_dict(image.to_dict()).hidden

    guide = Guide(V(2, 2, 0), V(1, 0, 0))
    guide.hidden = True
    assert Guide.from_dict(guide.to_dict()).hidden

    shown = TextLabel(V(0, 0, 0), V(0, 1, 0), "visible")
    assert not TextLabel.from_dict(shown.to_dict()).hidden


def test_a_hidden_dimension_round_trips_through_igz(tmp_path):
    scene = Scene()
    dim = Dimension(V(0, 0, 0), V(3, 0, 0), V(0, 1, 0))
    dim.hidden = True
    scene.dimensions.append(dim)
    p = tmp_path / "cotas.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    assert len(scene2.dimensions) == 1
    assert scene2.dimensions[0].hidden
    assert not scene2.entity_visible(scene2.dimensions[0])
