# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP tag folders keep their hierarchy through import and native saving."""
import pytest

from core.history import History, SnapshotImport
from core.layers import Layer
from core.scene import Scene
from formats import skp


def _tlv(tag, payload):
    import struct
    return bytes.fromhex(tag) + struct.pack("<I", len(payload)) + payload


def _ref(value):
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "little")
    return bytes([len(raw)]) + raw


def _folder(name, ids=(), children=(), hidden=False):
    return _tlv("803E", _tlv("813E", name.encode("utf8"))
                + _tlv("833E", b"".join(children))
                + _tlv("843E", b"".join(_ref(i) for i in ids))
                + _tlv("823E", bytes([hidden])) + _tlv("853E", b"\x00"))


def _modern_file(tmp_path, malformed_ids=False):
    import zipfile
    from PySide6.QtGui import QImage
    # Byte structure checked against folders written by SketchUp itself.
    tags = {0x1234: "Walls", 0x123456: "Notes", 4: "Root tag", 5: "Hidden tag"}
    entries = b""
    for ident, name in tags.items():
        raw_id = _ref(ident)[1:]
        entries += _tlv("8C3C", _tlv("DC05", _tlv("DE05", raw_id))
                        + _tlv("8D3C", name.encode("utf8"))
                        + _tlv("8E3C", b"\x00"))
    hierarchy = _folder("", (4,), [
        _folder("Building", (0x123456,), [
            _folder("Structure", (0x1234,), [_folder("Empty")]),
            _folder("Duplicate")]),
        _folder("Other", children=[_folder("Duplicate")]),
        _folder("Hidden", children=[_folder("Hidden child", (5,))], hidden=True)])
    if malformed_ids:
        # An incomplete length-prefixed id is ignored, without inventing a tag.
        hierarchy = _folder("", children=[_tlv("803E",
            _tlv("813E", b"Broken") + _tlv("843E", b"\x04\x12"))])
    model = _tlv("F401", _tlv("F801", _tlv("983A",
        _tlv("993A", entries) + _tlv("9B3A", hierarchy))))
    image = QImage(8, 8, QImage.Format_RGBA8888)
    image.fill(0xffffffff)
    thumbnail = tmp_path / "blank.png"
    assert image.save(str(thumbnail))
    path = tmp_path / "tag-folders.skp"
    version = "{26.2.243}"
    header = (b"\xff\xfe\xff\x0e" + "SketchUp Model".encode("utf-16-le")
              + b"\xff\xfe\xff" + bytes([len(version)])
              + version.encode("utf-16-le") + b"VFF")
    with path.open("wb") as stream:
        stream.write(header)
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("model.dat", model)
            archive.write(thumbnail, "meta/model_thumbnail.png")
            for name in tags.values():
                archive.writestr(f"materials/{name}/material.xml", (
                    '<materialDocument xmlns="http://sketchup.google.com/'
                    'schemas/sketchup/1.0/material">'
                    f'<material name="Layer_{name}" colorRed="120" '
                    'colorGreen="160" colorBlue="200" useTrans="0"/>'
                    '</materialDocument>'))
    return path


def test_real_vff_parser_preserves_tag_folder_tree(tmp_path):
    pytest.importorskip("openskp")
    scene = Scene()
    payload = skp.parse_skp(_modern_file(tmp_path))
    skp.apply_payload(scene, payload)
    assert scene.layer_folders == ["Building", "Structure", "Empty", "Duplicate",
                                   "Other", "Duplicate 1", "Hidden", "Hidden child"]
    assert scene.folder_parents == {"Structure": "Building", "Empty": "Structure",
                                    "Duplicate": "Building", "Duplicate 1": "Other",
                                    "Hidden child": "Hidden"}
    assert scene.layer("Walls").folder == "Structure"
    assert scene.layer("Notes").folder == "Building"
    assert scene.layer("Root tag").folder is None
    assert scene.layer("Hidden tag").folder == "Hidden child"
    assert scene.layer("Hidden tag").visible is False
    assert scene.layer("Walls").visible is True


def test_malformed_tag_folder_reference_does_not_drop_other_layers(tmp_path):
    pytest.importorskip("openskp")
    scene = Scene()
    skp.apply_payload(scene, skp.parse_skp(_modern_file(tmp_path, malformed_ids=True)))
    assert scene.layer_folders == ["Broken"]
    assert all(scene.layer(n).folder is None
               for n in ("Walls", "Notes", "Root tag", "Hidden tag"))


def _payload():
    return {
        "layer_folders": [{"name": "Building"},
                          {"name": "Structure", "parent": "Building"},
                          {"name": "Empty", "parent": "Structure"}],
        "layers": [{"name": "Walls", "folder": "Structure", "visible": False},
                   {"name": "Notes", "folder": "Building"},
                   {"name": "Survey"}],
    }


def test_import_retains_nested_and_empty_tag_folders(tmp_path):
    from formats.igz import load_into, save_scene
    scene = Scene()
    skp.apply_payload(scene, _payload())
    assert scene.layer_folders == ["Building", "Structure", "Empty"]
    assert scene.folder_parents == {"Structure": "Building", "Empty": "Structure"}
    assert scene.layer("Walls").folder == "Structure"
    assert scene.layer("Walls").visible is False
    assert scene.layer("Notes").folder == "Building"
    assert scene.layer("Survey").folder is None
    path = tmp_path / "folders.igz"
    save_scene(scene, path)
    restored = Scene()
    load_into(restored, path)
    assert restored.layer_folders == scene.layer_folders
    assert restored.folder_parents == scene.folder_parents
    assert restored.layer("Walls").folder == "Structure"


def test_reimport_preserves_existing_folder_and_layer_placements():
    scene = Scene()
    scene.layer_folders = ["Personal", "Structure"]
    scene.folder_parents = {"Structure": "Personal"}
    walls = Layer("Walls", folder="Personal")
    scene.layers.append(walls)
    skp.apply_payload(scene, _payload())
    assert scene.folder_parents["Structure"] == "Personal"
    assert scene.layer("Walls") is walls
    assert walls.folder == "Personal"
    assert scene.folder_parents["Empty"] == "Structure"
    assert len(scene.layer_folders) == len(set(scene.layer_folders))


def test_import_folder_hierarchy_is_undone_and_redone():
    scene = Scene()
    scene.layer_folders = ["Existing"]
    history = History(scene)
    command = SnapshotImport(lambda s: skp.apply_payload(s, _payload()))
    assert history.execute(command)
    assert command.changed
    assert scene.folder_parents == {"Structure": "Building", "Empty": "Structure"}
    history.undo()
    assert scene.layer_folders == ["Existing"]
    assert scene.folder_parents == {}
    assert not any(ly.name == "Walls" for ly in scene.layers)
    history.redo()
    assert scene.layer_folders == ["Existing", "Building", "Structure", "Empty"]
    assert scene.folder_parents == {"Structure": "Building", "Empty": "Structure"}
    assert scene.layer("Walls").folder == "Structure"


def test_empty_folder_only_import_is_an_undoable_change():
    scene = Scene()
    history = History(scene)
    command = SnapshotImport(lambda s: skp.apply_payload(s, {
        "layer_folders": [{"name": "Empty"}]}))
    assert history.execute(command)
    assert command.changed
    history.undo()
    assert scene.layer_folders == []
    history.redo()
    assert scene.layer_folders == ["Empty"]


def test_failed_import_restores_folder_hierarchy():
    scene = Scene()
    scene.layer_folders = ["Existing", "Child"]
    scene.folder_parents = {"Child": "Existing"}

    def fail(s):
        skp.apply_payload(s, _payload())
        s.folder_parents["Child"] = "Building"
        raise ValueError("failed import")

    command = SnapshotImport(fail)
    with pytest.raises(ValueError, match="failed import"):
        command.do(scene)
    assert scene.layer_folders == ["Existing", "Child"]
    assert scene.folder_parents == {"Child": "Existing"}
