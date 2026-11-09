# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #943: groups a file carries without a name are numbered on load
from the document itself — not from the session-wide counter, whose next
numbers depend on whatever was opened before. The same file must load to
the same names in any session, or saving it hands back different names
than the last session did."""
from __future__ import annotations

import json

from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


def _group(name, x=0.0):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return Group(m, name=name)


def _save_document_with_two_unnamed(path):
    """A document with a stored "Group 2", a named group and two groups
    whose entries carry no name at all — as a file written before group
    names were saved does."""
    scene = Scene()
    scene.groups.append(_group("Group 2", 0))
    scene.groups.append(_group("Pérgola", 3))
    scene.groups.append(_group("strip me", 6))
    scene.groups.append(_group("strip me too", 9))
    igz.save_scene(scene, path)
    raw = path.read_bytes()
    assert raw.startswith(b"{")          # a small document is plain JSON
    doc = json.loads(raw)

    def strip(entry):
        if (entry.get("name") or "").startswith("strip me"):
            entry.pop("name", None)
        for child in entry.get("children", []) or []:
            strip(child)

    for entry in doc["scene"]["groups"]:
        strip(entry)
    path.write_text(json.dumps(doc))


def _load_names(path):
    scene = Scene()
    igz.load_into(scene, path)
    return [g.name for g in scene.groups]


def test_unnamed_groups_are_numbered_from_the_document(tmp_path):
    path = tmp_path / "doc.igz"
    _save_document_with_two_unnamed(path)
    # Session history: other work has already handed out many names, so
    # the session counter sits far past the document's own numbers.
    for _ in range(40):
        Group(Mesh())
    assert _load_names(path) == ["Group 2", "Pérgola", "Group 3", "Group 4"]
    # Still more history must not change what the same file loads to.
    for _ in range(5):
        Group(Mesh())
    assert _load_names(path) == ["Group 2", "Pérgola", "Group 3", "Group 4"]


def test_a_group_created_after_load_does_not_reuse_a_loaded_number(tmp_path):
    path = tmp_path / "doc.igz"
    _save_document_with_two_unnamed(path)
    scene = Scene()
    igz.load_into(scene, path)
    fresh = Group(Mesh())
    assert fresh.name not in {g.name for g in scene.groups}
    assert fresh.name.startswith("Group ")
