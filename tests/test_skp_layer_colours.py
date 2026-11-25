# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SketchUp tag colours survive adaptation, import and native saving."""
from types import SimpleNamespace as NS

import pytest

from core.layers import Layer, layer_paint
from core.materials import effective_attrs
from core.scene import Scene
from formats import skp
from formats.skp_openskp import file_layer_records


def _coloured_layers():
    # VFF files keep tag opacity in Layer_<name> materials. They are not
    # in materials_by_id, which only joins materials painted on geometry.
    return file_layer_records(NS(
        layers=[NS(name="Rose", color_r=229, color_g=57, color_b=165,
                   hidden=False),
                NS(name="Noir", color_r=0, color_g=0, color_b=0,
                   hidden=True),
                NS(name="Concrete", color_r=202, color_g=202, color_b=202,
                   hidden=False)],
        materials=[NS(name="Layer_Rose", transparency=0.24),
                   NS(name="Layer_Noir", transparency=0.4),
                   NS(name="Layer_Concrete", transparency=1.0),
                   NS(name="Rose", transparency=0.9)],
        materials_by_id={}))


def test_vff_tag_colours_include_their_material_opacity():
    records = {r["name"]: r for r in _coloured_layers()}
    assert records["Rose"]["color"] == pytest.approx(
        (229 / 255, 57 / 255, 165 / 255, 0.24))
    assert records["Noir"]["color"] == pytest.approx((0, 0, 0, 0.4))
    assert records["Noir"]["visible"] is False
    assert records["Concrete"]["color"] == pytest.approx((202 / 255,) * 3)


def test_modern_skp_tag_colour_and_opacity_reach_the_scene(tmp_path):
    import zipfile
    from PySide6.QtGui import QImage
    pytest.importorskip("openskp")
    # A minimal VFF template: real material XMLs and the blank thumbnail
    # that lets the importer recognise a deliberately empty model.
    image = QImage(8, 8, QImage.Format_RGBA8888)
    image.fill(0xffffffff)
    thumbnail = tmp_path / "blank.png"
    assert image.save(str(thumbnail))
    path = tmp_path / "modern-tags.skp"
    version = "{26.2.243}"
    header = (b"\xff\xfe\xff\x0e" + "SketchUp Model".encode("utf-16-le")
              + b"\xff\xfe\xff" + bytes([len(version)])
              + version.encode("utf-16-le") + b"VFF")
    with path.open("wb") as stream:
        stream.write(header)
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("model.dat", b"")
            archive.write(thumbnail, "meta/model_thumbnail.png")
            for name, rgb, use_trans, trans in [
                    ("Rose", (229, 57, 165), 1, 0.76),
                    ("Noir", (0, 0, 0), 1, 0.6),
                    ("Concrete", (202, 202, 202), 0, 0.5),
                    ("Invisible", (81, 159, 255), 1, 1.0)]:
                archive.writestr(f"materials/{name}/material.xml", (
                    '<materialDocument xmlns="http://sketchup.google.com/'
                    'schemas/sketchup/1.0/material">'
                    f'<material name="Layer_{name}" colorRed="{rgb[0]}" '
                    f'colorGreen="{rgb[1]}" colorBlue="{rgb[2]}" '
                    f'useTrans="{use_trans}" trans="{trans}"/>'
                    '</materialDocument>'))
    scene = Scene()
    skp.apply_payload(scene, skp.parse_skp(path))
    assert scene.layer("Rose").color == pytest.approx(
        (229 / 255, 57 / 255, 165 / 255, 0.24))
    assert scene.layer("Noir").color == pytest.approx((0, 0, 0, 0.4))
    # A disabled transparency ignores the XML's leftover trans value.
    assert scene.layer("Concrete").color == pytest.approx((202 / 255,) * 3)
    assert scene.layer("Invisible").color == pytest.approx(
        (81 / 255, 159 / 255, 1, 0))


def test_imported_tag_alpha_only_affects_colour_by_layer_and_survives_save(tmp_path):
    from formats.igz import load_into, save_scene
    scene = Scene()
    skp.apply_payload(scene, {"layers": _coloured_layers()})
    expected = (229 / 255, 57 / 255, 165 / 255, 0.24)
    assert scene.layer("Rose").color == pytest.approx(expected)
    assert scene.layer("Rose").opacity == 1.0
    attrs = {"layer": "Rose"}
    painted = effective_attrs(attrs, layer_paint(scene))
    assert painted["color"] == pytest.approx(expected[:3])
    assert painted["opacity"] == pytest.approx(0.24)
    assert effective_attrs(attrs, None).get("opacity", 1.0) == 1.0
    path = tmp_path / "tag-colours.igz"
    save_scene(scene, path)
    loaded = Scene()
    load_into(loaded, path)
    assert loaded.layer("Rose").color == pytest.approx(expected, abs=0.00005)
    assert loaded.layer("Noir").visible is False


def test_reimport_keeps_existing_tag_colour_and_visibility():
    scene = Scene()
    original = Layer("Rose", color=(0.2, 0.3, 0.4, 0.6), visible=False)
    scene.layers.append(original)
    skp.apply_payload(scene, {"layers": [
        {"name": "Rose", "color": [1, 0, 0, 0.24], "visible": True},
        {"name": "New", "color": [0, 0, 1, 0.25], "visible": False},
        {"name": "Automatic", "visible": True}]})
    assert scene.layer("Rose") is original
    assert original.color == (0.2, 0.3, 0.4, 0.6)
    assert original.visible is False
    assert scene.layer("New").color == (0, 0, 1, 0.25)
    assert scene.layer("New").visible is False
    assert scene.layer("Automatic").color is None


def test_classic_skp_tag_rgb_survives_import_undo_and_redo(tmp_path):
    from core.history import History, SnapshotImport
    create = pytest.importorskip("openskp.create")
    builder = create.SkpBuilder()
    tag = builder.add_layer("Blue", color=(81, 159, 255), hidden=True)
    builder.add_face([(0, 0, 0), (100, 0, 0), (0, 100, 0)], layer=tag)
    path = tmp_path / "coloured-tags.skp"
    builder.save(str(path))
    payload = skp.parse_skp(path)
    scene = Scene()
    history = History(scene)
    history.execute(SnapshotImport(lambda s: skp.apply_payload(s, payload)))
    expected = (81 / 255, 159 / 255, 1.0)
    assert scene.layer("Blue").color == pytest.approx(expected)
    assert scene.layer("Blue").visible is False
    history.undo()
    assert not any(ly.name == "Blue" for ly in scene.layers)
    history.redo()
    assert scene.layer("Blue").color == pytest.approx(expected)
    assert scene.layer("Blue").visible is False
