# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A GLB that carries the model's layers, for a web viewer that switches
them (``save_glb(..., layers=True)``).

Without the option a file holds only what shows, and nothing in it says
which layer a part is on: a web viewer could not show a saved view's
layers. With it every node names its layer, the hidden layers are
written too, and the asset lists the layers with their state. A nested
group that does not show now leaves the file as it leaves the screen.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.group import Group  # noqa: E402
from core.layers import DEFAULT_LAYER, Layer  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats.gltf import save_glb  # noqa: E402
from tests.test_gltf_dae_export import _read_glb  # noqa: E402


def _square(x0=0.0):
    m = Mesh()
    m.add_face([V(x0, 0, 0), V(x0 + 1, 0, 0), V(x0 + 1, 1, 0), V(x0, 1, 0)])
    return m


def _at(dx):
    xf = QMatrix4x4()
    xf.translate(dx, 0, 0)
    return xf


def _scene():
    """Walls (shown) and Rebar (hidden): a wall group with a rebar cage
    nested in it, a loose face on each layer, and a group on the default
    layer."""
    s = Scene()
    s.layers.append(Layer("Walls"))
    s.layers.append(Layer("Rebar", visible=False))
    cage = Group(_square(), "cage")
    cage.layer = "Rebar"
    cage.xform = _at(1.0)
    wall = Group(Mesh(), "wall")
    wall.layer = "Walls"
    wall.adopt([cage])
    wall.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 1), V(0, 0, 1)])
    s.groups.append(wall)
    s.groups.append(Group(_square(10.0), "table"))
    for x0, layer in ((20.0, "Walls"), (30.0, "Rebar")):
        f = s.loose_mesh.add_face([V(x0, 0, 0), V(x0 + 1, 0, 0),
                                   V(x0 + 1, 1, 0), V(x0, 1, 0)])
        f.attrs["layer"] = layer
    return s


def _nodes(gltf):
    return {n["name"]: n for n in gltf["nodes"]}


def test_without_the_option_the_file_is_as_before_and_nested_hidden_goes(tmp_path):
    out = tmp_path / "m.glb"
    save_glb(_scene(), out)
    gltf, _ = _read_glb(out)
    names = [n["name"] for n in gltf["nodes"]]
    # The rebar cage is on a hidden layer two levels down: it is not on
    # screen, so it is not in the file either (it used to be).
    assert "cage" not in names
    assert "wall" in names and "table" in names
    assert names.count("Loose geometry") == 1
    assert "ingetrazo_layers" not in gltf["asset"]["extras"]
    assert not any("ingetrazo_layer" in n.get("extras", {})
                   for n in gltf["nodes"])


def test_with_layers_every_node_names_its_layer_and_hidden_ones_come_along(tmp_path):
    s = _scene()
    out = tmp_path / "m.glb"
    save_glb(s, out, layers=True)
    gltf, _ = _read_glb(out)
    nodes = _nodes(gltf)
    assert nodes["wall"]["extras"]["ingetrazo_layer"] == "Walls"
    assert nodes["cage"]["extras"]["ingetrazo_layer"] == "Rebar"
    assert nodes["table"]["extras"]["ingetrazo_layer"] == DEFAULT_LAYER
    # The cage stays inside the wall: hiding Walls hides it too.
    cage = gltf["nodes"].index(nodes["cage"])
    assert cage in nodes["wall"]["children"]
    # The loose geometry: one node per layer, the hidden one included.
    loose = [n["extras"]["ingetrazo_layer"] for n in gltf["nodes"]
             if n["name"] == "Loose geometry"]
    assert sorted(loose) == ["Rebar", "Walls"]
    listed = gltf["asset"]["extras"]["ingetrazo_layers"]
    assert [(ly["name"], ly["visible"]) for ly in listed] == [
        (DEFAULT_LAYER, True), ("Walls", True), ("Rebar", False)]
    assert all(len(ly["color"]) == 3 for ly in listed)


def test_with_layers_hide_still_leaves_things_out(tmp_path):
    s = _scene()
    table = next(g for g in s.groups if g.name == "table")
    table.hidden = True
    out = tmp_path / "m.glb"
    save_glb(s, out, layers=True)
    gltf, _ = _read_glb(out)
    assert "table" not in _nodes(gltf)


def test_the_document_is_not_changed(tmp_path):
    s = _scene()
    save_glb(s, tmp_path / "m.glb", layers=True)
    assert [(ly.name, ly.visible) for ly in s.layers] == [
        (DEFAULT_LAYER, True), ("Walls", True), ("Rebar", False)]
