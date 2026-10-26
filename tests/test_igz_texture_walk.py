# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Texture discovery stays generic, ordered and byte-preserving."""
import copy
import json
from pathlib import Path
import zipfile

from PySide6.QtGui import QImage

from formats import igz


def _payload(tmp_path):
    entries = []
    for i in range(7):
        image = QImage(2, 2, QImage.Format_RGB32)
        image.fill(0x112233 + i)
        path = tmp_path / f"image-{i}.png"
        assert image.save(str(path))
        entries.append({"path": str(path), "sw": 1.0, "sh": 2.0})
    entries[0]["base"] = entries[-1]["path"]
    payload = {
        "faces": [{"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                   "color": [0.1, 0.2, 0.3], "texture": entries[0],
                   "back": {"texture": entries[1]}}],
        "groups": [{"material": {"texture": entries[2]},
                    "children": [{"material": {"texture": entries[3]}}]}],
        "protos": [{"geom": {"face_attrs": [{"texture": entries[4]}],
                               "arrays": {"pos": {"path": "geom/0"}}}}],
        # An extension's new place for a texture needs no walker change.
        "plugin_data": {"future": [[{"recipe": {"texture": entries[5]}}]]},
        "image_planes": [{"texture": entries[6]}],
    }
    return payload, entries


def _reference_walk(node):
    """The original recursive walk, kept as a serialization oracle."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "texture" and isinstance(value, dict):
                yield value
            elif key not in igz._TEXTURE_WALK_SKIP:
                yield from _reference_walk(value)
    elif isinstance(node, list):
        if node and not isinstance(node[0], (dict, list)):
            return
        for value in node:
            yield from _reference_walk(value)


def test_every_texture_packs_unpacks_and_resaves_identically(tmp_path, monkeypatch):
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache"))
    payload, entries = _payload(tmp_path)
    assert [id(t) for t in igz._texture_entries(payload)] == [id(t) for t in entries]
    expected = copy.deepcopy(payload)
    images = [Path(t["path"]).read_bytes() for t in entries]
    blobs, missing = igz._pack_textures(payload)
    assert missing == 0 and len(blobs) == len(entries)
    assert all("embed" in t and "path" not in t for t in entries)
    assert "base_embed" in entries[0] and "base" not in entries[0]
    with monkeypatch.context() as mp:
        mp.setattr(igz, "_texture_entries", _reference_walk)
        old_blobs, old_missing = igz._pack_textures(expected)
    assert (payload, list(blobs.items()), missing) == \
        (expected, list(old_blobs.items()), old_missing)
    before, after = tmp_path / "before.igz", tmp_path / "after.igz"
    igz._write_container(before, json.dumps(expected), old_blobs)
    igz._write_container(after, json.dumps(payload), blobs)
    assert before.read_bytes() == after.read_bytes()
    with zipfile.ZipFile(after) as archive:
        igz._unpack_textures(payload, archive)
    assert [Path(t["path"]).read_bytes() for t in entries] == images
    assert Path(entries[0]["base"]).read_bytes() == images[-1]
    assert all("embed" not in t and "base_embed" not in t for t in entries)
    again, missing = igz._pack_textures(payload)
    assert missing == 0
    igz._write_container(after, json.dumps(payload), again)
    assert before.read_bytes() == after.read_bytes()


def test_coordinate_and_leaf_lists_are_not_walked():
    class UnreadableList(list):
        def __iter__(self):
            raise AssertionError("the texture walk entered a value list")

    payload = {"vertices": UnreadableList([[0, 0, 0]]),
               "color": UnreadableList([0.1, 0.2, 0.3]),
               "faces": [{"vertices": [], "back": True}], "empty": []}
    assert list(igz._texture_entries(payload)) == []
